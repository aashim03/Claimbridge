"""Applicability of precedent and clause-level gates (Verifier). Decisions are pure Cypher."""
from claimbridge import db
from claimbridge.tools import FENCE


def check_applicability(g, cid: str, me: str | None = None) -> list[dict]:
    """Q4: a verdict for every CONSIDERED Finding, written back onto the edge.

    Order of checks: reason, lineage, version validity, contradiction, conditions.
    """
    return db.run(g, f"""
        MATCH (c:Claim {{claim_id: $cid}})-[:GOVERNED_BY]->(v:PolicyVersion)
        WHERE {FENCE}
        MATCH (c)-[:DENIED_FOR]->(r:DenialReason)
        MATCH (c)-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(cc:Clause)
        MATCH (c)-[k:CONSIDERED]->(f:Finding)-[:ON_LINEAGE]->(fl:Clause)
        OPTIONAL MATCH (f)-[fr:FOR_REASON]->(r)
        OPTIONAL MATCH (f)-[vi:VALID_IN]->(v)
        OPTIONAL MATCH (v)-[:CONTAINS]->(gov:Clause)
        WHERE gov.lineage_id = fl.lineage_id
        OPTIONAL MATCH (f)-[:CONTRADICTED_BY]->(contra:Resolution)
        WITH c, k, f, fl, fr, vi, gov, cc, collect(contra.resolution_id) AS contras
        WITH c, k, f, fl, gov, contras,
          CASE
            WHEN fr IS NULL                          THEN 'REASON_MISMATCH'
            WHEN fl.lineage_id <> cc.lineage_id      THEN 'LINEAGE_MISMATCH'
            WHEN vi IS NULL                          THEN 'VERSION_DRIFT'
            WHEN f.status = 'CONTRADICTED'           THEN 'CONTRADICTED'
            WHEN f.req_emergency IS NOT NULL AND f.req_emergency <> c.is_emergency
                                                     THEN 'CONDITION_UNMET'
            WHEN f.req_in_network IS NOT NULL AND f.req_in_network <> c.in_network
                                                     THEN 'CONDITION_UNMET'
            ELSE 'ACCEPTED'
          END AS code
        SET k.verdict = CASE code WHEN 'ACCEPTED' THEN 'ACCEPTED' ELSE 'REJECTED' END,
            k.reason_code = code
        RETURN f.finding_id AS finding_id, code, k.source AS source,
               fl.clause_id AS learned_on_clause, gov.clause_id AS governing_clause,
               contras AS contradicted_by
        ORDER BY finding_id
    """, {"cid": cid, "me": me})


def gates(g, cid: str, me: str | None = None) -> dict | None:
    """Clause-level reasons why no appeal basis exists (includes Q4b, the timely-filing gate)."""
    return db.one(g, f"""
        MATCH (c:Claim {{claim_id: $cid}})-[:GOVERNED_BY]->(v:PolicyVersion)
        WHERE {FENCE}
        MATCH (c)-[:DENIED_FOR]->(r:DenialReason)
        MATCH (c)-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(cc:Clause)
        OPTIONAL MATCH (v)-[:CONTAINS]->(tf:Clause {{lineage_id: 'L-TIMELY-FILING'}})
        WITH c, [x IN [
            CASE WHEN cc.no_basis = true THEN 'EXCLUSION_NO_BASIS' END,
            CASE WHEN cc.req_emergency = true AND c.is_emergency <> true THEN 'EMERGENCY_REQUIRED' END,
            CASE WHEN r.code = 'TIMELY_FILING' AND c.filing_lag_days > tf.limit_days THEN 'FILED_LATE' END,
            CASE WHEN r.code = 'WAITING_PERIOD' AND coalesce(c.enrolled_months, 0) < cc.wait_months
                 THEN 'WAITING_NOT_MET' END
          ] WHERE x IS NOT NULL] AS gs, cc, tf
        SET c.gates = gs
        RETURN gs AS gates, cc.clause_id AS cited_clause, tf.limit_days AS filing_limit_days,
               c.filing_lag_days AS filing_lag_days
    """, {"cid": cid, "me": me})
