# ClaimBridge evaluation results

Run `20261017T183219+0530-7dee90` (final) · started 2026-10-17T18:32:19+05:30 · report generated 2026-10-17T18:37:10+05:30.

- **Code:** revision `ca01047a6a04` (uncommitted changes present); backend source digest `804f21182ab99b69`; dataset digest `3dbeaec8d0bce312`.
- **Model:** `groq/openai/gpt-oss-120b`, mode `cached` (replay a recorded provider response if present, else call and record). LLM calls in this run: 2 fresh from the provider, 98 replayed from recorded responses, 0 from the fake test model. Replayed calls reuse the tokens recorded when they were first made.
- **Data:** 34 authored synthetic claims (see docs/03); ground truth from a rule engine implemented separately from the graph queries (Python, no Cypher) by the same team; it is not external validation.
- **Scope:** Authored synthetic fixtures; whole-system comparison, not database-only causality. Missing outputs count as failures and are listed with their cause.

## Run notes

- Baseline RAG + findings (the information-parity comparison) was NOT run: the free Groq tier's daily token limit (200,000) was exhausted earlier the same day, and every attempt returned a provider rate-limit error. The code is in place; it is the comparison that most needs running.
- The large-embedding baseline may show missing outputs for the same reason; each is listed with its cause.
- **Baseline RAG + findings** was not run in this run, so it is absent from every table below.

> **Incomplete outputs.** Missing claims stay in every system's denominator and count as failures: Baseline RAG (large embeddings): EV-M-B1. Causes are listed under *Missing outputs*.

Systems: **ClaimBridge**; **No-memory ablation**; **Baseline RAG** (`BAAI/bge-small-en-v1.5`, top-8); **Baseline RAG (large embeddings)** (`mixedbread-ai/mxbai-embed-large-v1`, top-8).

## What each system can see

| System | Policy clauses | Abstract findings | Raw case records | What decides the answer |
|---|---|---|---|---|
| ClaimBridge | all versions, as graph nodes with lineage and content fingerprints | yes: the shared memory (statement, versions valid in, status, evidence needs, conditions) | own tenant only; other tenants' cases are redacted | deterministic Cypher for version, applicability, gates and evidence; the LLM only reads notices that cite no section |
| No-memory ablation | same as ClaimBridge | hidden (ablation) | own tenant only | same deterministic rules without semantic memory |
| Baseline RAG | all versions, as text passages | no | own tenant only (filtered before prompting) | the LLM makes every decision from the retrieved passages |
| Baseline RAG (large embeddings) | all versions, as text passages | no | own tenant only (filtered before prompting) | the LLM makes every decision; larger embedding model |

Read the columns before the numbers. A system that cannot see a precedent cannot cite it, and a system whose answers come from an LLM differs from one whose answers come from rules for reasons other than how the data is stored. Only the **Baseline RAG + findings** row isolates what is left once information access is equal.

## Headline metrics

| Metric | ClaimBridge | No-memory ablation | Baseline RAG | Baseline RAG (large embeddings) |
|---|---:|---:|---:|---:|
| Completion rate (a disposition, not handed to a person) ? | 100% | 100% | 100% | 97% |
| Escalated to a person (safe abstention, counted separately) n | 0 | 0 | 0 | 0 |
| No output (error or missing; cause listed below) n | 0 | 0 | 0 | 1 |
| Decision correctness (excludes precedent recall) ? | 100% | 100% | 76% | 76% |
| Denial reason accuracy ↑ | 100% | 100% | 100% | 97% |
| Governing policy version accuracy ↑ | 100% | 100% | 100% | 97% |
| Precedent precision ↑ | 100% | n/a | 67% | n/a |
| Precedent recall (all expected precedents) ↑ | 100% | 0% | 10% | 0% |
| Precedent recall (only precedents the system's permitted corpus can reach) ↑ | 100% | 0% | 67% | 0% |
| Wrong-precedent rate (claims reusing a precedent that does not apply) ↓ | 0% | 0% | 3% | 0% |
| Missing-evidence F1 ↑ | 100% | 100% | 88% | 94% |
| Missing-evidence exact match ↑ | 100% | 100% | 86% | 89% |
| Disposition accuracy ↑ | 100% | 100% | 79% | 79% |
| Items without valid citation IDs (not semantic entailment) ↓ | 0% | 0% | 6% | 3% |
| Stale or contradicted precedent avoided ↑ | 100% | 100% | 100% | 100% |
| …and rejected with the right reason ↑ | 100% | 0% | 0% | 0% |
| Other-tenant case fields exposed (T7) ↓ | 0 | 0 | 0 | 0 |
| LLM tokens per claim ↓ | 332 | 332 | 2892 | 2761 |
| Claims fully correct (reason, version, precedents, evidence, disposition) ↑ | 100% | 38% | 24% | 21% |

Decision correctness (reason, version, disposition, missing evidence, completion) and precedent recall are reported apart on purpose: the no-memory ablation cannot name precedents by design, so its *fully correct* score is lower while its decisions are equal. **Where decision correctness is equal, memory adds precedents and a changed checklist, not a measured gain in decisions.**

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
| M memory scenario | 2/2 | 2/2 | 2/2 | 1/2 |
| Normal cases | 13/13 | 0/13 | 1/13 | 0/13 |

## Why wrong precedents were used

Each time a system relied on a precedent that does not apply, the ground truth says why it does not:

| System | VERSION_DRIFT | LINEAGE_MISMATCH | CONTRADICTED | CONDITION_UNMET | NOT_APPLICABLE |
|---|---:|---:|---:|---:|---:|
| ClaimBridge | 0 | 0 | 0 | 0 | 0 |
| No-memory ablation | 0 | 0 | 0 | 0 | 0 |
| Baseline RAG | 0 | 1 | 0 | 0 | 0 |
| Baseline RAG (large embeddings) | 0 | 0 | 0 | 0 | 0 |

## Missing outputs and escalations

**Baseline RAG (large embeddings)**
- `EV-M-B1`: no output. Cause: **provider_rate_limit** — GroqProvider 429: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_…` service tier `on_demand` o
- `EV-M-B2`: a later step failed. Cause: **provider_rate_limit**

A provider limit or timeout says nothing about a system's reasoning; it is reported as a missing output because the benchmark needs an answer, and a re-run is a new run.

## Memory gain (M11)

Claim EV-M-A (ambulance, emergency) is approved and its **recorded synthetic outcome** is OVERTURNED. EV-M-B1 was processed before that, EV-M-B2 (same facts) after. This shows that a recorded association changes a later checklist; it does not show the change helps a real appeal.

- **ClaimBridge**: before: missing evidence none, APPEAL_VIABLE; after: missing evidence ['ITEMIZED_BILL'], APPEAL_NEEDS_EVIDENCE. Support score none yet to 0.667 (not a probability) (Curator: learned ['F-L-AMBULANCE-3fc5cd595b568ee3']).
- **No-memory ablation**: before: missing evidence none, APPEAL_VIABLE; after: missing evidence none, APPEAL_VIABLE. Support score none yet to none yet (not a probability) (Curator: learned ['F-L-AMBULANCE-3fc5cd595b568ee3']).
- **Baseline RAG**: before: precedent cases none; after adding EV-M-A to the corpus: retrieved it: False, precedent cases none.

## Coordination under failure (M10)

12 claims, worker pool `intake=2,retrieval=2,verifier=2,planner=2,curator=1`, 10 random hard kills of workers holding a lease (a replacement started each time), lease TTL 4 s.

| Measure | Result |
|---|---:|
| Claims completed | 12/12 |
| Claims correct | 12/12 |
| Kills that interrupted a step in progress | 7 of 10 |
| …each resumed by another worker | 7 |
| Mean time from kill to the interrupted step completing | 7.44 s (includes the 4 s lease timeout) |
| Duplicate step outputs | 0 |
| Late writes rejected during the random kills | 0 |

A killed process never wakes up, so the random kills alone cannot show a stale worker being refused; a zero in the last row is expected and proves nothing about fencing.

**Deliberate paused-worker scenario.** A living worker is paused past its lease, a replacement completes the step, then the first worker wakes and tries to write:

| Measure | Result |
|---|---:|
| Stale worker's tool write | rejected |
| Stale worker's checkpoint | rejected |
| Stale worker's commit | none: rejected |
| `FENCED_WRITE_REJECTED` audit events recorded | 1 |
| Stale checkpoint survived | no |

## ClaimBridge failures

None in this run.


## Per-claim results

Each claim's raw prediction is in `raw/<system>.json` in this run, and at `/api/eval/raw/<system>/<claim>`.

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
| EV-N-11 | - | ✅ | ❌ precedents | ❌ disposition,missing | ❌ precedents,disposition,missing |
| EV-N-12 | - | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-N-13 | - | ✅ | ❌ precedents | ❌ precedents | ❌ precedents |
| EV-M-A | M | ✅ | ✅ | ✅ | ✅ |
| EV-M-B1 | M | ✅ | ✅ | ✅ | ❌ reason,version,disposition,completed |

## How to read this

- This compares **whole systems**. ClaimBridge combines structured rules, a graph and curated memory; the baselines send retrieved text to an LLM. Unless rules, inputs, memory, prompts and compute are controlled, a gap cannot be attributed to the database alone. The *Baseline RAG + findings* row equalises information access; the rest of the gap is deterministic rules versus LLM judgement.
- The **baseline** uses the same LLM, the same documents (every clause of every policy version) and, by default, the same embedding model as ClaimBridge. It is told to use the version in force on the service date and to cite passages. Larger embeddings do not remove retrieval, filtering or prompt confounders.
- Because the baselines see only their own tenant's case records, some expected precedents cannot be reached by them at all. *Precedent recall (reachable)* excludes those; compare it, not the plain recall, when judging retrieval.
- The **no-memory ablation** is ClaimBridge with Findings hidden: it isolates what semantic memory adds on top of versioned clauses and gates. It cannot name precedents by design.
- Baseline precedents are past cases mapped to the Finding they support; cited losses (which support no Finding) are not counted as precedents.
- Missing evidence is not scored on claims whose correct disposition is NO_BASIS_ESCALATE: when no appeal is possible, which documents are missing is moot.
- M9 counts other-tenant case fields (claim ID, date, notice text) put in front of a tenant (3 per exposed case). Both systems enforce tenant access, so this is an access-control test, not a graph advantage.

## Threats to validity

- The data is synthetic and the expected answers come from rules we wrote; real denials are messier. The rule engine is separate code from the Cypher, not an external check.
- 34 scored claims is a small sample; one claim is about 3 points.
- The baseline prompts were written once and not tuned per trap; a heavily engineered RAG could do better.
- LLM outputs are recorded and replayed for reproducibility; a fresh live run can differ.
- Nothing here measures real-world appeal outcomes or whether a changed checklist is useful.
