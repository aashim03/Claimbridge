"""The Cypher tools reproduce ground truth for every evaluation claim.

Intake is bypassed here (reason and cited clause are written from ground truth), so
these tests isolate the graph logic: version selection, applicability, gates and
evidence gaps.
"""
import pytest

from claimbridge.tools import applicability, evidence, retrieval, versions


@pytest.fixture(scope="module")
def processed(seeded, truth):
    g = seeded
    for cid, t in truth.items():
        assert versions.select_version(g, cid) == t["expected_version"], cid
        assert versions.write_classification(g, cid, t["expected_reason"], t["expected_clause"])
        cands = [{"finding_id": c["finding_id"], "source": "graph", "score": 1.0}
                 for c in retrieval.graph_candidates(g, cid)]
        retrieval.write_candidates(g, cid, cands)
        applicability.check_applicability(g, cid)
        applicability.gates(g, cid)
    return g


def test_route_clause_matches_rules(seeded, truth):
    for cid, t in truth.items():
        versions.select_version(seeded, cid)
        assert versions.route_clause(seeded, cid, t["expected_reason"])["clause_id"] == t["expected_clause"], cid


def test_applicability_verdicts(processed, truth):
    from claimbridge.report import actual
    for cid, t in truth.items():
        codes = {v["finding_id"]: v["code"] for v in actual(processed, cid)["verdicts"]}
        accepted = sorted(f for f, c in codes.items() if c == "ACCEPTED")
        assert accepted == t["expected_applicable_findings"], cid
        for r in t["expected_rejected_findings"]:
            assert codes[r["finding_id"]] == r["code"], (cid, r)


def test_gates(processed, truth):
    from claimbridge.report import actual
    for cid, t in truth.items():
        assert sorted(actual(processed, cid)["gates"] or []) == sorted(t["expected_gates"]), cid


def test_evidence_gap(processed, truth):
    for cid, t in truth.items():
        assert evidence.missing_evidence(processed, cid) == t["expected_missing_evidence"], cid


def test_version_drift_points_at_superseding_clause(processed):
    rows = {r["finding_id"]: r for r in applicability.check_applicability(processed, "EV-T1-01")}
    r = rows["F-MRI-REFERRAL"]
    assert r["code"] == "VERSION_DRIFT"
    assert r["learned_on_clause"] == "C-2025-MRI-PREAUTH"
    assert r["governing_clause"] == "C-2026-MRI-PREAUTH"


def test_contradiction_returns_contradicting_resolutions(processed):
    rows = {r["finding_id"]: r for r in applicability.check_applicability(processed, "EV-T4-01")}
    assert rows["F-SLEEP-RETRO"]["code"] == "CONTRADICTED"
    assert len(rows["F-SLEEP-RETRO"]["contradicted_by"]) == 2
