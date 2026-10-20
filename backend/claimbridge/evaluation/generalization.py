"""The pre-registered generalization check (data/scenarios/generalization.yaml).

Unseen letters with expected answers written before any run. The expectation file is locked by a sha256 the
first time it runs; if it changes afterwards the runner refuses, so expectations cannot be edited to fit results.
Results are reported by `kind` (generalization / known-defect-regression / design-intent) because only the first
is evidence of generalization, and the sample is small and separately authored, not independent.

    GRAPH=claimbridge_eval python -m claimbridge.cli eval generalization [--file generalization_<name>.yaml]
"""
import hashlib
import json
from pathlib import Path

import yaml

from claimbridge import config, db, report
from claimbridge.evaluation import harness
from claimbridge.evaluation import provenance as pv
from claimbridge.knowledge import load
from claimbridge.seed.generate import add_days
from claimbridge.seed.load import load_cases_into, reset
from claimbridge.tools import coordination as coord

DEFAULT_FILE = config.DATA_DIR / "scenarios" / "generalization.yaml"
KINDS = ("generalization", "known-defect-regression", "design-intent")


def lock(path: Path) -> str:
    """Record the expectation file's digest on first use; refuse to run if it changed after registration."""
    digest = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    lock_file = path.with_suffix(".sha256")
    if lock_file.exists():
        recorded = lock_file.read_text(encoding="utf-8").split()[0]
        if recorded != digest:
            raise SystemExit(f"{path.name} changed after its expectations were registered ({lock_file.name}). "
                             "If that was deliberate, delete the lock file and say why in the report; "
                             "otherwise restore the file.")
    else:
        lock_file.write_text(f"{digest}  {path.name}  registered {pv.now_iso()}\n", encoding="utf-8")
    return digest


def load_cases(path: Path) -> list[dict]:
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for c in spec["cases"]:
        lag = c.get("filing_lag_days", 20)
        filed = add_days(c["service_date"], lag)
        out.append({
            "id": c["id"], "kind": c.get("kind", "generalization"), "purpose": c.get("purpose", ""), "expected": c["expected"],
            "graph_case": {
                "claim_id": c["id"], "tenant_id": c.get("tenant", "TEN-02"), "source": "generalization",
                "service": c["service"], "service_date": c["service_date"], "filed_date": filed, "filing_lag_days": lag,
                "amount": None, "in_network": c.get("in_network", True), "is_emergency": c.get("is_emergency", False),
                "enrolled_months": c.get("enrolled_months", 12), "session_number": c.get("session_number"),
                "notice_text": " ".join(c["notice"].replace("{id}", c["id"]).split()),
                "notice_issued": add_days(filed, 14), "evidence": list(c.get("evidence", []))}})
    return out


def observe(g, cid: str) -> dict:
    a = report.actual(g, cid)
    reason_for_human = None
    for e in reversed(coord.timeline(g, cid)):
        if e["type"] == "NEEDS_HUMAN":
            reason_for_human = json.loads(e["payload"] or "{}").get("reason")
            break
    return {"status": a["status"], "reason": a.get("reason"), "version": a.get("version"),
            "disposition": a.get("disposition"), "missing": sorted(a["missing"] or []),
            "accepted": sorted(v["finding_id"] for v in a["verdicts"] if v["code"] == "ACCEPTED"),
            "escalation_reason": reason_for_human}


def judge(expected: dict, got: dict) -> list[str]:
    """What differs from the pre-registered expectation (empty = met). `null` expectations are not scored."""
    miss = []
    if expected["outcome"] == "escalate":
        if got["status"] != "NEEDS_HUMAN":
            miss.append(f"expected an escalation to a person, got status {got['status']} ({got['reason']}/{got['disposition']})")
        elif expected.get("escalation_phrase") and expected["escalation_phrase"] not in (got["escalation_reason"] or ""):
            miss.append(f"escalated for a different reason: {got['escalation_reason']!r}")
        return miss
    if got["status"] != "AWAITING_REVIEW":
        return [f"expected a recommendation, got status {got['status']}" + (f" ({got['escalation_reason']})" if got["escalation_reason"] else "")]
    for key, field in (("reason", "reason"), ("version", "version"), ("disposition", "disposition")):
        if expected.get(key) != got[field]:
            miss.append(f"{key}: expected {expected.get(key)}, got {got[field]}")
    if expected.get("missing_evidence") is not None and sorted(expected["missing_evidence"]) != got["missing"]:
        miss.append(f"missing evidence: expected {sorted(expected['missing_evidence'])}, got {got['missing']}")
    if expected.get("applicable_findings") is not None and sorted(expected["applicable_findings"]) != got["accepted"]:
        miss.append(f"applicable findings: expected {sorted(expected['applicable_findings'])}, got {got['accepted']}")
    return miss


def run(path: Path | None = None) -> dict:
    from claimbridge.cli import run_pipeline
    path = Path(path) if path else DEFAULT_FILE
    run_dir = harness.run_dir()
    harness._system("generalization")
    started = pv.now_iso()
    digest = lock(path)
    cases = load_cases(path)
    reset()
    g = db.connect()
    load_cases_into(g, load(), [c["graph_case"] for c in cases])
    ids = [c["id"] for c in cases]
    run_pipeline(ids, quiet=True)
    results = []
    for c in cases:
        got = observe(g, c["id"])
        miss = judge(c["expected"], got)
        # A miss caused by the provider being unavailable says nothing about reasoning: label it, do not count it.
        unavailable = bool(miss) and "LLM unavailable" in (got["escalation_reason"] or "") and c["expected"]["outcome"] != "escalate"
        results.append({"id": c["id"], "kind": c["kind"], "purpose": c["purpose"], "passed": not miss,
                        "not_evaluated": unavailable, "mismatches": miss, "expected": c["expected"], "observed": got})
    by_kind = {k: [r for r in results if r["kind"] == k] for k in KINDS}
    out = {"file": path.name, "expectations_sha256": digest, "started_at": started, "ended_at": pv.now_iso(),
           "total": len(results), "passed": sum(r["passed"] for r in results),
           "not_evaluated": sum(r["not_evaluated"] for r in results),
           "by_kind": {k: {"total": len(v), "evaluated": sum(not r["not_evaluated"] for r in v),
                           "passed": sum(r["passed"] for r in v), "not_evaluated": sum(r["not_evaluated"] for r in v)}
                       for k, v in by_kind.items() if v},
           "results": results,
           "authorship": ("Written by the AI assistant that helped build the system, before any run, from the policy "
                          "text. Separately authored, not independent. Sample is small and synthetic.")}
    (run_dir / "generalization.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    (run_dir / "generalization.md").write_text(render_md(out), encoding="utf-8")
    return out


def render_md(out: dict) -> str:
    L = ["# Generalization check (pre-registered)\n",
         f"`{out['file']}` · expectations locked at sha256 `{out['expectations_sha256'][:16]}` · run {out['started_at']}.\n",
         f"**{out['authorship']}**\n",
         "| Kind | Met | What it shows |", "|---|---:|---|"]
    meaning = {"generalization": "Unseen letters, expectations set before any run: the only rows that speak to generalization.",
               "known-defect-regression": "Written after defects were found and fixed: regression tests, not generalization.",
               "design-intent": "Behaviour the design already aimed for; the author knew the intended answer."}
    for k, v in out["by_kind"].items():
        extra = f" ({v['not_evaluated']} not evaluated: provider unavailable)" if v["not_evaluated"] else ""
        L.append(f"| {k} | {v['passed']}/{v['evaluated']}{extra} | {meaning[k]} |")
    L.append("")
    for kind in KINDS:
        rows = [r for r in out["results"] if r["kind"] == kind]
        if not rows:
            continue
        L.append(f"## {kind}\n")
        L.append("| Case | Probes | Result | Detail |")
        L.append("|---|---|---|---|")
        for r in rows:
            L.append(f"| {r['id']} | {r['purpose']} | {'met' if r['passed'] else 'not evaluated (provider unavailable)' if r['not_evaluated'] else '**MISSED**'} | "
                     f"{'; '.join(r['mismatches']) or '—'} |")
        L.append("")
    L.append("Expected answers and the reasoning behind each are in the YAML file (`because`).\n")
    return "\n".join(L) + "\n"
