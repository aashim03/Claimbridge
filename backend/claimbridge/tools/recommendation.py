"""Planner context (read) and Recommendation (write)."""
from claimbridge import db
from claimbridge.tools import FENCE
from claimbridge.tools.evidence import evidence_gap

# Which property identifies a citable node, by ID prefix family.
CITABLE = {
    "PolicyVersion": "version_id",
    "Clause": "clause_id",
    "Finding": "finding_id",
    "EvidenceType": "code",
    "PlaybookStep": "step_id",
    "Resolution": "resolution_id",
}


def planner_context(g, cid: str) -> dict:
    head = db.one(g, """
        MATCH (c:Claim {claim_id: $cid})-[:GOVERNED_BY]->(v:PolicyVersion)
        MATCH (c)-[:DENIED_FOR]->(r:DenialReason)
        MATCH (c)-[:FOR_SERVICE]->(s:ServiceCategory)
        MATCH (c)-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(cc:Clause)
        RETURN c.claim_id AS claim_id, c.service_date AS service_date, c.is_emergency AS is_emergency,
               c.in_network AS in_network, c.filing_lag_days AS filing_lag_days,
               c.enrolled_months AS enrolled_months, coalesce(c.gates, []) AS gates,
               v.version_id AS version_id, r.code AS reason, r.name AS reason_name, s.name AS service,
               cc.clause_id AS clause_id, cc.title AS clause_title, cc.text AS clause_text,
               cc.section AS section
    """, {"cid": cid})
    accepted = db.run(g, """
        MATCH (:Claim {claim_id: $cid})-[:CONSIDERED {verdict: 'ACCEPTED'}]->(f:Finding)
        OPTIONAL MATCH (f)-[:RECOMMENDS]->(:Playbook)-[:HAS_STEP]->(st:PlaybookStep)
        WITH f, st ORDER BY st.order
        RETURN f.finding_id AS finding_id, f.statement AS statement, f.confidence AS confidence,
               f.support AS support, f.status AS status,
               collect(CASE WHEN st IS NULL THEN null ELSE {step_id: st.step_id, action: st.action} END) AS playbook_steps
        ORDER BY finding_id
    """, {"cid": cid})
    rejected = db.run(g, """
        MATCH (c:Claim {claim_id: $cid})-[k:CONSIDERED]->(f:Finding)-[:ON_LINEAGE]->(fl:Clause)
        WHERE k.verdict = 'REJECTED' AND k.reason_code <> 'REASON_MISMATCH'
        MATCH (c)-[:GOVERNED_BY]->(v:PolicyVersion)
        OPTIONAL MATCH (v)-[:CONTAINS]->(gov:Clause)
        WHERE gov.lineage_id = fl.lineage_id
        OPTIONAL MATCH (f)-[:CONTRADICTED_BY]->(x:Resolution)
        RETURN f.finding_id AS finding_id, k.reason_code AS code, f.statement AS statement,
               fl.clause_id AS learned_on, gov.clause_id AS governing,
               collect(x.resolution_id) AS contradicted_by
        ORDER BY finding_id
    """, {"cid": cid})
    for a in accepted:
        a["playbook_steps"] = [s for s in a["playbook_steps"] if s]
    gap = evidence_gap(g, cid)
    return {
        "claim": {k: head[k] for k in ("claim_id", "service", "service_date", "is_emergency",
                                       "in_network", "filing_lag_days", "enrolled_months")},
        "policy_version": head["version_id"],
        "denial_reason": {"code": head["reason"], "name": head["reason_name"]},
        "clause": {"clause_id": head["clause_id"], "section": head["section"],
                   "title": head["clause_title"], "text": head["clause_text"]},
        "gates": head["gates"],
        "evidence": [{"code": e["evidence"], "name": e["name"], "satisfied": e["satisfied"],
                      "sources": e["sources"]} for e in gap],
        "accepted_precedents": accepted,
        "rejected_precedents": rejected,
    }


def allowed_ids(ctx: dict) -> dict[str, str]:
    """Every node the plan may cite, mapped to its label."""
    ids = {ctx["policy_version"]: "PolicyVersion", ctx["clause"]["clause_id"]: "Clause"}
    for e in ctx["evidence"]:
        ids[e["code"]] = "EvidenceType"
    for a in ctx["accepted_precedents"]:
        ids[a["finding_id"]] = "Finding"
        for s in a["playbook_steps"]:
            ids[s["step_id"]] = "PlaybookStep"
    for r in ctx["rejected_precedents"]:
        ids[r["finding_id"]] = "Finding"
        for k in ("learned_on", "governing"):
            if r[k]:
                ids[r[k]] = "Clause"
        for x in r["contradicted_by"]:
            ids[x] = "Resolution"
    return ids


def write_recommendation(g, cid: str, me: str | None, rec: dict, items: list[dict],
                         labels: dict[str, str]) -> int:
    """Replace the claim's Recommendation. Each item is linked to the nodes it cites."""
    params = {"cid": cid, "me": me}
    db.run(g, f"""
        MATCH (c:Claim {{claim_id: $cid}})-[:RECOMMENDATION]->(rec:Recommendation)
        WHERE {FENCE}
        OPTIONAL MATCH (rec)-[:HAS_ITEM]->(i:RecItem)
        DELETE i, rec
    """, params)
    ok = db.one(g, f"""
        MATCH (c:Claim {{claim_id: $cid}})
        WHERE {FENCE}
        CREATE (rec:Recommendation {{rec_id: 'REC-' + $cid}})
        SET rec += $rec
        CREATE (c)-[:RECOMMENDATION]->(rec)
        SET c.disposition = $rec.disposition
        WITH rec
        UNWIND $items AS it
        CREATE (i:RecItem {{item_id: it.item_id, order: it.order, kind: it.kind, text: it.text,
                            origin: it.origin}})
        CREATE (rec)-[:HAS_ITEM]->(i)
        RETURN count(i) AS n
    """, {**params, "rec": rec, "items": [{k: it[k] for k in ("item_id", "order", "kind", "text", "origin")}
                                          for it in items]})
    if ok is None:
        return 0
    for label, key in CITABLE.items():
        pairs = [{"item": it["item_id"], "id": x} for it in items for x in it["cite_ids"]
                 if labels.get(x) == label]
        if pairs:
            db.run(g, f"""
                MATCH (c:Claim {{claim_id: $cid}}) WHERE {FENCE}
                WITH c
                UNWIND $pairs AS p
                MATCH (i:RecItem {{item_id: p.item}}), (n:{label} {{{key}: p.id}})
                CREATE (i)-[:CITES]->(n)
            """, {**params, "pairs": pairs})
    return ok["n"]


def recommendation(g, cid: str) -> dict | None:
    rec = db.one(g, """
        MATCH (:Claim {claim_id: $cid})-[:RECOMMENDATION]->(rec:Recommendation)
        RETURN properties(rec) AS rec
    """, {"cid": cid})
    if not rec:
        return None
    items = db.run(g, """
        MATCH (:Claim {claim_id: $cid})-[:RECOMMENDATION]->(:Recommendation)-[:HAS_ITEM]->(i:RecItem)
        OPTIONAL MATCH (i)-[:CITES]->(n)
        WITH i, collect(coalesce(n.clause_id, n.finding_id, n.code, n.step_id, n.resolution_id,
                                 n.version_id)) AS cites
        RETURN i.order AS order, i.kind AS kind, i.text AS text, i.origin AS origin, cites
        ORDER BY order
    """, {"cid": cid})
    return {**rec["rec"], "items": items}
