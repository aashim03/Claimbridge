"""Ground truth for the trap cases matches the intended design (no database needed)."""
from claimbridge.knowledge import load


def rejected(t):
    return {r["finding_id"]: r["code"] for r in t["expected_rejected_findings"]}


def test_versions_and_lineages_expand():
    kn = load()
    assert kn.clause("V2026", "L-MRI-PREAUTH").supersedes == "C-2025-MRI-PREAUTH"
    assert kn.clause("V2024", "L-GENETIC-TEST") is None
    assert kn.route("EXCLUDED_SERVICE", "GENETIC_TEST", "V2024").lineage_id == "L-EXPERIMENTAL-EXCL"
    assert kn.route("EXCLUDED_SERVICE", "GENETIC_TEST", "V2025").lineage_id == "L-GENETIC-TEST"
    assert kn.route("NOT_MED_NECESSARY", "MRI", "V2025").lineage_id == "L-MED-NECESSITY-DEF"


def test_finding_validity_follows_clause_params():
    kn = load()
    valid = {f.finding_id: f.valid_in for f in kn.findings}
    assert valid["F-MRI-REFERRAL"] == ["V2024", "V2025"]
    assert valid["F-OON-ER"] == ["V2024", "V2025"]
    assert valid["F-DME-NECESSITY"] == ["V2024", "V2025", "V2026"]
    assert valid["F-BARIATRIC"] == ["V2025", "V2026"]


def test_t1_version_drift(truth):
    t = truth["EV-T1-01"]
    assert t["expected_version"] == "V2026"
    assert rejected(t)["F-MRI-REFERRAL"] == "VERSION_DRIFT"
    assert t["expected_disposition"] == "APPEAL_NEEDS_EVIDENCE"


def test_t2_lineage_mismatch(truth):
    t = truth["EV-T2-01"]
    assert rejected(t)["F-MRI-REFERRAL"] == "LINEAGE_MISMATCH"
    assert t["expected_applicable_findings"] == ["F-INPATIENT-RETRO"]


def test_t3_missing_evidence(truth):
    t = truth["EV-T3-01"]
    assert t["expected_applicable_findings"] == ["F-PHYSIO-NECESSITY"]
    assert t["expected_missing_evidence"] == ["PHYSICIAN_NECESSITY_LETTER", "PROGRESS_NOTES"]


def test_t4_contradicted(truth):
    assert rejected(truth["EV-T4-01"])["F-SLEEP-RETRO"] == "CONTRADICTED"


def test_t5_condition_unmet(truth):
    t = truth["EV-T5-01"]
    assert rejected(t)["F-OON-ER"] == "CONDITION_UNMET"
    assert t["expected_disposition"] == "NO_BASIS_ESCALATE"


def test_t6_no_basis(truth):
    assert truth["EV-T6-01"]["expected_gates"] == ["FILED_LATE"]
    assert truth["EV-T6-02"]["expected_gates"] == ["EXCLUSION_NO_BASIS"]
    assert truth["EV-T6-03"]["expected_gates"] == ["WAITING_NOT_MET"]
    assert all(truth[c]["expected_disposition"] == "NO_BASIS_ESCALATE"
               for c in ("EV-T6-01", "EV-T6-02", "EV-T6-03"))
