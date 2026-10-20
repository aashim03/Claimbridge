"""Supervisor: deterministic infrastructure, not an agent (no LLM).

  - runs the worker pool (each worker is its own OS process) and executes control
    commands that anyone writes into the graph: KILL <agent>, START <role>, SHUTDOWN;
  - lease reaper: records LEASE_EXPIRED when a worker dies holding a claim (any
    replica of that role then reclaims it on its own);
  - marks workers whose heartbeat stopped as dead;
  - the human gate: only `approve` / `record_outcome` move a claim past review.
"""
import json
import logging
import os
import subprocess
import sys
import time
import uuid

from claimbridge import config, db
from claimbridge.tools import coordination as coord

log = logging.getLogger("claimbridge.supervisor")

DEFAULT_POOL = {"intake": 1, "retrieval": 1, "verifier": 2, "planner": 1, "curator": 1}
ME = "supervisor"


# ------------------------------------------------------------------ human gate

def approve(g, cid: str, reviewer: str) -> bool:
    params = {"cid": cid, "who": reviewer, "now": db.now_ms()}
    ok = db.one(g, """
        MATCH (c:Claim {claim_id: $cid})
        WHERE c.status = 'AWAITING_REVIEW' AND c.lease_owner IS NULL
        SET c.status = 'APPROVED'
        WITH c
        OPTIONAL MATCH (c)-[:RECOMMENDATION]->(rec:Recommendation)
        SET rec.approved_by = $who, rec.approved_at = $now
        RETURN c.claim_id AS ok
    """, params)
    if ok:
        coord.append_event(g, cid, "APPROVED", reviewer, "reviewer", "AWAITING_REVIEW", {"reviewer": reviewer})
    return ok is not None


def record_outcome(g, cid: str, outcome: str, reviewer: str, confirmed_evidence: list[str] | None = None) -> bool:
    """The real-world result of the appeal, entered by a human. Feeds the Curator."""
    if outcome not in ("OVERTURNED", "UPHELD", "PARTIAL"):
        raise ValueError(outcome)
    ok = db.one(g, """
        MATCH (c:Claim {claim_id: $cid})-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(cl:Clause)
        WHERE c.status = 'APPROVED'
        CREATE (res:Resolution {resolution_id: 'R-' + $cid, outcome: $outcome, verified: true,
                                verified_on: $today, verified_by: $who, confirmed_evidence: $confirmed})
        CREATE (c)-[:RESOLVED_BY]->(res)
        CREATE (res)-[:RELIED_ON]->(cl)
        SET c.status = 'VERIFIED_OUTCOME'
        WITH c, res
        OPTIONAL MATCH (c)-[:HAS_EVIDENCE]->(d:Evidence) WHERE coalesce(d.withdrawn, false) = false
        FOREACH (_ IN CASE WHEN d IS NULL THEN [] ELSE [1] END | CREATE (res)-[:SUPPORTED_BY]->(d))
        RETURN DISTINCT c.claim_id AS ok
    """, {"cid": cid, "outcome": outcome, "who": reviewer, "confirmed": confirmed_evidence,
          "today": int(time.strftime("%Y%m%d"))})
    if ok:
        coord.append_event(g, cid, "OUTCOME_RECORDED", reviewer, "reviewer", "APPROVED",
                           {"outcome": outcome, "reviewer": reviewer})
    return ok is not None


# ----------------------------------------------- human correction and evidence updates
#
# Who may do what (enforced by the API; recorded in the audit trail):
#   correct the denial reason of a claim the agents could not read   operator only
#   declare that a document is on file                               the owning policyholder, or an operator
#   withdraw a declared document                                     operator only
# Declaring a document says it exists. ClaimBridge does not open, read or verify documents.
# The original denial notice is never edited: a correction is a separate, attributed record.

CORRECTABLE = ("NEEDS_HUMAN", "AWAITING_REVIEW")
EVIDENCE_EDITABLE = ("NEW", "NEEDS_HUMAN", "AWAITING_REVIEW")
RESUME_STEPS = ("CLASSIFIED", "RETRIEVED", "VERIFIED")        # inputs of Retrieval, Verifier, Planner


def _status(g, cid: str) -> dict:
    row = db.one(g, "MATCH (c:Claim {claim_id: $cid}) RETURN c.status AS status, c.lease_owner AS owner", {"cid": cid})
    if not row:
        raise LookupError(f"no claim {cid}")
    return row


def _clear_computed_outputs(g, cid: str, from_step: str):
    """Remove what the agents computed from `from_step` on, so that no stale advice survives a change.
    CLASSIFIED: precedents, verdicts, gates and the recommendation. VERIFIED: the recommendation only."""
    p = {"cid": cid}
    if from_step == "CLASSIFIED":
        db.run(g, "MATCH (:Claim {claim_id: $cid})-[k:CONSIDERED]->() DELETE k", p)
        db.run(g, "MATCH (c:Claim {claim_id: $cid}) REMOVE c.gates", p)
    db.run(g, """MATCH (c:Claim {claim_id: $cid})-[:RECOMMENDATION]->(rec:Recommendation)
                 OPTIONAL MATCH (rec)-[:HAS_ITEM]->(i:RecItem) DETACH DELETE i, rec""", p)
    db.run(g, "MATCH (c:Claim {claim_id: $cid}) REMOVE c.disposition", p)
    steps = RESUME_STEPS[RESUME_STEPS.index(from_step):]
    db.run(g, "MATCH (:Claim {claim_id: $cid})-[:HAS_CHECKPOINT]->(cp:Checkpoint) WHERE cp.step IN $steps DETACH DELETE cp",
           {**p, "steps": list(steps)})


def _escalation(g, cid: str) -> dict:
    """Why a claim is with a person: the latest NEEDS_HUMAN event's reason and the step that raised it."""
    for e in reversed(coord.timeline(g, cid)):
        if e["type"] in ("NEEDS_HUMAN", "GAVE_UP"):
            try:
                payload = json.loads(e["payload"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            return {"reason": payload.get("reason") or ("the agents gave up after repeated failures" if e["type"] == "GAVE_UP" else None),
                    "step": e["step"], "agent": e["agent"], "ts": e["ts"]}
    return {"reason": None, "step": None, "agent": None, "ts": None}


def correct_classification(g, cid: str, reason: str, note: str, reviewer: str) -> dict:
    """A person classifies a notice the agents could not (or got wrong) and resumes the claim at Retrieval.

    The clause comes from the graph's routing for (reason, service) in the claim's pinned policy version,
    never from the caller. Everything computed after classification is removed first, so repeated corrections
    cannot leave advice from an earlier reading behind."""
    from claimbridge.tools import versions
    note = " ".join((note or "").split())
    if not 10 <= len(note) <= 500:
        raise ValueError("Say why in 10 to 500 characters; this becomes part of the audit record.")
    if reason == "UNKNOWN" or not db.one(g, "MATCH (r:DenialReason {code: $r}) RETURN r.code AS c", {"r": reason}):
        raise ValueError("Choose one of the known denial reasons.")
    st = _status(g, cid)
    if st["status"] not in CORRECTABLE or st["owner"]:
        raise PermissionError("This claim cannot be corrected in its current state.")
    clause = versions.route_clause(g, cid, reason)
    if not clause:
        raise ValueError("No clause in the governing policy routes that denial reason for this service, "
                         "or no policy version covers the service date yet.")
    esc = _escalation(g, cid)
    prior = db.one(g, """MATCH (c:Claim {claim_id: $cid}) OPTIONAL MATCH (c)-[:DENIED_FOR]->(r:DenialReason)
                         RETURN r.code AS reason, c.disposition AS disposition""", {"cid": cid}) or {}
    # 1. Quiesce: a claim in review goes back to "needs a person" so nothing half-corrected is ever shown as ready.
    if not db.one(g, """MATCH (c:Claim {claim_id: $cid}) WHERE c.status IN $ok AND c.lease_owner IS NULL
                        SET c.status = 'NEEDS_HUMAN' RETURN c.claim_id AS ok""", {"cid": cid, "ok": list(CORRECTABLE)}):
        raise PermissionError("This claim cannot be corrected in its current state.")
    _clear_computed_outputs(g, cid, "CLASSIFIED")
    versions.write_classification(g, cid, reason, clause["clause_id"], None)
    corr_id = f"CORR-{cid}-{db.now_ms()}"
    payload = {"reason": reason, "clause": clause["clause_id"], "previous_reason": prior.get("reason"),
               "previous_disposition": prior.get("disposition"), "escalation_reason": esc["reason"],
               "reviewer": reviewer, "note": note}
    # 2. Resume, atomically: record the correction and hand the claim to Retrieval in one write.
    params = {"cid": cid, "corr": corr_id, "reason": reason, "note": note, "who": reviewer, "prev": prior.get("reason"),
              "esc": esc["reason"], **coord._event_params("HUMAN_CORRECTION", reviewer, "reviewer", "NEEDS_HUMAN", payload)}
    ok = db.one(g, f"""
        MATCH (c:Claim {{claim_id: $cid}})
        WHERE c.status = 'NEEDS_HUMAN' AND c.lease_owner IS NULL
        SET c.status = 'CLASSIFIED', c.attempt = 0, c.event_seq = coalesce(c.event_seq, 0) + 1
        {coord._EVENT}
        CREATE (corr:Correction {{correction_id: $corr, reason_code: $reason, note: $note, reviewer: $who, ts: $now,
                                 previous_reason: $prev, escalation_reason: $esc}})
        CREATE (c)-[:CORRECTED_BY]->(corr)
        RETURN c.claim_id AS ok
    """, params)
    if not ok:
        raise PermissionError("The claim changed while it was being corrected; nothing was resumed.")
    return {"claim_id": cid, "correction_id": corr_id, "reason": reason, "clause": clause["clause_id"]}


def _doc_rows(g, cid: str) -> list[dict]:
    return db.run(g, """MATCH (:Claim {claim_id: $cid})-[:HAS_EVIDENCE]->(d:Evidence)-[:OF_TYPE]->(e:EvidenceType)
                        WHERE coalesce(d.withdrawn, false) = false
                        RETURN d.doc_id AS doc_id, e.code AS code""", {"cid": cid})


def _plan_snapshot(g, cid: str, status: str) -> dict:
    """What the claim's plan said BEFORE an evidence change, for the audit trail (taken before anything is written)."""
    from claimbridge import report
    if status != "AWAITING_REVIEW":
        return {}
    before = report.actual(g, cid)
    return {"previous_disposition": before.get("disposition"), "previous_missing": before["missing"],
            "previous_summary": (before.get("recommendation") or {}).get("summary")}


def _after_evidence_change(g, cid: str, status: str, etype: str, who: str, payload: dict, snapshot: dict):
    """Record the change; a claim already planned goes back to the Planner so its checklist and advice are recomputed."""
    if status == "AWAITING_REVIEW":
        payload = {**payload, **snapshot}
        # Withdraw the stale recommendation first; the evidence change and the re-plan then happen in one write.
        _clear_computed_outputs(g, cid, "VERIFIED")
        params = {"cid": cid, **coord._event_params(etype, who, "reviewer", status, payload)}
        done = db.one(g, f"""
            MATCH (c:Claim {{claim_id: $cid}}) WHERE c.status = 'AWAITING_REVIEW' AND c.lease_owner IS NULL
            SET c.status = 'VERIFIED', c.attempt = 0, c.event_seq = coalesce(c.event_seq, 0) + 1
            {coord._EVENT}
            RETURN c.claim_id AS ok""", params)
        if not done:
            raise PermissionError("The claim changed while it was being updated.")
    else:
        coord.append_event(g, cid, etype, who, "reviewer", status, payload)


def declare_evidence(g, cid: str, code: str, reference: str | None, who: str) -> dict:
    """Declare that a document of this type is on file. It is not verified: ClaimBridge never reads documents."""
    reference = " ".join((reference or "").split())[:200] or None
    st = _status(g, cid)
    if st["status"] not in EVIDENCE_EDITABLE or st["owner"]:
        raise PermissionError("Evidence can be changed before filing, while a claim needs a person, or while it awaits review.")
    if not db.one(g, "MATCH (e:EvidenceType {code: $c}) RETURN e.code AS c", {"c": code}):
        raise ValueError("Unknown evidence type.")
    if any(r["code"] == code for r in _doc_rows(g, cid)):
        raise ValueError("That document type is already on file for this claim.")
    doc_id = f"D-{cid}-U{uuid.uuid4().hex[:8]}"
    snapshot = _plan_snapshot(g, cid, st["status"])
    created = db.one(g, """
        MATCH (c:Claim {claim_id: $cid}) WHERE c.status IN $ok AND c.lease_owner IS NULL
        MATCH (et:EvidenceType {code: $code})
        CREATE (d:Evidence {doc_id: $doc, summary: 'Declared on file by ' + $who, submitted_date: $today,
                            declared_by: $who, declared_at: $now, verified: false, reference: $ref, source: 'declared'})
        CREATE (c)-[:HAS_EVIDENCE]->(d)
        CREATE (d)-[:OF_TYPE]->(et)
        RETURN d.doc_id AS doc""", {"cid": cid, "ok": list(EVIDENCE_EDITABLE), "code": code, "doc": doc_id, "who": who,
                                    "today": int(time.strftime("%Y%m%d")), "now": db.now_ms(), "ref": reference})
    if not created:
        raise PermissionError("The claim changed while the document was being declared.")
    _after_evidence_change(g, cid, st["status"], "EVIDENCE_DECLARED", who,
                           {"doc_id": doc_id, "type": code, "reference": reference, "verified": False, "reviewer": who}, snapshot)
    return {"doc_id": doc_id, "type": code}


def withdraw_evidence(g, cid: str, doc_id: str, who: str) -> dict:
    """Mark a document as no longer on file. The record stays, with who withdrew it and when; it stops counting."""
    st = _status(g, cid)
    if st["status"] not in EVIDENCE_EDITABLE or st["owner"]:
        raise PermissionError("Evidence can be changed before filing, while a claim needs a person, or while it awaits review.")
    row = db.one(g, """MATCH (:Claim {claim_id: $cid})-[:HAS_EVIDENCE]->(d:Evidence {doc_id: $doc})-[:OF_TYPE]->(e)
                       WHERE coalesce(d.withdrawn, false) = false RETURN e.code AS code""", {"cid": cid, "doc": doc_id})
    if not row:
        raise LookupError("No such document on file.")
    snapshot = _plan_snapshot(g, cid, st["status"])
    db.run(g, """MATCH (:Claim {claim_id: $cid})-[:HAS_EVIDENCE]->(d:Evidence {doc_id: $doc})
                 SET d.withdrawn = true, d.withdrawn_by = $who, d.withdrawn_at = $now""",
           {"cid": cid, "doc": doc_id, "who": who, "now": db.now_ms()})
    _after_evidence_change(g, cid, st["status"], "EVIDENCE_WITHDRAWN", who,
                           {"doc_id": doc_id, "type": row["code"], "reviewer": who}, snapshot)
    return {"doc_id": doc_id, "type": row["code"]}


# ------------------------------------------------------------------ commands

def command(g, ctype: str, target: str | None = None) -> str:
    cmd_id = f"CMD-{db.now_ms()}-{os.getpid()}"
    db.run(g, """CREATE (:Command {cmd_id: $id, type: $t, target: $target, status: 'PENDING',
                                   created_at: $now})""",
           {"id": cmd_id, "t": ctype, "target": target, "now": db.now_ms()})
    return cmd_id


def request_shutdown(g):
    db.run(g, "MERGE (s:Control {id: 'global'}) SET s.shutdown_at = $now", {"now": db.now_ms()})


# ------------------------------------------------------------------ the loop

class Supervisor:
    def __init__(self, pool: dict[str, int] | None = None, env: dict | None = None, tick_s: float = 1.0):
        self.pool = pool or DEFAULT_POOL
        self.env = env or {}
        self.tick_s = tick_s
        self.g = db.connect()
        self.procs: dict[str, subprocess.Popen] = {}
        self.counter: dict[str, int] = {}
        self.started_at = db.now_ms()

    def spawn(self, role: str) -> str:
        self.counter[role] = self.counter.get(role, 0) + 1
        agent_id = f"{role}-{self.counter[role]}"
        cmd = [sys.executable, "-m", "claimbridge.cli", "worker", role, "--id", agent_id]
        self.procs[agent_id] = subprocess.Popen(cmd, cwd=config.BACKEND_DIR, env={**os.environ, **self.env})
        log.info("started %s (pid %s)", agent_id, self.procs[agent_id].pid)
        return agent_id

    def kill(self, agent_id: str) -> bool:
        p = self.procs.get(agent_id)
        if not p or p.poll() is not None:
            return False
        p.kill()  # hard kill: no cleanup, its lease is left to expire
        p.wait()
        coord.heartbeat(self.g, agent_id, agent_id.rsplit("-", 1)[0], "killed")
        log.warning("killed %s", agent_id)
        return True

    def reap_leases(self) -> list[dict]:
        expired = db.run(self.g, """
            MATCH (c:Claim)
            WHERE c.lease_owner IS NOT NULL AND c.lease_until < timestamp()
              AND coalesce(c.reaped, '') <> c.lease_owner + ':' + toString(coalesce(c.lease_gen, 0))
            SET c.reaped = c.lease_owner + ':' + toString(coalesce(c.lease_gen, 0))
            RETURN c.claim_id AS claim_id, c.lease_owner AS owner, c.status AS status, c.attempt AS attempt,
                   c.lease_gen AS gen
        """)
        for e in expired:
            coord.append_event(self.g, e["claim_id"], "LEASE_EXPIRED", ME, "supervisor", e["status"],
                               {"owner": e["owner"], "attempt": e["attempt"], "lease_gen": e["gen"]})
            log.warning("lease of %s on %s expired", e["owner"], e["claim_id"])
        return expired

    def mark_dead(self):
        db.run(self.g, """
            MATCH (h:WorkerHeartbeat)
            WHERE h.last_seen < $cutoff AND NOT h.state IN ['stopped', 'killed', 'dead']
            SET h.state = 'dead'
        """, {"cutoff": db.now_ms() - int(3 * config.LEASE_TTL_S * 1000)})

    def handle_commands(self) -> bool:
        """Returns False when a SHUTDOWN was requested."""
        cmds = db.run(self.g, """
            MATCH (c:Command {status: 'PENDING'}) RETURN c.cmd_id AS id, c.type AS type, c.target AS target
            ORDER BY c.created_at
        """)
        keep_running = True
        for c in cmds:
            ok, note = True, None
            if c["type"] == "KILL":
                ok = self.kill(c["target"])
                note = None if ok else "no such running worker"
            elif c["type"] == "START":
                note = self.spawn(c["target"])
            elif c["type"] == "SHUTDOWN":
                keep_running = False
            else:
                ok, note = False, "unknown command"
            db.run(self.g, "MATCH (c:Command {cmd_id: $id}) SET c.status = $s, c.done_at = $now, c.note = $note",
                   {"id": c["id"], "s": "DONE" if ok else "FAILED", "now": db.now_ms(), "note": note})
        return keep_running

    def shutdown_requested(self) -> bool:
        r = db.one(self.g, "MATCH (s:Control {id: 'global'}) RETURN s.shutdown_at AS t")
        return bool(r and r["t"] and r["t"] >= self.started_at)

    def run(self):
        db.run(self.g, "MERGE (s:Control {id: 'global'}) SET s.supervisor_started = $now", {"now": self.started_at})
        for role, n in self.pool.items():
            for _ in range(n):
                self.spawn(role)
        try:
            while True:
                coord.heartbeat(self.g, ME, "supervisor", "running")
                if not self.handle_commands() or self.shutdown_requested():
                    break
                self.reap_leases()
                self.mark_dead()
                time.sleep(self.tick_s)
        finally:
            for agent_id, p in self.procs.items():
                if p.poll() is None:
                    p.kill()
                    p.wait()
            coord.heartbeat(self.g, ME, "supervisor", "stopped")
            log.info("supervisor stopped")
