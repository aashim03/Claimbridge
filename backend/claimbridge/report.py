"""Compare what the agents wrote into the graph with the ground truth."""
from claimbridge import db
from claimbridge.tools import evidence
from claimbridge.tools.recommendation import recommendation


def actual(g, cid: str) -> dict:
    head = db.one(g, """
        MATCH (c:Claim {claim_id: $cid})
        OPTIONAL MATCH (c)-[:GOVERNED_BY]->(v:PolicyVersion)
        OPTIONAL MATCH (c)-[:DENIED_FOR]->(r:DenialReason)
        OPTIONAL MATCH (c)-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(cl:Clause)
        RETURN c.status AS status, v.version_id AS version, r.code AS reason,
               cl.clause_id AS clause, cl.lineage_id AS lineage, c.gates AS gates,
               c.disposition AS disposition
    """, {"cid": cid}) or {}
    verdicts = db.run(g, """
        MATCH (:Claim {claim_id: $cid})-[k:CONSIDERED]->(f:Finding)
        RETURN f.finding_id AS finding_id, k.verdict AS verdict, k.reason_code AS code,
               k.source AS source
        ORDER BY finding_id
    """, {"cid": cid})
    return {**head, "verdicts": verdicts, "missing": evidence.missing_evidence(g, cid),
            "recommendation": recommendation(g, cid)}


def check(g, truth: dict) -> dict:
    a = actual(g, truth["claim_id"])
    codes = {v["finding_id"]: v["code"] for v in a["verdicts"]}
    accepted = sorted(f for f, c in codes.items() if c == "ACCEPTED")
    rejected_ok = all(codes.get(r["finding_id"]) == r["code"]
                      for r in truth["expected_rejected_findings"])
    checks = {
        "version": a.get("version") == truth["expected_version"],
        "reason": a.get("reason") == truth["expected_reason"],
        "clause": a.get("clause") == truth["expected_clause"],
        "accepted": accepted == truth["expected_applicable_findings"],
        "rejected": rejected_ok,
        "gates": sorted(a.get("gates") or []) == sorted(truth["expected_gates"]),
        "missing": a["missing"] == truth["expected_missing_evidence"],
    }
    rec = a["recommendation"]
    if a.get("status") in ("AWAITING_REVIEW", "APPROVED", "VERIFIED_OUTCOME", "CURATED"):
        checks["disposition"] = a.get("disposition") == truth["expected_disposition"]
        checks["all_cited"] = bool(rec) and all(i["cites"] for i in rec["items"])
    return {"claim_id": truth["claim_id"], "trap": truth["trap"], "status": a.get("status"),
            "ok": all(checks.values()), "checks": checks, "actual": a, "accepted": accepted}


def explain_line(res: dict) -> str:
    a = res["actual"]
    rej = [f"{v['finding_id']}:{v['code']}" for v in a["verdicts"]
           if v["code"] not in ("ACCEPTED", "REASON_MISMATCH")]
    bad = [k for k, ok in res["checks"].items() if not ok]
    mark = "PASS" if res["ok"] else "FAIL " + ",".join(bad)
    rec = a["recommendation"] or {}
    return (f"{res['claim_id']:9} {str(res['trap'] or '-'):3} {a.get('version')} "
            f"{(a.get('reason') or '?'):18} {(a.get('clause') or '?'):26} "
            f"accept={res['accepted']} reject={rej} gates={a.get('gates') or []} "
            f"missing={a['missing']} -> {a.get('disposition')} "
            f"(items={len(rec.get('items', []))}, conf={rec.get('confidence')})  [{mark}]")
