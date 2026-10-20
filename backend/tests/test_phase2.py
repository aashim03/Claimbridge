"""Phase 2: planner + citation guard, curator memory, staleness, supervisor reaper.
Agents run in-process (step_once) against the fake LLM provider."""
import pytest

from claimbridge import db, guard, report
from claimbridge.agents.curator import Curator, publish_version
from claimbridge.agents.intake import Intake
from claimbridge.agents.planner import Planner
from claimbridge.agents.retrieval import Retrieval
from claimbridge.agents.verifier import Verifier
from claimbridge.supervisor import Supervisor, approve, record_outcome
from claimbridge.tools import coordination as coord


def process(g, cid):
    """Run one claim through intake -> planner with in-process workers."""
    coord.inject(g, [cid])
    for cls in (Intake, Retrieval, Verifier, Planner):
        assert cls(agent_id=f"t-{cls.role}").step_once(), cls.role
    return report.actual(g, cid)


def finish(g, cid, outcome):
    assert approve(g, cid, "tester")
    assert record_outcome(g, cid, outcome, "tester")
    assert Curator(agent_id="t-curator").step_once()
    return coord.timeline(g, cid)[-1]


# ----------------------------------------------------------------------- guard

CTX = {
    "clause": {"clause_id": "C-1", "title": "Some clause", "section": "1.1"},
    "gates": [],
    "evidence": [{"code": "E1", "name": "Letter", "satisfied": False},
                 {"code": "E2", "name": "Bill", "satisfied": True}],
    "rejected_precedents": [{"finding_id": "F-OLD", "code": "VERSION_DRIFT",
                             "learned_on": "C-0", "governing": "C-1", "contradicted_by": []}],
    "accepted_precedents": [],
}
ALLOWED = {"C-1": "Clause", "C-0": "Clause", "E1": "EvidenceType", "E2": "EvidenceType", "F-OLD": "Finding"}


def test_guard_drops_bad_items_and_adds_required():
    draft = [
        {"kind": "ACTION", "text": "Call the plan.", "cite_ids": []},                       # uncited
        {"kind": "ACTION", "text": "Use precedent F-X.", "cite_ids": ["F-X"]},             # unknown id
        {"kind": "ACTION", "text": "This will be approved.", "cite_ids": ["C-1"]},          # promise
        {"kind": "ACTION", "text": "Appeal citing the clause.", "cite_ids": ["C-1"]},       # good
    ]
    items, stats = guard.apply(draft, CTX, ALLOWED, "APPEAL_NEEDS_EVIDENCE")
    assert (stats["dropped_uncited"], stats["dropped_unknown_id"], stats["dropped_promise"]) == (1, 1, 1)
    kinds = {(i["kind"], tuple(i["cite_ids"])) for i in items}
    assert ("ACTION", ("C-1",)) in kinds
    assert ("EVIDENCE_NEEDED", ("E1", "C-1")) in kinds          # missing evidence was added
    assert any(i["kind"] == "REJECTED_PRECEDENT" and "F-OLD" in i["cite_ids"] for i in items)
    assert all(i["cite_ids"] for i in items)


def test_guard_adds_warning_when_no_basis():
    items, _ = guard.apply([], {**CTX, "gates": ["FILED_LATE"]}, ALLOWED, "NO_BASIS_ESCALATE")
    assert items[0]["kind"] == "WARNING" and items[0]["cite_ids"] == ["C-1"]


def test_guard_drops_moot_steps_when_no_basis():
    draft = [{"kind": "EVIDENCE_NEEDED", "text": "Get the letter.", "cite_ids": ["E1", "C-1"]},
             {"kind": "ACTION", "text": "File the appeal.", "cite_ids": ["C-1"]},
             {"kind": "REJECTED_PRECEDENT", "text": "Do not rely on F-OLD.", "cite_ids": ["F-OLD", "C-1"]}]
    items, stats = guard.apply(draft, {**CTX, "gates": ["FILED_LATE"]}, ALLOWED, "NO_BASIS_ESCALATE")
    assert stats["dropped_moot"] == 2
    assert not any(i["kind"] == "EVIDENCE_NEEDED" for i in items)
    assert any(i["kind"] == "ACTION" and "Escalate" in i["text"] for i in items)
    assert any(i["kind"] == "REJECTED_PRECEDENT" for i in items)


# ------------------------------------------------------------ planner + memory

def test_planner_writes_cited_recommendation(seeded, truth):
    a = process(seeded, "EV-T1-01")
    assert a["status"] == "AWAITING_REVIEW"
    assert a["disposition"] == truth["EV-T1-01"]["expected_disposition"]
    rec = a["recommendation"]
    assert rec["items"] and all(i["cites"] for i in rec["items"])
    assert any("F-MRI-REFERRAL" in i["cites"] for i in rec["items"] if i["kind"] == "REJECTED_PRECEDENT")


def test_no_basis_disposition(seeded, truth):
    a = process(seeded, "EV-T6-01")
    assert a["disposition"] == "NO_BASIS_ESCALATE"
    assert a["recommendation"]["items"][0]["kind"] in ("WARNING", "EVIDENCE_NEEDED", "REJECTED_PRECEDENT")


def test_memory_gain_learns_and_reuses(seeded):
    b1 = process(seeded, "EV-M-B1")
    assert not [v for v in b1["verdicts"] if v["code"] == "ACCEPTED"]
    process(seeded, "EV-M-A")
    ev = finish(seeded, "EV-M-A", "OVERTURNED")
    assert ev["type"] == "CURATOR_DONE" and '"learned"' in ev["payload"]
    b2 = process(seeded, "EV-M-B2")
    accepted = [v["finding_id"] for v in b2["verdicts"] if v["code"] == "ACCEPTED"]
    assert accepted and accepted[0].startswith("F-L-AMBULANCE")
    assert b2["recommendation"]["confidence"] > b1["recommendation"]["confidence"]
    f = db.one(seeded, """MATCH (f:Finding {finding_id: $id})-[:VALID_IN]->(v)
                          RETURN f.status AS s, collect(v.version_id) AS vs""", {"id": accepted[0]})
    assert f["s"] == "ACTIVE" and sorted(f["vs"]) == ["V2024", "V2025", "V2026"]


def test_win_strengthens_existing_finding(seeded):
    before = db.one(seeded, "MATCH (f:Finding {finding_id: 'F-CODING'}) RETURN f.wins AS w")["w"]
    process(seeded, "EV-T7-01")
    finish(seeded, "EV-T7-01", "OVERTURNED")
    after = db.one(seeded, "MATCH (f:Finding {finding_id: 'F-CODING'}) RETURN f.wins AS w")["w"]
    assert after == before + 1


def test_loss_contradicts_finding(seeded):
    process(seeded, "EV-N-04")
    finish(seeded, "EV-N-04", "UPHELD")
    f = db.one(seeded, "MATCH (f:Finding {finding_id: 'F-ER-NECESSITY'}) RETURN f.confidence AS c, f.status AS s")
    assert f["c"] == pytest.approx(0.6) and f["s"] == "ACTIVE"   # 2 wins, 1 contradiction


def test_reaper_records_expired_lease_once(seeded):
    db.run(seeded, """MATCH (c:Claim {claim_id: 'EV-N-06'})
                      SET c.status = 'RECEIVED', c.lease_owner = 'ghost', c.lease_until = 1, c.attempt = 1""")
    sup = Supervisor(pool={})
    assert [e["claim_id"] for e in sup.reap_leases()] == ["EV-N-06"]
    assert sup.reap_leases() == []
    assert coord.timeline(seeded, "EV-N-06")[-1]["type"] == "LEASE_EXPIRED"


# --------------------------------------------------------------- staleness

def test_publish_marks_changed_lineages_stale():
    from claimbridge.seed.load import reset
    reset(upto="V2025")
    g = db.connect()
    assert db.one(g, "MATCH (f:Finding) WHERE f.status = 'STALE' RETURN count(f) AS n")["n"] == 0
    out = publish_version(g, "V2026")
    stale = sorted(s["finding_id"] for s in out["stale"])
    assert stale == ["F-MRI-REFERRAL", "F-OON-ER", "F-PHYSIO-NOTES", "F-TIMELY-180"]
    assert "F-CODING" in out["carried_forward"] and "F-MRI-REFERRAL" not in out["carried_forward"]
    # A stale Finding still applies to claims under the versions it was learned on.
    vs = db.one(g, "MATCH (:Finding {finding_id: 'F-MRI-REFERRAL'})-[:VALID_IN]->(v) "
                   "RETURN collect(v.version_id) AS vs")["vs"]
    assert sorted(vs) == ["V2024", "V2025"]
    with pytest.raises(ValueError):
        publish_version(g, "V2026")
