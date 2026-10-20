"""Memory under repeated, duplicate and contradictory outcomes. Real FalkorDB; fake LLM."""
import json

from claimbridge import db, report
from claimbridge.agents.curator import Curator
from claimbridge.agents.intake import Intake
from claimbridge.agents.planner import Planner
from claimbridge.agents.retrieval import Retrieval
from claimbridge.agents.verifier import Verifier
from claimbridge.supervisor import approve, declare_evidence, record_outcome
from claimbridge.tools import coordination as coord


def pipeline(g, cid):
    coord.inject(g, [cid])
    for cls in (Intake, Retrieval, Verifier, Planner):
        assert cls(agent_id=f"mem-{cls.role}").step_once()


def learned(g):
    return db.run(g, """MATCH (f:Finding {origin: 'learned'}) OPTIONAL MATCH (f)-[:DERIVED_FROM]->(r:Resolution)
                        OPTIONAL MATCH (f)-[:CONTRADICTED_BY]->(x:Resolution)
                        RETURN f.finding_id AS id, f.status AS status, f.wins AS wins, f.confidence AS confidence,
                               count(DISTINCT r) AS wins_linked, count(DISTINCT x) AS losses ORDER BY id""")


def test_duplicate_confirmation_changes_nothing_and_a_contradiction_weakens_the_learned_precedent(seeded):
    # 1. One recorded win teaches memory.
    pipeline(seeded, "EV-M-A")
    assert approve(seeded, "EV-M-A", "reviewer")
    assert record_outcome(seeded, "EV-M-A", "OVERTURNED", "reviewer", ["EMERGENCY_ATTESTATION", "ITEMIZED_BILL"])
    assert Curator(agent_id="mem-curator").step_once()
    [f] = learned(seeded)
    assert f["wins"] == 1 and f["losses"] == 0 and f["status"] == "ACTIVE" and 0 < f["confidence"] < 1

    # 2. Confirming the same outcome again is refused, and replaying the memory step cannot double count.
    assert record_outcome(seeded, "EV-M-A", "OVERTURNED", "reviewer", ["EMERGENCY_ATTESTATION", "ITEMIZED_BILL"]) is False
    from claimbridge.agents.curator import curate
    db.run(seeded, "MATCH (c:Claim {claim_id: 'EV-M-A'}) SET c.status = 'VERIFIED_OUTCOME'")
    curate(seeded, "EV-M-A")
    curate(seeded, "EV-M-A")
    db.run(seeded, "MATCH (c:Claim {claim_id: 'EV-M-A'}) SET c.status = 'CURATED'")      # put it back; a worker would have
    assert learned(seeded) == [f]

    # 3. A later claim is offered the learned document as a suggestion ...
    pipeline(seeded, "EV-M-B1")
    b1 = report.actual(seeded, "EV-M-B1")
    assert b1["missing"] == ["ITEMIZED_BILL"] and b1["disposition"] == "APPEAL_NEEDS_EVIDENCE"
    # ... the policyholder produces it, and the appeal is nevertheless UPHELD under the same conditions.
    declare_evidence(seeded, "EV-M-B1", "ITEMIZED_BILL", "bill of 2 Feb", "alice")
    assert Planner(agent_id="mem-planner").step_once()
    assert approve(seeded, "EV-M-B1", "reviewer")
    assert record_outcome(seeded, "EV-M-B1", "UPHELD", "reviewer")
    assert Curator(agent_id="mem-curator-2").step_once()

    # 4. The precedent is weakened, not erased: one win against one loss is CONTRADICTED and its score fell.
    [after] = learned(seeded)
    assert after["id"] == f["id"] and after["wins"] == 1 and after["losses"] == 1
    assert after["status"] == "CONTRADICTED" and after["confidence"] < f["confidence"]

    # 5. The next similar claim is told not to rely on it, and its checklist falls back to the modeled requirements.
    pipeline(seeded, "EV-M-B2")
    b2 = report.actual(seeded, "EV-M-B2")
    assert {v["finding_id"]: v["code"] for v in b2["verdicts"]}[f["id"]] == "CONTRADICTED"
    assert "ITEMIZED_BILL" not in b2["missing"] and b2["disposition"] == "APPEAL_VIABLE"
    items = b2["recommendation"]["items"]
    assert any(i["kind"] == "REJECTED_PRECEDENT" and f["id"] in i["cites"] for i in items)
    assert not any(i["kind"] == "EVIDENCE_NEEDED" and "ITEMIZED_BILL" in i["cites"] for i in items)
    assert b2["recommendation"]["support_state"] == "NO_PRECEDENT"                 # no score is shown for a precedent that was refuted
