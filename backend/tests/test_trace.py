"""The graph explains itself: precedent traces agree with the Verifier, and a clause's impact is a real traversal."""
import pytest

from claimbridge.tools import applicability, retrieval, trace, versions


@pytest.fixture(scope="module")
def processed(seeded, truth):
    g = seeded
    for cid, t in truth.items():
        versions.select_version(g, cid)
        versions.write_classification(g, cid, t["expected_reason"], t["expected_clause"])
        retrieval.write_candidates(g, cid, [{"finding_id": c["finding_id"], "source": "graph", "score": 1.0}
                                            for c in retrieval.graph_candidates(g, cid)])
        applicability.check_applicability(g, cid)
    return g


def test_trace_breaks_where_the_verifier_did(processed, truth):
    """For every considered precedent of every claim, the first failing hop reproduces the stored verdict."""
    seen = set()
    for cid in truth:
        rows = processed.query("MATCH (:Claim {claim_id: $c})-[k:CONSIDERED]->(f:Finding) RETURN f.finding_id, k.reason_code",
                               {"c": cid}).result_set
        for fid, code in rows:
            t = trace.precedent_trace(processed, cid, fid)
            assert t["derived_code"] == code, (cid, fid, code, [h for h in t["hops"] if h["break"]])
            assert (t["broken"] is None) == (code == "ACCEPTED")
            seen.add(code)
    assert {"ACCEPTED", "VERSION_DRIFT"} <= seen   # the trace was exercised on both outcomes


def test_version_drift_trace_names_the_superseding_clause(processed):
    # Find any drifted pair from the stored verdicts rather than hard-coding ids.
    cid, fid = processed.query("MATCH (c:Claim)-[k:CONSIDERED {reason_code: 'VERSION_DRIFT'}]->(f:Finding) "
                               "RETURN c.claim_id, f.finding_id LIMIT 1").result_set[0]
    t = trace.precedent_trace(processed, cid, fid)
    assert t["broken"] == "version"
    keys = [h["key"] for h in t["hops"]]
    assert "supersedes" in keys and keys.index("supersedes") < keys.index("version")
    assert next(h for h in t["hops"] if h["break"])["rel"] == "valid in"


def test_trace_is_none_for_an_unconsidered_precedent(processed, truth):
    assert trace.precedent_trace(processed, next(iter(truth)), "F-DOES-NOT-EXIST") is None


def test_impact_follows_the_lineage_across_versions(processed):
    # A clause that has been superseded: its impact must include the newer clause by traversal.
    old, new = processed.query("MATCH (n:Clause)-[:SUPERSEDES]->(o:Clause) RETURN o.clause_id, n.clause_id LIMIT 1").result_set[0]
    a, b = trace.clause_impact(processed, old), trace.clause_impact(processed, new)
    ids = {c["clause_id"] for c in a["clauses"]}
    assert {old, new} <= ids and ids == {c["clause_id"] for c in b["clauses"]}   # same family from either end
    lineage = {r[0] for r in processed.query("MATCH (x:Clause {lineage_id: $l}) RETURN x.clause_id",
                                             {"l": a["lineage_id"]}).result_set}
    assert ids == lineage                                                          # traversal agrees with the lineage key
    assert a["counts"]["findings"] == len(a["findings"])
    assert all(e["from"] in {n["id"] for n in a["nodes"]} and e["to"] in {n["id"] for n in a["nodes"]} for e in a["edges"])


def test_impact_counts_but_does_not_name_other_tenants(processed, truth):
    cid = next(iter(truth))
    clause = processed.query("MATCH (c:Claim {claim_id: $c})-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(x:Clause) RETURN x.clause_id",
                             {"c": cid}).result_set[0][0]
    everyone = trace.clause_impact(processed, clause)
    assert everyone["counts"]["claims_withheld"] == 0
    tenant = processed.query("MATCH (c:Claim {claim_id: $c}) RETURN c.tenant_id", {"c": cid}).result_set[0][0]
    mine = trace.clause_impact(processed, clause, tenant)
    assert set(mine["claims"]) <= set(everyone["claims"])
    assert mine["counts"]["claims"] == everyone["counts"]["claims"]
    assert mine["counts"]["claims_visible"] + mine["counts"]["claims_withheld"] == mine["counts"]["claims"]
    assert not {n["id"] for n in mine["nodes"] if n["kind"] == "claim"} - set(mine["claims"])


def test_unknown_clause_has_no_impact(processed):
    assert trace.clause_impact(processed, "C-NOPE") is None
