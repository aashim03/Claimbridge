"""Leases, fencing, events and checkpoints."""
import threading

from claimbridge import db
from claimbridge.tools import coordination as coord


def _fresh(g, cid):
    db.run(g, """MATCH (c:Claim {claim_id: $cid})
                 SET c.status = 'RECEIVED', c.lease_owner = null, c.lease_until = null, c.attempt = 0""",
           {"cid": cid})
    db.run(g, "MATCH (c:Claim) WHERE c.claim_id <> $cid AND c.status = 'RECEIVED' SET c.status = 'NEW'",
           {"cid": cid})


def test_lease_race_has_exactly_one_winner(seeded):
    for trial in range(10):
        _fresh(seeded, "EV-N-01")
        wins, barrier = [], threading.Barrier(16)

        def claimer(i):
            g = db.connect()
            barrier.wait()
            if coord.claim_lease(g, "RECEIVED", f"racer-{i}"):
                wins.append(i)

        ts = [threading.Thread(target=claimer, args=(i,)) for i in range(16)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert len(wins) == 1, f"trial {trial}: {len(wins)} winners"


def test_expired_lease_can_be_reclaimed(seeded):
    _fresh(seeded, "EV-N-02")
    assert coord.claim_lease(seeded, "RECEIVED", "a", ttl_s=10)["attempt"] == 1
    assert coord.claim_lease(seeded, "RECEIVED", "b", ttl_s=10) is None       # still held
    db.run(seeded, "MATCH (c:Claim {claim_id: 'EV-N-02'}) SET c.lease_until = 0")  # expire it
    again = coord.claim_lease(seeded, "RECEIVED", "b", ttl_s=10)
    assert again["attempt"] == 2 and again["prev_owner"] == "a"


def test_commit_is_fenced(seeded):
    _fresh(seeded, "EV-N-03")
    coord.claim_lease(seeded, "RECEIVED", "old", ttl_s=10)
    db.run(seeded, "MATCH (c:Claim {claim_id: 'EV-N-03'}) SET c.lease_until = 0")
    coord.claim_lease(seeded, "RECEIVED", "new", ttl_s=10)
    # The presumed-dead worker wakes up and tries to commit: rejected, nothing written.
    assert not coord.commit(seeded, "EV-N-03", "old", "test", "RECEIVED", "CLASSIFIED", "X")
    assert not coord.extend_lease(seeded, "EV-N-03", "old")
    assert coord.commit(seeded, "EV-N-03", "new", "test", "RECEIVED", "CLASSIFIED", "X")
    st = db.one(seeded, "MATCH (c:Claim {claim_id: 'EV-N-03'}) RETURN c.status AS s, c.lease_owner AS o")
    assert st == {"s": "CLASSIFIED", "o": None}


def test_events_chain_and_checkpoint(seeded):
    _fresh(seeded, "EV-N-04")
    coord.claim_lease(seeded, "RECEIVED", "w1", ttl_s=10)
    coord.append_event(seeded, "EV-N-04", "CLAIMED", "w1", "test", "RECEIVED", me="w1")
    assert coord.save_checkpoint(seeded, "EV-N-04", "w1", "RECEIVED", {"half": True})
    cp = coord.load_checkpoint(seeded, "EV-N-04", "RECEIVED")
    assert cp["half"] is True and cp["_complete"] is False and cp["_agent_id"] == "w1"
    assert coord.commit(seeded, "EV-N-04", "w1", "test", "RECEIVED", "CLASSIFIED", "DONE", {}, {"all": 1})
    assert coord.load_checkpoint(seeded, "EV-N-04", "RECEIVED")["_complete"] is True
    seqs = [e["seq"] for e in coord.timeline(seeded, "EV-N-04")]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))
    linked = db.one(seeded, """MATCH (:Claim {claim_id: 'EV-N-04'})-[:HAS_EVENT]->(a)-[:NEXT]->(b)
                               RETURN count(*) AS n""")["n"]
    assert linked == len(seqs) - 1


def test_inject_only_new_claims(seeded):
    db.run(seeded, "MATCH (c:Claim {claim_id: 'EV-N-05'}) SET c.status = 'NEW'")
    assert coord.inject(seeded, ["EV-N-05"]) == ["EV-N-05"]
    assert coord.inject(seeded, ["EV-N-05"]) == []
