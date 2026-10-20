"""Memory Curator: VERIFIED_OUTCOME -> CURATED.

When a human records the real outcome of a claim, the Curator turns it into memory:
  OVERTURNED  strengthen the matching Finding, or learn a new one
  UPHELD      contradict Findings whose conditions and evidence were all met
  PARTIAL     no Finding change
Playbook usage is updated either way. Policy-version publishing (mode B) lives in
`publish_version` below and is triggered by the Supervisor or the CLI.
"""
from claimbridge import db
from claimbridge.tools.coordination import FencedGraph
from claimbridge.agents.base import Context, NeedsHuman, StepResult, Worker
from claimbridge.knowledge import load
from claimbridge.seed.load import load_version
from claimbridge.tools import evidence, memory


def _conditions_hold(f: dict, octx: dict) -> bool:
    if f["req_emergency"] is not None and f["req_emergency"] != octx["is_emergency"]:
        return False
    if f["req_in_network"] is not None and f["req_in_network"] != octx["in_network"]:
        return False
    return True


def curate(g, cid: str, me: str | None = None) -> dict:
    if me is not None:
        g = FencedGraph(g, cid, me)
    octx = memory.outcome_context(g, cid)
    if not octx:
        raise NeedsHuman("outcome recorded without classification or resolution")
    now = db.now_ms()
    cands = [f for f in memory.findings_on(g, octx["reason"], octx["lineage"], octx["version"])
             if _conditions_hold(f, octx)]
    have = set(octx["have"])
    result = {"outcome": octx["outcome"], "action": "none", "findings": []}

    if octx["outcome"] == "OVERTURNED":
        # The evidence that won = the required evidence this claim actually had.
        key = (sorted(octx["confirmed_evidence"]) if octx.get("confirmed_evidence") is not None else
               sorted(e["evidence"] for e in evidence.evidence_gap(g, cid) if e["satisfied"]))
        match = next((f for f in cands if sorted(f["needs"]) == key and f["status"] != "CONTRADICTED"), None)
        if match:
            result["action"] = "strengthened"
            result["findings"].append(memory.strengthen(g, match["finding_id"], octx["resolution_id"], now))
        else:
            created = memory.create_finding(g, octx, key, now)
            memory.strengthen(g, created["finding_id"], octx["resolution_id"], now)
            result["action"] = "learned"
            result["findings"].append(created)
        # Repair a retry interrupted between node creation and statement publication.
        fid = result["findings"][0]["finding_id"]
        if fid.startswith("F-L-"):
            kn = load()
            needs = ", ".join(kn.name("evidence_types", e) for e in key) or "no additional evidence"
            cond = " in an emergency" if octx["is_emergency"] else " outside an emergency"
            memory.set_statement(g, fid,
                                 f"{kn.name('denial_reasons', octx['reason'])} denials under "
                                 f"{octx['lineage']}{cond} have recorded overturned outcomes with: {needs}. "
                                 "This is an observed association, not proof that these documents caused the outcome.")
    elif octx["outcome"] == "UPHELD":
        hit = [f for f in cands if set(f["needs"]) <= have]
        for f in hit:
            result["findings"].append(memory.contradict(g, f["finding_id"], octx["resolution_id"], now))
        result["action"] = "contradicted" if hit else "none"
    result["playbook"] = memory.record_playbook_use(g, cid, octx["outcome"])
    return result


def publish_version(g, version_id: str) -> dict:
    """Mode B: load a new policy version, then propagate staleness (Q6)."""
    exists = db.one(g, "MATCH (v:PolicyVersion {version_id: $v}) RETURN v.version_id AS v", {"v": version_id})
    if exists:
        raise ValueError(f"{version_id} is already published")
    n = load_version(g, load(), version_id)
    now = db.now_ms()
    stale = memory.mark_stale(g, version_id, now)
    carried = memory.carry_forward(g, version_id)
    db.run(g, "MERGE (s:Control {id: 'global'}) SET s.world = $v", {"v": version_id})
    return {"version": version_id, "clauses": n, "stale": stale, "carried_forward": carried}


class Curator(Worker):
    role = "curator"
    input_state = "VERIFIED_OUTCOME"
    output_state = "CURATED"

    def work(self, ctx: Context) -> StepResult:
        result = curate(ctx.g, ctx.claim_id, ctx.me)
        return StepResult(payload=result, checkpoint=result)
