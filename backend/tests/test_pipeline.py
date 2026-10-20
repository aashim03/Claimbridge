"""End to end: agents as separate OS processes coordinating only through FalkorDB."""
from claimbridge import report
from claimbridge.cli import run_pipeline, spawn, wait_for
from claimbridge.tools import coordination as coord


def test_traps_end_to_end(seeded, truth):
    results = run_pipeline(["EV-T1-01", "EV-T2-01", "EV-T4-01", "EV-T5-01", "EV-T6-01"], quiet=True)
    bad = [report.explain_line(r) for r in results if not r["ok"]]
    assert not bad, "\n".join(bad)


def test_verifier_crash_is_resumed_from_checkpoint(seeded, truth):
    cid = "EV-T3-02"
    coord.inject(seeded, [cid])
    procs = [spawn("intake", "t-intake"), spawn("retrieval", "t-retrieval")]
    crashed = spawn("verifier", "t-verifier-1", crash_at="after_verdicts")
    assert crashed.wait(timeout=120) == 137
    procs.append(spawn("verifier", "t-verifier-2"))
    try:
        assert wait_for(seeded, [cid], 60, done={"VERIFIED"})[cid] == "VERIFIED"
    finally:
        for p in procs:
            p.kill()
            p.wait()

    events = coord.timeline(seeded, cid)
    types = [(e["type"], e["agent"]) for e in events]
    assert ("RESUMED", "t-verifier-2") in types
    assert ("VERIFIER_DONE", "t-verifier-2") in types
    assert not any(t == "VERIFIER_DONE" and a == "t-verifier-1" for t, a in types)
    assert '"resumed": true' in [e for e in events if e["type"] == "VERIFIER_DONE"][0]["payload"]
    assert report.check(seeded, truth[cid])["ok"]
