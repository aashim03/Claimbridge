"""Tenant-scoped access (Q11). Shared memory (Findings) is anonymous; the claims a
Finding was learned from are only shown in full to the tenant who filed them."""
from claimbridge import db


def precedent_detail(g, finding_id: str, tenant_id: str) -> list[dict]:
    """The verified resolutions behind a Finding, as seen by `tenant_id`."""
    return db.run(g, """
        MATCH (f:Finding {finding_id: $fid})-[:DERIVED_FROM]->(r:Resolution)<-[:RESOLVED_BY]-(pc:Claim)
        WITH r, pc, pc.tenant_id = $tenant AS own
        OPTIONAL MATCH (pc)-[:HAS_NOTICE]->(n:DenialNotice)
        RETURN r.resolution_id AS resolution_id, r.outcome AS outcome, own,
               CASE WHEN own THEN pc.claim_id ELSE null END AS claim_id,
               CASE WHEN own THEN pc.service_date ELSE null END AS service_date,
               CASE WHEN own THEN n.text ELSE null END AS notice_text
        ORDER BY resolution_id
    """, {"fid": finding_id, "tenant": tenant_id})


def claim_for_tenant(g, claim_id: str, tenant_id: str) -> dict | None:
    """Case-level reads always anchor on the tenant."""
    return db.one(g, """
        MATCH (:Tenant {tenant_id: $tenant})-[:FILED]->(c:Claim {claim_id: $cid})
        RETURN c.claim_id AS claim_id, c.status AS status, c.service_date AS service_date
    """, {"cid": claim_id, "tenant": tenant_id})


def leaked_fields(rows: list[dict]) -> int:
    """How many case-level fields of other tenants a precedent lookup exposed."""
    return sum(1 for r in rows if not r["own"]
               for k in ("claim_id", "service_date", "notice_text") if r[k] is not None)
