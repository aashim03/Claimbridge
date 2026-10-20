"""HTTP API for the ClaimBridge console (FastAPI).

The API only reads the graph and writes the same things a human or the Supervisor
would: claim submissions, approvals, outcomes, control commands, policy publishing.
Agents keep coordinating through the graph; the API never talks to them directly.

    uv run uvicorn claimbridge.api:app --port 8000
"""
import asyncio
import json
import random
import re
import threading
import os
import time
import uuid
from datetime import date
from functools import lru_cache

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from claimbridge import auth, catalogue, config, db, investigator, llm, report
from claimbridge.knowledge import load
from claimbridge.supervisor import approve, command, correct_classification, declare_evidence, record_outcome, withdraw_evidence
from claimbridge.tools import coordination as coord
from claimbridge.tools import blast, tenancy, trace

app = FastAPI(title="ClaimBridge API", version="0.4.0")


@app.middleware("http")
async def access_boundary(request: Request, call_next):
    token = None
    try:
        if request.url.path.startswith("/api/") and request.url.path != "/api/session":
            token = auth.current.set(auth.from_request(request))
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-transform"   # no-transform: proxies must not compress or buffer the live stream
        # Tells the page whose data this is, so a tab never shows one identity's data under another's
        # banner after the shared cookie changed in a different tab.
        principal = auth.current.get()
        if principal is not None:
            response.headers["X-ClaimBridge-Subject"] = principal.subject
        return response
    except HTTPException as e:
        return JSONResponse({"detail": e.detail}, status_code=e.status_code)
    finally:
        if token is not None:
            auth.current.reset(token)


class SessionBody(BaseModel):
    token: str = Field(min_length=1, max_length=512)


@app.get("/api/session")
def session(request: Request):
    try:
        p = auth.from_request(request)
    except HTTPException as e:
        if e.status_code != 401:
            raise
        return {"mode": auth.mode(), "authenticated": False}
    return {"mode": auth.mode(), "authenticated": True, "subject": p.subject,
            "role": p.role, "tenant_id": p.tenant_id}


@app.post("/api/session")
def sign_in(body: SessionBody, request: Request, response: Response):
    if request.headers.get("x-claimbridge-request") != "1":
        raise HTTPException(403, "Same-origin request header required.")
    p = auth.authenticate(body.token)
    response.set_cookie("claimbridge_session", body.token, httponly=True, samesite="strict",
                        secure=os.getenv("COOKIE_SECURE", "0") == "1", max_age=auth.SESSION_SECONDS, path="/api")
    return {"subject": p.subject, "role": p.role, "tenant_id": p.tenant_id}


@app.delete("/api/session")
def sign_out(request: Request, response: Response):
    if request.headers.get("x-claimbridge-request") != "1":
        raise HTTPException(403, "Same-origin request header required.")
    response.delete_cookie("claimbridge_session", path="/api")
    return {"ok": True}

STEPS = ["RECEIVED", "CLASSIFIED", "RETRIEVED", "VERIFIED", "AWAITING_REVIEW", "APPROVED",
         "VERIFIED_OUTCOME", "CURATED"]
_world_lock = threading.Lock()
_world_job: dict = {"running": False, "action": None, "error": None}
_new_lock = threading.Lock()


def g():
    return db.connect()


@app.on_event("startup")
def _warm_embedder():
    # Entering a claim by hand embeds its notice; load the model now, not on the first click.
    from claimbridge.embed import embed
    threading.Thread(target=lambda: embed(["warm up"]), daemon=True).start()


@lru_cache(maxsize=1)
def truth() -> dict:
    from claimbridge.seed.generate import load_truth
    return load_truth()


def _names(kind: str) -> dict[str, str]:
    return {x["code"]: x["name"] for x in load().raw[kind]}


def _tenants() -> dict[str, str]:
    return {t["tenant_id"]: t["display_name"] for t in load().raw["tenants"]}


def _payload(e: dict) -> dict:
    try:
        return json.loads(e.get("payload") or "{}")
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------- overview

@app.get("/api/overview")
def overview():
    gr = g()
    ctrl = db.one(gr, "MATCH (s:Control {id: 'global'}) RETURN s.world AS world") or {}
    statuses = {r["s"]: r["n"] for r in db.run(gr, """
        MATCH (c:Claim) WHERE c.source <> 'historical' AND ($tenant IS NULL OR c.tenant_id = $tenant)
        RETURN c.status AS s, count(c) AS n""", {"tenant": auth.tenant()})}
    findings = {r["s"]: r["n"] for r in db.run(gr, "MATCH (f:Finding) RETURN f.status AS s, count(f) AS n")}
    now = db.now_ms()
    workers = db.run(gr, """MATCH (h:WorkerHeartbeat) RETURN h.agent_id AS id, h.role AS role,
                            h.state AS state, h.last_seen AS seen""")
    alive = [w for w in workers if w["seen"] and now - w["seen"] < 15000 and w["state"] not in ("stopped", "killed", "dead")]
    return {
        "world": ctrl.get("world"),
        "statuses": statuses,
        "findings": findings,
        "workers_alive": len([w for w in alive if w["role"] != "supervisor"]),
        "supervisor_alive": any(w["role"] == "supervisor" for w in alive),
        "llm": {"platform": config.LLM_PLATFORM, "model": llm.model_name(), "mode": config.LLM_MODE},
        "world_job": _world_job if auth.tenant() is None else {"running": False},
    }


# ------------------------------------------------------------------ claims

@app.get("/api/claims")
def claims():
    gr = g()
    services, reasons, tenants, t = _names("service_categories"), _names("denial_reasons"), _tenants(), truth()
    rows = db.run(gr, """
        MATCH (c:Claim)-[:FOR_SERVICE]->(s:ServiceCategory)
        WHERE c.source <> 'historical' AND ($tenant IS NULL OR c.tenant_id = $tenant)
        OPTIONAL MATCH (c)-[:DENIED_FOR]->(r:DenialReason)
        OPTIONAL MATCH (c)-[:GOVERNED_BY]->(v:PolicyVersion)
        OPTIONAL MATCH (c)-[:RECOMMENDATION]->(rec:Recommendation)
        RETURN c.claim_id AS claim_id, c.tenant_id AS tenant_id, s.code AS service, c.service_date AS service_date,
               c.status AS status, r.code AS reason, v.label AS version, c.disposition AS disposition,
               c.lease_owner AS lease_owner, c.attempt AS attempt, c.amount AS amount,
               rec.confidence AS confidence, c.event_seq AS events
        ORDER BY claim_id""", {"tenant": auth.tenant()})
    flags = {}
    for f in db.run(gr, """
        MATCH (c:Claim)-[k:CONSIDERED]->(f:Finding) WHERE c.source <> 'historical' AND k.reason_code <> 'REASON_MISMATCH'
        RETURN c.claim_id AS cid, f.finding_id AS fid, k.reason_code AS code ORDER BY fid"""):
        flags.setdefault(f["cid"], []).append({"finding_id": f["fid"], "code": f["code"]})
    last = {r["cid"]: r["ts"] for r in db.run(gr, """
        MATCH (c:Claim)-[:HAS_EVENT]->(e:CaseEvent) WHERE c.source <> 'historical'
        RETURN c.claim_id AS cid, max(e.ts) AS ts""")}
    out = []
    for r in rows:
        tr = t.get(r["claim_id"], {})
        out.append({**r, "service_name": services.get(r["service"]), "reason_name": reasons.get(r["reason"]),
                    "tenant": tenants.get(r["tenant_id"]), "trap": tr.get("trap"), "note": tr.get("note"),
                    "flags": flags.get(r["claim_id"], []), "updated_at": last.get(r["claim_id"])})
    return out


class InjectBody(BaseModel):
    ids: list[str] = []
    group: str | None = None   # T1..T7, M, normal, all


@app.post("/api/claims/inject")
def inject(body: InjectBody):
    t = truth()
    ids = list(body.ids)
    if body.group:
        grp = body.group.upper()
        ids += [c for c, x in t.items() if (grp == "ALL") or (grp == "NORMAL" and not x["trap"])
                or x["trap"] == grp]
    ids = list(dict.fromkeys(ids))
    for cid in ids:
        _claim_access(cid)
    return {"injected": coord.inject(g(), ids)}


@app.get("/api/catalog")
def catalog():
    """What a caseworker can choose from when entering a claim by hand."""
    raw = load().raw
    pick = lambda kind: [{"code": x["code"], "name": x["name"]} for x in raw[kind]]  # noqa: E731
    return {"tenants": [{"code": t["tenant_id"], "name": t["display_name"]} for t in raw["tenants"]
                        if auth.tenant() is None or t["tenant_id"] == auth.tenant()],
            "services": pick("service_categories"), "reasons": pick("denial_reasons"),
            "evidence": pick("evidence_types")}


def _date_int(s: str) -> int:
    try:
        y, m, d = (int(x) for x in s.split("-"))
        return date(y, m, d).year * 10000 + m * 100 + d
    except ValueError:
        raise HTTPException(422, "Dates must be YYYY-MM-DD.") from None


class SampleBody(BaseModel):
    service: str
    reason: str
    service_date: str


@app.post("/api/claims/sample-notice")
def sample_notice(body: SampleBody):
    """A realistic denial notice for (service, reason), citing the clause in force on that date."""
    from claimbridge.seed.notices import notice_text
    kn = load()
    sd = _date_int(body.service_date)
    try:
        clause = kn.route(body.reason, body.service, kn.version_for(sd))
    except (ValueError, KeyError):
        clause = None
    try:
        text = notice_text(random.Random(), "(new)", kn.name("service_categories", body.service), sd,
                           body.reason, clause, "cited")
    except KeyError:
        raise HTTPException(422, "Unknown service or denial reason.") from None
    return {"text": text, "cites": clause.clause_id if clause else None}


class NewClaimBody(BaseModel):
    tenant_id: str
    service: str
    service_date: str              # YYYY-MM-DD
    filed_date: str                # YYYY-MM-DD
    notice: str
    evidence: list[str] = []
    in_network: bool = True
    is_emergency: bool = False
    enrolled_months: int | None = Field(default=12, ge=0, le=1200)
    file_now: bool = True


@app.post("/api/claims/new")
def new_claim(body: NewClaimBody):
    """Enter a denied claim by hand. It gets the same graph shape as a seeded claim
    (Claim, DenialNotice, Evidence) and, if asked, goes straight to the agents."""
    from claimbridge.seed.load import load_cases_into
    auth.require_tenant(body.tenant_id)
    kn, gr = load(), g()
    cat = catalog()
    if body.tenant_id not in {t["code"] for t in cat["tenants"]}:
        raise HTTPException(422, "Choose one of the fictional policyholders.")
    if body.service not in {s["code"] for s in cat["services"]}:
        raise HTTPException(422, "Unknown service.")
    bad = set(body.evidence) - {e["code"] for e in cat["evidence"]}
    if bad:
        raise HTTPException(422, f"Unknown evidence: {', '.join(sorted(bad))}.")
    notice = " ".join(body.notice.split())
    if not 40 <= len(notice) <= 4000:
        raise HTTPException(422, "The denial notice should be between 40 and 4000 characters.")
    sd, fd = _date_int(body.service_date), _date_int(body.filed_date)
    lag = (date(fd // 10000, fd // 100 % 100, fd % 100) - date(sd // 10000, sd // 100 % 100, sd % 100)).days
    if lag < 0:
        raise HTTPException(422, "The claim cannot be filed before the service date.")
    try:
        version = kn.version_for(sd)
    except ValueError:
        raise HTTPException(422, "No policy version covers that service date.") from None
    if not db.one(gr, "MATCH (v:PolicyVersion {version_id: $v}) RETURN v.version_id AS v", {"v": version}):
        raise HTTPException(409, f"The {version[1:]} policy is not published in this world yet.")

    with _new_lock:
        cid = f"NC-{uuid.uuid4().hex[:12].upper()}"
        notice = notice.replace("(new)", cid)
        load_cases_into(gr, kn, [{
            "claim_id": cid, "tenant_id": body.tenant_id, "source": "manual",
            "service": body.service, "service_date": sd, "filed_date": fd, "filing_lag_days": lag,
            "amount": None, "in_network": body.in_network, "is_emergency": body.is_emergency,
            "enrolled_months": body.enrolled_months, "session_number": None,
            "notice_text": notice, "notice_issued": fd, "evidence": list(dict.fromkeys(body.evidence)),
        }])
    filed = coord.inject(gr, [cid]) if body.file_now else []
    return {"claim_id": cid, "filed": bool(filed), "version": version}


def support_text(rec: dict, verdicts: list[dict]) -> str:
    """The same wording as the console: never a bare 0%."""
    accepted = [v for v in verdicts if v["code"] == "ACCEPTED"]
    state = rec.get("support_state") or ("RECORDED_OUTCOMES" if accepted else "NO_PRECEDENT")
    if state == "NO_PRECEDENT":
        return "none yet (no recorded outcome supports a precedent for this claim)"
    if state == "NO_APPEAL_BASIS":
        return "not applicable (a policy gate leaves no basis for appeal)"
    top = max(accepted, key=lambda v: v["support"], default=None)
    counts = f" ({top['support']} recorded win(s), {len(top['contradicted_by'])} contradicted)" if top else ""
    return f"{round(rec['confidence'] * 100)}%{counts}"


def evidence_origin(sources: list[str]) -> str:
    """Clause IDs are policy requirements; finding IDs are suggestions learned from resolved cases."""
    learned = any(s.startswith("F-") for s in sources)
    policy = any(not s.startswith("F-") for s in sources)
    return "both" if learned and policy else "learned" if learned else "policy"


def _claim_access(cid: str):
    row = db.one(g(), "MATCH (c:Claim {claim_id: $cid}) RETURN c.tenant_id AS tenant", {"cid": cid})
    if not row:
        raise HTTPException(404, "Claim not found.")
    auth.require_tenant(row["tenant"])


@app.get("/api/claims/{cid}")
def claim(cid: str):
    _claim_access(cid)
    gr = g()
    head = db.one(gr, """
        MATCH (c:Claim {claim_id: $cid})-[:FOR_SERVICE]->(s:ServiceCategory)
        MATCH (c)-[:HAS_NOTICE]->(n:DenialNotice)
        OPTIONAL MATCH (c)-[:GOVERNED_BY]->(v:PolicyVersion)
        OPTIONAL MATCH (n)-[:CITES]->(cl:Clause)
        OPTIONAL MATCH (c)-[:DENIED_FOR]->(r:DenialReason)
        RETURN properties(c) AS claim, s.name AS service, n.text AS notice, n.issued_date AS notice_date,
               properties(v) AS version, properties(cl) AS clause, r.code AS reason, r.name AS reason_name
    """, {"cid": cid})
    if not head:
        raise HTTPException(404, f"no claim {cid}")
    c = head["claim"]
    c.pop("embedding", None)
    evidence = db.run(gr, """
        MATCH (:Claim {claim_id: $cid})-[:HAS_EVIDENCE]->(d:Evidence)-[:OF_TYPE]->(e:EvidenceType)
        WHERE coalesce(d.withdrawn, false) = false
        RETURN e.code AS code, e.name AS name, d.submitted_date AS submitted, d.doc_id AS doc_id,
               d.declared_by AS declared_by, coalesce(d.verified, false) AS verified, d.reference AS reference
        ORDER BY code""", {"cid": cid})
    withdrawn = db.run(gr, """
        MATCH (:Claim {claim_id: $cid})-[:HAS_EVIDENCE]->(d:Evidence)-[:OF_TYPE]->(e:EvidenceType)
        WHERE d.withdrawn = true
        RETURN e.name AS name, d.withdrawn_by AS by, d.withdrawn_at AS at ORDER BY at""", {"cid": cid})
    corrections = db.run(gr, """
        MATCH (:Claim {claim_id: $cid})-[:CORRECTED_BY]->(k:Correction)
        RETURN k.correction_id AS id, k.reason_code AS reason, k.previous_reason AS previous_reason, k.note AS note,
               k.reviewer AS reviewer, k.ts AS ts ORDER BY k.ts""", {"cid": cid})
    from claimbridge.supervisor import _escalation
    human_review = _escalation(gr, cid) if c.get("status") == "NEEDS_HUMAN" else None
    verdicts = db.run(gr, """
        MATCH (c:Claim {claim_id: $cid})-[k:CONSIDERED]->(f:Finding)-[:ON_LINEAGE]->(fl:Clause)
        OPTIONAL MATCH (c)-[:GOVERNED_BY]->(v:PolicyVersion)-[:CONTAINS]->(gov:Clause)
        WHERE gov.lineage_id = fl.lineage_id
        OPTIONAL MATCH (f)-[:CONTRADICTED_BY]->(x:Resolution)
        OPTIONAL MATCH (f)-[:VALID_IN]->(vi:PolicyVersion)
        RETURN f.finding_id AS finding_id, k.reason_code AS code, k.source AS source, f.statement AS statement,
               f.status AS status, f.confidence AS confidence, f.support AS support,
               f.req_emergency AS req_emergency, f.req_in_network AS req_in_network,
               fl.clause_id AS learned_on, fl.section AS learned_section, gov.clause_id AS governing,
               collect(DISTINCT x.resolution_id) AS contradicted_by, collect(DISTINCT vi.label) AS valid_in
        ORDER BY finding_id""", {"cid": cid})
    for v in verdicts:
        v["valid_in"] = sorted(v["valid_in"])
    from claimbridge.tools.evidence import evidence_gap
    gap = [{"code": r["evidence"], "name": r["name"], "satisfied": r["satisfied"], "sources": r["sources"]}
           for r in evidence_gap(gr, cid)]
    timeline = []
    for e in coord.timeline(gr, cid):
        timeline.append({"seq": e["seq"], "type": e["type"], "agent": e["agent"], "step": e["step"],
                         "ts": e["ts"], "payload": _payload(e)})
    tr = truth().get(cid, {})
    return {
        "claim": c, "tenant": _tenants().get(c.get("tenant_id")), "service": head["service"],
        "notice": head["notice"], "notice_date": head["notice_date"],
        "version": head["version"], "clause": head["clause"],
        "reason": head["reason"], "reason_name": head["reason_name"],
        "evidence": evidence, "evidence_withdrawn": withdrawn, "requirements": gap, "verdicts": verdicts,
        "human_review": human_review, "corrections": corrections,
        "recommendation": report.actual(gr, cid)["recommendation"],
        "timeline": timeline, "trap": tr.get("trap"), "note": tr.get("note"),
    }


@app.get("/api/claims/{cid}/packet")
def review_packet(cid: str):
    """Portable, tenant-scoped review record. It is never an insurer submission."""
    d = claim(cid)
    rec = d["recommendation"]
    if not rec:
        raise HTTPException(409, "The recommendation is not ready for review.")
    lines = [f"# ClaimBridge review packet: {cid}", "",
             "Synthetic demonstration. Human review required. This packet has not been submitted to an insurer.", "",
             f"Status: {d['claim']['status']}", f"Service: {d['service']}",
             f"Governing version: {(d['version'] or {}).get('version_id', 'unknown')}",
             f"Disposition: {rec['disposition']}", f"Support score: {support_text(rec, d['verdicts'])}",
             "(A smoothed count of recorded outcomes, not an approval probability.)", "", rec["summary"], "", "## Cited plan", ""]
    for item in rec["items"]:
        lines += [f"- {item['text']} [Sources: {', '.join(item['cites'])}]"]
    lines += ["", "## Evidence checklist", ""]
    if d["requirements"]:
        for r in d["requirements"]:
            origin = evidence_origin(r["sources"])
            basis = {"policy": "required by the governing clause",
                     "learned": "suggested by a learned precedent (an observed association, not a policy requirement)",
                     "both": "required by the governing clause and also suggested by a learned precedent"}[origin]
            lines.append(f"- {r['name']}: {'on file' if r['satisfied'] else 'missing'}; {basis} [Sources: {', '.join(r['sources'])}]")
    else:
        lines.append("- No evidence requirements were determined.")
    lines += ["", "## Documents on file (declared documents are not verified)", ""]
    for e in d["evidence"]:
        who = f"declared on file by {e['declared_by']}; not verified" if e.get("declared_by") else "submitted with the claim"
        lines.append(f"- {e['name']}: {who}" + (f" ({e['reference']})" if e.get("reference") else ""))
    lines += [f"- {w['name']}: withdrawn by {w['by']} (kept for the record; not counted)" for w in d["evidence_withdrawn"]]
    if not d["evidence"] and not d["evidence_withdrawn"]:
        lines.append("- None.")
    if d["corrections"]:
        lines += ["", "## Human corrections (the original notice is unchanged)", ""]
        lines += [f"- {c['reviewer']} classified the notice as {c['reason']} (was {c['previous_reason'] or 'unclassified'}): {c['note']}"
                  for c in d["corrections"]]
    lines += ["", "## Governing clause", "", (d["clause"] or {}).get("text", "Unavailable"),
              "", "## Precedent decisions", ""]
    lines += [f"- {v['finding_id']}: {v['code']} (learned on {v['learned_on']}; governing {v['governing']})"
              for v in d["verdicts"] if v["code"] != "REASON_MISMATCH"]
    lines += ["", "## Uncertainty", "", *[f"- {u}" for u in rec.get("uncertainty", [])],
              "", "## Audit events", ""]
    lines += [f"- {e['seq']}: {e['type']} / {e['agent']} / timestamp {e['ts']}" for e in d["timeline"]]
    filename = "claimbridge-" + "".join(ch for ch in cid if ch.isalnum() or ch == "-") + ".md"
    return Response("\n".join(lines) + "\n", media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/claims/{cid}/graph")
def claim_graph(cid: str):
    """The evidence subgraph behind a claim's recommendation (Q10), as nodes and edges."""
    d = claim(cid)
    nodes, edges = {}, []

    def node(i, kind, label, **kw):
        nodes.setdefault(i, {"id": i, "kind": kind, "label": label, **kw})

    c = d["claim"]
    node(cid, "claim", cid, sub=d["service"])
    if d["version"]:
        node(d["version"]["version_id"], "version", f"Policy {d['version']['label']}")
        edges.append({"from": cid, "to": d["version"]["version_id"], "label": "governed by"})
    if d["clause"]:
        cl = d["clause"]
        node(cl["clause_id"], "clause", f"§{cl['section']} {cl['title']}", sub=cl["clause_id"])
        edges.append({"from": cid, "to": cl["clause_id"], "label": "denial cites"})
        if d["version"]:
            edges.append({"from": d["version"]["version_id"], "to": cl["clause_id"], "label": "contains"})
    for r in d["requirements"]:
        node(r["code"], "evidence", r["name"], satisfied=r["satisfied"], origin=evidence_origin(r["sources"]))
        for source in r["sources"]:
            edges.append({"from": source, "to": r["code"],
                          "label": "on file" if r["satisfied"] else "missing", "state": "ok" if r["satisfied"] else "missing",
                          "origin": "learned" if source.startswith("F-") else "policy"})
    for v in d["verdicts"]:
        if v["code"] == "REASON_MISMATCH":
            continue
        code = v["code"] or "CANDIDATE"          # retrieved but not yet judged by the Verifier (a claim mid-pipeline)
        node(v["finding_id"], "finding", v["finding_id"], code=code, status=v["status"])
        edges.append({"from": cid, "to": v["finding_id"], "label": code.replace("_", " ").lower(), "code": code})
        if v["learned_on"]:
            node(v["learned_on"], "clause", v["learned_on"], sub="learned on")
            edges.append({"from": v["finding_id"], "to": v["learned_on"], "label": "learned on"})
        if v["code"] == "VERSION_DRIFT" and v["governing"] and v["governing"] != v["learned_on"]:
            node(v["governing"], "clause", v["governing"], sub="supersedes")
            edges.append({"from": v["governing"], "to": v["learned_on"], "label": "supersedes", "code": "VERSION_DRIFT"})
        for x in v["contradicted_by"]:
            node(x, "resolution", x, sub="upheld")
            edges.append({"from": v["finding_id"], "to": x, "label": "contradicted by", "code": "CONTRADICTED"})
    return {"nodes": list(nodes.values()), "edges": edges}


class ReviewBody(BaseModel):
    reviewer: str = "caseworker"


class OutcomeBody(BaseModel):
    outcome: str
    reviewer: str = "caseworker"
    confirmed_evidence: list[str] | None = None


@app.post("/api/claims/{cid}/approve")
def approve_claim(cid: str, body: ReviewBody):
    _claim_access(cid)
    if not approve(g(), cid, auth.reviewer(body.reviewer)):
        raise HTTPException(409, "This claim is not awaiting review.")
    return {"ok": True}


class CorrectBody(BaseModel):
    denial_reason: str
    note: str = Field(min_length=1, max_length=500)
    reviewer: str = "caseworker"


class EvidenceBody(BaseModel):
    type: str
    reference: str | None = Field(default=None, max_length=200)
    reviewer: str = "caseworker"


def _human_gate(fn, *args):
    """One mapping from the supervisor's human-gate errors to HTTP."""
    try:
        return fn(*args)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except PermissionError as e:
        raise HTTPException(409, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@app.post("/api/claims/{cid}/correct")
def correct_claim(cid: str, body: CorrectBody):
    """An operator classifies a notice the agents escalated, and resumes the claim at Retrieval."""
    _claim_access(cid)
    auth.require_admin()
    return _human_gate(correct_classification, g(), cid, body.denial_reason, body.note, auth.reviewer(body.reviewer))


@app.post("/api/claims/{cid}/evidence")
def declare_claim_evidence(cid: str, body: EvidenceBody):
    """Declare that a document is on file (the owning policyholder or an operator). It is not verified."""
    _claim_access(cid)
    return _human_gate(declare_evidence, g(), cid, body.type, body.reference, auth.reviewer(body.reviewer))


@app.delete("/api/claims/{cid}/evidence/{doc_id}")
def withdraw_claim_evidence(cid: str, doc_id: str):
    _claim_access(cid)
    auth.require_admin()
    return _human_gate(withdraw_evidence, g(), cid, doc_id, auth.reviewer("caseworker"))


@app.post("/api/claims/{cid}/outcome")
def outcome_claim(cid: str, body: OutcomeBody):
    _claim_access(cid)
    auth.require_admin()
    if body.outcome not in ("OVERTURNED", "UPHELD", "PARTIAL"):
        raise HTTPException(422, "Outcome must be OVERTURNED, UPHELD or PARTIAL.")
    if body.confirmed_evidence is not None:
        available = {e["code"] for e in claim(cid)["evidence"]}
        if not set(body.confirmed_evidence) <= available:
            raise HTTPException(422, "Only evidence on file can be confirmed as supporting the outcome.")
    if not record_outcome(g(), cid, body.outcome, auth.reviewer(body.reviewer), body.confirmed_evidence):
        raise HTTPException(409, "Approve the recommendation before recording an outcome.")
    return {"ok": True}


# ------------------------------------------------------------------ memory

@app.get("/api/memory")
def memory():
    gr = g()
    reasons = _names("denial_reasons")
    findings = db.run(gr, """
        MATCH (f:Finding)-[:FOR_REASON]->(r:DenialReason)
        MATCH (f)-[:ON_LINEAGE]->(cl:Clause)
        OPTIONAL MATCH (f)-[:VALID_IN]->(v:PolicyVersion)
        WITH f, r, cl, collect(DISTINCT v.label) AS valid
        OPTIONAL MATCH (f)-[:NEEDS_EVIDENCE]->(e:EvidenceType)
        WITH f, r, cl, valid, collect(DISTINCT e.name) AS needs
        OPTIONAL MATCH (f)-[:CONTRADICTED_BY]->(x:Resolution)
        WITH f, r, cl, valid, needs, count(DISTINCT x) AS contradictions
        OPTIONAL MATCH (f)-[:STALE_BECAUSE]->(sc:Clause)
        OPTIONAL MATCH (f)-[:RECOMMENDS]->(pb:Playbook)
        RETURN f.finding_id AS finding_id, f.statement AS statement, f.status AS status, f.support AS support,
               f.wins AS wins, f.confidence AS confidence, f.origin AS origin, f.updated_at AS updated_at,
               r.code AS reason, cl.lineage_id AS lineage, cl.clause_id AS learned_on, cl.section AS section,
               cl.title AS clause_title, valid, needs, contradictions,
               collect(DISTINCT sc.clause_id) AS stale_because, pb.name AS playbook
        ORDER BY finding_id""")
    for f in findings:
        f["valid_in"] = sorted(f.pop("valid"))
        f["reason_name"] = reasons.get(f["reason"])
    playbooks = db.run(gr, """
        MATCH (p:Playbook)-[:FOR_REASON]->(r:DenialReason)
        OPTIONAL MATCH (p)-[:HAS_STEP]->(s:PlaybookStep)
        WITH p, r, s ORDER BY s.order
        RETURN p.playbook_id AS playbook_id, p.name AS name, p.uses AS uses, p.wins AS wins, r.code AS reason,
               collect(s.action) AS steps ORDER BY name""")
    versions = db.run(gr, """MATCH (v:PolicyVersion) RETURN v.version_id AS id, v.label AS label,
                             v.effective_from AS effective_from ORDER BY effective_from""")
    return {"findings": findings, "playbooks": playbooks, "versions": versions,
            "next_version": next((x["version_id"] for x in load().versions
                                  if x["version_id"] not in {v["id"] for v in versions}), None)}


@app.get("/api/memory/findings/{fid}/precedents")
def precedents(fid: str, x_tenant_id: str = Header(default="TEN-01")):
    x_tenant_id = auth.tenant() or x_tenant_id
    rows = tenancy.precedent_detail(g(), fid, x_tenant_id)
    return {"tenant": x_tenant_id, "rows": rows, "redacted": sum(1 for r in rows if not r["own"])}


@app.get("/api/claims/{cid}/trace/{fid}")
def precedent_trace(cid: str, fid: str):
    """The edges between a claim and one precedent, with the first hop that does not hold marked."""
    _claim_access(cid)
    t = trace.precedent_trace(g(), cid, fid)
    if not t:
        raise HTTPException(404, "That claim did not consider that precedent.")
    return t


@app.get("/api/impact/clauses")
def impact_clauses():
    return {"clauses": trace.clauses_with_dependents(g())}


@app.get("/api/impact/clause/{clause_id}")
def clause_impact(clause_id: str):
    """What rests on a clause: its lineage, the memory learned on it, the evidence that memory asks for and the claims
    that weighed it. Other policyholders' claims are counted, not named."""
    out = trace.clause_impact(g(), clause_id, auth.tenant())
    if not out:
        raise HTTPException(404, "No such clause.")
    return out


# ------------------------------------------------- investigator and graph algorithms

_INVESTIGATE_PER_MINUTE = 6
_investigate_log: dict[str, list[float]] = {}
_investigate_lock = threading.Lock()


def _scope() -> catalogue.Scope:
    return catalogue.Scope(auth.tenant())


def _llm_allowed() -> bool:
    """Rate limit for runs that may call the model: _INVESTIGATE_PER_MINUTE per identity. Graph-only runs are never limited."""
    p = auth.current.get()
    who = p.subject if p else "anonymous"
    now = time.time()
    with _investigate_lock:
        recent = [t for t in _investigate_log.get(who, []) if now - t < 60]
        ok = len(recent) < _INVESTIGATE_PER_MINUTE
        if ok:
            recent.append(now)
        _investigate_log[who] = recent
    return ok


@app.get("/api/tools")
def tool_catalogue():
    """The read-only tools the investigator and the MCP server share."""
    return {"tools": catalogue.specs()}


@app.post("/api/claims/{cid}/investigate")
async def investigate_claim(cid: str, request: Request):
    """Run the investigator on a claim and store the trace. Body (optional): {"mode": "auto" | "graph_only"}."""
    raw = await request.body()
    if len(raw) > 1024:
        raise HTTPException(400, "That request is too large.")
    try:
        body = json.loads(raw) if raw.strip() else {}
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "The request body is not valid JSON.") from None
    if not isinstance(body, dict) or set(body) - {"mode"} or body.get("mode", "auto") not in ("auto", "graph_only"):
        raise HTTPException(400, 'Send {} or {"mode": "auto" | "graph_only"}.')
    if not re.fullmatch(r"[A-Za-z0-9_.:\-]{1,80}", cid):
        raise HTTPException(400, "That is not a claim id.")
    row = db.one(g(), "MATCH (c:Claim {claim_id: $cid}) RETURN c.tenant_id AS tenant", {"cid": cid})
    if not row:
        raise HTTPException(404, "We could not find that claim.")
    auth.require_tenant(row["tenant"])
    use_llm = body.get("mode", "auto") == "auto"
    if use_llm and config.LLM_PLATFORM != "fake" and not _llm_allowed():
        raise HTTPException(429, f"Investigations that use the language model are limited to {_INVESTIGATE_PER_MINUTE} a minute. "
                                 "Wait a moment, or run the graph-only investigation.")
    from starlette.concurrency import run_in_threadpool
    run = await run_in_threadpool(investigator.investigate, db.connect(), _scope(), cid, use_llm=use_llm)
    return investigator.as_json(run)


@app.get("/api/claims/{cid}/investigations")
def claim_investigations(cid: str):
    """Stored investigation traces for a claim, newest first (the graph remembers them)."""
    _claim_access(cid)
    return {"investigations": investigator.history(g(), cid)}


@app.get("/api/blast/lineages")
def blast_lineages():
    """Clause lineages ranked by how much memory depends on them (PageRank over the dependency edges)."""
    return {"lineages": blast.rank_lineages(g(), auth.tenant()), "algorithm": "algo.pageRank"}


@app.get("/api/blast/clause/{clause_id}")
def blast_clause(clause_id: str):
    """What is affected if a clause changes, with hop distances (algo.BFS)."""
    out = catalogue.call(g(), _scope(), "policy_blast_radius", {"clause_id": clause_id})
    if not out["ok"]:
        raise HTTPException(404 if out["error"]["code"] == "NOT_FOUND" else 400, out["error"]["message"])
    return out["data"]


# ------------------------------------------------------------------- world

class WorldBody(BaseModel):
    action: str                 # "reset" | "reset_2025" | "publish"
    version: str | None = None


def _run_world(action: str, version: str | None):
    try:
        if action == "publish":
            from claimbridge.agents.curator import publish_version
            _world_job["result"] = publish_version(db.connect(), version or "V2026")
        else:
            from claimbridge.seed.load import reset
            reset(upto="V2025" if action == "reset_2025" else None)
            _world_job["result"] = {"reset": action}
    except Exception as e:  # surfaced to the UI
        _world_job["error"] = str(e)
    finally:
        _world_job["running"] = False


@app.post("/api/world")
def world(body: WorldBody):
    auth.require_admin()
    if body.action not in ("reset", "reset_2025", "publish"):
        raise HTTPException(422, "Unknown action.")
    with _world_lock:
        if _world_job["running"]:
            raise HTTPException(409, f"Already running: {_world_job['action']}.")
        _world_job.update(running=True, action=body.action, error=None, result=None)
    if body.action == "publish":
        _run_world(body.action, body.version)   # fast: a few queries
        if _world_job["error"]:
            raise HTTPException(409, _world_job["error"])
        return _world_job
    threading.Thread(target=_run_world, args=(body.action, body.version), daemon=True).start()
    return _world_job


# ------------------------------------------------------------------ agents

@app.get("/api/agents")
def agents():
    auth.require_admin()
    gr = g()
    now = db.now_ms()
    workers = db.run(gr, """MATCH (h:WorkerHeartbeat) RETURN h.agent_id AS agent_id, h.role AS role,
                            h.state AS state, h.current_claim AS current_claim, h.last_seen AS last_seen
                            ORDER BY role, agent_id""")
    for w in workers:
        stale = not w["last_seen"] or now - w["last_seen"] > 15000
        w["alive"] = not stale and w["state"] not in ("stopped", "killed", "dead")
    leases = db.run(gr, """MATCH (c:Claim) WHERE c.lease_owner IS NOT NULL
                           RETURN c.claim_id AS claim_id, c.status AS status, c.lease_owner AS owner,
                                  c.lease_until - timestamp() AS expires_in_ms, c.attempt AS attempt
                           ORDER BY claim_id""")
    events = db.run(gr, """
        MATCH (c:Claim)-[:HAS_EVENT]->(e:CaseEvent)
        WHERE e.type IN ['CLAIMED', 'RESUMED', 'LEASE_EXPIRED', 'FENCED_WRITE_REJECTED', 'NEEDS_HUMAN', 'GAVE_UP']
           OR e.type ENDS WITH '_DONE'
        RETURN c.claim_id AS claim_id, e.type AS type, e.agent_id AS agent, e.ts AS ts, e.payload AS payload
        ORDER BY ts DESC LIMIT 40""")
    for e in events:
        e["payload"] = _payload(e)
    commands = db.run(gr, """MATCH (c:Command) RETURN c.cmd_id AS id, c.type AS type, c.target AS target,
                             c.status AS status, c.note AS note, c.created_at AS created_at
                             ORDER BY created_at DESC LIMIT 10""")
    return {"workers": workers, "leases": leases, "events": events, "commands": commands, "now": now}


class StartBody(BaseModel):
    role: str


@app.post("/api/agents/{agent_id}/kill")
def kill(agent_id: str):
    auth.require_admin()
    return {"command": command(g(), "KILL", agent_id)}


@app.post("/api/agents/start")
def start(body: StartBody):
    auth.require_admin()
    if body.role not in ("intake", "retrieval", "verifier", "planner", "curator"):
        raise HTTPException(422, "Unknown role.")
    return {"command": command(g(), "START", body.role)}


# -------------------------------------------------------------- evaluation

@app.get("/api/eval")
def evaluation():
    p = config.RESULTS_DIR / "latest.json"
    if not p.exists():
        raise HTTPException(404, "No evaluation results yet. Run `cli eval all`, review the report, then `cli eval promote`.")
    return json.loads(p.read_text(encoding="utf-8"))


_SYSTEM_ID = re.compile(r"^[a-z_]+$")


@app.get("/api/eval/raw/{system}/{claim}")
def evaluation_raw(system: str, claim: str):
    """From a number to its evidence: one claim's raw prediction, the expected answer and, for the RAG
    baselines, the model's own answer. Operators only: these are per-claim records of every tenant's fixtures."""
    auth.require_admin()
    p = config.RESULTS_DIR / "raw" / f"{system}.json"
    if not _SYSTEM_ID.match(system) or not p.exists():
        raise HTTPException(404, "No such evaluated system.")
    raw = json.loads(p.read_text(encoding="utf-8"))
    expected = truth().get(claim)
    if expected is None or claim not in raw.get("predictions", {}) and claim not in raw.get("not_run", []):
        raise HTTPException(404, "No such evaluated claim.")
    return {"system": system, "claim": claim, "run_id": (raw.get("provenance") or {}).get("run_id"),
            "prediction": raw.get("predictions", {}).get(claim), "no_output": claim in raw.get("not_run", []),
            "error": (raw.get("errors") or {}).get(claim), "model_answer": (raw.get("answers") or {}).get(claim),
            "expected": {k: v for k, v in expected.items() if k != "tenant_probe"}}


# ------------------------------------------------------------------ stream

@app.get("/api/stream")
async def stream(request: Request):
    """Server-sent events: one 'tick' whenever the graph's activity changes.

    Lifetime: the stream re-checks the caller's credential on every poll and ends with an
    `auth` event when it is revoked, removed, misconfigured or older than SESSION_SECONDS.
    Signing out in the browser clears the cookie and the page closes its stream; the server
    cannot see a cookie being cleared, so revocation is what ends a stream it still holds."""
    started = time.monotonic()

    async def gen():
        last = None
        while True:
            try:
                principal = auth.from_request(request)
                if auth.mode() == "protected" and time.monotonic() - started > auth.SESSION_SECONDS:
                    raise HTTPException(401, "Session expired.")
            except HTTPException as e:
                yield f'event: auth\ndata: {json.dumps({"error": "session ended", "status": e.status_code})}\n\n'
                return
            tenant = principal.tenant_id if principal.role == "tenant" else None
            try:
                if tenant:
                    r = db.one(g(), """MATCH (c:Claim {tenant_id: $tenant})
                        OPTIONAL MATCH (c)-[:HAS_EVENT]->(e:CaseEvent)
                        RETURN max(e.ts) AS ev""", {"tenant": tenant}) or {}
                else:
                    r = db.one(g(), """
                    OPTIONAL MATCH (e:CaseEvent) WITH max(e.ts) AS ev
                    OPTIONAL MATCH (h:WorkerHeartbeat) WITH ev, collect(h.state + ':' + coalesce(h.current_claim, '')) AS hs
                    OPTIONAL MATCH (f:Finding) WITH ev, hs, count(f) AS nf, max(f.updated_at) AS fu
                    OPTIONAL MATCH (c:Claim) WHERE c.lease_owner IS NOT NULL
                    RETURN ev, hs, nf, fu, collect(c.claim_id + c.lease_owner) AS ls""")
                stamp = json.dumps(r, sort_keys=True, default=str)
                if stamp != last:
                    last = stamp
                    yield f"event: tick\ndata: {json.dumps({'ev': r.get('ev')})}\n\n"
                else:
                    yield ": keepalive\n\n"
            except Exception as e:  # graph being reset
                yield 'event: error\ndata: {"error":"Graph temporarily unavailable"}\n\n'
            await asyncio.sleep(0.8)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
