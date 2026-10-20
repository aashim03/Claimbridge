"""Graph tools: every load-bearing Cypher query lives here (see docs/05-cypher-queries.md).

Write tools take `me` (the calling agent) and only write while that agent holds the
claim's lease. Tests and scripts may pass me=None to skip the fence.

Lease contract. A lease is valid only while ALL of these hold, checked inside the same
query that writes (so check and write are one atomic operation):

  1. `lease_owner` equals the caller;
  2. `lease_gen` equals the generation the caller was given when it acquired the lease
     (every acquisition increments it, so a restarted worker that reuses an old name is
     still told apart from its earlier incarnation);
  3. `lease_until` is not in the past by the DATABASE's clock (`timestamp()`), so worker
     clock skew cannot extend a lease. An expired lease is gone even if nobody has
     reclaimed it yet, and it cannot be renewed.
"""


class Owner(str):
    """A worker's identity for one lease acquisition: its agent id plus the lease generation.

    It behaves exactly like the agent id everywhere (events, logs, equality). `db.run` reads
    `.gen` and passes it to the query as `$gen`, so tools do not change their signatures."""

    gen: int | None

    def __new__(cls, name: str, gen: int | None = None):
        o = super().__new__(cls, name)
        o.gen = gen
        return o


# `c` is the Claim. `$gen` is injected by db.run (None for a plain agent id).
FENCE = ("($me IS NULL OR (c.lease_owner = $me AND ($gen IS NULL OR c.lease_gen = $gen)"
         " AND c.lease_until >= timestamp()))")
