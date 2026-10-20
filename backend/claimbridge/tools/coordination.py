"""Coordination through the graph: leases, fenced commits, events, checkpoints, heartbeats.

There is no queue and no agent-to-agent messaging. A claim's status says which role
may work on it, and its lease says which agent currently is.
"""
import json
import os

from claimbridge import config, db
from claimbridge.tools import FENCE


class FencedGraph:
    """Fence each curator query in the same database operation as its effects.

    A stale worker cannot update shared memory after another worker takes its
    lease. Mutations themselves must also be idempotent to survive retries.
    """
    def __init__(self, graph, cid, owner):
        self.graph, self.cid, self.owner = graph, cid, owner

    def query(self, query, params=None):
        from claimbridge.agents.base import Recoverable
        guard = """MATCH (_lease:Claim {claim_id: $_cid})
            WHERE _lease.lease_owner = $_owner AND ($_gen IS NULL OR _lease.lease_gen = $_gen)
              AND _lease.lease_until >= timestamp()
            WITH _lease """
        p = {**(params or {}), "_cid": self.cid, "_owner": str(self.owner), "_gen": getattr(self.owner, "gen", None)}
        # The prefix is the atomic fence; this check gives callers a useful error.
        alive = db.one(self.graph, guard + "RETURN _lease.claim_id AS id", p)
        if not alive:
            raise Recoverable("memory write fenced: lease no longer owned")
        return self.graph.query(guard + query, p)

# Appends one CaseEvent after `c` (expects `c` bound and c.event_seq already incremented).
_EVENT = """
    WITH c
    OPTIONAL MATCH (c)-[:HAS_EVENT]->(prev:CaseEvent)
    WHERE prev.seq = c.event_seq - 1
    CREATE (e:CaseEvent {event_id: c.claim_id + ':' + toString(c.event_seq), seq: c.event_seq,
                         type: $etype, ts: $now, agent_id: $agent, step: $step, payload: $payload})
    CREATE (c)-[:HAS_EVENT]->(e)
    FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END | CREATE (prev)-[:NEXT]->(e))
    MERGE (a:Agent {agent_id: $agent})
    ON CREATE SET a.role = $role
    CREATE (a)-[:PERFORMED]->(e)
"""


def _event_params(etype, agent, role, step, payload) -> dict:
    return {"etype": etype, "agent": agent, "role": role, "step": step,
            "payload": json.dumps(payload or {}), "now": db.now_ms()}


def claim_lease(g, state: str, me: str, ttl_s: float = config.LEASE_TTL_S) -> dict | None:
    """Q7: atomically take the oldest claim in `state` whose lease is free or expired.
    FalkorDB applies write queries to a graph one at a time, so exactly one worker wins."""
    # Time is the database's clock, and every acquisition bumps `lease_gen`: the fencing token
    # a worker presents on each later write (see the lease contract in tools/__init__.py).
    return db.one(g, """
        MATCH (c:Claim {status: $state})
        WHERE c.lease_owner IS NULL OR c.lease_until < timestamp()
        WITH c ORDER BY c.filed_date, c.claim_id LIMIT 1
        SET c.prev_owner = c.lease_owner,
            c.lease_owner = $me,
            c.lease_until = timestamp() + $ttl,
            c.attempt = coalesce(c.attempt, 0) + 1,
            c.lease_gen = coalesce(c.lease_gen, 0) + 1
        RETURN c.claim_id AS claim_id, c.attempt AS attempt, c.prev_owner AS prev_owner, c.lease_gen AS gen
    """, {"state": state, "me": str(me), "ttl": int(ttl_s * 1000)})


def extend_lease(g, cid: str, me: str, ttl_s: float = config.LEASE_TTL_S) -> bool:
    """Q7b: heartbeat. Renews only a lease that is still valid: same owner, same generation and
    not yet expired. A lease that lapsed cannot be revived, even if nobody has reclaimed it."""
    r = db.one(g, """
        MATCH (c:Claim {claim_id: $cid})
        WHERE c.lease_owner = $me AND ($gen IS NULL OR c.lease_gen = $gen) AND c.lease_until >= timestamp()
        SET c.lease_until = timestamp() + $ttl
        RETURN c.claim_id AS ok
    """, {"cid": cid, "me": me, "ttl": int(ttl_s * 1000)})
    return r is not None


def commit(g, cid: str, me: str, role: str, from_state: str, to_state: str,
           etype: str, payload: dict | None = None, checkpoint: dict | None = None) -> bool:
    """Q8: the single commit point of a step. Advances status, clears the lease,
    appends an event and a completed checkpoint, only if `me` still owns the lease
    and the claim is still in `from_state`. False means we were fenced out."""
    params = {"cid": cid, "me": me, "from": from_state, "to": to_state,
              "checkpoint": json.dumps(checkpoint or {}),
              **_event_params(etype, me, role, from_state, payload)}
    r = db.one(g, f"""
        MATCH (c:Claim {{claim_id: $cid}})
        WHERE c.lease_owner = $me AND ($gen IS NULL OR c.lease_gen = $gen)
          AND c.lease_until >= timestamp() AND c.status = $from
        SET c.status = $to, c.lease_owner = null, c.lease_until = null, c.attempt = 0,
            c.event_seq = coalesce(c.event_seq, 0) + 1
        {_EVENT}
        MERGE (cp:Checkpoint {{checkpoint_id: c.claim_id + ':' + $from}})
        SET cp.step = $from, cp.state = $checkpoint, cp.ts = $now, cp.agent_id = $me,
            cp.complete = true
        MERGE (c)-[:HAS_CHECKPOINT]->(cp)
        RETURN c.status AS status
    """, params)
    return r is not None


def append_event(g, cid: str, etype: str, agent: str, role: str, step: str | None = None,
                 payload: dict | None = None, me: str | None = None) -> bool:
    """Append an event without changing status (e.g. CLAIMED, RESUMED, LEASE_EXPIRED)."""
    params = {"cid": cid, "me": me, **_event_params(etype, agent, role, step, payload)}
    r = db.one(g, f"""
        MATCH (c:Claim {{claim_id: $cid}})
        WHERE {FENCE}
        SET c.event_seq = coalesce(c.event_seq, 0) + 1
        {_EVENT}
        RETURN c.claim_id AS ok
    """, params)
    return r is not None


def save_checkpoint(g, cid: str, me: str, step: str, state: dict) -> bool:
    """Intermediate checkpoint inside a step, so a replacement can skip finished work."""
    r = db.one(g, f"""
        MATCH (c:Claim {{claim_id: $cid}})
        WHERE {FENCE}
        MERGE (cp:Checkpoint {{checkpoint_id: c.claim_id + ':' + $step}})
        SET cp.step = $step, cp.state = $state, cp.ts = $now, cp.agent_id = $me, cp.complete = false
        MERGE (c)-[:HAS_CHECKPOINT]->(cp)
        RETURN cp.checkpoint_id AS ok
    """, {"cid": cid, "me": me, "step": step, "state": json.dumps(state), "now": db.now_ms()})
    return r is not None


def load_checkpoint(g, cid: str, step: str) -> dict | None:
    r = db.one(g, """
        MATCH (:Claim {claim_id: $cid})-[:HAS_CHECKPOINT]->(cp:Checkpoint {step: $step})
        RETURN cp.state AS state, cp.agent_id AS agent_id, cp.complete AS complete
    """, {"cid": cid, "step": step})
    if not r:
        return None
    return {**json.loads(r["state"]), "_agent_id": r["agent_id"], "_complete": r["complete"]}


def release(g, cid: str, me: str) -> bool:
    """Give the lease back without advancing (recoverable failure)."""
    return db.one(g, """
        MATCH (c:Claim {claim_id: $cid}) WHERE c.lease_owner = $me AND ($gen IS NULL OR c.lease_gen = $gen)
        SET c.lease_owner = null, c.lease_until = null
        RETURN c.claim_id AS ok
    """, {"cid": cid, "me": me}) is not None


def heartbeat(g, me: str, role: str, state: str, cid: str | None = None):
    db.run(g, """
        MERGE (h:WorkerHeartbeat {agent_id: $me})
        SET h.role = $role, h.state = $state, h.current_claim = $cid, h.last_seen = $now, h.pid = $pid
        MERGE (a:Agent {agent_id: $me})
        ON CREATE SET a.role = $role
        MERGE (a)-[:RUNS_ON]->(h)
    """, {"me": me, "role": role, "state": state, "cid": cid, "now": db.now_ms(), "pid": os.getpid()})


def inject(g, claim_ids: list[str]) -> list[str]:
    """Submit seeded claims to the pipeline (NEW -> RECEIVED)."""
    out = []
    for cid in claim_ids:
        params = {"cid": cid, "me": None, **_event_params("SUBMITTED", "system", "system", "NEW", {})}
        r = db.one(g, f"""
            MATCH (c:Claim {{claim_id: $cid}})
            WHERE c.status = 'NEW'
            SET c.status = 'RECEIVED', c.event_seq = coalesce(c.event_seq, 0) + 1
            {_EVENT}
            RETURN c.claim_id AS claim_id
        """, params)
        if r:
            out.append(r["claim_id"])
    return out


def timeline(g, cid: str) -> list[dict]:
    return db.run(g, """
        MATCH (:Claim {claim_id: $cid})-[:HAS_EVENT]->(e:CaseEvent)
        RETURN e.seq AS seq, e.type AS type, e.agent_id AS agent, e.step AS step,
               e.ts AS ts, e.payload AS payload
        ORDER BY seq
    """, {"cid": cid})
