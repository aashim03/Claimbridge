"""One catalogue of read-only graph tools, shared by the MCP server and the investigator agent.

What an MCP client can do and what the investigator can do are the same list, because both call
`call()` here. Rules every tool follows:

* read-only: no tool writes to the graph;
* the tenant comes from the caller's `Scope` (MCP server start-up config, or the API identity),
  never from a tool argument; a claim that belongs to another tenant looks exactly like a claim that
  does not exist;
* a failure is an error object (`{"ok": False, "error": {...}}`), never an exception or a stack trace;
* every result carries `ids`, the identifiers it mentions, so a guard can check that a sentence
  quoting an identifier is backed by something a tool actually returned.

Most tools reuse an existing query (tools/trace.py, tools/retrieval.py, tools/evidence.py). Where the
existing query also writes (`select_version` pins the claim, `check_applicability` stores the verdict),
the catalogue reads the same facts without the write.
"""
import logging
import re
from dataclasses import dataclass
from typing import Callable

from claimbridge import db
from claimbridge.tools import evidence, retrieval, trace

log = logging.getLogger("claimbridge.catalogue")

# An identifier: CLAIM-STYLE-IDS (EV-T1-01, F-MRI-REFERRAL, C-2026-MRI-PREAUTH, ITEMIZED_BILL) or a version (V2026).
ID_TOKEN = re.compile(r"\b(?:[A-Z][A-Z0-9]*(?:[-_][A-Za-z0-9]+)+|V\d{4})\b")
_ARG_OK = re.compile(r"^[A-Za-z0-9_.:\-]{1,80}$")


@dataclass(frozen=True)
class Scope:
    """Who is asking. `tenant=None` means an operator or the public demo: every claim is visible."""
    tenant: str | None = None


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    properties: dict
    fn: Callable

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": self.properties, "required": list(self.properties),
                "additionalProperties": False}


def ids_in(obj) -> list[str]:
    """Every identifier mentioned anywhere in a JSON-like value."""
    found: set[str] = set()

    def walk(x):
        if isinstance(x, str):
            found.update(ID_TOKEN.findall(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    walk(obj)
    return sorted(found)


# ---------------------------------------------------------------------------- helpers

def _claim_row(g, scope: Scope, cid: str) -> dict:
    row = db.one(g, "MATCH (c:Claim {claim_id: $cid}) RETURN c.tenant_id AS tenant", {"cid": cid})
    if not row or (scope.tenant is not None and row["tenant"] != scope.tenant):
        raise ToolError("NOT_FOUND", f"No claim {cid} is visible to this caller.")
    return row


def _statement(g, fid: str) -> str | None:
    r = db.one(g, "MATCH (f:Finding {finding_id: $fid}) RETURN f.statement AS s", {"fid": fid})
    return r["s"] if r else None


# ---------------------------------------------------------------------------- tools

def get_claim(g, scope: Scope, claim_id: str) -> dict:
    _claim_row(g, scope, claim_id)
    r = db.one(g, """
        MATCH (c:Claim {claim_id: $cid})-[:FOR_SERVICE]->(s:ServiceCategory)
        OPTIONAL MATCH (c)-[:GOVERNED_BY]->(v:PolicyVersion)
        OPTIONAL MATCH (c)-[:DENIED_FOR]->(r:DenialReason)
        OPTIONAL MATCH (c)-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(cl:Clause)
        RETURN c.claim_id AS claim_id, c.status AS status, c.service_date AS service_date, s.name AS service,
               c.is_emergency AS is_emergency, c.in_network AS in_network, c.disposition AS disposition,
               v.version_id AS policy_version, v.label AS policy_label,
               r.code AS denial_reason, r.name AS denial_reason_name,
               cl.clause_id AS cited_clause, cl.section AS cited_section, cl.title AS cited_title
    """, {"cid": claim_id})
    return {k: v for k, v in r.items()}


def select_version(g, scope: Scope, claim_id: str) -> dict:
    _claim_row(g, scope, claim_id)
    r = db.one(g, """
        MATCH (c:Claim {claim_id: $cid})
        MATCH (v:PolicyVersion)
        WHERE v.effective_from <= c.service_date AND c.service_date < v.effective_to
        OPTIONAL MATCH (c)-[:GOVERNED_BY]->(pinned:PolicyVersion)
        RETURN c.service_date AS service_date, v.version_id AS version_in_force, v.label AS label,
               v.effective_from AS effective_from, v.effective_to AS effective_to,
               pinned.version_id AS pinned_version
    """, {"cid": claim_id})
    if not r:
        raise ToolError("NO_VERSION", f"No policy version covers the service date of {claim_id}.")
    return {**r, "pinned_matches": r["pinned_version"] in (None, r["version_in_force"])}


def find_candidates(g, scope: Scope, claim_id: str) -> dict:
    _claim_row(g, scope, claim_id)
    rows = retrieval.graph_candidates(g, claim_id)
    cands = [{**r, "statement": _statement(g, r["finding_id"])} for r in rows]
    out = {"claim_id": claim_id, "count": len(cands), "candidates": cands}
    if not cands:
        out["note"] = "No candidate precedents: the claim has no classified denial reason yet, or memory holds none for it."
    return out


def _trace(g, scope: Scope, claim_id: str, finding_id: str) -> dict:
    _claim_row(g, scope, claim_id)
    t = trace.precedent_trace(g, claim_id, finding_id)
    if not t:
        raise ToolError("NOT_FOUND", f"Claim {claim_id} did not consider precedent {finding_id}.")
    return t


def check_applicability(g, scope: Scope, claim_id: str, finding_id: str) -> dict:
    t = _trace(g, scope, claim_id, finding_id)
    broken = next((h for h in t["hops"] if h["break"]), None)
    hop = {h["key"]: h["to"] for h in t["hops"]}
    return {"claim_id": claim_id, "finding_id": finding_id, "verdict": t["derived_code"],
            "stored_verdict": t["code"], "agrees_with_verifier": t["code"] in (None, t["derived_code"]),
            "learned_on_clause": hop.get("lineage"), "governing_clause": hop.get("contains"),
            "reason": broken["note"] if broken else "Every check holds: reason, lineage, version, contradiction, conditions.",
            "broken_hop": broken["key"] if broken else None}


def evidence_gap(g, scope: Scope, claim_id: str) -> dict:
    _claim_row(g, scope, claim_id)
    rows = evidence.evidence_gap(g, claim_id)
    items = [{"evidence_code": r["evidence"], "name": r["name"], "on_file": r["satisfied"], "required_by": r["sources"]}
             for r in rows]
    return {"claim_id": claim_id, "count": len(items), "missing_count": sum(1 for i in items if not i["on_file"]),
            "evidence": items}


def explain_path(g, scope: Scope, claim_id: str, finding_id: str) -> dict:
    t = _trace(g, scope, claim_id, finding_id)
    hops = [{"step": n + 1, "check": h["key"], "from": h["from"], "relationship": h["rel"], "to": h["to"],
             "holds": h["ok"], "first_broken": h["break"], "note": h["note"]} for n, h in enumerate(t["hops"])]
    return {"claim_id": claim_id, "finding_id": finding_id, "verdict": t["derived_code"],
            "first_broken_check": t["broken"], "count": len(hops), "hops": hops}


def what_rests_on_clause(g, scope: Scope, clause_id: str) -> dict:
    out = trace.clause_impact(g, clause_id, scope.tenant)
    if not out:
        raise ToolError("NOT_FOUND", f"No clause {clause_id}.")
    return {
        "clause_id": clause_id, "lineage_id": out["lineage_id"], "counts": out["counts"],
        "clauses": [{"clause_id": c["clause_id"], "version_id": c["version_id"], "section": c["section"],
                     "title": c["title"], "changed_from_previous": c["changed"]} for c in out["clauses"]],
        "findings": [{"finding_id": f["finding_id"], "status": f["status"], "learned_on": f["learned_on"],
                      "evidence": f["evidence_codes"], "stale_because": f["stale_because"]} for f in out["findings"]],
        "claims_you_can_see": out["claims"],
    }


# ---------------------------------------------------------------------------- registry

_CLAIM = {"claim_id": {"type": "string", "description": "A claim id, for example EV-T1-01."}}
_FINDING = {"finding_id": {"type": "string", "description": "A precedent (Finding) id, for example F-MRI-REFERRAL."}}
_CLAUSE = {"clause_id": {"type": "string", "description": "A policy clause id, for example C-2026-MRI-PREAUTH."}}

_TOOLS: list[Tool] = [
    Tool("get_claim", "The claim: status, service, denial reason, cited clause and governing policy version.", _CLAIM, get_claim),
    Tool("select_version", "Which policy version was in force on the claim's service date.", _CLAIM, select_version),
    Tool("find_candidates", "Candidate precedents (Findings) memory proposes for the claim's denial reason.", _CLAIM, find_candidates),
    Tool("check_applicability", "Whether one precedent applies to the claim: a verdict code (ACCEPTED, VERSION_DRIFT, "
         "LINEAGE_MISMATCH, REASON_MISMATCH, CONTRADICTED, CONDITION_UNMET) and the reason.", {**_CLAIM, **_FINDING}, check_applicability),
    Tool("evidence_gap", "The evidence the cited clause and accepted precedents require, and which is still missing.", _CLAIM, evidence_gap),
    Tool("explain_path", "The edge-by-edge path in the graph between a claim and one precedent, with the first broken edge marked.",
         {**_CLAIM, **_FINDING}, explain_path),
    Tool("what_rests_on_clause", "What depends on a policy clause: its versions, the precedents learned on it, the evidence they "
         "ask for and the claims that weighed them.", _CLAUSE, what_rests_on_clause),
]


def _algorithm_tools() -> list[Tool]:
    """policy_blast_radius runs FalkorDB graph algorithms; it lives in tools/blast.py (imported here to avoid a cycle)."""
    from claimbridge.tools import blast
    return [Tool("policy_blast_radius", blast.DESCRIPTION, _CLAUSE, blast.policy_blast_radius)]


_TOOLS += _algorithm_tools()

TOOLS: dict[str, Tool] = {t.name: t for t in _TOOLS}


def specs() -> list[dict]:
    """The catalogue as the tool list an LLM or an MCP client is shown."""
    return [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in TOOLS.values()]


def call(g, scope: Scope, name: str, args: dict | None) -> dict:
    """Run one tool. Always returns an object; never raises."""
    tool = TOOLS.get(name)
    if tool is None:
        return error_result(name, "UNKNOWN_TOOL", f"There is no tool named {str(name)[:60]!r}. Available: {', '.join(TOOLS)}.")
    args = args if isinstance(args, dict) else {}
    extra = set(args) - set(tool.properties)
    missing = set(tool.properties) - set(args)
    if extra or missing:
        return error_result(name, "BAD_ARGUMENTS", f"{name} takes exactly: {', '.join(tool.properties)}.")
    for k, v in args.items():
        if not isinstance(v, str) or not _ARG_OK.match(v):
            return error_result(name, "BAD_ARGUMENTS", f"{k} must be an id of 1 to 80 letters, digits, - _ . :")
    try:
        data = tool.fn(g, scope, **args)
    except ToolError as e:
        return error_result(name, e.code, e.message)
    except Exception:       # a database or code fault must not leak a stack trace to a client or an LLM
        log.exception("tool %s failed", name)
        return error_result(name, "INTERNAL", "The graph could not answer that right now.")
    return {"ok": True, "tool": name, "args": args, "data": data, "ids": ids_in([args, data])}


def error_result(name: str, code: str, message: str) -> dict:
    return {"ok": False, "tool": name, "error": {"code": code, "message": message}, "ids": []}
