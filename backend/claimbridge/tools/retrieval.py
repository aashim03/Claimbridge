"""Candidate precedent retrieval (Retrieval agent).

The graph proposes candidates by structure; vectors only add recall.
Neither decides applicability: that is the Verifier's job (applicability.py).
"""
from claimbridge import config, db
from claimbridge.tools import FENCE


def graph_candidates(g, cid: str, limit: int = config.MAX_CANDIDATES) -> list[dict]:
    """Q3: Findings for the claim's denial reason, same-lineage first."""
    return db.run(g, """
        MATCH (c:Claim {claim_id: $cid})-[:DENIED_FOR]->(r:DenialReason)<-[:FOR_REASON]-(f:Finding)
        MATCH (f)-[:ON_LINEAGE]->(fl:Clause)
        OPTIONAL MATCH (c)-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(cc:Clause)
        RETURN f.finding_id AS finding_id, fl.lineage_id AS lineage_id,
               (cc IS NOT NULL AND fl.lineage_id = cc.lineage_id) AS same_lineage,
               f.status AS status, f.confidence AS confidence
        ORDER BY same_lineage DESC, confidence DESC, finding_id
        LIMIT $limit
    """, {"cid": cid, "limit": limit})


def vector_candidates(g, cid: str, k: int = config.VECTOR_NEIGHBORS) -> list[dict]:
    """Q2b: Findings derived from the k most similar historical denial notices."""
    return db.run(g, """
        MATCH (c:Claim {claim_id: $cid})-[:HAS_NOTICE]->(n:DenialNotice)
        CALL db.idx.vector.queryNodes('DenialNotice', 'embedding', $search, n.embedding)
        YIELD node, score
        MATCH (pc:Claim)-[:HAS_NOTICE]->(node)
        WHERE pc.source = 'historical'
        WITH node, score ORDER BY score LIMIT $k
        MATCH (pc:Claim)-[:HAS_NOTICE]->(node)
        MATCH (pc)-[:RESOLVED_BY]->(:Resolution)<-[:DERIVED_FROM]-(f:Finding)
        RETURN f.finding_id AS finding_id, min(score) AS distance
        ORDER BY distance
    """, {"cid": cid, "k": k, "search": k + 40})


def reason_votes_from_history(g, cid: str, k: int = 7) -> list[dict]:
    """How the k most similar historical notices were classified (weighted by similarity)."""
    return db.run(g, """
        MATCH (c:Claim {claim_id: $cid})-[:HAS_NOTICE]->(n:DenialNotice)
        CALL db.idx.vector.queryNodes('DenialNotice', 'embedding', $search, n.embedding)
        YIELD node, score
        MATCH (pc:Claim)-[:HAS_NOTICE]->(node)
        WHERE pc.source = 'historical'
        WITH pc, score ORDER BY score LIMIT $k
        MATCH (pc)-[:DENIED_FOR]->(r:DenialReason)
        RETURN r.code AS code, sum(1.0 - score) AS weight, count(pc) AS n
        ORDER BY weight DESC
    """, {"cid": cid, "k": k, "search": k + 40})


def nearest_historical(g, cid: str, k: int = 1) -> list[dict]:
    """Nearest historical cases by notice text: what a pure similarity system would reuse."""
    return db.run(g, """
        MATCH (c:Claim {claim_id: $cid})-[:HAS_NOTICE]->(n:DenialNotice)
        CALL db.idx.vector.queryNodes('DenialNotice', 'embedding', $search, n.embedding)
        YIELD node, score
        MATCH (pc:Claim)-[:HAS_NOTICE]->(node)
        WHERE pc.source = 'historical'
        MATCH (pc)-[:RESOLVED_BY]->(res:Resolution)
        OPTIONAL MATCH (res)<-[:DERIVED_FROM]-(f:Finding)
        RETURN pc.claim_id AS claim_id, res.outcome AS outcome, f.finding_id AS finding_id, score
        ORDER BY score
        LIMIT $k
    """, {"cid": cid, "k": k, "search": k + 40})


def write_candidates(g, cid: str, cands: list[dict], me: str | None = None) -> int:
    """Replace the claim's CONSIDERED edges with this candidate list."""
    params = {"cid": cid, "me": me, "cands": cands}
    db.run(g, f"MATCH (c:Claim {{claim_id: $cid}})-[k:CONSIDERED]->() WHERE {FENCE} DELETE k", params)
    r = db.one(g, f"""
        MATCH (c:Claim {{claim_id: $cid}})
        WHERE {FENCE}
        UNWIND $cands AS x
        MATCH (f:Finding {{finding_id: x.finding_id}})
        CREATE (c)-[k:CONSIDERED {{verdict: 'CANDIDATE', source: x.source, score: x.score}}]->(f)
        RETURN count(k) AS n
    """, params)
    return r["n"] if r else 0
