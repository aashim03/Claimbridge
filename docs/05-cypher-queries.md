# 05 — Load-Bearing Cypher Queries

> **Status (updated 17 Oct 2026): the query walkthrough is the original design; the executable source is authoritative.** Where they differ, trust `backend/claimbridge/tools/`.
>
> | Query | As built, and where |
> |---|---|
> | Q4 applicability | `tools/applicability.py`: also checks `req_in_network`; verdict order is reason, lineage, version validity, contradiction, conditions |
> | Q5 evidence gap | `tools/evidence.py`: requirements from the cited clause **and** from accepted findings, each with `sources`; withdrawn documents are ignored |
> | Q6 staleness | `tools/memory.py`: compares clause **fingerprints** (text, params, evidence, routing), not only numeric parameters |
> | Q7 / Q7b leases | `tools/coordination.py`: `timestamp()` for time; `lease_gen` incremented on acquisition; renewal refuses an expired lease |
> | Q8 commit | `tools/coordination.py`: owner, generation and expiry checked in the same write that advances the claim |
> | The fence | `tools/__init__.py` (`FENCE`): `lease_owner`, `lease_gen` and `lease_until >= timestamp()` in every fenced write; memory writes use `FencedGraph` |
> | Q9 contradiction, Q11 tenant precedents | `tools/memory.py`, `tools/tenancy.py` (the API's tenant comes from the credential) |
> | Q10 explanation subgraph | `api.py` `claim_graph`: evidence nodes and edges carry `origin` (`policy` or `learned`) |
> | New | `supervisor.py`: correction (`correct_classification`) and evidence (`declare_evidence`, `withdraw_evidence`) writes |

The submission must document "the Cypher queries or graph algorithms the product depends on." This is that list. Each query is wrapped by one function in `backend/claimbridge/tools/` and has a test against the seed data.

Conventions:
- `$now` is epoch ms.
- Dates are `YYYYMMDD` ints.
- `filing_lag_days` is computed once at intake, in Python.
- Finding conditions are flat, nullable properties (`req_emergency`, `req_in_network`), where `null` means "no requirement." Clause parameters that matter are flattened onto the clause (`limit_days`, `max_sessions`, `referral_exception`, `notify_hours`), with `params` kept as a canonical JSON string for change detection.

> Syntax is FalkorDB Cypher. Verify the vector procedure and constraint commands against docs.falkordb.com on Day 1.

---

## Q1 — Select the governing policy version (Intake)
```cypher
MATCH (c:Claim {claim_id: $cid}), (v:PolicyVersion)
WHERE v.effective_from <= c.service_date AND c.service_date < v.effective_to
MERGE (c)-[:GOVERNED_BY]->(v)
RETURN v.version_id
```
**Why the graph is needed:** RAG retrieves text from every version. This pins all later reasoning to one version.

## Q2 — Denial reason cross-check by vector (Intake)
```cypher
CALL db.idx.vector.queryNodes('DenialReason', 'embedding', 3, vecf32($notice_vec))
YIELD node, score
RETURN node.code AS code, score
```
In the implementation, the query vector is the claim's stored notice embedding (`n.embedding`), so no client-side embedding is needed at runtime. `score` is a cosine **distance** (lower is closer).

## Q2a — Reason votes from similar historical notices (Intake)
```cypher
MATCH (c:Claim {claim_id: $cid})-[:HAS_NOTICE]->(n:DenialNotice)
CALL db.idx.vector.queryNodes('DenialNotice', 'embedding', $search, n.embedding)
YIELD node, score
MATCH (pc:Claim)-[:HAS_NOTICE]->(node)
WHERE pc.source = 'historical'
WITH pc, score ORDER BY score LIMIT $k
MATCH (pc)-[:DENIED_FOR]->(r:DenialReason)
RETURN r.code AS code, sum(1.0 - score) AS weight, count(pc) AS n
ORDER BY weight DESC
```
**Intake decision rule (Phase 1, no LLM):**
1. If the notice cites a section, take that section in the governing version, plus the reason that routes to it.
2. Otherwise, take Q2 and Q2a together. If they agree, accept. If they disagree, take Q2a and set `needs_llm_review`.

**Measured on the 32 evaluation claims:** cited section 20/20, Q2a 29/32, Q2 27/32, combined rule 31/32. The one miss is the deliberately misleading notice (EV-N-11), and it's flagged for review.

## Q2b — Similar past notices as a recall signal only (Retrieval)
```cypher
MATCH (c:Claim {claim_id: $cid})-[:HAS_NOTICE]->(n:DenialNotice)
CALL db.idx.vector.queryNodes('DenialNotice', 'embedding', $search, n.embedding)
YIELD node, score
MATCH (pc:Claim)-[:HAS_NOTICE]->(node)
WHERE pc.source = 'historical'
WITH node, score ORDER BY score LIMIT $k
MATCH (pc:Claim)-[:HAS_NOTICE]->(node)
MATCH (pc)-[:RESOLVED_BY]->(:Resolution)<-[:DERIVED_FROM]-(f:Finding)
RETURN f.finding_id AS finding_id, min(score) AS distance
ORDER BY distance
```
Vectors only **propose** candidates. Q4 decides.

## Q3 — Graph candidates (Retrieval)
```cypher
MATCH (c:Claim {claim_id: $cid})-[:DENIED_FOR]->(r:DenialReason)<-[:FOR_REASON]-(f:Finding)
MATCH (f)-[:ON_LINEAGE]->(fl:Clause)
OPTIONAL MATCH (c)-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(cc:Clause)
RETURN f.finding_id, fl.lineage_id,
       (cc IS NOT NULL AND fl.lineage_id = cc.lineage_id) AS same_lineage,
       f.status, f.confidence
ORDER BY same_lineage DESC, f.confidence DESC
LIMIT 8
```
Retrieval then writes the candidates:
```cypher
UNWIND $cands AS x
MATCH (c:Claim {claim_id: $cid}), (f:Finding {finding_id: x.finding_id})
MERGE (c)-[k:CONSIDERED]->(f)
SET k.verdict = 'CANDIDATE', k.source = x.source, k.score = x.score
```

## Q4 — Applicability verdict per candidate (Verifier, the core query)
```cypher
MATCH (c:Claim {claim_id: $cid})-[:GOVERNED_BY]->(v:PolicyVersion)
WHERE ($me IS NULL OR c.lease_owner = $me)          // fencing
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
    WHEN fr IS NULL                                                      THEN 'REASON_MISMATCH'
    WHEN fl.lineage_id <> cc.lineage_id                                  THEN 'LINEAGE_MISMATCH'
    WHEN vi IS NULL                                                      THEN 'VERSION_DRIFT'
    WHEN f.status = 'CONTRADICTED'                                       THEN 'CONTRADICTED'
    WHEN f.req_emergency  IS NOT NULL AND f.req_emergency  <> c.is_emergency THEN 'CONDITION_UNMET'
    WHEN f.req_in_network IS NOT NULL AND f.req_in_network <> c.in_network   THEN 'CONDITION_UNMET'
    ELSE 'ACCEPTED'
  END AS verdict
SET k.verdict = CASE verdict WHEN 'ACCEPTED' THEN 'ACCEPTED' ELSE 'REJECTED' END,
    k.reason_code = verdict
RETURN f.finding_id, verdict,
       fl.clause_id  AS learned_on_clause,
       gov.clause_id AS governing_clause,
       contras
```
This is the query that answers "why not reuse that precedent?" with a path: Finding → learned on clause X (2025) → superseded by clause Y in the governing version (2026). Vector similarity can't express version scoping, condition checks, and contradiction edges in one decision.

`REASON_MISMATCH` covers candidates that only vector recall proposed (a look-alike notice with a different denial reason). It's checked first.

## Q4b — Clause-level gates, including timely filing (Verifier)
```cypher
MATCH (c:Claim {claim_id: $cid})-[:GOVERNED_BY]->(v:PolicyVersion)
MATCH (c)-[:DENIED_FOR]->(r:DenialReason)
MATCH (c)-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(cc:Clause)
OPTIONAL MATCH (v)-[:CONTAINS]->(tf:Clause {lineage_id: 'L-TIMELY-FILING'})
WITH c, [x IN [
    CASE WHEN cc.no_basis = true THEN 'EXCLUSION_NO_BASIS' END,
    CASE WHEN cc.req_emergency = true AND c.is_emergency <> true THEN 'EMERGENCY_REQUIRED' END,
    CASE WHEN r.code = 'TIMELY_FILING' AND c.filing_lag_days > tf.limit_days THEN 'FILED_LATE' END,
    CASE WHEN r.code = 'WAITING_PERIOD' AND coalesce(c.enrolled_months, 0) < cc.wait_months
         THEN 'WAITING_NOT_MET' END
  ] WHERE x IS NOT NULL] AS gs, cc, tf
SET c.gates = gs
RETURN gs AS gates, cc.clause_id AS cited_clause, tf.limit_days AS filing_limit_days
```

## Q5 — Evidence gap (Planner)
```cypher
MATCH (c:Claim {claim_id: $cid})-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(cl:Clause)
OPTIONAL MATCH (cl)-[:REQUIRES]->(e1:EvidenceType)
WITH c, collect(DISTINCT e1) AS r1
OPTIONAL MATCH (c)-[:CONSIDERED {verdict: 'ACCEPTED'}]->(:Finding)-[:NEEDS_EVIDENCE]->(e2:EvidenceType)
WITH c, r1, collect(DISTINCT e2) AS r2       // FalkorDB: aggregate in its own WITH
UNWIND r1 + r2 AS e
WITH DISTINCT c, e
OPTIONAL MATCH (c)-[:HAS_EVIDENCE]->(ev:Evidence)-[:OF_TYPE]->(e)
WITH e, count(ev) AS have
RETURN e.code AS evidence, have > 0 AS satisfied
ORDER BY satisfied, evidence
```
Required = the cited clause's `REQUIRES` plus accepted Findings' `NEEDS_EVIDENCE`. Playbook step evidence is guidance for the Planner, not a requirement, so it isn't included.

## Q6 — Staleness propagation on a new policy version (Curator, mode B)
Step 1: lineages that **changed** make dependent Findings stale.
```cypher
MATCH (new:Clause {version_id: $new_version})-[:SUPERSEDES]->(old:Clause)
WHERE new.params <> old.params
MATCH (f:Finding)-[:ON_LINEAGE]->(l:Clause {lineage_id: new.lineage_id})
MERGE (f)-[:STALE_BECAUSE]->(new)
SET f.status = CASE WHEN f.status = 'CONTRADICTED' THEN f.status ELSE 'STALE' END,
    f.updated_at = $now
RETURN f.finding_id, new.clause_id
```
Step 2: lineages that **didn't change** carry valid Findings forward.
```cypher
MATCH (new:Clause {version_id: $new_version})-[:SUPERSEDES]->(old:Clause)
WHERE new.params = old.params
MATCH (pv_new:PolicyVersion {version_id: $new_version}),
      (pv_old:PolicyVersion {version_id: old.version_id})
MATCH (f:Finding)-[:ON_LINEAGE]->(:Clause {lineage_id: new.lineage_id})
MATCH (f)-[:VALID_IN]->(pv_old)
MERGE (f)-[:VALID_IN]->(pv_new)
RETURN count(f) AS carried_forward
```
**Demo moment:** press "Publish 2026 policy." `F-MRI-REFERRAL` turns STALE with an edge to `C-2026-MRI-PREAUTH`. Every other Finding is carried forward.

## Q7 — Atomic lease claim (every worker)
```cypher
MATCH (c:Claim {status: $state})
WHERE c.lease_owner IS NULL OR c.lease_until < $now
WITH c ORDER BY c.filed_date, c.claim_id LIMIT 1
SET c.lease_owner = $me,
    c.lease_until = $now + $ttl_ms,
    c.attempt     = coalesce(c.attempt, 0) + 1
RETURN c.claim_id AS claim_id, c.attempt AS attempt
```
FalkorDB applies write queries to a graph one at a time, so only one worker can match and set a free claim. Test it on Day 1 with 10 parallel claimers against 1 claim, and expect exactly 1 winner.

## Q7b — Lease heartbeat (only while still owner)
```cypher
MATCH (c:Claim {claim_id: $cid})
WHERE c.lease_owner = $me
SET c.lease_until = $now + $ttl_ms
RETURN count(c) AS still_owner
```
If `still_owner = 0`, the worker aborts its step immediately.

## Q8 — Fenced commit (every worker)
```cypher
MATCH (c:Claim {claim_id: $cid})
WHERE c.lease_owner = $me AND c.status = $from
SET c.status = $to, c.lease_owner = null, c.lease_until = null, c.attempt = 0,
    c.event_seq = coalesce(c.event_seq, 0) + 1
WITH c
OPTIONAL MATCH (c)-[:HAS_EVENT]->(prev:CaseEvent)
WHERE prev.seq = c.event_seq - 1
CREATE (e:CaseEvent {event_id: c.claim_id + ':' + toString(c.event_seq), seq: c.event_seq,
                     type: $etype, ts: $now, agent_id: $agent, step: $step, payload: $payload})
CREATE (c)-[:HAS_EVENT]->(e)
FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END | CREATE (prev)-[:NEXT]->(e))
MERGE (a:Agent {agent_id: $agent}) ON CREATE SET a.role = $role
CREATE (a)-[:PERFORMED]->(e)
MERGE (cp:Checkpoint {checkpoint_id: c.claim_id + ':' + $from})
SET cp.step = $from, cp.state = $checkpoint, cp.ts = $now, cp.agent_id = $me, cp.complete = true
MERGE (c)-[:HAS_CHECKPOINT]->(cp)
RETURN c.status AS status
```
Zero rows returned means the worker was fenced out (it lost the lease), and nothing was written.

**How step outputs are protected:** each output write (classification, candidates, verdicts) is its own idempotent query, guarded by `WHERE ($me IS NULL OR c.lease_owner = $me)`. Q8 is the single commit point that makes the step visible to the next role. A worker that loses its lease can't write outputs or commit. A replacement worker overwrites any half-written outputs, because they're keyed deterministically.

A mid-step checkpoint (`complete: false`) lets a replacement skip finished work. The Verifier saves one after its applicability pass.

## Q9 — Contradiction update (Curator, mode A)
```cypher
MATCH (f:Finding {finding_id: $fid}), (r:Resolution {resolution_id: $rid})
MERGE (f)-[:CONTRADICTED_BY]->(r)
WITH f
MATCH (f)-[:CONTRADICTED_BY]->(x:Resolution)
WITH f, count(x) AS n
SET f.confidence = CASE WHEN f.support = 0 THEN 0.0
                        ELSE (toFloat(f.wins) / f.support) / (1 + n) END,
    f.status     = CASE WHEN n >= f.wins THEN 'CONTRADICTED' ELSE f.status END,
    f.updated_at = $now
RETURN f.finding_id, f.status, f.confidence, n
```

## Q10 — Explanation subgraph (API, path viewer)
```cypher
MATCH (c:Claim {claim_id: $cid})-[:GOVERNED_BY]->(v:PolicyVersion)
MATCH (c)-[:HAS_NOTICE]->(n:DenialNotice)-[:CITES]->(cc:Clause)
OPTIONAL MATCH (c)-[k:CONSIDERED]->(f:Finding)
OPTIONAL MATCH (f)-[:ON_LINEAGE]->(fl:Clause)
OPTIONAL MATCH (f)-[:STALE_BECAUSE]->(sc:Clause)
OPTIONAL MATCH (f)-[:CONTRADICTED_BY]->(cr:Resolution)
OPTIONAL MATCH (c)-[:RECOMMENDATION]->(rec)-[:HAS_ITEM]->(i:RecItem)-[:CITES]->(cited)
RETURN c, v, n, cc,
       collect(DISTINCT {finding: f, verdict: k.verdict, code: k.reason_code,
                         learned_on: fl, stale_by: sc, contradicted_by: cr}) AS considered,
       collect(DISTINCT {item: i, cites: cited}) AS items
```
The UI turns this into nodes and edges, and highlights accepted paths in one color and rejected paths in another.

## Q11 — Tenant-scoped precedent detail (API, trap T7)
```cypher
MATCH (f:Finding {finding_id: $fid})-[:DERIVED_FROM]->(r:Resolution)<-[:RESOLVED_BY]-(pc:Claim)
RETURN r.resolution_id, r.outcome,
       CASE WHEN pc.tenant_id = $tenant THEN pc.claim_id ELSE null END AS claim_id,
       pc.tenant_id = $tenant AS own_case
```
Case-level reads always anchor on the tenant:
```cypher
MATCH (:Tenant {tenant_id: $tenant})-[:FILED]->(c:Claim {claim_id: $cid})
RETURN c
```

## Q12 — Second session is smarter (Retrieval sees learned memory)
```cypher
MATCH (f:Finding)-[:DERIVED_FROM]->(r:Resolution)
WHERE f.created_at > $session_start OR f.updated_at > $session_start
RETURN f.finding_id, f.statement, f.support, f.confidence
```
The UI uses this for the "Memory learned since restart" panel.

## Q13 — Ops view (UI)
```cypher
MATCH (h:WorkerHeartbeat)
RETURN h.agent_id, h.role, h.state, h.current_claim, h.last_seen,
       h.last_seen > $now - 10000 AS alive
ORDER BY h.role, h.agent_id
```

## Graph algorithms (implemented: Q16)
Two FalkorDB built-ins, both present in the pinned image (`CALL dbms.procedures()` lists `algo.BFS` and `algo.pageRank`), are used by `policy_blast_radius`. See Q16 below. Shortest path and PageRank over clauses cited by OVERTURNED resolutions remain ideas, not features.

## Query tests

Implemented in `backend/tests/` (`uv run pytest`; the suite needs FalkorDB, see the README).

| Test | Query | Expectation | Status |
|---|---|---|---|
| All 32 evaluation claims | Q1, Q3, Q4, Q4b, Q5 | version, verdicts, gates and missing evidence equal ground truth | ✅ |
| T1 trap | Q4 | `F-MRI-REFERRAL` gives `VERSION_DRIFT`, learned on `C-2025-…`, governing `C-2026-MRI-PREAUTH` | ✅ |
| T2 trap | Q3 + Q4 | MRI Findings give `LINEAGE_MISMATCH` | ✅ |
| T4 trap | Q4 | `F-SLEEP-RETRO` gives `CONTRADICTED`, with 2 contradicting resolutions | ✅ |
| T5 trap | Q4 | `F-OON-ER` gives `CONDITION_UNMET` | ✅ |
| T6 trap | Q4b | `FILED_LATE`, `EXCLUSION_NO_BASIS`, `WAITING_NOT_MET` | ✅ |
| Lease | Q7 × 16 parallel, 10 trials | exactly 1 winner | ✅ |
| Fencing | Q8 and Q7b with a stale owner | rejected, no writes | ✅ |
| Crash and resume | worker processes | a second verifier resumes from the checkpoint | ✅ |
| Staleness | Q6 | only changed lineages stale, the rest carried forward | ✅ |
| Contradiction update | Q9 | confidence drops, status flips | ✅ |
| Learn a Finding | `create_finding` | `VALID_IN` computed from clause params, reused by the next claim | ✅ |
| Lease reaper | supervisor | `LEASE_EXPIRED` recorded once per expiry | ✅ |

The implemented Q6, Q9 and learning queries are in `backend/claimbridge/tools/memory.py`. Planner context and recommendation writes are in `tools/recommendation.py`.

## Q14 — What rests on a clause (blast radius) and Q15 — Why this precedent (path trace)

Both live in `backend/claimbridge/tools/trace.py`, are read-only, and are tested in `backend/tests/test_trace.py`.

**Q14, `GET /api/impact/clause/{id}`.** A variable-length traversal finds every version of a clause, then each hop adds a layer: memory learned on any of them, the evidence that memory asks for and the claims that weighed it.

```cypher
MATCH (c0:Clause {clause_id: $id})-[:SUPERSEDES*0..4]-(x:Clause)      // the clause and every version of it
WITH DISTINCT x
MATCH (f:Finding)-[:ON_LINEAGE]->(x)                                   // memory learned on any of them
OPTIONAL MATCH (f)-[:NEEDS_EVIDENCE]->(e:EvidenceType)                 // the evidence that memory asks for
OPTIONAL MATCH (cl:Claim)-[k:CONSIDERED]->(f)                          // and the claims that weighed it
WHERE cl.source <> 'historical' AND k.reason_code <> 'REASON_MISMATCH'
RETURN x, f, collect(DISTINCT e), collect(DISTINCT cl)
```

A test asserts that the traversal reaches exactly the clauses sharing the lineage key. A tenant sees its own claims by id; other policyholders' claims are only counted.

**Q15, `GET /api/claims/{cid}/trace/{fid}`.** For one claim and one precedent, it rebuilds the chain of edges the Verifier relies on (reason, lineage, governing version, `SUPERSEDES*` distance, `VALID_IN`, contradiction, conditions). The first hop that does not hold is the break. A test checks, for every precedent of every evaluation claim, that the break reproduces the verdict code stored on the `CONSIDERED` edge.

## Q16 — Blast radius with graph algorithms, and Q17 — the investigation trace

**Q16, `policy_blast_radius`, `GET /api/blast/clause/{id}`, `GET /api/blast/lineages`** (`backend/claimbridge/tools/blast.py`, tests in `tests/test_blast.py`). `algo.BFS` follows outgoing edges only, while the dependency runs claim → precedent → clause, so the live graph is only *read* (four plain queries over `SUPERSEDES`, `ON_LINEAGE`, `CONSIDERED`, `DERIVED_FROM`) and the dependency edges are copied into a throwaway scratch graph beside it, under two relationship types, `IMPACTS` (direction of effect) and `DEPENDS_ON` (direction of dependence). The scratch graph is deleted in a `finally`. `VALID_IN` is deliberately not walked: it points at `PolicyVersion` hubs shared by every precedent, which would connect unrelated lineages.

```cypher
// reach and hop distance (the BFS tree edges give each node's parent, hence its depth)
MATCH (s:N {id: $clause_id})
CALL algo.BFS(s, 6, 'IMPACTS') YIELD nodes, edges
RETURN nodes, edges

// how much depends on each clause (summed per lineage)
CALL algo.pageRank('N', 'DEPENDS_ON') YIELD node, score
RETURN node.id AS id, score
```

What the algorithms add over `COUNT`: the hop distance of each affected item and a rank that counts indirect dependence. They do not change *which* claims are affected; Q14 reaches the same set. On this small synthetic graph the ranking mostly follows the counts. The test builds a 4-clause, 3-precedent, 3-claim graph and checks every hop distance against a hand computation.

**Q17, investigation memory** (`backend/claimbridge/investigator.py`). Each investigator run is stored as `(Investigation)-[:OF]->(Claim)`, `(Investigation)-[:CALLED {seq, args}]->(ToolCall)` and `(ToolCall)-[:RETURNED]->(Finding|Clause|Claim|PolicyVersion|EvidenceType|Resolution)`. A later run on a claim of the same tenant citing the same lineage reads the latest one:

```cypher
MATCH (c:Claim {claim_id: $cid})
MATCH (cl:Clause {clause_id: $clause})
MATCH (inv:Investigation)-[:OF]->(pc:Claim)-[:HAS_NOTICE]->(:DenialNotice)-[:CITES]->(:Clause {lineage_id: cl.lineage_id})
WHERE pc.claim_id <> $cid AND pc.tenant_id = c.tenant_id
RETURN pc.claim_id, inv.summary ORDER BY inv.started_at DESC LIMIT 1
```

The result is shown as "Last time on this clause" and given to the model as a hint. It orders nothing and decides nothing.

The tool catalogue (`backend/claimbridge/catalogue.py`) reuses Q1, Q3, Q5, Q14, Q15 unchanged. The two tools whose stored queries also write (`select_version` pins the claim, `check_applicability` stores the verdict) read the same facts without the write: the version lookup is the match part of Q1, and the verdict is re-derived by the path trace of Q15.
