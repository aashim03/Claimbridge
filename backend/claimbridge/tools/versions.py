"""Version selection and clause resolution (Intake)."""
from claimbridge import db
from claimbridge.tools import FENCE


def select_version(g, cid: str, me: str | None = None) -> str | None:
    """Q1: pin the claim to the policy version in force on its service date."""
    r = db.one(g, f"""
        MATCH (c:Claim {{claim_id: $cid}})
        WHERE {FENCE}
        MATCH (v:PolicyVersion)
        WHERE v.effective_from <= c.service_date AND c.service_date < v.effective_to
        MERGE (c)-[:GOVERNED_BY]->(v)
        RETURN v.version_id AS version_id
    """, {"cid": cid, "me": me})
    return r["version_id"] if r else None


def clause_by_section(g, cid: str, section: str) -> dict | None:
    """The clause with this section number in the claim's governing version."""
    return db.one(g, """
        MATCH (c:Claim {claim_id: $cid})-[:GOVERNED_BY]->(:PolicyVersion)-[:CONTAINS]->(cl:Clause)
        WHERE cl.section = $section
        RETURN cl.clause_id AS clause_id, cl.lineage_id AS lineage_id, cl.title AS title
    """, {"cid": cid, "section": section})


def reasons_citing(g, cid: str, clause_id: str) -> list[str]:
    """Denial reasons that typically cite this clause for the claim's service."""
    return [r["code"] for r in db.run(g, """
        MATCH (c:Claim {claim_id: $cid})-[:FOR_SERVICE]->(s:ServiceCategory)
        MATCH (dr:DenialReason)-[t:TYPICALLY_CITES]->(cl:Clause {clause_id: $clause_id})
        WHERE t.service = s.code OR t.service = '*'
        RETURN DISTINCT dr.code AS code
    """, {"cid": cid, "clause_id": clause_id})]


def route_clause(g, cid: str, reason: str) -> dict | None:
    """The clause a (reason, service) denial cites in the governing version.
    A specific service route beats the wildcard; then the higher priority wins."""
    return db.one(g, """
        MATCH (c:Claim {claim_id: $cid})-[:GOVERNED_BY]->(:PolicyVersion)-[:CONTAINS]->(cl:Clause)
              <-[t:TYPICALLY_CITES]-(:DenialReason {code: $reason})
        MATCH (c)-[:FOR_SERVICE]->(s:ServiceCategory)
        WHERE t.service = s.code OR t.service = '*'
        RETURN cl.clause_id AS clause_id, cl.lineage_id AS lineage_id, cl.title AS title,
               t.service = s.code AS specific, t.priority AS priority
        ORDER BY specific DESC, priority DESC
        LIMIT 1
    """, {"cid": cid, "reason": reason})


def reason_by_vector(g, cid: str, k: int = 3) -> list[dict]:
    """Q2: nearest denial reasons to the claim's notice text (score = cosine distance)."""
    return db.run(g, """
        MATCH (c:Claim {claim_id: $cid})-[:HAS_NOTICE]->(n:DenialNotice)
        CALL db.idx.vector.queryNodes('DenialReason', 'embedding', $k, n.embedding)
        YIELD node, score
        RETURN node.code AS code, score
        ORDER BY score
    """, {"cid": cid, "k": k})


def write_classification(g, cid: str, reason: str, clause_id: str, me: str | None = None) -> bool:
    """Record the denial reason and the cited clause (replacing any earlier attempt)."""
    params = {"cid": cid, "me": me, "reason": reason, "clause_id": clause_id}
    db.run(g, f"MATCH (c:Claim {{claim_id: $cid}})-[r:DENIED_FOR]->() WHERE {FENCE} DELETE r", params)
    db.run(g, f"""MATCH (c:Claim {{claim_id: $cid}})-[:HAS_NOTICE]->(:DenialNotice)-[r:CITES]->()
                  WHERE {FENCE} DELETE r""", params)
    r = db.one(g, f"""
        MATCH (c:Claim {{claim_id: $cid}})-[:HAS_NOTICE]->(n:DenialNotice)
        WHERE {FENCE}
        MATCH (dr:DenialReason {{code: $reason}}), (cl:Clause {{clause_id: $clause_id}})
        CREATE (c)-[:DENIED_FOR]->(dr)
        CREATE (n)-[:CITES]->(cl)
        RETURN c.claim_id AS ok
    """, params)
    return r is not None
