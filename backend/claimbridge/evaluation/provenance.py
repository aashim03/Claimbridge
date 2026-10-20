"""The identity of one evaluation run: which code, data, prompts, model and cache policy produced it.

Every run lives in its own directory, `eval/runs/<run_id>/`, and raw predictions are written once:
a step that already has output is never overwritten, so a failed or partial run stays on disk and
a re-run is a NEW run. Digests are taken when the run starts and again each time a step saves;
if the source changed in between, the run is marked invalid and cannot be promoted.

    eval/runs/<run_id>/run.json       identity, digests, timings (with timezone), validity
    eval/runs/<run_id>/raw/*.json     one file per system step, never overwritten
    eval/runs/<run_id>/ledger.jsonl   one line per LLM call: system, task, claim, cache key, tokens, fresh/cached
    eval/runs/<run_id>/report.{json,md}
"""
import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from claimbridge import config


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")      # local time WITH its UTC offset


def _digest(files: list[Path], root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(p.relative_to(root).as_posix().encode())
        # Normalise line endings so the same checkout hashes the same on Windows and Linux.
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def source_digest() -> str:
    """The backend implementation under evaluation: every Python source plus its locked dependencies."""
    root = config.BACKEND_DIR
    files = [p for p in (root / "claimbridge").rglob("*.py") if "__pycache__" not in p.parts]
    files += [p for p in (root / "pyproject.toml", root / "uv.lock") if p.exists()]
    return _digest(files, root)


def dataset_digest() -> dict:
    root = config.DATA_DIR
    parts = {"knowledge": sorted((root / "knowledge").glob("*.yaml")),
             "scenarios": sorted((root / "scenarios").glob("*.yaml")),
             "generated": sorted((root / "generated").glob("*"))}
    out = {k: _digest(v, root) for k, v in parts.items()}
    out["all"] = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()
    return out


def prompt_digests() -> dict:
    from claimbridge.agents import intake, planner
    from claimbridge.evaluation import baseline
    texts = {"intake": intake.SYSTEM, "planner": planner.SYSTEM, "baseline": baseline.SYSTEM}
    return {k: hashlib.sha256(v.encode()).hexdigest()[:16] for k, v in texts.items()}


def git_state() -> dict | None:
    def git(*args):
        return subprocess.run(["git", *args], cwd=config.REPO_DIR, capture_output=True, text=True, timeout=30)
    try:
        head = git("rev-parse", "HEAD")
        if head.returncode != 0:
            return None
        status = git("status", "--porcelain", "--untracked-files=no").stdout
        diff = git("diff", "HEAD").stdout
        return {"revision": head.stdout.strip(), "dirty": bool(status.strip()),
                "tracked_diff_sha256": hashlib.sha256(diff.replace("\r\n", "\n").encode()).hexdigest() if diff else None}
    except (OSError, subprocess.SubprocessError):
        return None


def run_config() -> dict:
    return {"llm_platform": config.LLM_PLATFORM, "llm_model": config.LLM_MODEL or config.DEFAULT_MODELS[config.LLM_PLATFORM],
            "llm_mode": config.LLM_MODE, "reasoning_effort": config.LLM_REASONING_EFFORT,
            "embedding_model": config.EMBED_MODEL, "baseline_embedding_model": config.BASELINE_EMBED_MODEL,
            "baseline_strong_embedding_model": config.BASELINE_STRONG_EMBED_MODEL,
            "baseline_top_k": config.BASELINE_TOP_K, "planner_draft_audit": config.PLANNER_DRAFT_AUDIT,
            "graph": config.GRAPH, "lease_ttl_s": config.LEASE_TTL_S,
            "cache_policy": {"cached": "replay a recorded provider response if present, else call and record",
                             "live": "always call the provider", "offline": "replay only"}.get(config.LLM_MODE, config.LLM_MODE)}


def new_run_id() -> str:
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z") + "-" + uuid.uuid4().hex[:6]


def start_run(label: str | None = None) -> Path:
    run_id = new_run_id()
    d = config.RUNS_DIR / run_id
    (d / "raw").mkdir(parents=True)
    write_run(d, {"run_id": run_id, "label": label, "status": "running", "started_at": now_iso(),
                  "git": git_state(), "source_sha256": source_digest(), "dataset": dataset_digest(),
                  "prompts": prompt_digests(), "config": run_config(), "invalid_reasons": [], "steps": {}})
    return d


def open_run(run_id: str) -> Path:
    d = config.RUNS_DIR / run_id
    if not (d / "run.json").exists():
        raise SystemExit(f"no such run: {run_id}")
    return d


def read_run(d: Path) -> dict:
    return json.loads((d / "run.json").read_text(encoding="utf-8"))


def write_run(d: Path, data: dict):
    (d / "run.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")


def update_run(d: Path, **kw) -> dict:
    data = read_run(d)
    data.update(kw)
    write_run(d, data)
    return data


def invalidate(d: Path, reason: str):
    data = read_run(d)
    if reason not in data["invalid_reasons"]:
        data["invalid_reasons"].append(reason)
    write_run(d, data)


def verify_unchanged(d: Path, step: str) -> dict:
    """Digest the source and data again; any difference from the run start invalidates the run."""
    data = read_run(d)
    now_src, now_data = source_digest(), dataset_digest()["all"]
    if now_src != data["source_sha256"]:
        invalidate(d, f"source changed during the run (detected while saving {step})")
    if now_data != data["dataset"]["all"]:
        invalidate(d, f"dataset changed during the run (detected while saving {step})")
    return {"source_sha256_at_save": now_src, "source_unchanged": now_src == data["source_sha256"],
            "dataset_unchanged": now_data == data["dataset"]["all"]}


def ledger_path(d: Path) -> Path:
    return d / "ledger.jsonl"


def read_ledger(d: Path) -> list[dict]:
    p = ledger_path(d)
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []


def activate(d: Path):
    """Point this process (and the workers it spawns) at the run: LLM calls are written to its ledger."""
    os.environ["EVAL_LEDGER"] = str(ledger_path(d))
    os.environ["EVAL_RUN_ID"] = read_run(d)["run_id"]


def ledger_summary(d: Path) -> dict:
    rows = read_ledger(d)
    out = {"calls": len(rows), "fresh": sum(1 for r in rows if not r["cached"] and r["platform"] != "fake"),
           "replayed": sum(1 for r in rows if r["cached"]), "fake": sum(1 for r in rows if r["platform"] == "fake"),
           "by_system": {}}
    for r in rows:
        s = out["by_system"].setdefault(r.get("system") or "unattributed", {"fresh": 0, "replayed": 0, "fake": 0,
                                                                            "input_tokens": 0, "output_tokens": 0})
        s["fake" if r["platform"] == "fake" else "replayed" if r["cached"] else "fresh"] += 1
        s["input_tokens"] += r.get("input_tokens") or 0
        s["output_tokens"] += r.get("output_tokens") or 0
    return out


def ledger_tokens(d: Path, system: str) -> dict[str, tuple[int, int]]:
    """Tokens per claim for ONE system in THIS run, from the calls this run actually made or replayed.
    (Replayed calls carry the tokens recorded when they were first made; the ledger says which is which.)"""
    out: dict[str, tuple[int, int]] = {}
    for r in read_ledger(d):
        if r.get("system") == system and r.get("claim_id"):
            a, b = out.get(r["claim_id"], (0, 0))
            out[r["claim_id"]] = (a + (r.get("input_tokens") or 0), b + (r.get("output_tokens") or 0))
    return out
