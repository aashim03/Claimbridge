"""A policy version is published while a claim is mid-flight.

Contract: a claim is pinned at Intake to the policy version in force on its SERVICE DATE.
Publishing a later version marks memory stale for FUTURE claims, but never rewrites the
outputs of a claim already pinned. Real FalkorDB; no LLM."""
import pytest

from claimbridge import db, report
from claimbridge.agents.curator import publish_version
from claimbridge.agents.intake import Intake
from claimbridge.agents.planner import Planner
from claimbridge.agents.retrieval import Retrieval
from claimbridge.agents.verifier import Verifier
from claimbridge.seed.load import reset
from claimbridge.tools import coordination as coord

STEPS = [Intake, Retrieval, Verifier, Planner]
CID = "EV-N-01"          # service date in 2025; its precedent F-MRI-REFERRAL turns stale when 2026 is published


def outcome(g):
    rec = report.actual(g, CID)
    verdicts = db.run(g, """MATCH (:Claim {claim_id:$c})-[k:CONSIDERED]->(f:Finding)
                            RETURN f.finding_id AS f, k.reason_code AS code ORDER BY f""", {"c": CID})
    pinned = db.one(g, "MATCH (:Claim {claim_id:$c})-[:GOVERNED_BY]->(v) RETURN v.version_id AS v", {"c": CID})["v"]
    return {"status": rec["status"], "pinned": pinned, "disposition": rec["disposition"], "missing": rec["missing"],
            "verdicts": [(v["f"], v["code"]) for v in verdicts],
            "items": [(i["kind"], i["text"], tuple(sorted(i["cites"]))) for i in rec["recommendation"]["items"]],
            "summary": rec["recommendation"]["summary"]}


def run(g, classes):
    for cls in classes:
        assert cls(agent_id=f"race-{cls.role}").step_once()


@pytest.fixture(scope="module")
def reference():
    reset(upto="V2025")
    g = db.connect()
    coord.inject(g, [CID])
    run(g, STEPS)
    ref = outcome(g)
    assert ref["pinned"] == "V2025" and ("F-MRI-REFERRAL", "ACCEPTED") in ref["verdicts"]
    return ref


@pytest.mark.parametrize("published_after", [0, 1, 2, 3], ids=["before-intake", "after-intake", "after-retrieval", "after-verifier"])
def test_publishing_mid_flight_does_not_change_a_pinned_claim(reference, published_after):
    reset(upto="V2025")
    g = db.connect()
    coord.inject(g, [CID])
    run(g, STEPS[:published_after])
    published = publish_version(g, "V2026")                       # lands between two agents' steps
    assert "F-MRI-REFERRAL" in [s["finding_id"] for s in published["stale"]]
    run(g, STEPS[published_after:])
    got = outcome(g)
    assert got == reference, f"output changed when 2026 was published after step {published_after}"
    # Memory itself did change: for a claim filed from now on, the precedent is limited.
    status = db.one(g, "MATCH (f:Finding {finding_id:'F-MRI-REFERRAL'}) RETURN f.status AS s")["s"]
    assert status == "STALE"
