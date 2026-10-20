"""A deliberate stale-worker scenario: a LIVING worker is paused past its lease, a replacement finishes
the step, then the first worker wakes up and tries to write and commit. Used by the tests and by the
chaos evaluation, so the rejected-stale-write evidence comes from the same code in both.

A hard kill (what the random-kill chaos run does) cannot show this: a killed process never wakes up.
"""
import threading
import time

from claimbridge import db
from claimbridge.agents import base
from claimbridge.agents.base import StepResult, Worker
from claimbridge.tools import coordination as coord
from claimbridge.tools import versions


class _NoKeeper:
    """A paused worker's lease-renewal thread does not run either."""
    def __init__(self, *_a, **_k):
        self.lost = False

    def start(self):
        pass

    def stop(self):
        pass


class _Stale(Worker):
    role, input_state, output_state = "intake", "RECEIVED", "CLASSIFIED"

    def __init__(self, pause_s: float, ttl_s: float):
        super().__init__(agent_id="stale-1", lease_ttl_s=ttl_s)
        self.pause_s, self.attempts = pause_s, []

    def work(self, ctx):
        time.sleep(self.pause_s)                                    # GC pause, SIGSTOP, network stall ...
        self.attempts.append(("tool write", versions.select_version(ctx.g, ctx.claim_id, ctx.me)))
        self.attempts.append(("checkpoint", coord.save_checkpoint(ctx.g, ctx.claim_id, ctx.me, "RECEIVED", {"late": True})))
        return StepResult(payload={"by": "stale"})


class _Replacement(Worker):
    role, input_state, output_state = "intake", "RECEIVED", "CLASSIFIED"

    def work(self, ctx):
        assert versions.select_version(ctx.g, ctx.claim_id, ctx.me), "the replacement must be able to write"
        return StepResult(payload={"by": "replacement"})


def prepare_claim(g, cid: str):
    """Only `cid` is RECEIVED, with no lease and no earlier classification."""
    db.run(g, "MATCH (c:Claim) WHERE c.claim_id <> $cid AND c.status = 'RECEIVED' SET c.status = 'NEW'", {"cid": cid})
    db.run(g, """MATCH (c:Claim {claim_id: $cid})
                 SET c.status = 'RECEIVED', c.lease_owner = null, c.lease_until = null, c.attempt = 0""", {"cid": cid})
    db.run(g, "MATCH (c:Claim {claim_id: $cid})-[r:GOVERNED_BY]->() DELETE r", {"cid": cid})


def run_stale_worker_scenario(g, cid: str, ttl_s: float = 4.0) -> dict:
    """Returns the evidence: what the stale worker tried, what was refused, and who committed."""
    prepare_claim(g, cid)
    original = base._LeaseKeeper
    base._LeaseKeeper = _NoKeeper
    try:
        stale = _Stale(pause_s=ttl_s + 2, ttl_s=ttl_s)
        t = threading.Thread(target=stale.step_once)
        t.start()
        deadline = time.time() + 10
        while time.time() < deadline and not db.one(
                g, "MATCH (c:Claim {claim_id:$c}) WHERE c.lease_owner = 'stale-1' RETURN c.claim_id AS x", {"c": cid}):
            time.sleep(0.1)
        time.sleep(ttl_s + 0.5)                                     # its lease expires while it is paused
        replaced = _Replacement(agent_id="replacement-1", lease_ttl_s=ttl_s).step_once()
        t.join(timeout=ttl_s + 60)
    finally:
        base._LeaseKeeper = original
    events = [(e["type"], e["agent"]) for e in coord.timeline(g, cid)]
    cp = coord.load_checkpoint(g, cid, "RECEIVED") or {}
    return {"claim": cid, "lease_ttl_s": ttl_s, "replacement_committed": replaced,
            "stale_attempts": [{"what": w, "accepted": bool(ok)} for w, ok in stale.attempts],
            "fenced_write_rejected_events": events.count(("FENCED_WRITE_REJECTED", "stale-1")),
            "step_done_events": [(t, a) for t, a in events if t.endswith("_DONE")],
            "stale_checkpoint_survived": "late" in cp,
            "events": events}
