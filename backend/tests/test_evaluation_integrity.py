"""The evaluation's own bookkeeping: scoring semantics, run identity, never-overwritten output, attribution."""
import json

import pytest

from claimbridge import config, llm
from claimbridge.evaluation import harness
from claimbridge.evaluation import provenance as pv
from claimbridge.evaluation.generalization import judge
from claimbridge.evaluation.score import score


def perfect(t):
    return {"status": "AWAITING_REVIEW", "reason": t["expected_reason"], "version": t["expected_version"],
            "accepted": list(t["expected_applicable_findings"]),
            "rejected": {r["finding_id"]: r["code"] for r in t["expected_rejected_findings"]},
            "missing": list(t["expected_missing_evidence"]), "disposition": t["expected_disposition"],
            "items_total": 2, "items_unsupported": 0, "leaked_fields": 0, "tokens_in": 10, "tokens_out": 5}


@pytest.fixture
def two(truth):
    ids = [c for c in truth if truth[c]["expected_rejected_findings"]][:2]
    return ids, {c: truth[c] for c in ids}


def test_a_hand_off_to_a_person_is_an_abstention_not_a_completed_recommendation(truth, two):
    ids, t = two
    preds = {c: perfect(t[c]) for c in ids}
    preds[ids[0]]["status"] = "NEEDS_HUMAN"
    s = score(preds, t)
    assert s["metrics"]["completion_rate"] == 0.5
    assert s["metrics"]["abstained_to_human"] == 1 and s["metrics"]["no_output"] == 0
    assert s["abstained"] == [ids[0]] and s["per_claim"][ids[0]]["ok"] is False


def test_missing_output_is_a_failure_and_earns_no_stale_avoidance_credit(truth, two):
    ids, t = two
    s = score({ids[1]: perfect(t[ids[1]])}, t)
    assert s["metrics"]["no_output"] == 1 and s["no_output"] == [ids[0]]
    assert s["metrics"]["claims"] == 2 and s["metrics"]["completion_rate"] == 0.5
    assert s["metrics"]["all_correct"] == 0.5
    stale_expected = [r for c in ids for r in t[c]["expected_rejected_findings"] if r["code"] in ("VERSION_DRIFT", "CONTRADICTED")]
    if stale_expected:
        # the claim with no output cannot have "avoided" its stale precedent
        assert s["metrics"]["M8_stale_precedent_avoided"] < 1


def test_recall_over_reachable_precedents_excludes_what_a_tenant_filtered_system_cannot_see(truth):
    cid = next(c for c, t in truth.items() if t["expected_applicable_findings"])
    t = {cid: {**truth[cid], "recoverable_findings": []}}              # no supporting case belongs to this tenant
    s = score({cid: {**perfect(truth[cid]), "accepted": []}}, t)       # a system that cites nothing
    assert s["metrics"]["M3_precedent_recall"] == 0                    # the plain number says it failed ...
    assert s["metrics"]["M3_precedent_recall_reachable"] is None       # ... the reachable one says there was nothing to find
    assert s["metrics"]["claims_with_unreachable_precedent"] == 1


def test_error_causes_are_told_apart():
    assert harness.classify_error(llm.LLMError("GroqProvider 429: Rate limit reached for tokens per day")) == "provider_rate_limit"
    assert harness.classify_error(TimeoutError("request timed out")) == "timeout"
    assert harness.classify_error(llm.LLMError("generation stopped: length")) == "unparseable_or_truncated_generation"
    assert harness.classify_error(llm.LLMError("no API key: set one of GROQ_API_KEY")) == "configuration_or_auth"
    assert harness.classify_error(RuntimeError("boom")) == "other_error"


# ---------------------------------------------------------------------------------------- run identity

@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(config, "ARCHIVE_DIR", tmp_path / "archive")
    for var in ("EVAL_LEDGER", "EVAL_RUN_ID", "EVAL_SYSTEM"):
        monkeypatch.delenv(var, raising=False)
    yield tmp_path
    for var in ("EVAL_LEDGER", "EVAL_RUN_ID", "EVAL_SYSTEM"):
        monkeypatch.delenv(var, raising=False)


def test_a_run_records_what_was_run_and_when(runs):
    d = harness.begin(label="unit")
    r = pv.read_run(d)
    assert r["run_id"] == d.name and r["status"] == "running" and r["invalid_reasons"] == []
    assert len(r["source_sha256"]) == 64 and len(r["dataset"]["all"]) == 64 and set(r["prompts"]) == {"intake", "planner", "baseline"}
    assert r["started_at"][-6] in "+-" and r["started_at"][-3] == ":"              # carries a UTC offset
    assert r["config"]["llm_mode"] and r["config"]["cache_policy"]
    assert d.name != harness.begin(label="second").name                              # every run is a new identity


def test_raw_output_is_never_overwritten(runs):
    harness.begin()
    harness._save("claimbridge", {"predictions": {}}, pv.now_iso())
    first = (harness.raw_dir() / "claimbridge.json").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        harness._save("claimbridge", {"predictions": {"changed": 1}}, pv.now_iso())
    assert (harness.raw_dir() / "claimbridge.json").read_text(encoding="utf-8") == first
    assert harness.has_output("claimbridge") and not harness.has_output("no_memory")


def test_a_source_change_during_the_run_invalidates_it(runs, monkeypatch):
    d = harness.begin()
    monkeypatch.setattr(pv, "source_digest", lambda: "f" * 64)                      # someone edited the code mid-run
    harness._save("claimbridge", {"predictions": {}}, pv.now_iso())
    r = pv.read_run(d)
    assert r["invalid_reasons"] and "source changed" in r["invalid_reasons"][0]
    raw = json.loads((harness.raw_dir() / "claimbridge.json").read_text(encoding="utf-8"))
    assert raw["provenance"]["source_unchanged"] is False
    with pytest.raises(SystemExit, match="invalid"):
        harness.build_report(d) and harness.promote(d.name)


def test_every_llm_call_is_attributed_to_a_system_claim_and_cache_entry(runs, monkeypatch):
    d = harness.begin()
    harness._system("claimbridge")
    from claimbridge.llm.schemas import IntakeExtraction
    llm.complete("intake", "sys", "Denial notice: Claim EV-T1-01 was denied", IntakeExtraction)
    harness._system("baseline_rag")
    llm.complete("intake", "sys", "Denial notice: Claim EV-T1-01 other", IntakeExtraction)
    rows = pv.read_ledger(d)
    assert [(r["system"], r["claim_id"], r["platform"], r["cached"]) for r in rows] == [
        ("claimbridge", "EV-T1-01", "fake", False), ("baseline_rag", "EV-T1-01", "fake", False)]
    assert all(r["run_id"] == d.name and len(r["key"]) == 32 for r in rows)
    assert pv.ledger_summary(d)["fake"] == 2 and pv.ledger_summary(d)["fresh"] == 0
    assert set(pv.ledger_tokens(d, "claimbridge")) <= {"EV-T1-01"}
    assert pv.ledger_tokens(d, "no_memory") == {}                                   # nothing borrowed from another system


def test_the_report_names_its_run_and_does_not_overclaim(runs, truth):
    d = harness.begin(label="unit")
    ids = harness._eval_ids(truth)
    harness._save("claimbridge", {"predictions": {c: perfect(truth[c]) for c in ids}, "memory_gain": None}, pv.now_iso())
    harness._save("baseline_rag", {"predictions": {c: {**perfect(truth[c]), "accepted": []} for c in ids[:-2]}, "memory_gain": None,
                                   "not_run": ids[-2:], "errors": {ids[-2]: {"kind": "provider_rate_limit", "message": "429"},
                                                                   ids[-1]: {"kind": "timeout", "message": "slow"}}}, pv.now_iso())
    out = harness.build_report(d)
    md = (d / "report.md").read_text(encoding="utf-8")
    assert out["valid"] and out["run"]["run_id"] in md and out["run"]["source_sha256"][:16] in md
    assert "provider_rate_limit" in md and "timeout" in md and "Missing outputs and escalations" in md
    assert "What each system can see" in md and "Baseline RAG + findings" in md
    assert "real outcome" not in md.lower() and "independent rule engine" not in md.lower()
    assert "not external validation" in md and "recorded synthetic outcome" in md
    assert out["systems"]["baseline_rag"]["metrics"]["no_output"] == 2 and out["systems"]["baseline_rag"]["metrics"]["claims"] == len(ids)
    assert json.loads((d / "report.json").read_text(encoding="utf-8"))["run"]["run_id"] == d.name


def test_promotion_archives_the_previous_results_and_serves_one_consistent_run(runs, truth):
    ids = harness._eval_ids(truth)
    first = harness.begin(label="first")
    harness._save("claimbridge", {"predictions": {c: perfect(truth[c]) for c in ids}}, pv.now_iso())
    harness.build_report(first)
    harness.promote(first.name)
    assert json.loads((config.RESULTS_DIR / "latest.json").read_text(encoding="utf-8"))["run"]["run_id"] == first.name
    second = harness.begin(label="second")
    harness._save("claimbridge", {"predictions": {c: perfect(truth[c]) for c in ids}}, pv.now_iso())
    harness.build_report(second)
    harness.promote(second.name)
    served = json.loads((config.RESULTS_DIR / "latest.json").read_text(encoding="utf-8"))
    assert served["run"]["run_id"] == second.name
    assert (config.RESULTS_DIR / "raw" / "claimbridge.json").exists() and (config.RESULTS_DIR / "run.json").exists()
    archived = list(config.ARCHIVE_DIR.iterdir())
    assert len(archived) == 1 and first.name in archived[0].name and (archived[0] / "latest.json").exists()


# --------------------------------------------------------------------------- generalization judging

def test_generalization_judge_scores_what_was_pre_registered_and_nothing_else():
    got = {"status": "AWAITING_REVIEW", "reason": "CODING_ERROR", "version": "V2026", "disposition": "APPEAL_NEEDS_EVIDENCE",
           "missing": ["CORRECTED_CODING_SUBMISSION"], "accepted": ["F-CODING"], "escalation_reason": None}
    exp = {"outcome": "complete", "reason": "CODING_ERROR", "version": "V2026", "disposition": "APPEAL_NEEDS_EVIDENCE",
           "missing_evidence": ["CORRECTED_CODING_SUBMISSION"], "applicable_findings": ["F-CODING"]}
    assert judge(exp, got) == []
    assert judge({**exp, "reason": "PREAUTH_MISSING"}, got) == ["reason: expected PREAUTH_MISSING, got CODING_ERROR"]
    assert judge({**exp, "missing_evidence": None, "applicable_findings": None}, {**got, "missing": ["X"], "accepted": []}) == []
    assert judge({"outcome": "escalate"}, got)[0].startswith("expected an escalation")
    esc = {**got, "status": "NEEDS_HUMAN", "escalation_reason": "the cited section does not govern this service"}
    assert judge({"outcome": "escalate", "escalation_phrase": "does not govern"}, esc) == []
    assert "different reason" in judge({"outcome": "escalate", "escalation_phrase": "other"}, esc)[0]
    assert judge(exp, esc)[0].startswith("expected a recommendation")


def test_no_output_earns_no_credit_for_nothing_missing(truth):
    cid = next(c for c, t in truth.items() if t["expected_missing_evidence"] == [] and t["expected_disposition"] != "NO_BASIS_ESCALATE")
    s = score({}, {cid: truth[cid]})
    assert s["metrics"]["M5_missing_evidence_exact"] == 0
    s = score({cid: perfect(truth[cid])}, {cid: truth[cid]})
    assert s["metrics"]["M5_missing_evidence_exact"] == 1


def test_provider_errors_do_not_leak_account_identifiers():
    e = llm.LLMError("429 Rate limit reached in organization `org_01jand21taf979e3m64c7sq3xk` service tier on_demand")
    assert "org_01jand21" not in harness.clean_error(e) and "org_…" in harness.clean_error(e)


def test_the_report_says_why_a_system_was_not_run_and_never_prints_a_zero_support_score(runs, truth):
    d = harness.begin(label="notes", notes=["Baseline RAG + findings not run: the provider's daily token limit was exhausted."])
    ids = harness._eval_ids(truth)
    gain = {"learned": ["F-L-X"], "curator_action": "learned",
            "before": {"accepted": [], "disposition": "APPEAL_VIABLE", "confidence": 0.0, "missing": []},
            "after": {"accepted": ["F-L-X"], "disposition": "APPEAL_NEEDS_EVIDENCE", "confidence": 0.667, "missing": ["ITEMIZED_BILL"]}}
    harness._save("claimbridge", {"predictions": {c: perfect(truth[c]) for c in ids}, "memory_gain": gain}, pv.now_iso())
    harness.build_report(d)
    md = (d / "report.md").read_text(encoding="utf-8")
    assert "## Run notes" in md and "daily token limit was exhausted" in md
    assert "**Baseline RAG + findings** was not run" in md
    assert "Support score none yet to 0.667" in md and "Support score 0.0" not in md


def test_a_run_cannot_be_promoted_after_the_code_it_describes_has_changed(runs, truth, monkeypatch):
    d = harness.begin()
    ids = harness._eval_ids(truth)
    harness._save("claimbridge", {"predictions": {c: perfect(truth[c]) for c in ids}}, pv.now_iso())
    harness.build_report(d)
    monkeypatch.setattr(pv, "source_digest", lambda: "e" * 64)                      # the code was edited after the run
    with pytest.raises(SystemExit, match="no longer matches"):
        harness.promote(d.name)
