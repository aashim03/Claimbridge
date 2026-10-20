"""policy_blast_radius against a small graph whose answer is worked out by hand.

    Clauses of lineage L1:  C3 supersedes C2 supersedes C1.  Lineage L2: D1 alone.
    Findings:   F1 learned on C1,  F2 learned on C2,  G1 learned on D1.
    Claims:     A weighed F1,  B weighed F1 and F2 (tenant T2),  X weighed G1.
    Outcome:    R1 supports F1.

Hand-computed hops from C3 (SUPERSEDES walked both ways, ON_LINEAGE and CONSIDERED followed
towards the claim):  C2=1, C1=2, F2=2, F1=3, R1=4, B=3 (via F2), A=4 (via F1).  G1, D1 and X are not reached.
"""
import pytest

from claimbridge import db
from claimbridge.catalogue import Scope
from claimbridge.tools import blast

GRAPH = "claimbridge_blast_test"


@pytest.fixture(scope="module")
def tiny():
    db.drop(GRAPH)
    g = db.connect(GRAPH)
    g.query("""
        CREATE (c1:Clause {clause_id:'C1', lineage_id:'L1', version_id:'V1', section:'1', title:'One'}),
               (c2:Clause {clause_id:'C2', lineage_id:'L1', version_id:'V2', section:'1', title:'One'}),
               (c3:Clause {clause_id:'C3', lineage_id:'L1', version_id:'V3', section:'1', title:'One'}),
               (d1:Clause {clause_id:'D1', lineage_id:'L2', version_id:'V1', section:'2', title:'Two'}),
               (c3)-[:SUPERSEDES]->(c2), (c2)-[:SUPERSEDES]->(c1),
               (f1:Finding {finding_id:'F1', status:'ACTIVE'}), (f2:Finding {finding_id:'F2', status:'STALE'}),
               (g1:Finding {finding_id:'G1', status:'ACTIVE'}),
               (f1)-[:ON_LINEAGE]->(c1), (f2)-[:ON_LINEAGE]->(c2), (g1)-[:ON_LINEAGE]->(d1),
               (a:Claim {claim_id:'A', tenant_id:'T1', source:'live', status:'CLOSED'}),
               (b:Claim {claim_id:'B', tenant_id:'T2', source:'live', status:'CLOSED'}),
               (x:Claim {claim_id:'X', tenant_id:'T1', source:'live', status:'CLOSED'}),
               (a)-[:CONSIDERED {reason_code:'ACCEPTED'}]->(f1),
               (b)-[:CONSIDERED {reason_code:'ACCEPTED'}]->(f1), (b)-[:CONSIDERED {reason_code:'VERSION_DRIFT'}]->(f2),
               (x)-[:CONSIDERED {reason_code:'ACCEPTED'}]->(g1),
               (r1:Resolution {resolution_id:'R1'}), (f1)-[:DERIVED_FROM]->(r1)
    """)
    yield g
    db.drop(GRAPH)


def test_bfs_hops_match_the_hand_computed_case(tiny):
    out = blast.policy_blast_radius(tiny, Scope(None), "C3")
    hops = {c["clause_id"]: c["hops"] for c in out["clauses"]}
    hops.update({f["finding_id"]: f["hops"] for f in out["findings"]})
    hops.update({o["resolution_id"]: o["hops"] for o in out["outcomes"]})
    hops.update({c["claim_id"]: c["hops"] for c in out["claims"]})
    assert hops == {"C3": 0, "C2": 1, "C1": 2, "F2": 2, "F1": 3, "R1": 4, "B": 3, "A": 4}
    assert out["counts"]["farthest_hop"] == 4


def test_other_tenants_claims_are_counted_not_named(tiny):
    out = blast.policy_blast_radius(tiny, Scope("T1"), "C3")
    assert [c["claim_id"] for c in out["claims"]] == ["A"]
    assert out["counts"]["claims_withheld"] == 1
    assert "'claim_id': 'B'" not in str(out)


def test_lineage_with_more_dependents_ranks_first(tiny):
    ranked = blast.rank_lineages(tiny)
    assert [r["lineage_id"] for r in ranked] == ["L1", "L2"]
    assert ranked[0]["score"] > ranked[1]["score"]
    assert ranked[0]["claims_total"] == 2 and ranked[1]["claims_total"] == 1


def test_scratch_graph_is_dropped_and_live_graph_untouched(tiny):
    before = db.one(tiny, "MATCH (n) RETURN count(n) AS n")["n"]
    blast.policy_blast_radius(tiny, Scope(None), "C1")
    assert db.one(tiny, "MATCH (n) RETURN count(n) AS n")["n"] == before
    from falkordb import FalkorDB
    from claimbridge import config
    left = [k for k in FalkorDB(host=config.FALKORDB_HOST, port=config.FALKORDB_PORT).list_graphs() if k.startswith(GRAPH + "__algo_")]
    assert left == []


def test_unknown_clause(tiny):
    from claimbridge import catalogue
    out = catalogue.call(tiny, Scope(None), "policy_blast_radius", {"clause_id": "NOPE"})
    assert out["ok"] is False and out["error"]["code"] == "NOT_FOUND"
