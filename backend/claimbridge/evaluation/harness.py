"""Run the evaluation. Every run is its own directory (see provenance.py): raw predictions are written
once and never replaced, tokens are attributed from a per-call ledger, and the report carries the run's
identity (code, data, prompts, model, cache policy, timestamps) so any number can be traced to its source.

Systems
  claimbridge          the full pipeline (graph + memory), supervised worker pool
  no_memory            the same pipeline with Findings hidden from Retrieval (ablation)
  baseline_rag         plain vector RAG (clauses + own-tenant case records), same LLM and embedding model
  baseline_rag_strong  the same baseline with a much larger embedding model (sensitivity check)
  baseline_rag_findings  the same baseline that ALSO receives the abstract finding facts ClaimBridge stores
                         (information parity: what is left is rules and graph queries, not access)
Experiments
  memory gain          claim A's recorded outcome, then a look-alike claim B (docs/07 M11)
  chaos                random worker kills under load, plus a deliberate paused-worker scenario (M10)

`cli eval all` starts a new run. `cli eval <steps> --run <id>` adds steps that have no output yet;
it never overwrites one, so a re-run of a failed step means a new run.
"""
import json
import logging
import random
import re
import shutil
import time
from datetime import datetime
import os
from pathlib import Path

from claimbridge import config, db, llm, report
from claimbridge.evaluation import baseline as bl
from claimbridge.evaluation import provenance as pv
from claimbridge.evaluation.score import GROUPS, score
from claimbridge.seed.generate import load_cases, load_truth
from claimbridge.tools import coordination as coord
from claimbridge.tools import tenancy

log = logging.getLogger("claimbridge.eval")

HELD_OUT = ["EV-M-B2"]           # processed only inside the memory-gain experiment
SYSTEM_LABELS = {
    "claimbridge": "ClaimBridge",
    "no_memory": "No-memory ablation",
    "baseline_rag": "Baseline RAG",
    "baseline_rag_strong": "Baseline RAG (large embeddings)",
    "baseline_rag_findings": "Baseline RAG + findings",
}
GROUND_TRUTH = ("a rule engine implemented separately from the graph queries (Python, no Cypher) by the same "
                "team; it is not external validation")

# What each system can see and what decides its answer. Differences here, not only graph storage, explain
# differences in the results.
ACCESS = {
    "claimbridge": {
        "policy_clauses": "all versions, as graph nodes with lineage and content fingerprints",
        "abstract_findings": "yes: the shared memory (statement, versions valid in, status, evidence needs, conditions)",
        "raw_cases": "own tenant only; other tenants' cases are redacted",
        "decided_by": "deterministic Cypher for version, applicability, gates and evidence; the LLM only reads "
                      "notices that cite no section",
    },
    "no_memory": {
        "policy_clauses": "same as ClaimBridge", "abstract_findings": "hidden (ablation)",
        "raw_cases": "own tenant only", "decided_by": "same deterministic rules without semantic memory",
    },
    "baseline_rag": {
        "policy_clauses": "all versions, as text passages",
        "abstract_findings": "no",
        "raw_cases": "own tenant only (filtered before prompting)",
        "decided_by": "the LLM makes every decision from the retrieved passages",
    },
    "baseline_rag_strong": {
        "policy_clauses": "all versions, as text passages", "abstract_findings": "no",
        "raw_cases": "own tenant only (filtered before prompting)",
        "decided_by": "the LLM makes every decision; larger embedding model",
    },
    "baseline_rag_findings": {
        "policy_clauses": "all versions, as text passages",
        "abstract_findings": "yes: the same facts ClaimBridge stores, as passages (no verdicts about any claim)",
        "raw_cases": "own tenant only (filtered before prompting)",
        "decided_by": "the LLM makes every decision from the retrieved passages",
    },
}

_RUN: Path | None = None


# ----------------------------------------------------------------------------- run management

def begin(run_id: str | None = None, label: str | None = None, notes: list[str] | None = None) -> Path:
    """Start a new run, or continue an existing one (adding steps that have no output yet)."""
    global _RUN
    _RUN = pv.open_run(run_id) if run_id else pv.start_run(label)
    pv.activate(_RUN)
    if notes:
        run = pv.read_run(_RUN)
        pv.update_run(_RUN, notes=[*run.get("notes", []), *notes])
    return _RUN


def run_dir() -> Path:
    if _RUN is None:
        raise RuntimeError("no active evaluation run: call harness.begin() first")
    return _RUN


def raw_dir() -> Path:
    return run_dir() / "raw"


def has_output(name: str) -> bool:
    return (raw_dir() / f"{name}.json").exists()


def _save(name: str, data: dict, started_at: str):
    path = raw_dir() / f"{name}.json"
    if path.exists():
        raise FileExistsError(f"{name} already has raw output in run {run_dir().name}; start a new run instead")
    check = pv.verify_unchanged(run_dir(), name)
    ended = pv.now_iso()
    data["provenance"] = {"run_id": run_dir().name, "step": name, "started_at": started_at, "ended_at": ended,
                          **check, "llm_platform": config.LLM_PLATFORM, "llm_model": llm.model_name(),
                          "llm_mode": config.LLM_MODE, "access": ACCESS.get(name)}
    raw_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    run = pv.read_run(run_dir())
    run["steps"][name] = {"started_at": started_at, "ended_at": ended, "source_unchanged": check["source_unchanged"]}
    pv.write_run(run_dir(), run)


def _load(name: str) -> dict | None:
    p = raw_dir() / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _eval_ids(truth) -> list[str]:
    return [c for c in truth if c not in HELD_OUT]


def _system(name: str):
    os.environ["EVAL_SYSTEM"] = name


def clean_error(e: Exception) -> str:
    """Keep what a reader needs (the cause) and drop account identifiers the provider echoes back."""
    return re.sub(r"org_[0-9A-Za-z]+", "org_…", str(e))[:600]


def classify_error(e: Exception) -> str:
    """Why an output is missing. A provider limit or timeout is not a reasoning failure."""
    msg = f"{type(e).__name__} {e}".lower()
    if "429" in msg or "rate limit" in msg or "rate_limit" in msg or "tokens per" in msg:
        return "provider_rate_limit"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "api key" in msg or "401" in msg or "403" in msg:
        return "configuration_or_auth"
    if "no recorded response" in msg:
        return "no_recorded_response_offline"
    if "json" in msg or "validation" in msg or "stopped" in msg or "length" in msg:
        return "unparseable_or_truncated_generation"
    return "other_error"


# --------------------------------------------------------------------- ground truth reach

def truth_with_reach(truth: dict) -> dict:
    """Mark, per claim, which expected precedents a system limited to its own tenant's raw case records
    could ever cite: those with at least one supporting historical case from the claim's own tenant."""
    cases = {c["claim_id"]: c for c in load_cases()}
    support: dict[str, set] = {}
    for c in cases.values():
        r = c.get("resolution") or {}
        if c["source"] == "historical" and r.get("supports_finding"):
            support.setdefault(r["supports_finding"], set()).add(c["tenant_id"])
    out = {}
    for cid, t in truth.items():
        tenant = cases[cid]["tenant_id"]
        out[cid] = {**t, "recoverable_findings": [f for f in t["expected_applicable_findings"]
                                                  if tenant in support.get(f, set())]}
    return out


# ---------------------------------------------------------------- ClaimBridge

def predict_claimbridge(g, ids: list[str], truth: dict, system: str) -> dict:
    tokens = pv.ledger_tokens(run_dir(), system)
    preds = {}
    for c in ids:
        a = report.actual(g, c)
        rec = a["recommendation"] or {"items": []}
        codes = {v["finding_id"]: v["code"] for v in a["verdicts"]}
        accepted = sorted(f for f, k in codes.items() if k == "ACCEPTED")
        leaked = 0
        probe = truth[c].get("tenant_probe")
        if probe:
            if tenancy.claim_for_tenant(g, c, probe):
                leaked += 3
            for f in accepted:
                leaked += tenancy.leaked_fields(tenancy.precedent_detail(g, f, probe))
        ti, to = tokens.get(c, (0, 0))
        preds[c] = {
            "status": a.get("status"), "reason": a.get("reason"), "version": a.get("version"),
            "accepted": accepted,
            "rejected": {f: k for f, k in codes.items() if k not in ("ACCEPTED", "REASON_MISMATCH")},
            "missing": a["missing"], "disposition": a.get("disposition"),
            "items_total": len(rec["items"]),
            "items_unsupported": sum(1 for i in rec["items"] if not i["cites"]),
            "guard_dropped": rec.get("guard_dropped", 0), "guard_added": rec.get("guard_added", 0),
            "confidence": rec.get("confidence"), "leaked_fields": leaked,
            "tokens_in": ti, "tokens_out": to,
        }
    return preds


def memory_gain_claimbridge(g, env: dict) -> dict:
    from claimbridge.cli import spawn_supervisor, stop_supervisor, wait_for
    from claimbridge.supervisor import approve, record_outcome
    b1 = report.actual(g, "EV-M-B1")
    sup = spawn_supervisor(env=env)
    try:
        approve(g, "EV-M-A", "eval")
        record_outcome(g, "EV-M-A", "OVERTURNED", "eval", ["EMERGENCY_ATTESTATION", "ITEMIZED_BILL"])
        wait_for(g, ["EV-M-A"], 180, done={"CURATED", "NEEDS_HUMAN"})
        curated = json.loads(coord.timeline(g, "EV-M-A")[-1]["payload"])
        coord.inject(g, ["EV-M-B2"])
        wait_for(g, ["EV-M-B2"], 600)
    finally:
        stop_supervisor(g, sup)
    b2 = report.actual(g, "EV-M-B2")

    def view(a):
        rec = a["recommendation"] or {}
        return {"accepted": [v["finding_id"] for v in a["verdicts"] if v["code"] == "ACCEPTED"],
                "disposition": a.get("disposition"), "confidence": rec.get("confidence"),
                "uncertainty": rec.get("uncertainty"), "missing": a["missing"]}
    return {"learned": [f["finding_id"] for f in curated.get("findings", [])],
            "curator_action": curated.get("action"), "before": view(b1), "after": view(b2)}


def run_claimbridge(no_memory: bool = False) -> dict:
    from claimbridge.cli import run_pipeline
    from claimbridge.seed.load import reset
    name = "no_memory" if no_memory else "claimbridge"
    _system(name)
    started = pv.now_iso()
    env = {"CB_NO_MEMORY": "1"} if no_memory else {}
    truth = load_truth()
    ids = _eval_ids(truth)
    reset()
    g = db.connect()
    t0 = time.time()
    run_pipeline(ids, env=env, quiet=True)
    wall = time.time() - t0
    preds = predict_claimbridge(g, ids, truth, name)
    gain = memory_gain_claimbridge(g, env)
    data = {"system": name, "wall_seconds": round(wall, 1), "predictions": preds, "memory_gain": gain}
    _save(name, data, started)
    return data


# ------------------------------------------------------------------- baseline

def predict_baseline(case: dict, result: dict, chunk_findings: dict, known_findings: set | None = None) -> dict:
    a = result["answer"]
    retrieved = {h["chunk_id"]: h for h in result["retrieved"]}
    if "precedent_finding_ids" in a:                       # information-parity variant: names findings directly
        accepted = sorted({f for f in a["precedent_finding_ids"] if f in (known_findings or set())})
        precedent_cases = a["precedent_finding_ids"]
    else:
        accepted = sorted({chunk_findings[f"CS-{p}"] for p in a["precedent_case_ids"] if chunk_findings.get(f"CS-{p}")})
        precedent_cases = a["precedent_case_ids"]
    unsupported = sum(1 for i in a["items"] if not i["cite_ids"] or any(x not in retrieved for x in i["cite_ids"]))
    exposed = set()
    for p in a.get("precedent_case_ids", []):
        exposed.add(f"CS-{p}")
    for i in a["items"]:
        exposed.update(x for x in i["cite_ids"] if x.startswith("CS-"))
    leaked = 3 * sum(1 for x in exposed if x in retrieved and retrieved[x]["tenant_id"]
                     and retrieved[x]["tenant_id"] != case["tenant_id"])
    return {
        "reason": a["denial_reason"], "version": a["policy_version"], "accepted": accepted,
        "precedent_cases": precedent_cases, "rejected": {},
        "missing": sorted(set(a["missing_evidence"])), "disposition": a["disposition"],
        "items_total": len(a["items"]), "items_unsupported": unsupported, "leaked_fields": leaked,
        "tokens_in": result["llm"]["input_tokens"] or 0, "tokens_out": result["llm"]["output_tokens"] or 0,
        "retrieved": [h["chunk_id"] for h in result["retrieved"]],
        "llm_cached": result["llm"]["cached"],
    }


def run_baseline(model: str, name: str, variant: str = "cases") -> dict:
    _system(name)
    started = pv.now_iso()
    truth = load_truth()
    cases = {c["claim_id"]: c for c in load_cases()}
    bl.build_index(model, variant)
    chunk_findings = {c["chunk_id"]: c.get("finding_id") for c in bl.corpus()}
    known = {f.finding_id for f in __import__("claimbridge.knowledge", fromlist=["load"]).load().findings}
    preds, raw, errors = {}, {}, {}
    t0 = time.time()
    for cid in _eval_ids(truth):
        try:
            res = bl.answer(cases[cid], model, variant=variant)
        except Exception as e:                                    # a provider limit and a parse failure look alike here
            kind = classify_error(e)
            log.error("%s failed on %s (%s): %s", name, cid, kind, e)
            errors[cid] = {"kind": kind, "message": clean_error(e)}
            continue
        raw[cid] = res
        preds[cid] = predict_baseline(cases[cid], res, chunk_findings, known)
    wall = time.time() - t0

    gain = None
    if variant == "cases":
        # Memory gain: the baseline's only memory is its corpus. Add A's recorded outcome as a case record.
        a = cases["EV-M-A"]
        chunk = {"chunk_id": "CS-EV-M-A", "claim_id": "EV-M-A", "tenant_id": a["tenant_id"],
                 "finding_id": "LEARNED-FROM-EV-M-A",
                 "text": (f"Past case EV-M-A. Service: Ambulance transport, service date 2025-06-10 (policy V2025). "
                          f"Emergency: yes. In network: yes. Denial notice: {bl.notice_core(a['notice_text'])} "
                          "Evidence submitted on appeal: Emergency attestation (EMERGENCY_ATTESTATION), "
                          "Itemized bill (ITEMIZED_BILL). Recorded outcome: OVERTURNED.")}
        bl.add_case(model, chunk)
        chunk_findings["CS-EV-M-A"] = "LEARNED-FROM-EV-M-A"
        try:
            b2 = predict_baseline(cases["EV-M-B2"], bl.answer(cases["EV-M-B2"], model), chunk_findings, known)
            b1 = preds.get("EV-M-B1", {})
            gain = {"before": {"precedent_cases": b1.get("precedent_cases"), "disposition": b1.get("disposition")},
                    "after": {"precedent_cases": b2["precedent_cases"], "disposition": b2["disposition"],
                              "retrieved_new_case": "CS-EV-M-A" in b2["retrieved"]}}
        except Exception as e:
            errors["EV-M-B2"] = {"kind": classify_error(e), "message": clean_error(e)}
            log.error("%s memory-gain step failed: %s", name, e)
    missing = [c for c in _eval_ids(truth) if c not in preds]
    data = {"system": name, "variant": variant, "embedding_model": model,
            "top_k": bl.FINDINGS_TOP_K if variant == "findings" else config.BASELINE_TOP_K,
            "wall_seconds": round(wall, 1), "predictions": preds, "memory_gain": gain,
            "not_run": missing, "errors": errors, "answers": {c: r["answer"] for c, r in raw.items()}}
    _save(name, data, started)
    return data


# ---------------------------------------------------------------------- chaos

def run_chaos(n_claims: int = 12, kill_every_s: float = 4.0, max_kills: int = 10, seed: int = 7) -> dict:
    """Random hard kills of workers that hold a lease (a replacement is started each time), then a
    deliberate paused-worker scenario: a kill cannot show a stale worker that wakes up and tries to write."""
    from claimbridge.cli import spawn_supervisor, stop_supervisor
    from claimbridge.evaluation.stale_probe import run_stale_worker_scenario
    from claimbridge.seed.load import reset
    from claimbridge.supervisor import command
    _system("chaos")
    started = pv.now_iso()
    truth = load_truth()
    rng = random.Random(seed)
    ids = [c for c in _eval_ids(truth) if not c.startswith("EV-M")][:n_claims]
    reset()
    g = db.connect()
    env = {"STEP_DELAY_S": "2", "LEASE_TTL_S": "4", "HEARTBEAT_S": "1"}
    pool = "intake=2,retrieval=2,verifier=2,planner=2,curator=1"
    coord.inject(g, ids)
    sup = spawn_supervisor(pool, env)
    kills = []
    t0 = time.time()
    try:
        while time.time() - t0 < 900:
            st = {r["id"]: (r["s"], r["o"]) for r in db.run(
                g, "MATCH (c:Claim) WHERE c.claim_id IN $ids RETURN c.claim_id AS id, c.status AS s, "
                   "c.lease_owner AS o", {"ids": ids})}
            if all(s in ("AWAITING_REVIEW", "NEEDS_HUMAN") for s, _ in st.values()):
                break
            dead = {k["agent"] for k in kills}   # a killed worker keeps its lease until it expires
            busy = sorted((o, c) for c, (_, o) in st.items() if o and o != "supervisor" and o not in dead)
            if busy and len(kills) < max_kills and (not kills or time.time() - kills[-1]["t"] >= kill_every_s):
                victim, cid = rng.choice(busy)
                command(g, "KILL", victim)
                command(g, "START", victim.rsplit("-", 1)[0])
                kills.append({"agent": victim, "claim": cid, "t": time.time()})
                log.warning("chaos: killed %s holding %s", victim, cid)
            time.sleep(0.5)
    finally:
        stop_supervisor(g, sup)
    wall = time.time() - t0

    done_steps, duplicates, fenced, expired = {}, 0, 0, 0
    for c in ids:
        tl = coord.timeline(g, c)
        seen = {}
        for e in tl:
            if e["type"].endswith("_DONE"):
                seen[e["type"]] = seen.get(e["type"], 0) + 1
            fenced += e["type"] == "FENCED_WRITE_REJECTED"
            expired += e["type"] == "LEASE_EXPIRED"
        duplicates += sum(n - 1 for n in seen.values() if n > 1)
        done_steps[c] = tl
    # A kill "interrupted a step" when the killed agent was still the claim's last owner,
    # i.e. another agent later RESUMED that claim taking over from it.
    takeovers, recoveries = [], []
    for c, tl in done_steps.items():
        for e in tl:
            if e["type"] != "RESUMED":
                continue
            prev = json.loads(e["payload"] or "{}").get("previous_owner")
            k = next((k for k in kills if k["agent"] == prev and k["claim"] == c), None)
            if not k:
                continue
            nxt = [x["ts"] / 1000 for x in tl if x["type"].endswith("_DONE") and x["seq"] > e["seq"]]
            takeovers.append({"claim": c, "killed": prev, "resumed_by": e["agent"]})
            if nxt:
                recoveries.append(round(min(nxt) - k["t"], 2))
    checks = [report.check(g, truth[c]) for c in ids]

    probe = next((c for c in _eval_ids(truth) if c not in ids and not c.startswith("EV-M")), None)
    stale = run_stale_worker_scenario(g, probe, ttl_s=4.0) if probe else None
    data = {
        "claims": len(ids), "kills": len(kills), "pool": pool, "lease_ttl_s": 4, "step_delay_s": 2,
        "completed": sum(1 for r in checks if r["status"] == "AWAITING_REVIEW"),
        "correct": sum(r["ok"] for r in checks),
        "duplicate_step_outputs": duplicates, "fenced_writes_rejected": fenced,
        "lease_expiries_recorded": expired,
        "steps_interrupted": len(takeovers), "takeovers": takeovers,
        "recovery_seconds": recoveries,
        "mean_recovery_seconds": round(sum(recoveries) / len(recoveries), 2) if recoveries else None,
        "wall_seconds": round(wall, 1),
        "killed": [{"agent": k["agent"], "claim": k["claim"]} for k in kills],
        "stale_worker_scenario": stale,
    }
    _save("chaos", data, started)
    return data


# --------------------------------------------------------------------- report

def _support(confidence, accepted) -> str:
    """No accepted precedent means there is nothing to score: say so instead of printing 0.0."""
    return f"{confidence}" if accepted else "none yet"


def _fmt(v, pct=True):
    if v is None:
        return "n/a"
    if isinstance(v, float) and pct:
        return f"{v * 100:.0f}%"
    return str(v)


def build_report(run_path: Path | None = None) -> dict:
    """Score every system the run has raw output for and write report.json / report.md into the run."""
    d = run_path or run_dir()
    global _RUN
    _RUN = d
    run = pv.read_run(d)
    all_truth = {c: t for c, t in load_truth().items() if c not in HELD_OUT}
    truth = truth_with_reach(all_truth)            # the same denominator for every system; missing outputs stay in it
    systems = [s for s in SYSTEM_LABELS if _load(s)]
    raw = {s: _load(s) for s in systems}
    scored = {s: score(raw[s]["predictions"], truth) for s in systems}
    chaos = _load("chaos")
    gen_path = d / "generalization.json"
    generalization = json.loads(gen_path.read_text(encoding="utf-8")) if gen_path.exists() else None
    ledger = pv.ledger_summary(d)
    out = {"generated_at": pv.now_iso(),
           "run": {k: run[k] for k in ("run_id", "label", "started_at", "git", "source_sha256", "dataset", "prompts",
                                       "config", "invalid_reasons", "steps")},
           "llm": f"{config.LLM_PLATFORM}/{llm.model_name()}",
           "llm_calls": ledger,
           "valid": not run["invalid_reasons"],
           "scored_claims": len(truth), "total_claims": len(all_truth),
           "ground_truth": GROUND_TRUTH,
           "evaluation_version": 3,
           "limitations": ("Authored synthetic fixtures; whole-system comparison, not database-only causality. "
                           "Missing outputs count as failures and are listed with their cause."),
           "access": {s: ACCESS.get(s) for s in systems},
           "not_run": {s: raw[s].get("not_run") or [] for s in systems},
           "errors": {s: raw[s].get("errors") or {} for s in systems},
           "systems": {s: {"label": SYSTEM_LABELS[s], **scored[s],
                           "wall_seconds": raw[s].get("wall_seconds"),
                           "embedding_model": raw[s].get("embedding_model"),
                           "top_k": raw[s].get("top_k"),
                           "provenance": raw[s].get("provenance"),
                           "memory_gain": raw[s].get("memory_gain")} for s in systems},
           "chaos": chaos, "generalization": generalization,
           "notes": run.get("notes", []),
           "systems_not_run": [{"system": s, "label": SYSTEM_LABELS[s]} for s in SYSTEM_LABELS if s not in systems]}
    (d / "report.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    (d / "report.md").write_text(render_md(out, truth), encoding="utf-8")
    run["status"] = "complete" if systems and not [s for s, v in out["not_run"].items() if v] else "incomplete"
    run["ended_at"] = pv.now_iso()
    pv.write_run(d, run)
    return out


def promote(run_id: str, allow_invalid: bool = False) -> Path:
    """Make a reviewed run the one the API and the site serve. The previous results are archived first."""
    d = pv.open_run(run_id)
    run = pv.read_run(d)
    if run["invalid_reasons"] and not allow_invalid:
        raise SystemExit(f"run {run_id} is invalid and cannot be promoted: {'; '.join(run['invalid_reasons'])}")
    if not (d / "report.json").exists():
        raise SystemExit(f"run {run_id} has no report yet: run `eval report --run {run_id}`")
    now = pv.verify_unchanged(d, "promotion check")
    if not (now["source_unchanged"] and now["dataset_unchanged"]) and not allow_invalid:
        raise SystemExit(f"the code or data in the working tree no longer matches run {run_id} (source digest "
                         f"{run['source_sha256'][:12]} then, {now['source_sha256_at_save'][:12]} now). A number must describe the "
                         "code that is published: run the evaluation again, or pass --allow-invalid and say so.")
    dest = config.RESULTS_DIR
    if (dest / "latest.json").exists():
        try:
            previous = json.loads((dest / "latest.json").read_text(encoding="utf-8")).get("run", {}).get("run_id")
        except (json.JSONDecodeError, OSError):
            previous = None
        arch = config.ARCHIVE_DIR / (datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z") + "-" + (previous or "untracked"))
        arch.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(dest, arch)
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(d / "raw", dest / "raw")
    for name in ("run.json", "ledger.jsonl", "generalization.json", "generalization.md"):
        if (d / name).exists():
            shutil.copy2(d / name, dest / name)
    shutil.copy2(d / "report.json", dest / "latest.json")
    shutil.copy2(d / "report.md", dest / "latest.md")
    return dest


ROWS = [
    ("completion_rate", "Completion rate (a disposition, not handed to a person)", "?"),
    ("abstained_to_human", "Escalated to a person (safe abstention, counted separately)", "n"),
    ("no_output", "No output (error or missing; cause listed below)", "n"),
    ("decision_correct", "Decision correctness (excludes precedent recall)", "?"),
    ("M1_reason_accuracy", "Denial reason accuracy", "↑"),
    ("M2_version_accuracy", "Governing policy version accuracy", "↑"),
    ("M3_precedent_precision", "Precedent precision", "↑"),
    ("M3_precedent_recall", "Precedent recall (all expected precedents)", "↑"),
    ("M3_precedent_recall_reachable", "Precedent recall (only precedents the system's permitted corpus can reach)", "↑"),
    ("M4_wrong_precedent_rate", "Wrong-precedent rate (claims reusing a precedent that does not apply)", "↓"),
    ("M5_missing_evidence_f1", "Missing-evidence F1", "↑"),
    ("M5_missing_evidence_exact", "Missing-evidence exact match", "↑"),
    ("M6_disposition_accuracy", "Disposition accuracy", "↑"),
    ("M7_unsupported_item_rate", "Items without valid citation IDs (not semantic entailment)", "↓"),
    ("M8_stale_precedent_avoided", "Stale or contradicted precedent avoided", "↑"),
    ("M8_stale_precedent_explained", "…and rejected with the right reason", "↑"),
    ("M9_tenant_fields_leaked", "Other-tenant case fields exposed (T7)", "↓"),
    ("M12_tokens_per_claim", "LLM tokens per claim", "↓"),
    ("all_correct", "Claims fully correct (reason, version, precedents, evidence, disposition)", "↑"),
]
COUNTS = ("abstained_to_human", "no_output", "claims_with_unreachable_precedent", "M9_tenant_fields_leaked",
          "M12_tokens_per_claim")


def render_md(out: dict, truth: dict) -> str:
    S = out["systems"]
    names = list(S)
    run = out["run"]
    L = []
    L.append("# ClaimBridge evaluation results\n")
    if not out["valid"]:
        L.append("> **INVALID RUN.** " + " ".join(run["invalid_reasons"]) + " These numbers must not be published.\n")
    git = run.get("git") or {}
    calls = out["llm_calls"]
    label = f" ({run['label']})" if run.get("label") else ""
    L.append(f"Run `{run['run_id']}`{label} · started {run['started_at']} · "
             f"report generated {out['generated_at']}.\n")
    L.append(f"- **Code:** revision `{(git.get('revision') or 'unknown')[:12]}`"
             f"{' (uncommitted changes present)' if git.get('dirty') else ''}; backend source digest "
             f"`{run['source_sha256'][:16]}`; dataset digest `{run['dataset']['all'][:16]}`.")
    L.append(f"- **Model:** `{out['llm']}`, mode `{run['config']['llm_mode']}` "
             f"({run['config']['cache_policy']}). LLM calls in this run: {calls['fresh']} fresh from the provider, "
             f"{calls['replayed']} replayed from recorded responses, {calls['fake']} from the fake test model. "
             "Replayed calls reuse the tokens recorded when they were first made.")
    L.append(f"- **Data:** {len(truth)} authored synthetic claims (see docs/03); ground truth from {out['ground_truth']}.")
    L.append(f"- **Scope:** {out['limitations']}\n")
    if out["notes"] or out["systems_not_run"]:
        L.append("## Run notes\n")
        for n in out["notes"]:
            L.append(f"- {n}")
        for x in out["systems_not_run"]:
            L.append(f"- **{x['label']}** was not run in this run, so it is absent from every table below.")
        L.append("")
    if any(out["not_run"].values()):
        gaps = "; ".join(f"{S[s]['label']}: {', '.join(v)}" for s, v in out["not_run"].items() if v)
        L.append(f"> **Incomplete outputs.** Missing claims stay in every system's denominator and count as failures: "
                 f"{gaps}. Causes are listed under *Missing outputs*.\n")
    emb = {s: S[s].get("embedding_model") for s in names if S[s].get("embedding_model")}
    L.append("Systems: " + "; ".join(
        f"**{S[s]['label']}**" + (f" (`{emb[s]}`, top-{S[s].get('top_k')})" if s in emb else "")
        for s in names) + ".\n")

    L.append("## What each system can see\n")
    L.append("| System | Policy clauses | Abstract findings | Raw case records | What decides the answer |")
    L.append("|---|---|---|---|---|")
    for s in names:
        a = out["access"].get(s) or {}
        L.append(f"| {S[s]['label']} | {a.get('policy_clauses', '')} | {a.get('abstract_findings', '')} | "
                 f"{a.get('raw_cases', '')} | {a.get('decided_by', '')} |")
    L.append("")
    L.append("Read the columns before the numbers. A system that cannot see a precedent cannot cite it, and a "
             "system whose answers come from an LLM differs from one whose answers come from rules for reasons "
             "other than how the data is stored. Only the **Baseline RAG + findings** row isolates what is left "
             "once information access is equal.\n")

    L.append("## Headline metrics\n")
    L.append("| Metric | " + " | ".join(S[s]["label"] for s in names) + " |")
    L.append("|---|" + "---:|" * len(names))
    for key, label, arrow in ROWS:
        pct = key not in COUNTS
        L.append(f"| {label} {arrow} | " + " | ".join(_fmt(S[s]["metrics"].get(key), pct) for s in names) + " |")
    L.append("")
    L.append("Decision correctness (reason, version, disposition, missing evidence, completion) and precedent "
             "recall are reported apart on purpose: the no-memory ablation cannot name precedents by design, so "
             "its *fully correct* score is lower while its decisions are equal. **Where decision correctness is "
             "equal, memory adds precedents and a changed checklist, not a measured gain in decisions.**\n")

    L.append("## By trap type (claims fully correct)\n")
    L.append("| Group | " + " | ".join(S[s]["label"] for s in names) + " |")
    L.append("|---|" + "---:|" * len(names))
    labels = {"T1": "T1 version drift", "T2": "T2 same reason, wrong clause", "T3": "T3 missing evidence",
              "T4": "T4 contradicted memory", "T5": "T5 condition unmet", "T6": "T6 no basis",
              "T7": "T7 tenant isolation", "M": "M memory scenario", "normal": "Normal cases"}
    for gname in GROUPS:
        cells = []
        for s in names:
            ok, n = S[s]["by_group"].get(gname, [0, 0])
            cells.append(f"{ok}/{n}" if n else "-")
        L.append(f"| {labels[gname]} | " + " | ".join(cells) + " |")
    L.append("")

    L.append("## Why wrong precedents were used\n")
    L.append("Each time a system relied on a precedent that does not apply, the ground truth says why it does not:\n")
    L.append("| System | " + " | ".join(["VERSION_DRIFT", "LINEAGE_MISMATCH", "CONTRADICTED", "CONDITION_UNMET",
                                         "NOT_APPLICABLE"]) + " |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for s in names:
        w = S[s]["wrong_precedent_by_code"]
        L.append(f"| {S[s]['label']} | " + " | ".join(str(w.get(k, 0)) for k in
                 ["VERSION_DRIFT", "LINEAGE_MISMATCH", "CONTRADICTED", "CONDITION_UNMET", "NOT_APPLICABLE"]) + " |")
    L.append("")

    L.append("## Missing outputs and escalations\n")
    any_missing = False
    for s in names:
        miss, errs = out["not_run"].get(s) or [], out["errors"].get(s) or {}
        abst = S[s].get("abstained") or []
        if not (miss or errs or abst):
            continue
        any_missing = True
        L.append(f"**{S[s]['label']}**")
        for c in miss:
            e = errs.get(c) or {}
            L.append(f"- `{c}`: no output. Cause: **{e.get('kind', 'not recorded')}**"
                     f"{' — ' + e['message'][:160] if e.get('message') else ''}")
        for c, e in errs.items():
            if c not in miss:
                L.append(f"- `{c}`: a later step failed. Cause: **{e['kind']}**")
        for c in abst:
            L.append(f"- `{c}`: escalated to a person (safe abstention, not counted as completed).")
        L.append("")
    if not any_missing:
        L.append("None in this run.\n")
    L.append("A provider limit or timeout says nothing about a system's reasoning; it is reported as a missing "
             "output because the benchmark needs an answer, and a re-run is a new run.\n")

    L.append("## Memory gain (M11)\n")
    L.append("Claim EV-M-A (ambulance, emergency) is approved and its **recorded synthetic outcome** is OVERTURNED. "
             "EV-M-B1 was processed before that, EV-M-B2 (same facts) after. This shows that a recorded association "
             "changes a later checklist; it does not show the change helps a real appeal.\n")
    for s in names:
        mg = S[s].get("memory_gain") or {}
        if not mg:
            continue
        b, a = mg.get("before", {}), mg.get("after", {})
        if "accepted" in b:
            L.append(f"- **{S[s]['label']}**: before: missing evidence {b.get('missing') or 'none'}, "
                     f"{b.get('disposition')}; after: missing evidence {a.get('missing') or 'none'}, {a.get('disposition')}. "
                     f"Support score {_support(b['confidence'], b['accepted'])} to {_support(a['confidence'], a['accepted'])} (not a probability)"
                     f" (Curator: {mg.get('curator_action')} {mg.get('learned')}).")
        else:
            L.append(f"- **{S[s]['label']}**: before: precedent cases {b.get('precedent_cases') or 'none'}; "
                     f"after adding EV-M-A to the corpus: retrieved it: {a.get('retrieved_new_case')}, "
                     f"precedent cases {a.get('precedent_cases') or 'none'}.")
    L.append("")

    ch = out.get("chaos")
    if ch:
        L.append("## Coordination under failure (M10)\n")
        L.append(f"{ch['claims']} claims, worker pool `{ch['pool']}`, {ch['kills']} random hard kills of workers "
                 f"holding a lease (a replacement started each time), lease TTL {ch['lease_ttl_s']} s.\n")
        L.append("| Measure | Result |\n|---|---:|")
        L.append(f"| Claims completed | {ch['completed']}/{ch['claims']} |")
        L.append(f"| Claims correct | {ch['correct']}/{ch['claims']} |")
        L.append(f"| Kills that interrupted a step in progress | {ch.get('steps_interrupted', 'n/a')} of {ch['kills']} |")
        L.append(f"| …each resumed by another worker | {len(ch.get('recovery_seconds', []))} |")
        L.append(f"| Mean time from kill to the interrupted step completing | {ch['mean_recovery_seconds']} s "
                 f"(includes the {ch['lease_ttl_s']} s lease timeout) |")
        L.append(f"| Duplicate step outputs | {ch['duplicate_step_outputs']} |")
        L.append(f"| Late writes rejected during the random kills | {ch['fenced_writes_rejected']} |")
        L.append("")
        L.append("A killed process never wakes up, so the random kills alone cannot show a stale worker being "
                 "refused; a zero in the last row is expected and proves nothing about fencing.\n")
        st = ch.get("stale_worker_scenario")
        if st:
            L.append("**Deliberate paused-worker scenario.** A living worker is paused past its lease, a replacement "
                     "completes the step, then the first worker wakes and tries to write:\n")
            L.append("| Measure | Result |\n|---|---:|")
            for a in st["stale_attempts"]:
                L.append(f"| Stale worker's {a['what']} | {'ACCEPTED (bug)' if a['accepted'] else 'rejected'} |")
            L.append(f"| Stale worker's commit | {'none: rejected' if not any(a == 'stale-1' for _, a in st['step_done_events']) else 'ACCEPTED (bug)'} |")
            L.append(f"| `FENCED_WRITE_REJECTED` audit events recorded | {st['fenced_write_rejected_events']} |")
            L.append(f"| Stale checkpoint survived | {'yes (bug)' if st['stale_checkpoint_survived'] else 'no'} |")
            L.append("")

    if "claimbridge" in S:
        fails = [(c, v) for c, v in S["claimbridge"]["per_claim"].items() if not v["ok"]]
        L.append("## ClaimBridge failures\n")
        if not fails:
            L.append("None in this run.\n")
        for c, v in fails:
            bad = [k for k, ok in v["checks"].items() if not ok]
            L.append(f"- {c} ({truth[c]['trap'] or 'normal'}): wrong {', '.join(bad)}")
        L.append("")

    L.append("## Per-claim results\n")
    L.append("Each claim's raw prediction is in `raw/<system>.json` in this run, and at `/api/eval/raw/<system>/<claim>`.\n")
    L.append("| Claim | Trap | " + " | ".join(S[s]["label"] for s in names) + " |")
    L.append("|---|---|" + "---|" * len(names))
    for c, t in truth.items():
        cells = []
        for s in names:
            pc = S[s]["per_claim"].get(c)
            if not pc:
                cells.append("-")
            else:
                cells.append("✅" if pc["ok"] else "❌ " + ",".join(k for k, ok in pc["checks"].items() if not ok))
        L.append(f"| {c} | {t['trap'] or '-'} | " + " | ".join(cells) + " |")
    L.append("")

    L.append("## How to read this\n")
    L.append("- This compares **whole systems**. ClaimBridge combines structured rules, a graph and curated memory; "
             "the baselines send retrieved text to an LLM. Unless rules, inputs, memory, prompts and compute are "
             "controlled, a gap cannot be attributed to the database alone. The *Baseline RAG + findings* row equalises "
             "information access; the rest of the gap is deterministic rules versus LLM judgement.")
    L.append("- The **baseline** uses the same LLM, the same documents (every clause of every policy version) and, by "
             "default, the same embedding model as ClaimBridge. It is told to use the version in force on the service "
             "date and to cite passages. Larger embeddings do not remove retrieval, filtering or prompt confounders.")
    L.append("- Because the baselines see only their own tenant's case records, some expected precedents cannot be "
             "reached by them at all. *Precedent recall (reachable)* excludes those; compare it, not the plain recall, "
             "when judging retrieval.")
    L.append("- The **no-memory ablation** is ClaimBridge with Findings hidden: it isolates what semantic memory adds "
             "on top of versioned clauses and gates. It cannot name precedents by design.")
    L.append("- Baseline precedents are past cases mapped to the Finding they support; cited losses (which support no "
             "Finding) are not counted as precedents.")
    L.append("- Missing evidence is not scored on claims whose correct disposition is NO_BASIS_ESCALATE: when no "
             "appeal is possible, which documents are missing is moot.")
    L.append("- M9 counts other-tenant case fields (claim ID, date, notice text) put in front of a tenant (3 per "
             "exposed case). Both systems enforce tenant access, so this is an access-control test, not a graph advantage.")
    L.append("")
    L.append("## Threats to validity\n")
    L.append("- The data is synthetic and the expected answers come from rules we wrote; real denials are messier. "
             "The rule engine is separate code from the Cypher, not an external check.")
    L.append(f"- {len(truth)} scored claims is a small sample; one claim is about {100 / max(len(truth), 1):.0f} points.")
    L.append("- The baseline prompts were written once and not tuned per trap; a heavily engineered RAG could do better.")
    L.append("- LLM outputs are recorded and replayed for reproducibility; a fresh live run can differ.")
    L.append("- Nothing here measures real-world appeal outcomes or whether a changed checklist is useful.")
    return "\n".join(L) + "\n"
