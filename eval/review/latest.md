# ClaimBridge evaluation results

Generated 2026-10-17T17:13:43 · LLM `groq/openai/gpt-oss-120b` · 34 evaluation claims (synthetic, see docs/03) · ground truth from an independent rule engine.

Systems: **ClaimBridge**; **No-memory ablation**; **Baseline RAG** (`BAAI/bge-small-en-v1.5`, top-8); **Baseline RAG (large embeddings)** (`mixedbread-ai/mxbai-embed-large-v1`, top-8).

## Headline metrics

| Metric | ClaimBridge | No-memory ablation | Baseline RAG | Baseline RAG (large embeddings) |
|---|---:|---:|---:|---:|
| Completion rate ? | 100% | 100% | 100% | 85% |
| Decision correctness (excludes precedent recall) ? | 100% | 100% | 76% | 68% |
| Denial reason accuracy ↑ | 100% | 100% | 100% | 85% |
| Governing policy version accuracy ↑ | 100% | 100% | 100% | 85% |
| Precedent precision ↑ | 100% | n/a | 67% | n/a |
| Precedent recall ↑ | 100% | 0% | 10% | 0% |
| Wrong-precedent rate (claims reusing a precedent that does not apply) ↓ | 0% | 0% | 3% | 0% |
| Missing-evidence F1 ↑ | 100% | 100% | 88% | 90% |
| Disposition accuracy ↑ | 100% | 100% | 79% | 71% |
| Items without valid citation IDs (not semantic entailment) ↓ | 0% | 0% | 6% | 2% |
| Stale or contradicted precedent avoided ↑ | 100% | 100% | 100% | 100% |
| …and rejected with the right reason ↑ | 100% | 0% | 0% | 0% |
| Other-tenant case fields exposed (T7) ↓ | 0 | 0 | 0 | 0 |
| LLM tokens per claim ↓ | 332 | 332 | 2892 | 2415 |
| Claims fully correct (reason, version, precedents, evidence, disposition) ↑ | 100% | 38% | 24% | 18% |

## By trap type (claims fully correct)

| Group | ClaimBridge | No-memory ablation | Baseline RAG | Baseline RAG (large embeddings) |
|---|---:|---:|---:|---:|
| T1 version drift | 4/4 | 3/4 | 0/4 | 2/4 |
| T2 same reason, wrong clause | 3/3 | 1/3 | 1/3 | 1/3 |
| T3 missing evidence | 3/3 | 0/3 | 0/3 | 0/3 |
| T4 contradicted memory | 2/2 | 2/2 | 2/2 | 2/2 |
| T5 condition unmet | 2/2 | 2/2 | 2/2 | 1/2 |
| T6 no basis | 3/3 | 3/3 | 0/3 | 0/3 |
| T7 tenant isolation | 2/2 | 0/2 | 0/2 | 0/2 |
| M memory scenario | 2/2 | 2/2 | 2/2 | 0/2 |
| Normal cases | 13/13 | 0/13 | 1/13 | 0/13 |

## Why wrong precedents were used

Each time a system relied on a precedent that does not apply, the ground truth says why it does not:

| System | VERSION_DRIFT | LINEAGE_MISMATCH | CONTRADICTED | CONDITION_UNMET | NOT_APPLICABLE |
|---|---:|---:|---:|---:|---:|
| ClaimBridge | 0 | 0 | 0 | 0 | 0 |
| No-memory ablation | 0 | 0 | 0 | 0 | 0 |
| Baseline RAG | 0 | 1 | 0 | 0 | 0 |
| Baseline RAG (large embeddings) | 0 | 0 | 0 | 0 | 0 |

## Memory gain (M11)

Claim EV-M-A (ambulance, emergency) is approved and its real outcome recorded as OVERTURNED. EV-M-B1 was processed before that, EV-M-B2 (same facts) after.

- **ClaimBridge**: before: missing evidence none, APPEAL_VIABLE; after: missing evidence ['ITEMIZED_BILL'], APPEAL_NEEDS_EVIDENCE. Support score 0.0 to 0.667 (not a probability) (Curator: learned ['F-L-AMBULANCE-3fc5cd595b568ee3']).
- **No-memory ablation**: before: missing evidence none, APPEAL_VIABLE; after: missing evidence none, APPEAL_VIABLE. Support score 0.0 to 0.0 (not a probability) (Curator: learned ['F-L-AMBULANCE-3fc5cd595b568ee3']).
- **Baseline RAG**: before: precedent cases none; after adding EV-M-A to the corpus: retrieved it: False, precedent cases none.

## Coordination under failure (M10)

12 claims, worker pool `intake=2,retrieval=2,verifier=2,planner=2,curator=1`, 10 random hard kills of workers holding a lease (a replacement started each time), lease TTL 4 s.

| Measure | Result |
|---|---:|
| Claims completed | 12/12 |
| Claims correct | 12/12 |
| Kills that interrupted a step in progress | 10 of 10 |
| …each resumed by another worker | 10 |
| Mean time from kill to the interrupted step completing | 7.0 s (includes the 4 s lease timeout) |
| Duplicate step outputs | 0 |
| Late writes fenced out | 0 |

Kills that land after a worker already committed its step interrupt nothing; the claim simply moves on. The Supervisor's `LEASE_EXPIRED` event is recorded only when it sees the expired lease before another replica reclaims it, so `RESUMED` events are the reliable count.

## ClaimBridge failures

None in this run.


## Per-claim results

| Claim | Trap | ClaimBridge | No-memory ablation | Baseline RAG | Baseline RAG (large embeddings) |
|---|---|---|---|---|---|
| EV-T1-01 | T1 | ✅ | ✅ | ❌ precedents | ✅ |
| EV-T1-02 | T1 | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-T1-03 | T1 | ✅ | ✅ | ❌ disposition,missing | ✅ |
| EV-T1-04 | T1 | ✅ | ✅ | ❌ disposition | ❌ disposition |
| EV-T2-01 | T2 | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-T2-02 | T2 | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-T2-03 | T2 | ✅ | ✅ | ✅ | ✅ |
| EV-T3-01 | T3 | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-T3-02 | T3 | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-T3-03 | T3 | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-T4-01 | T4 | ✅ | ✅ | ✅ | ✅ |
| EV-T4-02 | T4 | ✅ | ✅ | ✅ | ✅ |
| EV-T5-01 | T5 | ✅ | ✅ | ✅ | ❌ disposition |
| EV-T5-02 | T5 | ✅ | ✅ | ✅ | ✅ |
| EV-T6-01 | T6 | ✅ | ✅ | ❌ disposition | ❌ disposition |
| EV-T6-02 | T6 | ✅ | ✅ | ❌ disposition | ❌ disposition |
| EV-T6-03 | T6 | ✅ | ✅ | ❌ disposition | ❌ disposition |
| EV-T7-01 | T7 | ✅ | ❌ precedents | ❌ precedents,disposition,missing | ❌ precedents |
| EV-T7-02 | T7 | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-N-01 | - | ✅ | ❌ precedents | ✅ | ❌ precedents |
| EV-N-02 | - | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-N-03 | - | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-N-04 | - | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-N-05 | - | ✅ | ❌ precedents | ❌ precedents,missing | ❌ precedents,missing |
| EV-N-06 | - | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-N-07 | - | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-N-08 | - | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-N-09 | - | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-N-10 | - | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-N-11 | - | ✅ | ❌ precedents | ❌ disposition,missing | ❌ reason,version,precedents,disposition,completed |
| EV-N-12 | - | ✅ | ❌ precedents | ❌ precedents | ❌ reason,version,precedents,disposition,missing,completed |
| EV-N-13 | - | ✅ | ❌ precedents | ❌ precedents | ❌ reason,version,precedents,disposition,missing,completed |
| EV-M-A | M | ✅ | ✅ | ✅ | ❌ reason,version,disposition,completed |
| EV-M-B1 | M | ✅ | ✅ | ✅ | ❌ reason,version,disposition,completed |

## How to read this

- The **baseline** uses the same LLM, the same documents (every clause of every policy version, every historical case record with its verified outcome) and, by default, the same embedding model as ClaimBridge. It is told to use the version in force on the service date and to cite passages. This compares complete systems: ClaimBridge additionally uses structured rules and curated memory. Larger embeddings do not eliminate retrieval, filtering, or prompt confounders.
- The **no-memory ablation** is ClaimBridge with Findings hidden: it isolates what semantic memory adds on top of versioned clauses and gates.
- Baseline precedents are past cases mapped to the Finding they support; cited losses (which support no Finding) are not counted as precedents.
- Missing evidence is not scored on claims whose correct disposition is NO_BASIS_ESCALATE: when no appeal is possible, which documents are missing is moot.
- The no-memory ablation cannot name precedents by design, so it fails the precedent check on every claim that has one; compare it on dispositions and evidence, where memory is not needed.
- M9 counts other-tenant case fields (claim ID, date, notice text) put in front of a tenant (3 per exposed case). Both systems enforce tenant access: baseline passages are filtered before prompting; ClaimBridge shares abstract findings but hides other tenants' case records (Q11). This is an access-control test, not a graph advantage.

## Threats to validity

- The data is synthetic and the ground truth comes from rules we wrote (independent Python code, not the Cypher); real denials are messier.
- 34 scored claims is a small sample; one claim is about 3 points.
- The baseline prompt was written once and not tuned per trap; a heavily engineered RAG could do better.
- LLM outputs are recorded and replayed for reproducibility; a fresh live run can differ slightly.
- Nothing here measures real-world appeal outcomes.
