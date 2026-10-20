"""Metrics from docs/07-evaluation.md, computed the same way for every system.

Every system's output is first reduced to one prediction per claim:
    reason, version, accepted (precedent Finding IDs), rejected ({finding: code}, ClaimBridge only),
    missing (evidence codes), disposition, items_total, items_unsupported, leaked_fields,
    tokens_in, tokens_out
For the baseline, cited past cases are mapped to the Finding they support (cases that
support no Finding, e.g. losses, are not counted as precedents).
"""
from collections import defaultdict

GROUPS = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "M", "normal"]
STALE_CODES = ("VERSION_DRIFT", "CONTRADICTED")


def _ratio(a, b):
    return round(a / b, 3) if b else None


def _scores_evidence(t: dict) -> bool:
    """When there is no basis for an appeal, which evidence is "missing" is moot: no system is
    judged on it (an answer of "nothing would help" is as right as listing the clause's needs)."""
    return t["expected_disposition"] != "NO_BASIS_ESCALATE"


def claim_checks(p: dict, t: dict) -> dict:
    checks = {
        "reason": p["reason"] == t["expected_reason"],
        "version": p["version"] == t["expected_version"],
        "precedents": sorted(p["accepted"]) == t["expected_applicable_findings"],
        "disposition": p["disposition"] == t["expected_disposition"],
    }
    if _scores_evidence(t):
        checks["missing"] = sorted(p["missing"]) == t["expected_missing_evidence"]
    return checks


def score(preds: dict[str, dict], truth: dict[str, dict]) -> dict:
    ids = list(truth)
    n = len(ids)
    tp = fp = fn = 0
    rec_tp = rec_fn = 0                    # recall over precedents the system's permitted corpus could contain
    unrecoverable_claims = 0
    ev_exact = ev_scored = 0
    ev_tp = ev_fp = ev_fn = 0
    wrong_prec = 0
    stale_total = stale_avoided = stale_explained = 0
    items = unsupported = 0
    leaked = 0
    tok_in = tok_out = 0
    per_claim, by_group = {}, defaultdict(lambda: [0, 0])
    wrong_by_code = defaultdict(int)

    def completed(cid):
        # A completed claim has a disposition and was not handed to a person. NEEDS_HUMAN is a safe
        # abstention, reported separately below, but it is not a completed recommendation.
        p = preds.get(cid, {})
        return (p.get("disposition") in ("APPEAL_VIABLE", "APPEAL_NEEDS_EVIDENCE", "NO_BASIS_ESCALATE")
                and p.get("status") in (None, "AWAITING_REVIEW", "APPROVED", "CURATED"))

    abstained = [c for c in ids if (preds.get(c) or {}).get("status") == "NEEDS_HUMAN"]
    no_output = [c for c in ids if c not in preds]

    for c in ids:
        t = truth[c]
        p = preds.get(c, {"reason": None, "version": None, "accepted": [], "missing": [],
                          "disposition": None, "items_total": 0, "items_unsupported": 0})
        exp, got = set(t["expected_applicable_findings"]), set(p["accepted"])
        tp += len(exp & got)
        fp += len(got - exp)
        fn += len(exp - got)
        # Which expected precedents could this system reach at all? Systems that only see their own
        # tenant's raw cases cannot cite a precedent whose supporting cases belong to other tenants.
        reachable = set(t.get("recoverable_findings", t["expected_applicable_findings"])) & exp
        rec_tp += len(reachable & got)
        rec_fn += len(reachable - got)
        unrecoverable_claims += bool(exp - reachable)
        if got - exp:
            wrong_prec += 1
            exp_codes = {r["finding_id"]: r["code"] for r in t["expected_rejected_findings"]}
            for f in got - exp:
                wrong_by_code[exp_codes.get(f, "NOT_APPLICABLE")] += 1
        if _scores_evidence(t):
            em, gm = set(t["expected_missing_evidence"]), set(p["missing"])
            ev_scored += 1
            ev_exact += (c in preds) and em == gm      # no output earns no exact-match credit for "nothing missing"
            ev_tp += len(em & gm)
            ev_fp += len(gm - em)
            ev_fn += len(em - gm)
        for r in t["expected_rejected_findings"]:
            if r["code"] in STALE_CODES:
                stale_total += 1
                if completed(c) and r["finding_id"] not in got:
                    stale_avoided += 1
                if (p.get("rejected") or {}).get(r["finding_id"]) == r["code"]:
                    stale_explained += 1
        items += p["items_total"]
        unsupported += p["items_unsupported"]
        if t["trap"] == "T7":
            leaked += p.get("leaked_fields", 0)
        tok_in += p.get("tokens_in") or 0
        tok_out += p.get("tokens_out") or 0
        checks = claim_checks(p, t)
        checks["completed"] = completed(c)
        ok = all(checks.values())
        per_claim[c] = {"ok": ok, "checks": checks}
        g = t["trap"] or "normal"
        by_group[g][0] += ok
        by_group[g][1] += 1

    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    ev_p, ev_r = _ratio(ev_tp, ev_tp + ev_fp), _ratio(ev_tp, ev_tp + ev_fn)
    ev_f1 = round(2 * ev_p * ev_r / (ev_p + ev_r), 3) if ev_p and ev_r else 0.0
    m = {
        "claims": n,
        "completion_rate": _ratio(sum(completed(c) for c in ids), n),
        "abstained_to_human": len(abstained),
        "no_output": len(no_output),
        "decision_correct": _ratio(sum(all(per_claim[c]["checks"].get(k, True) for k in ("reason", "version", "disposition", "missing", "completed")) for c in ids), n),
        "M1_reason_accuracy": _ratio(sum(per_claim[c]["checks"]["reason"] for c in ids), n),
        "M2_version_accuracy": _ratio(sum(per_claim[c]["checks"]["version"] for c in ids), n),
        "M3_precedent_precision": precision,
        "M3_precedent_recall": recall,
        "M3_precedent_recall_reachable": _ratio(rec_tp, rec_tp + rec_fn),
        "claims_with_unreachable_precedent": unrecoverable_claims,
        "M5_missing_evidence_exact": _ratio(ev_exact, ev_scored),
        "M4_wrong_precedent_rate": _ratio(wrong_prec, n),
        "M5_missing_evidence_f1": ev_f1,
        "M6_disposition_accuracy": _ratio(sum(per_claim[c]["checks"]["disposition"] for c in ids), n),
        "M7_unsupported_item_rate": _ratio(unsupported, items),
        "M8_stale_precedent_avoided": _ratio(stale_avoided, stale_total),
        "M8_stale_precedent_explained": _ratio(stale_explained, stale_total),
        "M9_tenant_fields_leaked": leaked,
        "M12_tokens_per_claim": round((tok_in + tok_out) / n) if n else None,
        "all_correct": _ratio(sum(v["ok"] for v in per_claim.values()), n),
    }
    return {"metrics": m, "per_claim": per_claim, "abstained": abstained, "no_output": no_output,
            "by_group": {g: by_group[g] for g in GROUPS if g in by_group},
            "wrong_precedent_by_code": dict(wrong_by_code)}
