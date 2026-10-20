"""Evidence gap (Planner)."""
from claimbridge import db


def evidence_gap(g, cid: str) -> list[dict]:
    """Q5: evidence required by the cited clause and by accepted Findings, and whether
    the claim already has it."""
    return db.run(g, """
        MATCH (c:Claim {claim_id: $cid})-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(cl:Clause)
        OPTIONAL MATCH (cl)-[:REQUIRES]->(e1:EvidenceType)
        WITH c, collect(DISTINCT {e: e1, source: cl.clause_id}) AS r1
        OPTIONAL MATCH (c)-[:CONSIDERED {verdict: 'ACCEPTED'}]->(f:Finding)-[:NEEDS_EVIDENCE]->(e2:EvidenceType)
        WITH c, r1, collect(DISTINCT {e: e2, source: f.finding_id}) AS r2
        UNWIND r1 + r2 AS requirement
        WITH c, requirement.e AS e, collect(DISTINCT requirement.source) AS sources
        WHERE e IS NOT NULL
        OPTIONAL MATCH (c)-[:HAS_EVIDENCE]->(ev:Evidence)-[:OF_TYPE]->(e) WHERE coalesce(ev.withdrawn, false) = false
        WITH e, sources, count(ev) AS have
        RETURN e.code AS evidence, e.name AS name, have > 0 AS satisfied, sources
        ORDER BY satisfied, evidence
    """, {"cid": cid})


def missing_evidence(g, cid: str) -> list[str]:
    return sorted(r["evidence"] for r in evidence_gap(g, cid) if not r["satisfied"])
