"""ClaimBridge command line.

Data and graph
  generate                    build cases.jsonl + ground_truth.json from the YAML
  reset [--upto V2025]        drop + rebuild the graph (optionally as the pre-2026 world)
  selfcheck                   does each trap fool nearest-neighbour reuse?
  publish <version>           publish a policy version and propagate staleness (Curator mode B)

Agents
  up [--pool role=n,...]      run the Supervisor and its worker pool (foreground)
  down                        ask the Supervisor and all workers to stop
  worker <role>               run a single worker
  kill <agent_id>             hard-kill a worker (via the Supervisor)
  start <role>                start one more worker of a role

Claims
  run <ids|all|T1..|M>        reset, inject claims, run the pool until they are planned
  inject <ids>                submit claims to a running pool
  show <claim_id>             timeline, verdicts and recommendation
  approve <claim_id>          human approval of the recommendation
  outcome <claim_id> <OVERTURNED|UPHELD|PARTIAL>   record the real result

Tools for other agents
  mcp                         serve the read-only graph tool catalogue over MCP (stdio); see mcp_server.py
  investigate <claim_id> [--graph-only] [--tenant T]
                              run the investigator; writes results/investigator_<claim_id>.md

Evaluation (resets its OWN graph: set GRAPH=claimbridge_eval first; the demo graph is refused)
  eval [all|claimbridge|no_memory|baseline|baseline_strong|baseline_findings|chaos]
                              start a NEW run in eval/runs/<run_id>/ and run the step(s)
  eval ... --run <id>         add steps that have no output yet to an existing run (never overwrites)
  eval report --run <id>      rebuild that run's report from its raw outputs
  eval promote --run <id>     make a reviewed run the one the API and site serve (archives the old results)
  eval generalization         the pre-registered unseen-case check (data/scenarios/generalization.yaml)

Gates
  gate                        Phase 1: traps end to end + crash/resume
  gate2                       Phase 2: full loop, guard, memory gain, contradiction,
                              supervisor kill/resume, staleness on publish
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import time

from claimbridge import config, db

ROLES = ["intake", "retrieval", "verifier", "planner", "curator"]
DONE = {"AWAITING_REVIEW", "NEEDS_HUMAN", "CURATED"}


def _worker_cls(role: str):
    from claimbridge.agents.curator import Curator
    from claimbridge.agents.intake import Intake
    from claimbridge.agents.planner import Planner
    from claimbridge.agents.retrieval import Retrieval
    from claimbridge.agents.verifier import Verifier
    return {"intake": Intake, "retrieval": Retrieval, "verifier": Verifier,
            "planner": Planner, "curator": Curator}[role]


def _select(ids: list[str]) -> list[str]:
    from claimbridge.seed.generate import load_truth
    truth = load_truth()
    out = []
    for x in ids:
        if x == "all":
            out += list(truth)
        elif x.upper() in {"T1", "T2", "T3", "T4", "T5", "T6", "T7", "M"}:
            out += [c for c, t in truth.items() if t["trap"] == x.upper()]
        elif x.upper() == "NORMAL":
            out += [c for c, t in truth.items() if not t["trap"]]
        else:
            out.append(x)
    return list(dict.fromkeys(out))


def _pool(spec: str | None) -> dict[str, int] | None:
    if not spec:
        return None
    return {k: int(v) for k, v in (p.split("=") for p in spec.split(","))}


def spawn(role: str, agent_id: str, crash_at: str | None = None, env: dict | None = None):
    cmd = [sys.executable, "-m", "claimbridge.cli", "worker", role, "--id", agent_id]
    if crash_at:
        cmd += ["--crash-at", crash_at]
    return subprocess.Popen(cmd, cwd=config.BACKEND_DIR, env={**os.environ, **(env or {})})


def spawn_supervisor(pool: str | None = None, env: dict | None = None):
    cmd = [sys.executable, "-m", "claimbridge.cli", "up"] + (["--pool", pool] if pool else [])
    return subprocess.Popen(cmd, cwd=config.BACKEND_DIR, env={**os.environ, **(env or {})})


def stop_supervisor(g, proc, timeout: float = 30):
    from claimbridge.supervisor import request_shutdown
    request_shutdown(g)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()


def wait_for(g, ids: list[str], timeout_s: float = 900, done: set[str] = DONE) -> dict[str, str]:
    deadline = time.time() + timeout_s
    while True:
        st = {r["id"]: r["status"] for r in db.run(
            g, "MATCH (c:Claim) WHERE c.claim_id IN $ids RETURN c.claim_id AS id, c.status AS status",
            {"ids": ids})}
        if all(s in done for s in st.values()) or time.time() > deadline:
            return st
        time.sleep(0.5)


def print_results(results: list[dict]):
    from claimbridge import report
    for r in results:
        print(report.explain_line(r))
    print(f"\n{sum(r['ok'] for r in results)}/{len(results)} claims match ground truth")


def run_pipeline(ids: list[str], pool: str | None = None, quiet: bool = False,
                 env: dict | None = None) -> list[dict]:
    """Inject claims and run the Supervisor's pool until every claim is planned."""
    from claimbridge import report
    from claimbridge.seed.generate import load_truth
    from claimbridge.tools import coordination as coord
    g = db.connect()
    truth = load_truth()
    coord.inject(g, ids)
    sup = spawn_supervisor(pool, env)
    try:
        wait_for(g, ids)
    finally:
        stop_supervisor(g, sup)
    results = [report.check(g, truth[c]) for c in ids if c in truth]
    if not quiet:
        print_results(results)
    return results


def show(cid: str):
    from claimbridge import report
    from claimbridge.tools import coordination as coord
    g = db.connect()
    print(f"== {cid} timeline")
    for e in coord.timeline(g, cid):
        p = json.loads(e["payload"] or "{}")
        brief = {k: p[k] for k in ("attempt", "previous_owner", "owner", "method", "reason", "clause",
                                   "accepted", "gates", "disposition", "guard", "outcome", "action",
                                   "resumed", "notes") if k in p and p[k] not in (None, [], {})}
        print(f"  #{e['seq']:<2} {e['type']:22} {e['agent']:14} {brief}")
    a = report.actual(g, cid)
    print(f"== state: status={a.get('status')} version={a.get('version')} reason={a.get('reason')} "
          f"clause={a.get('clause')} gates={a.get('gates')} disposition={a.get('disposition')}")
    for v in a["verdicts"]:
        print(f"  {v['finding_id']:22} {v['code']:17} via {v['source']}")
    print(f"  missing evidence: {a['missing']}")
    rec = a["recommendation"]
    if rec:
        print(f"== recommendation ({rec['disposition']}, confidence {rec['confidence']}, "
              f"by {rec.get('llm_platform')}/{rec.get('llm_model')}; guard dropped {rec['guard_dropped']}, "
              f"added {rec['guard_added']})\n  {rec['summary']}")
        for i in rec["items"]:
            print(f"  {i['order']:>2}. [{i['kind']}] {i['text']}  <- {i['cites']} ({i['origin']})")
        for u in rec.get("uncertainty") or []:
            print(f"   ? {u}")


def selfcheck() -> bool:
    from claimbridge.seed.generate import load_truth
    from claimbridge.tools import retrieval
    g = db.connect()
    naive = {"OVERTURNED": "APPEAL_VIABLE", "UPHELD": "NO_BASIS_ESCALATE",
             "PARTIAL": "APPEAL_NEEDS_EVIDENCE"}
    fooled = 0
    traps = [t for t in load_truth().values() if t["trap"] and t["trap"] not in ("T7", "M")]
    print("Trap self-check: would reusing the most similar historical case give the wrong answer?\n")
    for t in traps:
        nn = retrieval.nearest_historical(g, t["claim_id"])
        if not nn:
            print(f"  {t['claim_id']}: no historical neighbor")
            continue
        n = nn[0]
        wrong_finding = n["finding_id"] is not None and n["finding_id"] not in t["expected_applicable_findings"]
        wrong_disp = naive[n["outcome"]] != t["expected_disposition"]
        is_trap = wrong_finding or wrong_disp
        fooled += is_trap
        why = []
        if wrong_finding:
            why.append(f"reuses {n['finding_id']}")
        if wrong_disp:
            why.append(f"{n['outcome']} implies {naive[n['outcome']]}, truth {t['expected_disposition']}")
        print(f"  {t['claim_id']:9} {t['trap']} nearest={n['claim_id']} ({n['outcome']}, "
              f"{n['finding_id'] or 'no finding'}) -> {'WRONG: ' + '; '.join(why) if is_trap else 'naive answer is right'}")
    print(f"\n{fooled}/{len(traps)} traps fool nearest-neighbour reuse "
          "(reported, not asserted: realistic look-alike losses make some naive answers right)")
    return True


def gate():
    """Phase 1 gate: traps through intake/retrieval/verifier + a crash resumed from checkpoint."""
    from claimbridge import report
    from claimbridge.seed.generate import load_truth
    from claimbridge.seed.load import reset
    from claimbridge.tools import coordination as coord

    print("== Phase 1 gate\n-- reset graph")
    reset()
    g = db.connect()
    truth = load_truth()
    ids = ["EV-T1-01", "EV-T5-01", "EV-T6-01"]
    coord.inject(g, ids)
    procs = [spawn(r, f"{r}-1") for r in ("intake", "retrieval", "verifier")]
    try:
        wait_for(g, ids, done={"VERIFIED", "NEEDS_HUMAN"})
    finally:
        for p in procs:
            p.kill()
    results = [report.check(g, truth[c]) for c in ids]
    print_results(results)
    ok = all(r["ok"] for r in results)

    print("\n-- crash and resume: verifier-1 dies after its applicability pass")
    cid = "EV-T3-01"
    env = {"LEASE_TTL_S": "4", "HEARTBEAT_S": "1"}
    coord.inject(g, [cid])
    up = [spawn("intake", "intake-1", env=env), spawn("retrieval", "retrieval-1", env=env)]
    v1 = spawn("verifier", "verifier-1", crash_at="after_verdicts", env=env)
    v1.wait(timeout=120)
    print(f"   verifier-1 exited with code {v1.returncode} (simulated crash, lease left dangling)")
    v2 = spawn("verifier", "verifier-2", env=env)
    try:
        wait_for(g, [cid], 60, done={"VERIFIED"})
    finally:
        for p in up + [v2]:
            p.kill()
    show(cid)
    res = report.check(g, truth[cid])
    resumed = "RESUMED" in [e["type"] for e in coord.timeline(g, cid)] and res["status"] == "VERIFIED"
    print(f"   resumed by verifier-2: {resumed}; result correct: {res['ok']}")
    passed = ok and resumed and res["ok"]
    print(f"\n== PHASE 1 GATE: {'PASS' if passed else 'FAIL'}")
    return passed


def gate2():
    from claimbridge import llm, report
    from claimbridge.agents.curator import publish_version
    from claimbridge.knowledge import load
    from claimbridge.seed.generate import load_truth
    from claimbridge.seed.load import reset
    from claimbridge.supervisor import approve, command, record_outcome
    from claimbridge.tools import coordination as coord

    truth = load_truth()
    checks: dict[str, bool] = {}
    print(f"== Phase 2 gate  (LLM: {config.LLM_PLATFORM}/{llm.model_name()}, mode {config.LLM_MODE})")

    # 1. Full loop for every evaluation claim except the two reserved for later steps.
    print("\n-- 1. all evaluation claims: intake -> retrieval -> verifier -> planner (supervised pool)")
    reset()
    g = db.connect()
    later = ["EV-M-B2", "EV-T4-02"]
    ids = [c for c in truth if c not in later]
    results = run_pipeline(ids)
    checks["all claims match ground truth (incl. disposition, all items cited)"] = all(r["ok"] for r in results)
    guard = db.one(g, """MATCH (r:Recommendation)
                         RETURN count(r) AS recs, sum(r.guard_dropped) AS dropped, sum(r.guard_added) AS added""")
    llm_items = db.one(g, "MATCH (i:RecItem) RETURN sum(CASE WHEN i.origin = 'llm' THEN 1 ELSE 0 END) AS llm, "
                          "count(i) AS total")
    uncited = db.one(g, "MATCH (i:RecItem) WHERE NOT (i)-[:CITES]->() RETURN count(i) AS n")["n"]
    print(f"   citation guard: {guard['recs']} recommendations, {llm_items['total']} items "
          f"({llm_items['llm']} from the LLM), {guard['dropped']} LLM items dropped, "
          f"{guard['added']} required items added; uncited items in graph: {uncited}")
    checks["no uncited recommendation item"] = uncited == 0

    sup = spawn_supervisor()
    try:
        # 2. Memory gain.
        print("\n-- 2. memory gain: approve EV-M-A, record OVERTURNED, then process EV-M-B2")
        b1 = report.actual(g, "EV-M-B1")["recommendation"]
        approve(g, "EV-M-A", "reviewer-demo")
        record_outcome(g, "EV-M-A", "OVERTURNED", "reviewer-demo")
        wait_for(g, ["EV-M-A"], 120, done={"CURATED", "NEEDS_HUMAN"})
        learned = json.loads(coord.timeline(g, "EV-M-A")[-1]["payload"])
        print(f"   curator: {learned.get('action')} {[f['finding_id'] for f in learned.get('findings', [])]}")
        coord.inject(g, ["EV-M-B2"])
        wait_for(g, ["EV-M-B2"], 300)
        b2 = report.actual(g, "EV-M-B2")
        b2_acc = [v["finding_id"] for v in b2["verdicts"] if v["code"] == "ACCEPTED"]
        print(f"   EV-M-B1 (before): accepted=[] confidence={b1['confidence']} uncertainty={b1['uncertainty']}")
        print(f"   EV-M-B2 (after):  accepted={b2_acc} confidence={b2['recommendation']['confidence']} "
              f"uncertainty={b2['recommendation']['uncertainty']}")
        checks["memory: B2 cites the precedent learned from A"] = (
            learned.get("action") == "learned" and bool(b2_acc)
            and b2["recommendation"]["confidence"] > b1["confidence"])

        # 3. Contradiction.
        print("\n-- 3. contradiction: EV-N-04 relied on F-ER-NECESSITY, but its appeal was UPHELD")
        before = db.one(g, "MATCH (f:Finding {finding_id: 'F-ER-NECESSITY'}) RETURN f.confidence AS c, f.status AS s")
        approve(g, "EV-N-04", "reviewer-demo")
        record_outcome(g, "EV-N-04", "UPHELD", "reviewer-demo")
        wait_for(g, ["EV-N-04"], 120, done={"CURATED", "NEEDS_HUMAN"})
        after = db.one(g, "MATCH (f:Finding {finding_id: 'F-ER-NECESSITY'}) RETURN f.confidence AS c, f.status AS s")
        print(f"   F-ER-NECESSITY confidence {before['c']} -> {after['c']}, status {before['s']} -> {after['s']}")
        checks["contradiction lowers confidence"] = after["c"] < before["c"]
    finally:
        stop_supervisor(g, sup)

    # 4. Supervisor kill, then another replica resumes.
    print("\n-- 4. kill a verifier through the Supervisor while it holds a claim")
    env = {"STEP_DELAY_S": "3", "LEASE_TTL_S": "5", "HEARTBEAT_S": "1"}
    sup = spawn_supervisor(env=env)
    cid = "EV-T4-02"
    try:
        coord.inject(g, [cid])
        victim, deadline = None, time.time() + 300
        while not victim and time.time() < deadline:
            r = db.one(g, "MATCH (c:Claim {claim_id: $cid}) RETURN c.lease_owner AS o, c.status AS s", {"cid": cid})
            if r["s"] == "RETRIEVED" and r["o"] and r["o"].startswith("verifier"):
                victim = r["o"]
            time.sleep(0.2)
        command(g, "KILL", victim)
        print(f"   KILL {victim} issued")
        wait_for(g, [cid], 300)
    finally:
        stop_supervisor(g, sup)
    events = [(e["type"], e["agent"]) for e in coord.timeline(g, cid)]
    res = report.check(g, truth[cid])
    resumed_by = [a for t, a in events if t == "RESUMED"]
    print(f"   timeline: {[t for t, _ in events]}")
    print(f"   lease expired: {('LEASE_EXPIRED', 'supervisor') in events}; resumed by: {resumed_by}; "
          f"result correct: {res['ok']}")
    checks["killed worker's claim resumed by another replica"] = (
        ("LEASE_EXPIRED", "supervisor") in events and bool(resumed_by)
        and resumed_by[0] != victim and res["ok"])

    # 5. Staleness when the 2026 policy is published into a 2025 world.
    print("\n-- 5. publish the 2026 policy into the pre-2026 world")
    reset(upto="V2025")
    g = db.connect()
    pre = {r["id"]: r["s"] for r in db.run(g, "MATCH (f:Finding) RETURN f.finding_id AS id, f.status AS s")}
    out = publish_version(g, "V2026")
    kn = load()
    changed = {l for l, c in kn.by_version["V2026"].items()
               if kn.clause("V2025", l) and kn.clause("V2025", l).params != c.params}
    expected = sorted(f.finding_id for f in kn.findings if f.finding_id in pre and f.lineage in changed)
    got = sorted(s["finding_id"] for s in out["stale"])
    print(f"   before: {sum(s == 'ACTIVE' for s in pre.values())}/{len(pre)} Findings ACTIVE")
    for s in out["stale"]:
        print(f"   STALE {s['finding_id']:18} {s['old_clause']} -> {s['new_clause']}")
    print(f"   carried forward to V2026: {len(out['carried_forward'])} Findings")
    checks["exactly the changed-lineage Findings go stale"] = got == expected

    print("\n-- restoring the full graph")
    reset()
    print()
    for name, ok in checks.items():
        print(f"   [{'PASS' if ok else 'FAIL'}] {name}")
    passed = all(checks.values())
    print(f"\n== PHASE 2 GATE: {'PASS' if passed else 'FAIL'}")
    return passed


def main(argv=None):
    p = argparse.ArgumentParser(prog="claimbridge")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate")
    r = sub.add_parser("reset")
    r.add_argument("--upto")
    sub.add_parser("selfcheck")
    pb = sub.add_parser("publish")
    pb.add_argument("version")
    u = sub.add_parser("up")
    u.add_argument("--pool")
    sub.add_parser("down")
    w = sub.add_parser("worker")
    w.add_argument("role", choices=ROLES)
    w.add_argument("--id")
    w.add_argument("--crash-at")
    w.add_argument("--exit-when-idle", action="store_true")
    k = sub.add_parser("kill")
    k.add_argument("agent_id")
    st = sub.add_parser("start")
    st.add_argument("role", choices=ROLES)
    rn = sub.add_parser("run")
    rn.add_argument("ids", nargs="+")
    rn.add_argument("--pool")
    inj = sub.add_parser("inject")
    inj.add_argument("ids", nargs="+")
    s = sub.add_parser("show")
    s.add_argument("claim_id")
    ap = sub.add_parser("approve")
    ap.add_argument("claim_id")
    ap.add_argument("--reviewer", default="reviewer-cli")
    oc = sub.add_parser("outcome")
    oc.add_argument("claim_id")
    oc.add_argument("outcome", choices=["OVERTURNED", "UPHELD", "PARTIAL"])
    oc.add_argument("--reviewer", default="reviewer-cli")
    sub.add_parser("gate")
    sub.add_parser("gate2")
    sub.add_parser("mcp")
    iv = sub.add_parser("investigate")
    iv.add_argument("claim_id")
    iv.add_argument("--graph-only", action="store_true", help="skip the model: fixed-order catalogue run")
    iv.add_argument("--tenant", help="act as this tenant (default: all claims, like the demo)")
    ev = sub.add_parser("eval")
    ev.add_argument("steps", nargs="*", default=["all"],
                    choices=["all", "claimbridge", "no_memory", "baseline", "baseline_strong", "baseline_findings",
                             "chaos", "report", "promote", "generalization"])
    ev.add_argument("--run", help="continue this run id (adds steps without output; never overwrites)")
    ev.add_argument("--label", help="a short name for a new run")
    ev.add_argument("--note", action="append", default=[], help="a sentence recorded in the run and its report (repeatable), e.g. why a system was not run")
    ev.add_argument("--allow-invalid", action="store_true", help="promote a run despite recorded invalidity (not recommended)")
    ev.add_argument("--file", help="generalization: an expectation file under data/scenarios (default generalization.yaml)")
    a = p.parse_args(argv)

    if a.cmd == "mcp":          # stdout belongs to the protocol: no reconfiguring, no prints
        from claimbridge.mcp_server import main as serve_mcp
        return serve_mcp()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for noisy in ("httpx", "httpx2", "openai", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    g = db.connect()
    if a.cmd == "investigate":
        from claimbridge import catalogue, investigator
        run = investigator.investigate(g, catalogue.Scope(a.tenant), a.claim_id, use_llm=not a.graph_only)
        out_dir = config.REPO_DIR / "results"
        out_dir.mkdir(exist_ok=True)
        path = out_dir / f"investigator_{a.claim_id}.md"
        path.write_text(investigator.to_markdown(run), encoding="utf-8")
        print(f"{run.outcome}: {run.label}", f"tokens: {run.tokens}", "", run.brief, "", f"written to {path}", sep=chr(10))
        sys.exit(0 if run.outcome != "unknown_claim" else 1)
    if a.cmd == "generate":
        from claimbridge.seed.generate import generate
        h, e = generate()
        print(f"generated {h} historical and {e} evaluation claims -> {config.GENERATED_DIR}")
    elif a.cmd == "reset":
        from claimbridge.seed.load import reset
        print(json.dumps(reset(upto=a.upto), indent=1))
    elif a.cmd == "selfcheck":
        sys.exit(0 if selfcheck() else 1)
    elif a.cmd == "publish":
        from claimbridge.agents.curator import publish_version
        print(json.dumps(publish_version(g, a.version), indent=1))
    elif a.cmd == "up":
        from claimbridge.supervisor import Supervisor
        Supervisor(pool=_pool(a.pool)).run()
    elif a.cmd == "down":
        from claimbridge.supervisor import request_shutdown
        request_shutdown(g)
    elif a.cmd == "worker":
        _worker_cls(a.role)(agent_id=a.id, crash_at=a.crash_at).run(exit_when_idle=a.exit_when_idle)
    elif a.cmd == "kill":
        from claimbridge.supervisor import command
        print(command(g, "KILL", a.agent_id))
    elif a.cmd == "start":
        from claimbridge.supervisor import command
        print(command(g, "START", a.role))
    elif a.cmd == "run":
        from claimbridge.seed.load import reset
        reset()
        results = run_pipeline(_select(a.ids), a.pool)
        sys.exit(0 if all(x["ok"] for x in results) else 1)
    elif a.cmd == "inject":
        from claimbridge.tools import coordination as coord
        print(coord.inject(g, _select(a.ids)))
    elif a.cmd == "show":
        show(a.claim_id)
    elif a.cmd == "approve":
        from claimbridge.supervisor import approve
        print("approved" if approve(g, a.claim_id, a.reviewer) else "not awaiting review")
    elif a.cmd == "outcome":
        from claimbridge.supervisor import record_outcome
        print("recorded" if record_outcome(g, a.claim_id, a.outcome, a.reviewer) else "claim not approved")
    elif a.cmd == "gate":
        sys.exit(0 if gate() else 1)
    elif a.cmd == "gate2":
        sys.exit(0 if gate2() else 1)
    elif a.cmd == "eval":
        run_eval(a.steps, a.run, a.label, a.allow_invalid, a.file, a.note)


def run_eval(steps: list[str], run_id: str | None = None, label: str | None = None, allow_invalid: bool = False,
             file: str | None = None, notes: list[str] | None = None):
    from claimbridge.evaluation import harness
    from claimbridge.evaluation import provenance as pv
    if "promote" in steps:
        if not run_id:
            raise SystemExit("promote needs --run <id>")
        dest = harness.promote(run_id, allow_invalid)
        print(f"promoted run {run_id} -> {dest}")
        return
    if config.GRAPH == "claimbridge":
        raise SystemExit("The evaluation resets its graph. Refusing to touch the demo graph 'claimbridge': "
                         "set GRAPH=claimbridge_eval (any other name) and run again.")
    order = ["claimbridge", "no_memory", "baseline", "baseline_strong", "baseline_findings", "chaos"]
    todo = order if "all" in steps else [s for s in order if s in steps]
    if "generalization" in steps:
        from claimbridge.evaluation import generalization
        run = harness.begin(run_id, label or "generalization", notes)
        out = generalization.run(config.DATA_DIR / "scenarios" / file if file else None)
        harness.build_report(run)                      # fold the result into the run's report
        print(f"generalization: {out['passed']}/{out['total']} pre-registered expectations met "
              f"(run {run.name}); report: {run / 'generalization.md'}")
        return
    run = harness.begin(run_id, label, notes)
    print(f"run {run.name}  ({run})", flush=True)
    for s in todo:
        name = {"baseline": "baseline_rag", "baseline_strong": "baseline_rag_strong",
                "baseline_findings": "baseline_rag_findings"}.get(s, s)
        if harness.has_output(name):
            print(f"== eval: {s}: already has output in this run; not overwriting (start a new run to repeat it)")
            continue
        print(f"== eval: {s}", flush=True)
        t0 = time.time()
        if s == "claimbridge":
            harness.run_claimbridge()
        elif s == "no_memory":
            harness.run_claimbridge(no_memory=True)
        elif s == "baseline":
            harness.run_baseline(config.BASELINE_EMBED_MODEL, "baseline_rag")
        elif s == "baseline_strong":
            harness.run_baseline(config.BASELINE_STRONG_EMBED_MODEL, "baseline_rag_strong")
        elif s == "baseline_findings":
            harness.run_baseline(config.BASELINE_EMBED_MODEL, "baseline_rag_findings", variant="findings")
        elif s == "chaos":
            harness.run_chaos()
        print(f"   done in {time.time() - t0:.0f} s", flush=True)
    out = harness.build_report(run)
    print(f"\nrun {run.name}: {'VALID' if out['valid'] else 'INVALID: ' + '; '.join(out['run']['invalid_reasons'])}")
    print(f"report: {run / 'report.md'}\n")
    for s, d in out["systems"].items():
        m = d["metrics"]
        print(f"  {d['label']:34} correct {m['all_correct']}  decisions {m['decision_correct']}  "
              f"wrong-precedent {m['M4_wrong_precedent_rate']}  completion {m['completion_rate']}")
    print(f"\nTo publish it: GRAPH={config.GRAPH} python -m claimbridge.cli eval promote --run {run.name}")


if __name__ == "__main__":
    main()
