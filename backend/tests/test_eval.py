"""Evaluation plumbing: scoring, the baseline index and answer mapping (fake LLM, no network)."""
from claimbridge import config
from claimbridge.evaluation import baseline as bl
from claimbridge.evaluation.harness import predict_baseline
from claimbridge.evaluation.score import score
from claimbridge.seed.generate import load_cases


def _pred(**kw):
    base = {"reason": None, "version": None, "accepted": [], "rejected": {}, "missing": [],
            "disposition": None, "items_total": 1, "items_unsupported": 0, "leaked_fields": 0}
    return {**base, **kw}


def test_score_counts_wrong_precedents_and_stale(truth):
    t1, n1 = truth["EV-T1-01"], truth["EV-N-01"]
    perfect = _pred(reason=t1["expected_reason"], version=t1["expected_version"],
                    accepted=[], missing=t1["expected_missing_evidence"],
                    disposition=t1["expected_disposition"], rejected={"F-MRI-REFERRAL": "VERSION_DRIFT"})
    naive = _pred(reason=t1["expected_reason"], version="V2025", accepted=["F-MRI-REFERRAL"],
                  missing=[], disposition="APPEAL_VIABLE", items_unsupported=1)
    good_n1 = _pred(reason=n1["expected_reason"], version=n1["expected_version"],
                    accepted=n1["expected_applicable_findings"], missing=n1["expected_missing_evidence"],
                    disposition=n1["expected_disposition"])
    sub = {"EV-T1-01": t1, "EV-N-01": n1}
    a = score({"EV-T1-01": perfect, "EV-N-01": good_n1}, sub)
    b = score({"EV-T1-01": naive, "EV-N-01": good_n1}, sub)
    assert a["metrics"]["all_correct"] == 1.0 and a["metrics"]["M4_wrong_precedent_rate"] == 0
    assert a["metrics"]["M8_stale_precedent_explained"] == 1.0
    assert b["metrics"]["M4_wrong_precedent_rate"] == 0.5
    assert b["wrong_precedent_by_code"] == {"VERSION_DRIFT": 1}
    assert b["metrics"]["M8_stale_precedent_avoided"] == 0.0
    assert b["metrics"]["M7_unsupported_item_rate"] == 0.5


def test_baseline_index_and_answer(seeded):
    model = config.BASELINE_EMBED_MODEL
    name = bl.build_index(model)
    assert name.startswith("claimbridge_test_baseline")
    hits = bl.retrieve(model, "Outpatient MRI. Prior authorization was not obtained.", 8, "TEN-01")
    assert len(hits) == 8 and all(h["chunk_id"].startswith(("CL-", "CS-")) for h in hits)
    assert all(h["kind"] == "clause" or h["tenant_id"] == "TEN-01" for h in hits)

    case = next(c for c in load_cases() if c["claim_id"] == "EV-T1-01")
    res = bl.answer(case, model)
    chunk_findings = {c["chunk_id"]: c.get("finding_id") for c in bl.corpus()}
    p = predict_baseline(case, res, chunk_findings)
    assert p["version"] == "V2026" and p["items_total"] == 1
    # The fake baseline reuses the top retrieved case; it maps to that case's Finding (if any).
    for cid in p["precedent_cases"]:
        assert chunk_findings.get(f"CS-{cid}") in (None, *p["accepted"])
