"""Expired and restarted workers, partial Curator writes. Real FalkorDB; no LLM.

Lease contract (tools/__init__.py): a write is accepted only while the caller still holds the
lease: same owner, same generation, not expired by the database's clock. These tests pause a
LIVING worker past its lease, which a hard kill cannot do."""
import pytest

from claimbridge import config, db, report
from claimbridge.agents import base
from claimbridge.agents.curator import Curator
from claimbridge.evaluation.stale_probe import run_stale_worker_scenario
from claimbridge.supervisor import approve, record_outcome
from claimbridge.tools import Owner, coordination as coord, memory, versions

from test_hardening import process  # the same four-step helper the review tests use


def fresh(g, cid):
    """Only `cid` is RECEIVED, with no lease."""
    db.run(g, "MATCH (c:Claim) WHERE c.claim_id <> $cid AND c.status = 'RECEIVED' SET c.status = 'NEW'", {"cid": cid})
    db.run(g, """MATCH (c:Claim {claim_id: $cid})
                 SET c.status = 'RECEIVED', c.lease_owner = null, c.lease_until = null, c.attempt = 0""", {"cid": cid})
    db.run(g, "MATCH (c:Claim {claim_id: $cid})-[r:GOVERNED_BY]->() DELETE r", {"cid": cid})


def governed(g, cid):
    return db.one(g, "MATCH (:Claim {claim_id:$c})-[:GOVERNED_BY]->(v) RETURN v.version_id AS v", {"c": cid})


def acquire(g, cid, name):
    lease = coord.claim_lease(g, "RECEIVED", name)
    assert lease and lease["claim_id"] == cid
    return Owner(name, lease["gen"])


def expire(g, cid):
    db.run(g, "MATCH (c:Claim {claim_id: $cid}) SET c.lease_until = 1", {"cid": cid})


def test_expired_lease_cannot_write_even_if_nobody_reclaimed_it(seeded):
    cid = "EV-N-07"
    fresh(seeded, cid)
    me = acquire(seeded, cid, "sleeper")
    assert coord.extend_lease(seeded, cid, me)                      # alive: renewable
    expire(seeded, cid)                                             # paused past its lease; owner unchanged
    assert db.one(seeded, "MATCH (c:Claim {claim_id:$c}) RETURN c.lease_owner AS o", {"c": cid})["o"] == "sleeper"
    assert versions.select_version(seeded, cid, me) is None         # tool write refused
    assert not coord.save_checkpoint(seeded, cid, me, "RECEIVED", {"late": True})
    assert not coord.append_event(seeded, cid, "CLAIMED", "sleeper", "intake", "RECEIVED", me=me)
    assert not coord.extend_lease(seeded, cid, me)                  # and it cannot be revived
    assert not coord.commit(seeded, cid, me, "intake", "RECEIVED", "CLASSIFIED", "X")
    assert governed(seeded, cid) is None
    assert db.one(seeded, "MATCH (c:Claim {claim_id:$c}) RETURN c.status AS s", {"c": cid})["s"] == "RECEIVED"


def test_a_restarted_worker_with_the_same_name_is_a_new_incarnation(seeded):
    cid = "EV-N-08"
    fresh(seeded, cid)
    first = acquire(seeded, cid, "worker-7")
    expire(seeded, cid)
    second = acquire(seeded, cid, "worker-7")                       # same name, new acquisition
    assert second.gen == first.gen + 1 and str(first) == str(second)
    assert versions.select_version(seeded, cid, first) is None      # the old incarnation is fenced
    assert not coord.commit(seeded, cid, first, "intake", "RECEIVED", "CLASSIFIED", "X")
    assert not coord.extend_lease(seeded, cid, first)
    assert versions.select_version(seeded, cid, second) is not None
    assert coord.commit(seeded, cid, second, "intake", "RECEIVED", "CLASSIFIED", "X")


def test_a_living_stale_worker_cannot_write_or_commit_and_the_rejection_is_audited(seeded):
    result = run_stale_worker_scenario(seeded, "EV-N-09", ttl_s=config.LEASE_TTL_S)
    events = result["events"]
    assert result["replacement_committed"]
    assert ("RESUMED", "replacement-1") in events
    assert events.count(("INTAKE_DONE", "replacement-1")) == 1
    assert not any(a == "stale-1" and t.endswith("_DONE") for t, a in events)      # it never committed
    assert result["fenced_write_rejected_events"] == 1                            # audit evidence
    assert result["stale_attempts"] == [{"what": "tool write", "accepted": False},
                                        {"what": "checkpoint", "accepted": False}]
    assert report.actual(seeded, "EV-N-09")["status"] == "CLASSIFIED"
    assert result["stale_checkpoint_survived"] is False


# ------------------------------------------------ Curator interrupted between statements

class _Crash(Exception):
    pass


def snapshot(g, cid):
    learned = db.run(g, """
        MATCH (f:Finding {origin: 'learned'})
        OPTIONAL MATCH (f)-[:DERIVED_FROM]->(r:Resolution)
        OPTIONAL MATCH (f)-[:VALID_IN]->(v:PolicyVersion)
        OPTIONAL MATCH (f)-[:NEEDS_EVIDENCE]->(e:EvidenceType)
        OPTIONAL MATCH (f)-[:FOR_REASON]->(dr)
        OPTIONAL MATCH (f)-[:ON_LINEAGE]->(cl)
        RETURN f.finding_id AS id, f.wins AS wins, f.support AS support, f.confidence AS confidence,
               f.status AS status, f.statement AS statement, count(DISTINCT dr) AS reasons, count(DISTINCT cl) AS lineages,
               collect(DISTINCT r.resolution_id) AS resolutions, collect(DISTINCT v.version_id) AS valid,
               collect(DISTINCT e.code) AS needs ORDER BY id""")
    for f in learned:
        for k in ("resolutions", "valid", "needs"):
            f[k] = sorted(f[k])
    playbooks = db.run(g, "MATCH (p:Playbook) RETURN p.playbook_id AS id, p.uses AS uses, p.wins AS wins ORDER BY id")
    followed = db.one(g, "MATCH (:Resolution {resolution_id: $r})-[:FOLLOWED]->(p) RETURN collect(p.playbook_id) AS p",
                      {"r": "R-" + cid})["p"]
    return {"learned": learned, "playbooks": playbooks, "followed": sorted(followed)}


def undo_curation(g, cid, baseline):
    db.run(g, "MATCH (f:Finding {origin: 'learned'}) DETACH DELETE f")
    db.run(g, "MATCH (:Resolution {resolution_id: $r})-[x:FOLLOWED]->() DELETE x", {"r": "R-" + cid})
    for p in baseline:
        db.run(g, "MATCH (p:Playbook {playbook_id: $id}) SET p.uses = $uses, p.wins = $wins", p)
    db.run(g, """MATCH (c:Claim {claim_id: $c})
                 SET c.status = 'VERIFIED_OUTCOME', c.lease_owner = null, c.lease_until = null, c.attempt = 0""", {"c": cid})


def curator_done(g, cid):
    return len([e for e in coord.timeline(g, cid) if e["type"] == "CURATOR_DONE"])


def test_curator_interrupted_after_every_statement_converges_to_one_correct_result(seeded, monkeypatch):
    cid = "EV-M-A"
    process(seeded, cid)
    assert approve(seeded, cid, "reviewer")
    assert record_outcome(seeded, cid, "OVERTURNED", "reviewer", ["EMERGENCY_ATTESTATION", "ITEMIZED_BILL"])
    baseline = db.run(seeded, "MATCH (p:Playbook) RETURN p.playbook_id AS id, p.uses AS uses, p.wins AS wins")

    done = curator_done(seeded, cid)
    assert Curator(agent_id="reference-curator").step_once()
    reference = snapshot(seeded, cid)
    assert curator_done(seeded, cid) == done + 1
    assert len(reference["learned"]) == 1 and reference["learned"][0]["wins"] == 1
    assert reference["learned"][0]["statement"] and reference["learned"][0]["resolutions"] == ["R-" + cid]
    assert reference["followed"] and "ITEMIZED_BILL" in reference["learned"][0]["needs"]

    writes = ["create_finding", "strengthen", "set_statement", "record_playbook_use"]
    crashed_at = []
    for n in range(1, len(writes) + 3):
        undo_curation(seeded, cid, baseline)
        calls = {"n": 0}
        for name in writes:
            original = getattr(memory, name)

            def wrapped(*a, _o=original, _name=name, **k):
                result = _o(*a, **k)                                 # the statement runs, then the worker dies
                calls["n"] += 1
                if calls["n"] == n:
                    raise _Crash(_name)
                return result
            monkeypatch.setattr(memory, name, wrapped)
        before = curator_done(seeded, cid)
        try:
            Curator(agent_id=f"crashing-curator-{n}").step_once()
            finished_uninterrupted = True
        except _Crash as c:
            finished_uninterrupted = False
            crashed_at.append(str(c))
            expire(seeded, cid)                                      # its lease lapses; the process is gone
            for name in writes:
                monkeypatch.undo()
            assert Curator(agent_id=f"replacement-curator-{n}").step_once()
        monkeypatch.undo()
        assert snapshot(seeded, cid) == reference, f"interrupted after write #{n}"
        assert curator_done(seeded, cid) == before + 1, "exactly one completed Curator step"
        assert report.actual(seeded, cid)["status"] == "CURATED"
        if finished_uninterrupted:
            break
    assert crashed_at == writes, "every statement boundary was exercised"


def test_stale_curator_cannot_mutate_memory_after_losing_its_lease(seeded):
    cid = "EV-N-01"
    process(seeded, cid)
    assert approve(seeded, cid, "reviewer") and record_outcome(seeded, cid, "OVERTURNED", "reviewer")
    lease = coord.claim_lease(seeded, "VERIFIED_OUTCOME", "slow-curator")
    slow = Owner("slow-curator", lease["gen"])
    expire(seeded, cid)
    new = coord.claim_lease(seeded, "VERIFIED_OUTCOME", "fast-curator")
    assert new["gen"] == lease["gen"] + 1
    before = snapshot(seeded, cid)
    with pytest.raises(base.Recoverable):
        memory.record_playbook_use(coord.FencedGraph(seeded, cid, slow), cid, "OVERTURNED")
    assert snapshot(seeded, cid) == before
