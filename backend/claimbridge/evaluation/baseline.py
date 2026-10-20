"""Plain vector-RAG baseline.

Same LLM and the same documents as ClaimBridge, but no graph reasoning:
  - corpus: the text of every clause of every policy version, and a record of every
    historical case (facts, evidence, verified outcome), one passage each;
  - index: a FalkorDB vector index in its own graph, with no relationships at all;
  - answer: top-k passages + the claim facts go to the LLM, which must make the same
    decisions ClaimBridge makes (reason, version, evidence, precedents, disposition).

It is told to use the policy version in force on the service date and to cite the
passages it relies on, so it is a fair effort rather than a straw man.
"""
import logging
import os
from datetime import date
from functools import lru_cache

from claimbridge import config, db, llm
from claimbridge.knowledge import load
from claimbridge.llm.schemas import BaselineAnswer, BaselineFindingsAnswer
from claimbridge.seed.generate import load_cases
from claimbridge.seed.notices import notice_core

log = logging.getLogger("claimbridge.baseline")

SYSTEM = """You help a caseworker respond to a denied health-insurance claim.
You get the claim and the passages retrieved from the policy documents (all policy versions) and from
past case records. Decide:
- the insurer's denial reason (one code);
- the policy version in force on the service date (versions run from their effective date until the next one);
- the evidence an appeal needs under the governing terms, and which of it the claim is missing;
- which past cases (HC-...) are valid precedents for this claim (empty if none truly apply);
- the disposition: APPEAL_VIABLE (all required evidence on file), APPEAL_NEEDS_EVIDENCE (an appeal is possible
  once evidence is added) or NO_BASIS_ESCALATE (the governing terms leave no basis for appeal);
- a short plan whose items cite the passage IDs they rely on.
Use only the passages and claim facts. Never promise approval."""


SYSTEM_FINDINGS = """You help a caseworker respond to a denied health-insurance claim.
You get the claim and the passages retrieved from the policy documents (all policy versions) and from
the shared memory of abstract findings (precedents distilled from verified past outcomes; each says which
policy versions it remains valid in, what evidence the winning appeals included, and any conditions).
Decide:
- the insurer's denial reason (one code);
- the policy version in force on the service date (versions run from their effective date until the next one);
- the evidence an appeal needs under the governing terms, and which of it the claim is missing;
- which findings (F-...) are valid precedents for this claim (empty if none truly apply). A finding applies only
  if it is for this denial reason, concerns the clause this denial rests on, is valid in the policy version in
  force, is not contradicted, and this claim meets its conditions;
- the disposition: APPEAL_VIABLE (all required evidence on file), APPEAL_NEEDS_EVIDENCE (an appeal is possible
  once evidence is added) or NO_BASIS_ESCALATE (the governing terms leave no basis for appeal);
- a short plan whose items cite the passage IDs they rely on.
Use only the passages and claim facts. Never promise approval."""

# Variants: "cases" = clauses + own-tenant case records (plain RAG); "findings" = the same plus the abstract
# finding facts ClaimBridge stores (information parity: what differs is then rules and graph queries, not access).
VARIANTS = ("cases", "findings")
FINDINGS_TOP_K = int(os.getenv("BASELINE_FINDINGS_TOP_K", "10"))


def short(model: str) -> str:
    return model.split("/")[-1].replace(".", "").replace("-en-v15", "").replace("-embed", "")


def graph_name(model: str, variant: str = "cases") -> str:
    return f"{config.GRAPH}_baseline_{short(model)}" + ("" if variant == "cases" else f"_{variant}")


@lru_cache(maxsize=4)
def _embedder(model: str):
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=model, cache_dir=config.EMBED_CACHE)


def embed_passages(model: str, texts: list[str]) -> list[list[float]]:
    return [[float(x) for x in v] for v in _embedder(model).passage_embed(texts)]


def embed_query(model: str, text: str) -> list[float]:
    return [float(x) for x in next(iter(_embedder(model).query_embed(text)))]


def _d(i: int) -> str:
    return "open-ended" if i >= 99990000 else date(i // 10000, i // 100 % 100, i % 100).isoformat()


def _yes(b) -> str:
    return "yes" if b else "no"


def corpus() -> list[dict]:
    kn = load()
    tenants = {t["tenant_id"]: t["display_name"] for t in kn.raw["tenants"]}
    versions = {v["version_id"]: v for v in kn.versions}
    findings_by_res = {}
    for c in load_cases():
        r = c.get("resolution") or {}
        if r.get("supports_finding"):
            findings_by_res[c["claim_id"]] = r["supports_finding"]
    out = []
    for cl in kn.clauses.values():
        v = versions[cl.version_id]
        req = ", ".join(f"{kn.name('evidence_types', e)} ({e})" for e in cl.requires) or "none"
        out.append({"chunk_id": f"CL-{cl.clause_id}", "kind": "clause", "version": cl.version_id,
                    "text": (f"Policy LumenCare Silver, version {cl.version_id} (in force {_d(v['effective_from'])} "
                             f"to {_d(v['effective_to'])}). Section {cl.section}, {cl.title}: {cl.text} "
                             f"Evidence required for an appeal under this section: {req}.")})
    for c in load_cases():
        if c["source"] != "historical":
            continue
        r = c["resolution"]
        ev = ", ".join(f"{kn.name('evidence_types', e)} ({e})" for e in c["evidence"]) or "none"
        out.append({"chunk_id": f"CS-{c['claim_id']}", "kind": "case", "claim_id": c["claim_id"],
                    "tenant_id": c["tenant_id"], "finding_id": findings_by_res.get(c["claim_id"]),
                    "text": (f"Past case {c['claim_id']}. Policyholder: {tenants[c['tenant_id']]}. "
                             f"Service: {kn.name('service_categories', c['service'])}, service date "
                             f"{_d(c['service_date'])} (policy {kn.version_for(c['service_date'])}). "
                             f"Emergency: {_yes(c['is_emergency'])}. In network: {_yes(c['in_network'])}. "
                             f"Denial notice: {notice_core(c['notice_text'])} Evidence submitted on appeal: {ev}. "
                             f"Verified outcome: {r['outcome']} on {_d(r['verified_on'])}.")})
    return out


def finding_passages() -> list[dict]:
    """One passage per seeded Finding: the abstract facts the graph stores for it (statement, reason, clause,
    versions it remains valid in, evidence the winning appeals had, conditions, wins, contradictions, status).
    No verdict about any claim, and no individual case: that reasoning is left to the model."""
    kn = load()
    versions = [v["version_id"] for v in kn.versions]
    latest = versions[-1]
    out = []
    for f in kn.findings:
        clause = kn.clause(f.learned_in[-1], f.lineage)
        valid = [v for v in f.valid_in if v in versions]
        status = "CONTRADICTED" if f.contradicted_by >= f.wins else ("ACTIVE" if latest in valid else "STALE")
        needs = ", ".join(f"{kn.name('evidence_types', e)} ({e})" for e in f.needs) or "no additional evidence"
        cond = []
        if f.req_emergency is not None:
            cond.append("only when the service was an emergency" if f.req_emergency else "only when it was not an emergency")
        if f.req_in_network is not None:
            cond.append("only for in-network care" if f.req_in_network else "only for out-of-network care")
        out.append({"chunk_id": f"FN-{f.finding_id}", "kind": "finding", "finding_id": f.finding_id,
                    "text": (f"Finding {f.finding_id} (abstract precedent distilled from verified past outcomes). "
                             f"Denial reason: {kn.name('denial_reasons', f.reason)} ({f.reason}). "
                             f"Learned under policy clause {clause.clause_id}, Section {clause.section} {clause.title}. "
                             f"Valid in policy versions: {', '.join(valid) or 'none'}. Status: {status}. "
                             f"Appeals succeeded when they included: {needs}. "
                             f"Conditions: {'; '.join(cond) or 'none'}. "
                             f"Verified wins: {f.wins}. Later contradicting verified losses: {f.contradicted_by}.")})
    return out


def build_index(model: str, variant: str = "cases") -> str:
    """(Re)build the baseline graph for one embedding model. Returns the graph name."""
    name = graph_name(model, variant)
    db.drop(name)
    g = db.connect(name)
    chunks = corpus() + (finding_passages() if variant == "findings" else [])
    vecs = embed_passages(model, [c["text"] for c in chunks])
    dim = len(vecs[0])
    g.query(f"CREATE VECTOR INDEX FOR (c:Chunk) ON (c.embedding) "
            f"OPTIONS {{dimension: {dim}, similarityFunction: 'cosine'}}")
    rows = [{**c, "emb": v} for c, v in zip(chunks, vecs)]
    for i in range(0, len(rows), 20):
        db.run(g, """
            UNWIND $rows AS r
            CREATE (:Chunk {chunk_id: r.chunk_id, kind: r.kind, text: r.text, claim_id: r.claim_id,
                            tenant_id: r.tenant_id, finding_id: r.finding_id, version: r.version,
                            embedding: vecf32(r.emb)})
        """, {"rows": rows[i:i + 20]})
    log.info("baseline index %s: %d passages, dim %d", name, len(rows), dim)
    return name


def add_case(model: str, chunk: dict):
    """A newly resolved case becomes one more passage (the baseline's only form of memory)."""
    g = db.connect(graph_name(model))
    vec = embed_passages(model, [chunk["text"]])[0]
    db.run(g, """CREATE (:Chunk {chunk_id: $c.chunk_id, kind: 'case', text: $c.text, claim_id: $c.claim_id,
                                 tenant_id: $c.tenant_id, finding_id: $c.finding_id, embedding: vecf32($v)})""",
           {"c": chunk, "v": vec})


def retrieve(model: str, query: str, k: int, tenant_id: str, variant: str = "cases") -> list[dict]:
    g = db.connect(graph_name(model, variant))
    count = db.one(g, "MATCH (c:Chunk) RETURN count(c) AS n")["n"]
    return db.run(g, """
        CALL db.idx.vector.queryNodes('Chunk', 'embedding', $count, vecf32($q)) YIELD node, score
        WHERE node.kind IN ['clause', 'finding'] OR node.tenant_id = $tenant
        RETURN node.chunk_id AS chunk_id, node.kind AS kind, node.text AS text, node.claim_id AS claim_id,
               node.tenant_id AS tenant_id, node.finding_id AS finding_id, score
        ORDER BY score LIMIT $k
    """, {"k": k, "count": count, "tenant": tenant_id, "q": embed_query(model, query)})


def claim_facts(case: dict) -> str:
    kn = load()
    ev = ", ".join(f"{kn.name('evidence_types', e)} ({e})" for e in case["evidence"]) or "none"
    lines = [f"Claim ID: {case['claim_id']}",
             f"Service: {kn.name('service_categories', case['service'])}",
             f"Service date: {_d(case['service_date'])}",
             f"Filed: {_d(case['filed_date'])} ({case['filing_lag_days']} days after the service)",
             f"Emergency: {_yes(case['is_emergency'])}",
             f"In network: {_yes(case['in_network'])}"]
    if case.get("enrolled_months") is not None:
        lines.append(f"Months enrolled before the service: {case['enrolled_months']}")
    if case.get("session_number"):
        lines.append(f"Session number this plan year: {case['session_number']}")
    lines += [f"Evidence already on file: {ev}", f"Denial notice: {case['notice_text']}"]
    return "\n".join(lines)


def answer(case: dict, model: str, k: int | None = None, variant: str = "cases") -> dict:
    k = k or (FINDINGS_TOP_K if variant == "findings" else config.BASELINE_TOP_K)
    query = (f"{load().name('service_categories', case['service'])}. {notice_core(case['notice_text'])} "
             f"Service date {_d(case['service_date'])}.")
    hits = retrieve(model, query, k, case["tenant_id"], variant)
    passages = "\n\n".join(f"[{h['chunk_id']}] {h['text']}" for h in hits)
    user = f"CLAIM:\n{claim_facts(case)}\n\nRETRIEVED PASSAGES:\n{passages}\n\nDecide and write the plan."
    if variant == "findings":
        out, meta = llm.complete(f"baseline-{short(model)}-findings", SYSTEM_FINDINGS, user, BaselineFindingsAnswer,
                                 effort="medium")
    else:
        out, meta = llm.complete(f"baseline-{short(model)}", SYSTEM, user, BaselineAnswer, effort="medium")
    return {"answer": out.model_dump(), "retrieved": hits,
            "llm": {"platform": meta.platform, "model": meta.model, "cached": meta.cached,
                    "input_tokens": meta.input_tokens, "output_tokens": meta.output_tokens}}
