"""Semantic and procedural memory maintenance (Curator).

A Finding is keyed by (denial reason, clause lineage, evidence that won, conditions).
It is valid in every policy version whose clause for that lineage has the same policy fingerprint
as the clause it was learned on. New verified outcomes strengthen or contradict
Findings, and a new policy version marks dependent Findings stale.
"""
import hashlib
import json

from claimbridge import db

# ---------------------------------------------------------------------------- outcomes


def outcome_context(g, cid: str) -> dict | None:
    """Everything the Curator needs about a claim whose real outcome was recorded."""
    return db.one(g, """
        MATCH (c:Claim {claim_id: $cid})-[:GOVERNED_BY]->(v:PolicyVersion)
        MATCH (c)-[:DENIED_FOR]->(r:DenialReason)
        MATCH (c)-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(cc:Clause)
        MATCH (c)-[:RESOLVED_BY]->(res:Resolution)
        OPTIONAL MATCH (c)-[:HAS_EVIDENCE]->(ev0:Evidence)-[:OF_TYPE]->(et:EvidenceType) WHERE coalesce(ev0.withdrawn, false) = false
        WITH c, v, r, cc, res, collect(DISTINCT et.code) AS have
        OPTIONAL MATCH (c)-[:CONSIDERED {verdict: 'ACCEPTED'}]->(af:Finding)
        RETURN c.claim_id AS claim_id, v.version_id AS version, r.code AS reason,
               cc.clause_id AS clause_id, cc.lineage_id AS lineage, cc.params AS params, cc.fingerprint AS fingerprint,
               coalesce(cc.req_emergency, false) AS clause_req_emergency,
               c.is_emergency AS is_emergency, c.in_network AS in_network,
               res.resolution_id AS resolution_id, res.outcome AS outcome, res.confirmed_evidence AS confirmed_evidence,
               have, collect(af.finding_id) AS accepted
    """, {"cid": cid})


def findings_on(g, reason: str, lineage: str, version: str) -> list[dict]:
    return db.run(g, """
        MATCH (f:Finding)-[:FOR_REASON]->(:DenialReason {code: $reason})
        MATCH (f)-[:ON_LINEAGE]->(:Clause {lineage_id: $lineage})
        MATCH (f)-[:VALID_IN]->(:PolicyVersion {version_id: $version})
        OPTIONAL MATCH (f)-[:NEEDS_EVIDENCE]->(e:EvidenceType)
        WITH f, collect(e.code) AS needs
        RETURN f.finding_id AS finding_id, needs, f.req_emergency AS req_emergency,
               f.req_in_network AS req_in_network, f.status AS status
        ORDER BY finding_id
    """, {"reason": reason, "lineage": lineage, "version": version})


def strengthen(g, finding_id: str, resolution_id: str, now: int) -> dict:
    return db.one(g, """
        MATCH (f:Finding {finding_id: $fid}), (res:Resolution {resolution_id: $rid})
        MERGE (f)-[:DERIVED_FROM]->(res)
        WITH f
        MATCH (f)-[:DERIVED_FROM]->(d:Resolution)
        WITH f, count(d) AS wins
        OPTIONAL MATCH (f)-[:CONTRADICTED_BY]->(x:Resolution)
        WITH f, wins, count(x) AS n
        SET f.wins = wins, f.support = wins, f.updated_at = $now,
            f.confidence = round(1000.0 * (wins + 1) / (wins + n + 2)) / 1000.0,
            f.status = CASE WHEN n >= wins THEN 'CONTRADICTED'
                            WHEN f.status = 'CONTRADICTED' THEN 'ACTIVE' ELSE f.status END
        RETURN f.finding_id AS finding_id, f.wins AS wins, f.confidence AS confidence, f.status AS status
    """, {"fid": finding_id, "rid": resolution_id, "now": now})


def contradict(g, finding_id: str, resolution_id: str, now: int) -> dict:
    """Q9: a verified loss under the same conditions lowers confidence; enough of them
    flip the Finding to CONTRADICTED."""
    return db.one(g, """
        MATCH (f:Finding {finding_id: $fid}), (r:Resolution {resolution_id: $rid})
        MERGE (f)-[:CONTRADICTED_BY]->(r)
        WITH f
        MATCH (f)-[:CONTRADICTED_BY]->(x:Resolution)
        WITH f, count(x) AS n
        SET f.confidence = round(1000.0 * (f.wins + 1) / (f.wins + n + 2)) / 1000.0,
            f.status     = CASE WHEN n >= f.wins THEN 'CONTRADICTED' ELSE f.status END,
            f.updated_at = $now
        RETURN f.finding_id AS finding_id, f.status AS status, f.confidence AS confidence, n AS contradictions
    """, {"fid": finding_id, "rid": resolution_id, "now": now})


def create_finding(g, ctx: dict, needs: list[str], now: int) -> dict:
    """A new Finding learned from one verified win. VALID_IN is computed in the graph:
    every version whose clause for this lineage has the same policy fingerprint."""
    identity = [ctx["reason"], ctx["lineage"], ctx.get("fingerprint"), sorted(needs),
                ctx["is_emergency"], ctx["in_network"]]
    suffix = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    fid = f"F-L-{ctx['lineage'].removeprefix('L-')}-{suffix}"
    req_em = ctx["is_emergency"]
    return db.one(g, """
        MATCH (dr:DenialReason {code: $reason}), (cc:Clause {clause_id: $clause_id}),
              (res:Resolution {resolution_id: $rid})
        OPTIONAL MATCH (accepted:Finding)-[:RECOMMENDS]->(pb0:Playbook)
        WHERE accepted.finding_id IN $accepted
        OPTIONAL MATCH (pb1:Playbook)-[:FOR_REASON]->(dr)
        WITH dr, cc, res, coalesce(head(collect(DISTINCT pb0.playbook_id)),
                                   head(collect(DISTINCT pb1.playbook_id))) AS pid
        OPTIONAL MATCH (pb:Playbook {playbook_id: pid})
        MERGE (f:Finding {finding_id: $fid})
        ON CREATE SET f.status = 'ACTIVE', f.support = 1, f.wins = 1, f.confidence = 0.667,
                      f.req_emergency = $req_em, f.req_in_network = $req_net,
                      f.origin = 'learned', f.created_at = $now, f.updated_at = $now
        MERGE (f)-[:FOR_REASON]->(dr)
        MERGE (f)-[:ON_LINEAGE]->(cc)
        MERGE (f)-[:DERIVED_FROM]->(res)
        FOREACH (_ IN CASE WHEN pb IS NULL THEN [] ELSE [1] END | MERGE (f)-[:RECOMMENDS]->(pb))
        WITH f, cc
        MATCH (v:PolicyVersion)-[:CONTAINS]->(x:Clause {lineage_id: cc.lineage_id})
        WHERE x.fingerprint IS NOT NULL AND x.fingerprint = cc.fingerprint
        MERGE (f)-[:VALID_IN]->(v)
        WITH f, collect(v.version_id) AS valid
        UNWIND (CASE WHEN size($needs) = 0 THEN [null] ELSE $needs END) AS code
        OPTIONAL MATCH (e:EvidenceType {code: code})
        FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END | MERGE (f)-[:NEEDS_EVIDENCE]->(e))
        WITH f, valid
        MATCH (latest:PolicyVersion) WHERE NOT (latest)<-[:SUCCEEDS]-()
        SET f.status = CASE WHEN latest.version_id IN valid THEN 'ACTIVE' ELSE 'STALE' END
        RETURN DISTINCT f.finding_id AS finding_id, valid, f.status AS status
    """, {"fid": fid, "reason": ctx["reason"], "clause_id": ctx["clause_id"], "rid": ctx["resolution_id"],
          "accepted": ctx["accepted"], "needs": needs, "req_em": req_em, "req_net": ctx["in_network"], "now": now})


def set_statement(g, finding_id: str, statement: str):
    db.run(g, "MATCH (f:Finding {finding_id: $fid}) SET f.statement = $s",
           {"fid": finding_id, "s": statement})


def record_playbook_use(g, cid: str, outcome: str) -> str | None:
    """The resolution followed the playbook its accepted precedent recommends (or the
    reason's default playbook). Updates uses / wins."""
    r = db.one(g, """
        MATCH (c:Claim {claim_id: $cid})-[:RESOLVED_BY]->(res:Resolution)
        MATCH (c)-[:DENIED_FOR]->(dr:DenialReason)
        OPTIONAL MATCH (c)-[:CONSIDERED {verdict: 'ACCEPTED'}]->(:Finding)-[:RECOMMENDS]->(pb0:Playbook)
        OPTIONAL MATCH (pb1:Playbook)-[:FOR_REASON]->(dr)
        WITH res, coalesce(head(collect(DISTINCT pb0.playbook_id)),
                           head(collect(DISTINCT pb1.playbook_id))) AS pid
        MATCH (pb:Playbook {playbook_id: pid})
        MERGE (res)-[:FOLLOWED]->(pb)
        WITH pb
        MATCH (r:Resolution)-[:FOLLOWED]->(pb)
        WITH pb, count(DISTINCT r) AS uses,
             count(DISTINCT CASE WHEN r.outcome = 'OVERTURNED' THEN r END) AS wins
        SET pb.uses = uses, pb.wins = wins
        RETURN pb.playbook_id AS playbook_id
    """, {"cid": cid, "outcome": outcome})
    return r["playbook_id"] if r else None


# ------------------------------------------------------------------- policy versions


def mark_stale(g, new_version: str, now: int) -> list[dict]:
    """Q6 step 1: lineages whose policy content changed in the new version make the Findings
    learned on them stale (they keep VALID_IN for the older versions)."""
    return db.run(g, """
        MATCH (new:Clause {version_id: $v})-[:SUPERSEDES]->(old:Clause)
        WHERE new.fingerprint IS NULL OR old.fingerprint IS NULL OR new.fingerprint <> old.fingerprint
        MATCH (f:Finding)-[:ON_LINEAGE]->(:Clause {lineage_id: new.lineage_id})
        MERGE (f)-[:STALE_BECAUSE]->(new)
        SET f.status = CASE WHEN f.status = 'CONTRADICTED' THEN f.status ELSE 'STALE' END,
            f.updated_at = $now
        RETURN f.finding_id AS finding_id, old.clause_id AS old_clause, new.clause_id AS new_clause,
               f.status AS status
        ORDER BY finding_id
    """, {"v": new_version, "now": now})


def carry_forward(g, new_version: str) -> list[str]:
    """Q6 step 2: Findings on lineages that did not change stay valid in the new version."""
    return [r["finding_id"] for r in db.run(g, """
        MATCH (new:Clause {version_id: $v})-[:SUPERSEDES]->(old:Clause)
        WHERE new.fingerprint IS NOT NULL AND new.fingerprint = old.fingerprint
        MATCH (pv_new:PolicyVersion {version_id: $v}),
              (pv_old:PolicyVersion {version_id: old.version_id})
        MATCH (f:Finding)-[:ON_LINEAGE]->(:Clause {lineage_id: new.lineage_id})
        MATCH (f)-[:VALID_IN]->(pv_old)
        MERGE (f)-[:VALID_IN]->(pv_new)
        RETURN DISTINCT f.finding_id AS finding_id
        ORDER BY finding_id
    """, {"v": new_version})]
