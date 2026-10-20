"""Graph traversals that explain themselves (read-only).

Two questions the console answers by walking the graph, not by reading a stored label:

* ``clause_impact``: what depends on this clause? The lineage is found by following
  ``SUPERSEDES`` edges in both directions, then Findings, the evidence they need, the playbook they
  recommend and the claims that considered them are reached by further hops.
* ``precedent_trace``: why was this precedent followed or refused for this claim? The chain of
  edges a precedent must satisfy is rebuilt hop by hop; the first hop that does not hold is the
  break, and it agrees with the verdict code the Verifier wrote.
"""
from claimbridge import db

# The same lineage walk is used by every impact query, so the reader sees one traversal.
LINEAGE = "MATCH (c0:Clause {clause_id: $id})-[:SUPERSEDES*0..4]-(x:Clause) WITH DISTINCT x"

IMPACT_CYPHER = """\
MATCH (c0:Clause {clause_id: $id})-[:SUPERSEDES*0..4]-(x:Clause)      // the clause and every version of it
WITH DISTINCT x
MATCH (f:Finding)-[:ON_LINEAGE]->(x)                                   // memory learned on any of them
OPTIONAL MATCH (f)-[:NEEDS_EVIDENCE]->(e:EvidenceType)                 // the evidence that memory asks for
OPTIONAL MATCH (cl:Claim)-[k:CONSIDERED]->(f)                          // and the claims that weighed it
WHERE cl.source <> 'historical' AND k.reason_code <> 'REASON_MISMATCH'
RETURN x, f, collect(DISTINCT e), collect(DISTINCT cl)"""

# Verdict codes in the order the Verifier checks them; the trace breaks at the first hop that fails.
HOP_FOR_CODE = {
    "REASON_MISMATCH": "reason",
    "LINEAGE_MISMATCH": "lineage",
    "VERSION_DRIFT": "version",
    "CONTRADICTED": "contradiction",
    "CONDITION_UNMET": "conditions",
}


def clause_impact(g, clause_id: str, tenant: str | None = None) -> dict | None:
    """Everything that rests on a clause. Other policyholders' claims are counted, never named."""
    p = {"id": clause_id}
    family = db.run(g, f"""
        {LINEAGE}
        OPTIONAL MATCH (x)-[:SUPERSEDES]->(o:Clause)
        RETURN x.clause_id AS clause_id, x.version_id AS version_id, x.section AS section, x.title AS title,
               x.lineage_id AS lineage_id, x.fingerprint AS fingerprint,
               o.clause_id AS supersedes, o.fingerprint AS old_fingerprint
        ORDER BY version_id""", p)
    if not family:
        return None
    clauses = {}
    for r in family:
        clauses[r["clause_id"]] = {
            "clause_id": r["clause_id"], "version_id": r["version_id"], "section": r["section"], "title": r["title"],
            "lineage_id": r["lineage_id"], "supersedes": r["supersedes"],
            # A changed fingerprint is what limits memory; an unchanged one carries it forward.
            "changed": (r["supersedes"] is not None
                        and (r["fingerprint"] is None or r["old_fingerprint"] is None or r["fingerprint"] != r["old_fingerprint"])),
        }
    findings = db.run(g, f"""
        {LINEAGE}
        MATCH (f:Finding)-[:ON_LINEAGE]->(x)
        OPTIONAL MATCH (f)-[:NEEDS_EVIDENCE]->(e:EvidenceType)
        OPTIONAL MATCH (f)-[:RECOMMENDS]->(pb:Playbook)
        OPTIONAL MATCH (f)-[:STALE_BECAUSE]->(sb:Clause)
        RETURN f.finding_id AS finding_id, f.status AS status, f.statement AS statement, f.origin AS origin,
               x.clause_id AS learned_on, pb.name AS playbook,
               collect(DISTINCT e.code) AS evidence_codes, collect(DISTINCT e.name) AS evidence_names,
               collect(DISTINCT sb.clause_id) AS stale_because
        ORDER BY finding_id""", p)
    considered = db.run(g, f"""
        {LINEAGE}
        MATCH (f:Finding)-[:ON_LINEAGE]->(x)
        MATCH (cl:Claim)-[k:CONSIDERED]->(f)
        WHERE cl.source <> 'historical' AND k.reason_code <> 'REASON_MISMATCH'
        RETURN cl.claim_id AS claim_id, cl.tenant_id AS tenant_id, cl.status AS status,
               f.finding_id AS finding_id, k.reason_code AS code
        ORDER BY claim_id""", p)
    citing = db.run(g, f"""
        {LINEAGE}
        MATCH (cl:Claim)-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(x)
        WHERE cl.source <> 'historical'
        RETURN cl.claim_id AS claim_id, cl.tenant_id AS tenant_id, cl.status AS status, x.clause_id AS clause_id
        ORDER BY claim_id""", p)

    def visible(row) -> bool:
        return tenant is None or row["tenant_id"] == tenant

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(i, kind, label, **kw):
        nodes.setdefault(i, {"id": i, "kind": kind, "label": label, **kw})

    for c in clauses.values():
        node(c["clause_id"], "clause", f"§{c['section']} {c['title']}", sub=c["clause_id"], version=c["version_id"])
        if c["supersedes"] in clauses:
            edges.append({"from": c["clause_id"], "to": c["supersedes"], "label": "supersedes",
                          "state": "changed" if c["changed"] else "same"})
    needed: dict[str, dict] = {}
    for f in findings:
        node(f["finding_id"], "finding", f["finding_id"], status=f["status"], sub=f["status"].lower())
        edges.append({"from": f["finding_id"], "to": f["learned_on"], "label": "learned on"})
        for code, name in zip(f["evidence_codes"], f["evidence_names"]):
            node(code, "evidence", name)
            edges.append({"from": f["finding_id"], "to": code, "label": "needs"})
            needed[code] = {"code": code, "name": name}
        if f["playbook"]:
            node("pb:" + f["playbook"], "playbook", f["playbook"])
            edges.append({"from": f["finding_id"], "to": "pb:" + f["playbook"], "label": "recommends"})
    claim_ids: dict[str, dict] = {}
    for r in considered:
        claim_ids.setdefault(r["claim_id"], r)
        if visible(r):
            node(r["claim_id"], "claim", r["claim_id"], sub=r["status"].lower())
            edges.append({"from": r["claim_id"], "to": r["finding_id"], "label": r["code"].replace("_", " ").lower(), "code": r["code"]})
    for r in citing:
        claim_ids.setdefault(r["claim_id"], r)
        if visible(r):
            node(r["claim_id"], "claim", r["claim_id"], sub=r["status"].lower())
            edges.append({"from": r["claim_id"], "to": r["clause_id"], "label": "denial cites"})
    own = [c for c in claim_ids.values() if visible(c)]
    return {
        "clause_id": clause_id,
        "lineage_id": next(iter(clauses.values()))["lineage_id"],
        "clauses": list(clauses.values()),
        "findings": findings,
        "claims": sorted({c["claim_id"] for c in own}),
        "nodes": list(nodes.values()),
        "edges": edges,
        "counts": {
            "clauses": len(clauses),
            "changed": sum(1 for c in clauses.values() if c["changed"]),
            "findings": len(findings),
            "stale": sum(1 for f in findings if f["status"] == "STALE"),
            "evidence": len(needed),
            "claims": len(claim_ids),
            "claims_visible": len(own),
            "claims_withheld": len(claim_ids) - len(own),
        },
        "cypher": IMPACT_CYPHER,
    }


def clauses_with_dependents(g) -> list[dict]:
    """Clauses to offer in the picker, with how much memory rests on each lineage."""
    return db.run(g, """
        MATCH (x:Clause)
        OPTIONAL MATCH (f:Finding)-[:ON_LINEAGE]->(:Clause {lineage_id: x.lineage_id})
        OPTIONAL MATCH (cl:Claim)-[k:CONSIDERED]->(f)
        WHERE cl.source <> 'historical' AND k.reason_code <> 'REASON_MISMATCH'
        WITH x, count(DISTINCT f) AS findings, count(DISTINCT cl) AS claims
        RETURN x.clause_id AS clause_id, x.version_id AS version_id, x.section AS section, x.title AS title,
               x.lineage_id AS lineage_id, findings, claims
        ORDER BY lineage_id, version_id""")


def precedent_trace(g, cid: str, fid: str) -> dict | None:
    """The chain of edges between a claim and one precedent, with the first broken hop marked."""
    row = db.one(g, """
        MATCH (c:Claim {claim_id: $cid})-[k:CONSIDERED]->(f:Finding {finding_id: $fid})
        MATCH (c)-[:DENIED_FOR]->(r:DenialReason)
        MATCH (c)-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(cc:Clause)
        MATCH (f)-[:ON_LINEAGE]->(fl:Clause)
        OPTIONAL MATCH (f)-[:FOR_REASON]->(fr:DenialReason)
        OPTIONAL MATCH (c)-[:GOVERNED_BY]->(v:PolicyVersion)
        OPTIONAL MATCH (v)-[:CONTAINS]->(gov:Clause)
        WHERE gov.lineage_id = fl.lineage_id
        OPTIONAL MATCH (f)-[vi:VALID_IN]->(v)
        OPTIONAL MATCH (f)-[:CONTRADICTED_BY]->(x:Resolution)
        RETURN k.reason_code AS code, k.source AS source, r.code AS reason, r.name AS reason_name, fr.code AS finding_reason,
               cc.clause_id AS cited, cc.lineage_id AS cited_lineage, cc.section AS cited_section,
               fl.clause_id AS learned_on, fl.lineage_id AS learned_lineage, fl.section AS learned_section,
               v.version_id AS version, v.label AS version_label, gov.clause_id AS governing, vi IS NOT NULL AS valid_in_version,
               f.status AS status, f.req_emergency AS req_emergency, f.req_in_network AS req_in_network,
               c.is_emergency AS is_emergency, c.in_network AS in_network,
               collect(DISTINCT x.resolution_id) AS contradicted_by""", {"cid": cid, "fid": fid})
    if not row:
        return None
    gap = None
    if row["governing"] and row["governing"] != row["learned_on"]:
        gap = db.one(g, """
            MATCH p = (n:Clause {clause_id: $gov})-[:SUPERSEDES*1..4]->(o:Clause {clause_id: $old})
            RETURN length(p) AS steps""", {"gov": row["governing"], "old": row["learned_on"]})

    hops = []

    def hop(key, frm, rel, to, ok, note):
        hops.append({"key": key, "from": frm, "rel": rel, "to": to, "ok": ok, "note": note})

    hop("claim", cid, "denied for", row["reason"], True, f"The notice was classified as {row['reason_name']}.")
    hop("reason", fid, "for reason", row["finding_reason"] or "(a different reason)", row["finding_reason"] == row["reason"],
        "The precedent is about the same kind of denial." if row["finding_reason"] == row["reason"]
        else "The precedent is about a different kind of denial.")
    hop("cites", cid, "notice cites", row["cited"], True, f"The notice cites §{row['cited_section']} (lineage {row['cited_lineage']}).")
    same_lineage = row["learned_lineage"] == row["cited_lineage"]
    hop("lineage", fid, "learned on", row["learned_on"], same_lineage,
        "The precedent was learned on the same clause lineage the notice cites." if same_lineage
        else f"The precedent was learned on {row['learned_lineage']}, not {row['cited_lineage']}.")
    hop("governed", cid, "governed by", row["version_label"] and f"Policy {row['version_label']}", row["version"] is not None,
        "The service date selects this policy version.")
    hop("contains", f"Policy {row['version_label']}", "contains", row["governing"] or "(no clause on this lineage)",
        row["governing"] is not None, "The governing clause of the lineage in force on the service date.")
    if gap:
        hop("supersedes", row["governing"], f"supersedes ×{gap['steps']}", row["learned_on"], True,
            "The governing clause replaced the one the precedent was learned on.")
    valid = bool(row["valid_in_version"])
    hop("version", fid, "valid in", f"Policy {row['version_label']}", valid,
        "Memory was learned on, or carried forward to, this version." if valid
        else "No VALID_IN edge reaches this version: the clause changed after the precedent was learned.")
    hop("contradiction", fid, "contradicted by", ", ".join(row["contradicted_by"]) or "none", not (row["status"] == "CONTRADICTED"),
        "No verified loss under the same conditions." if row["status"] != "CONTRADICTED"
        else "A verified loss under the same conditions withdrew this precedent.")
    unmet = []
    if row["req_emergency"] is not None and row["req_emergency"] != row["is_emergency"]:
        unmet.append("emergency" if row["req_emergency"] else "non-emergency")
    if row["req_in_network"] is not None and row["req_in_network"] != row["in_network"]:
        unmet.append("in-network" if row["req_in_network"] else "out-of-network")
    wants = [w for w, v in (("emergency", row["req_emergency"]), ("in-network", row["req_in_network"])) if v]
    hop("conditions", fid, "requires", ", ".join(wants) or "no conditions", not unmet,
        "This claim meets the precedent's conditions." if not unmet else f"This claim does not meet the condition: {', '.join(unmet)}.")

    # The verdict is whichever check fails first, in the Verifier's order. Hops outside the
    # Verifier's order (claim, cites, governed, contains, supersedes) cannot be the break.
    order = ["reason", "lineage", "version", "contradiction", "conditions"]
    broken = next((h["key"] for k in order for h in hops if h["key"] == k and not h["ok"]), None)
    derived = "ACCEPTED" if broken is None else {v: k for k, v in HOP_FOR_CODE.items()}[broken]
    for h in hops:
        h["break"] = h["key"] == broken
    return {"claim_id": cid, "finding_id": fid, "code": row["code"], "derived_code": derived,
            "broken": broken, "hops": hops, "source": row["source"]}
