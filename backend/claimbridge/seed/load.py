"""Load knowledge, cases and seed memory into FalkorDB. Deterministic and idempotent:
`reset()` drops the graph and rebuilds it from YAML + data/generated.

`reset(upto="V2025")` builds the world as it was before the 2026 policy existed
(only versions, cases and memory up to 2025). `load_version()` is also what the
Curator uses to publish a new policy version into a running graph.
"""
import json

from claimbridge import config, db, schema
from claimbridge.embed import embed
from claimbridge.knowledge import FLAT_PARAMS, Knowledge, load
from claimbridge.seed.generate import load_cases
from claimbridge.seed.notices import notice_core


def _batches(items, n=25):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def load_base(g, kn: Knowledge):
    """Insurer, plan, taxonomies, tenants and playbooks: everything not tied to a version."""
    raw = kn.raw
    db.run(g, """
        CREATE (i:Insurer {insurer_id: $ins.insurer_id, name: $ins.name})
        CREATE (p:Plan {plan_id: $plan.plan_id, name: $plan.name, tier: $plan.tier})
        CREATE (i)-[:OFFERS]->(p)
    """, {"ins": raw["insurer"], "plan": raw["plan"]})

    reasons = raw["denial_reasons"]
    vecs = embed([f"{r['name']}. {' '.join(r['profile'].split())}" for r in reasons])
    db.run(g, """
        UNWIND $rows AS r
        CREATE (:DenialReason {code: r.code, name: r.name, description: r.profile,
                               embedding: vecf32(r.emb)})
    """, {"rows": [{**r, "profile": " ".join(r["profile"].split()), "emb": v}
                   for r, v in zip(reasons, vecs)]})
    db.run(g, "UNWIND $rows AS r CREATE (:ServiceCategory {code: r.code, name: r.name})",
           {"rows": raw["service_categories"]})
    db.run(g, "UNWIND $rows AS r CREATE (:EvidenceType {code: r.code, name: r.name})",
           {"rows": raw["evidence_types"]})
    db.run(g, "UNWIND $rows AS r CREATE (:Tenant {tenant_id: r.tenant_id, display_name: r.display_name})",
           {"rows": raw["tenants"]})

    for pb in kn.playbooks:
        steps = [{"step_id": f"{pb['playbook_id']}-S{i + 1}", "order": i + 1,
                  "action": s["action"], "evidence": s.get("evidence")}
                 for i, s in enumerate(pb["steps"])]
        db.run(g, """
            MATCH (dr:DenialReason {code: $reason})
            CREATE (p:Playbook {playbook_id: $id, name: $name, uses: 0, wins: 0})
            CREATE (p)-[:FOR_REASON]->(dr)
            WITH p
            UNWIND $steps AS s
            CREATE (st:PlaybookStep {step_id: s.step_id, order: s.order, action: s.action})
            CREATE (p)-[:HAS_STEP]->(st)
            WITH st, s
            OPTIONAL MATCH (e:EvidenceType {code: s.evidence})
            FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END | CREATE (st)-[:USES_EVIDENCE]->(e))
        """, {"reason": pb["reason"], "id": pb["playbook_id"], "name": pb["name"], "steps": steps})
        db.run(g, """
            MATCH (a:PlaybookStep)<-[:HAS_STEP]-(:Playbook {playbook_id: $id})-[:HAS_STEP]->(b:PlaybookStep)
            WHERE b.order = a.order + 1
            CREATE (a)-[:NEXT]->(b)
        """, {"id": pb["playbook_id"]})


def load_version(g, kn: Knowledge, version_id: str) -> int:
    """One policy version and its clauses, linked to the previous version's clauses."""
    v = next(x for x in kn.versions if x["version_id"] == version_id)
    db.run(g, """
        MATCH (p:Plan)
        CREATE (pv:PolicyVersion {version_id: $v.version_id, label: $v.label,
                                  effective_from: $v.effective_from, effective_to: $v.effective_to})
        CREATE (p)-[:HAS_VERSION]->(pv)
        WITH pv
        OPTIONAL MATCH (prev:PolicyVersion {effective_to: $v.effective_from})
        FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END | CREATE (pv)-[:SUCCEEDS]->(prev))
    """, {"v": v})

    clause_rows = []
    for c in kn.by_version[version_id].values():
        props = {"clause_id": c.clause_id, "lineage_id": c.lineage_id, "version_id": c.version_id,
                 "section": c.section, "type": c.type, "title": c.title, "text": c.text,
                 "fingerprint": c.fingerprint, "params": json.dumps(c.params, sort_keys=True)}
        props.update({k: c.params[k] for k in FLAT_PARAMS if k in c.params})
        clause_rows.append({"props": props, "supersedes": c.supersedes, "governs": c.governs,
                            "requires": c.requires, "routes": c.routes})
    for batch in _batches(clause_rows):
        db.run(g, """
            UNWIND $rows AS r
            MATCH (v:PolicyVersion {version_id: r.props.version_id})
            CREATE (c:Clause)
            SET c += r.props
            CREATE (v)-[:CONTAINS]->(c)
            WITH c, r
            OPTIONAL MATCH (old:Clause {clause_id: r.supersedes})
            FOREACH (_ IN CASE WHEN old IS NULL THEN [] ELSE [1] END | CREATE (c)-[:SUPERSEDES]->(old))
        """, {"rows": batch})
        db.run(g, """
            UNWIND $rows AS r
            MATCH (c:Clause {clause_id: r.props.clause_id})
            UNWIND r.requires AS ev
            MATCH (e:EvidenceType {code: ev})
            CREATE (c)-[:REQUIRES]->(e)
        """, {"rows": batch})
        db.run(g, """
            UNWIND $rows AS r
            MATCH (c:Clause {clause_id: r.props.clause_id})
            UNWIND r.governs AS s
            MATCH (sc:ServiceCategory {code: s})
            CREATE (c)-[:GOVERNS]->(sc)
        """, {"rows": batch})
        db.run(g, """
            UNWIND $rows AS r
            MATCH (c:Clause {clause_id: r.props.clause_id})
            UNWIND r.routes AS rt
            MATCH (dr:DenialReason {code: rt.reason})
            CREATE (dr)-[:TYPICALLY_CITES {service: rt.service, priority: rt.priority}]->(c)
        """, {"rows": batch})
    return len(clause_rows)


def load_cases_into(g, kn: Knowledge, cases: list[dict]):
    vecs = embed([notice_core(c["notice_text"]) for c in cases])
    rows = []
    for c, v in zip(cases, vecs):
        hist = c["source"] == "historical"
        version = kn.version_for(c["service_date"])
        row = {
            "claim": {
                "claim_id": c["claim_id"], "tenant_id": c["tenant_id"], "source": c["source"],
                "service_date": c["service_date"], "filed_date": c["filed_date"],
                "filing_lag_days": c["filing_lag_days"], "amount": c["amount"],
                "in_network": c["in_network"], "is_emergency": c["is_emergency"],
                "enrolled_months": c["enrolled_months"], "session_number": c["session_number"],
                "status": "CLOSED" if hist else "NEW", "event_seq": 0, "attempt": 0,
            },
            "service": c["service"],
            "notice": {"notice_id": "N-" + c["claim_id"], "text": c["notice_text"],
                       "issued_date": c["notice_issued"], "emb": v},
            "evidence": [{"doc_id": f"D-{c['claim_id']}-{i + 1}", "type": e,
                          "summary": f"{kn.name('evidence_types', e)} submitted for claim {c['claim_id']}",
                          "submitted_date": c["filed_date"]}
                         for i, e in enumerate(c["evidence"])],
            "hist": None,
        }
        if hist:
            clause = kn.route(c["reason"], c["service"], version)
            row["hist"] = {"version": version, "reason": c["reason"], "clause": clause.clause_id,
                           **c["resolution"]}
        rows.append(row)

    for batch in _batches(rows, 20):
        db.run(g, """
            UNWIND $rows AS r
            MATCH (t:Tenant {tenant_id: r.claim.tenant_id}), (s:ServiceCategory {code: r.service})
            CREATE (c:Claim) SET c += r.claim
            CREATE (t)-[:FILED]->(c)
            CREATE (c)-[:FOR_SERVICE]->(s)
            CREATE (n:DenialNotice {notice_id: r.notice.notice_id, text: r.notice.text,
                                    issued_date: r.notice.issued_date, embedding: vecf32(r.notice.emb)})
            CREATE (c)-[:HAS_NOTICE]->(n)
        """, {"rows": batch})
        db.run(g, """
            UNWIND $rows AS r
            MATCH (c:Claim {claim_id: r.claim.claim_id})
            UNWIND r.evidence AS ev
            MATCH (et:EvidenceType {code: ev.type})
            CREATE (d:Evidence {doc_id: ev.doc_id, summary: ev.summary, submitted_date: ev.submitted_date})
            CREATE (c)-[:HAS_EVIDENCE]->(d)
            CREATE (d)-[:OF_TYPE]->(et)
        """, {"rows": batch})

    hist_rows = [r for r in rows if r["hist"]]
    for batch in _batches(hist_rows, 20):
        db.run(g, """
            UNWIND $rows AS r
            MATCH (c:Claim {claim_id: r.claim.claim_id})-[:HAS_NOTICE]->(n:DenialNotice)
            MATCH (v:PolicyVersion {version_id: r.hist.version})
            MATCH (dr:DenialReason {code: r.hist.reason})
            MATCH (cl:Clause {clause_id: r.hist.clause})
            CREATE (c)-[:GOVERNED_BY]->(v)
            CREATE (c)-[:DENIED_FOR]->(dr)
            CREATE (n)-[:CITES]->(cl)
            CREATE (res:Resolution {resolution_id: r.hist.resolution_id, outcome: r.hist.outcome,
                                    verified: true, verified_on: r.hist.verified_on})
            CREATE (c)-[:RESOLVED_BY]->(res)
            CREATE (res)-[:RELIED_ON]->(cl)
            WITH c, res, r
            OPTIONAL MATCH (pb:Playbook {playbook_id: r.hist.playbook})
            FOREACH (_ IN CASE WHEN pb IS NULL THEN [] ELSE [1] END | CREATE (res)-[:FOLLOWED]->(pb))
            WITH c, res
            MATCH (c)-[:HAS_EVIDENCE]->(d:Evidence)
            CREATE (res)-[:SUPPORTED_BY]->(d)
        """, {"rows": batch})


def load_findings(g, kn: Knowledge, cases: list[dict], versions: list[str]):
    """Seed memory, restricted to what was knowable with the loaded versions and cases."""
    latest = versions[-1]
    for f in kn.findings:
        supports = [c["resolution"]["resolution_id"] for c in cases
                    if (c.get("resolution") or {}).get("supports_finding") == f.finding_id]
        contradicts = [c["resolution"]["resolution_id"] for c in cases
                       if (c.get("resolution") or {}).get("contradicts_finding") == f.finding_id]
        learned = [v for v in f.learned_in if v in versions]
        if not supports or not learned:
            continue  # not yet learnable in this world
        wins, n = len(supports), len(contradicts)
        valid_in = [v for v in f.valid_in if v in versions]
        status = "CONTRADICTED" if n >= wins else ("ACTIVE" if latest in valid_in else "STALE")
        needs = ", ".join(kn.name("evidence_types", e) for e in f.needs)
        cond = " in an emergency" if f.req_emergency else ""
        statement = (f"{kn.name('denial_reasons', f.reason)} denials under {f.lineage}{cond} were "
                     f"overturned when the appeal included: {needs}.")
        r = {
            "props": {"finding_id": f.finding_id, "statement": statement, "status": status,
                      "support": wins, "wins": wins, "confidence": round((wins + 1) / (wins + n + 2), 3),
                      "req_emergency": f.req_emergency, "req_in_network": f.req_in_network,
                      "origin": "seed", "created_at": 0, "updated_at": 0},
            "reason": f.reason, "learned_on": kn.clause(learned[-1], f.lineage).clause_id,
            "playbook": f.playbook,
        }
        db.run(g, """
            MATCH (dr:DenialReason {code: $r.reason}), (cl:Clause {clause_id: $r.learned_on}),
                  (pb:Playbook {playbook_id: $r.playbook})
            CREATE (f:Finding) SET f += $r.props
            CREATE (f)-[:FOR_REASON]->(dr)
            CREATE (f)-[:ON_LINEAGE]->(cl)
            CREATE (f)-[:RECOMMENDS]->(pb)
        """, {"r": r})
        fid = f.finding_id
        db.run(g, """MATCH (f:Finding {finding_id: $id}) UNWIND $xs AS x
                     MATCH (v:PolicyVersion {version_id: x}) CREATE (f)-[:VALID_IN]->(v)""",
               {"id": fid, "xs": valid_in})
        db.run(g, """MATCH (f:Finding {finding_id: $id}) UNWIND $xs AS x
                     MATCH (e:EvidenceType {code: x}) CREATE (f)-[:NEEDS_EVIDENCE]->(e)""",
               {"id": fid, "xs": f.needs})
        db.run(g, """MATCH (f:Finding {finding_id: $id}) UNWIND $xs AS x
                     MATCH (res:Resolution {resolution_id: x}) CREATE (f)-[:DERIVED_FROM]->(res)""",
               {"id": fid, "xs": supports})
        db.run(g, """MATCH (f:Finding {finding_id: $id}) UNWIND $xs AS x
                     MATCH (res:Resolution {resolution_id: x}) CREATE (f)-[:CONTRADICTED_BY]->(res)""",
               {"id": fid, "xs": contradicts})
    # Playbook usage so far, from the historical record.
    db.run(g, """
        MATCH (res:Resolution)-[:FOLLOWED]->(pb:Playbook)
        WITH pb, count(res) AS uses, sum(CASE WHEN res.outcome = 'OVERTURNED' THEN 1 ELSE 0 END) AS wins
        SET pb.uses = uses, pb.wins = wins
    """)


def reset(graph: str | None = None, upto: str | None = None) -> dict:
    """Rebuild the graph. With `upto`, only versions (and cases, memory) up to that version."""
    graph = graph or config.GRAPH
    db.drop(graph)
    g = db.connect(graph)
    schema.ensure(g)
    kn = load()
    ids = [v["version_id"] for v in kn.versions]
    versions = ids[:ids.index(upto) + 1] if upto else ids
    cutoff = next(v for v in kn.versions if v["version_id"] == versions[-1])["effective_to"]
    cases = [c for c in load_cases() if c["service_date"] < cutoff]

    load_base(g, kn)
    for vid in versions:
        load_version(g, kn, vid)
    load_cases_into(g, kn, cases)
    load_findings(g, kn, cases, versions)
    db.run(g, "MERGE (s:Control {id: 'global'}) SET s.world = $w, s.shutdown_at = 0",
           {"w": versions[-1]})
    counts = db.run(g, "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS n ORDER BY label")
    return {r["label"]: r["n"] for r in counts}
