# 07 — Evaluation

Goal: credible, honest numbers that show **where the graph helps and where it doesn't**. Judges trust a table that includes failures.

> **Status: the "as built" section is current; sections 1 onward are the original plan (historical).**
>
> ## As built
>
> **Every run is its own directory.** `GRAPH=claimbridge_eval uv run python -m claimbridge.cli eval all --label <name>` starts a **new run** in `eval/runs/<run_id>/` (the CLI refuses to run against the demo graph, because an evaluation resets its graph). A run contains:
>
> | File | What it is |
> |---|---|
> | `run.json` | identity: git revision and whether the tree was dirty, **source digest**, **dataset digest**, prompt digests, model, mode and cache policy, start/end times with their UTC offset, and any reason the run is invalid |
> | `raw/<system>.json` | each system's raw predictions, written once. A step that already has output is never overwritten; re-running a failed step means a new run |
> | `ledger.jsonl` | one line per LLM call: system, task, claim, cache key, tokens, fresh / replayed / fake. Tokens are attributed from this ledger, never inferred from the latest cache entry |
> | `report.json`, `report.md` | the scored report |
> | `generalization.json/.md` | the pre-registered unseen-case check, when run |
>
> Digests are taken when the run starts and again each time a step saves. If the source or data changed in between, the run is marked **invalid** and `promote` refuses it. `eval promote --run <id>` copies a reviewed run to `eval/results/` (what `/api/eval` and the site serve) after archiving the previous results to `eval/archive/`.
>
> **Systems compared** (all with the same LLM; see the access table in every report):
>
> | System | Policy clauses | Abstract findings | Raw case records | What decides the answer |
> |---|---|---|---|---|
> | ClaimBridge | graph | yes (shared memory) | own tenant only | deterministic Cypher; LLM reads notices with no section |
> | No-memory ablation | graph | hidden | own tenant only | the same rules without memory |
> | Baseline RAG (small / large embeddings) | text passages | no | own tenant only, filtered before prompting | the LLM decides everything |
> | **Baseline RAG + findings** | text passages | yes, as passages with the same facts ClaimBridge stores (no verdicts) | own tenant only | the LLM decides everything |
>
> The last row is the information-parity comparison: once access is equal, what remains is deterministic rules versus LLM judgement. Do not read the plain-RAG gap as proof that FalkorDB alone causes an accuracy gain: rules, inputs, memory, prompts and compute all differ.
>
> **Scoring.** Every system is scored against the same claims; missing outputs stay in the denominator. Reported separately: *completion* (a disposition, not handed to a person), *escalated to a person* (safe abstention, not a crash), *no output* (with its cause: provider rate limit, timeout, unparseable generation, configuration, other), *decision correctness* (reason, version, disposition, missing evidence, completion; excludes precedent recall), *precedent recall* both over all expected precedents and over those **the system's permitted corpus can reach** (a tenant-filtered baseline cannot cite a precedent whose supporting cases belong to other tenants), and *fully correct*. Missing evidence is not scored when the right disposition is NO_BASIS_ESCALATE. "Items without valid citation IDs" measures only that an ID exists in the retrieved set; it does not establish that the text is true. EV-M-B2 is held out for the memory-gain experiment.
>
> **What the data is.** 34 authored synthetic claims. The expected answers come from a rule engine implemented separately from the graph queries (Python, no Cypher) by the same team: this is **not external validation**. The memory experiment shows that a *recorded synthetic outcome* changes a later checklist; it does not show the change helps a real appeal.
>
> **Coordination (M10).** Random hard kills of workers holding a lease (each replaced), counted by matching `RESUMED.previous_owner`. A killed process never wakes up, so the kills cannot show a stale worker being refused. The run therefore also executes a **deliberate paused-worker scenario**: a living worker is paused past its lease, a replacement finishes the step, then the first worker wakes and tries to write. Its tool write, checkpoint and commit are rejected and a `FENCED_WRITE_REJECTED` event is recorded.
>
> **Generalization check.** `data/scenarios/generalization.yaml` holds unseen letters with expected answers written before any run, locked by a sha256 on first use. Results are reported by `kind`: only `generalization` rows speak to generalization; `known-defect-regression` rows were written after defects were found and fixed; `design-intent` rows test behaviour the design already aimed for. The set was written by the AI assistant that helped build the system: **separately authored, not independent**. `generalization.template.yaml` is the template for a teammate's independent set.
>
> **Code:** `backend/claimbridge/evaluation/` (`harness.py`, `provenance.py`, `score.py`, `baseline.py`, `generalization.py`, `stale_probe.py`); tests in `backend/tests/test_evaluation_integrity.py`.

# Original plan (historical)

The text below is the first evaluation plan. Where it disagrees with the section above (the Claude baseline, `make eval`, the `backend/eval/` harness, "about 30 claims"), the section above is right.

## 1. Systems compared

| System | Description |
|---|---|
| **ClaimBridge** | Full pipeline: graph and memory, all 5 agents |
| **ClaimBridge without memory** (ablation) | Same agents, but the Finding/Playbook layer is hidden (Retrieval returns no Findings). This isolates the value of memory. |
| **Baseline RAG** | Same Claude model and same output schema. Retrieval is top-k vector search over chunks of **all** policy versions' clause text plus historical case summaries, stored in a separate FalkorDB graph (`baseline`) with no relationships. The prompt asks for the same JSON: reason, version, required/missing evidence, applicable precedents, disposition, and citations. |

The baseline is a fair, honest effort, not a straw man:
- It gets the service date in its prompt and is told to use the version in force.
- It gets the same denial notice and evidence list.
- Its prompt was tuned once on 5 non-trap examples before the final run.

## 2. Dataset
- About 30 evaluation claims: about 18 traps (T1–T7, 2–3 variants each) and about 12 normal.
- Ground truth comes from the independent rule engine ([03](03-dataset-and-traps.md) §7).
- The run uses `LLM_MODE=cached` after a first live run, so the published numbers are reproducible. The first live run's numbers are also reported.

## 3. Metrics

| # | Metric | Definition | Expectation |
|---|---|---|---|
| M1 | Denial reason accuracy | predicted reason = expected | Both systems high (tests LLM extraction) |
| M2 | Governing version accuracy | predicted version = expected | ClaimBridge 100%, baseline lower |
| M3 | Precedent precision / recall | accepted Findings vs. `expected_applicable_findings` | ClaimBridge much higher precision |
| M4 | Wrong-precedent rate | % of claims where a precedent that should be rejected is used | **The headline trap metric** |
| M5 | Missing-evidence F1 | predicted missing vs. expected missing | |
| M6 | Disposition accuracy | `APPEAL_VIABLE`, `NEEDS_EVIDENCE`, or `NO_BASIS` matches | |
| M7 | Unsupported-recommendation rate | % of output items without a valid citation to a real node/chunk | ClaimBridge 0% by construction. Also report how many items the guard **dropped**. |
| M8 | Stale/contradicted detection | % of T1/T4 claims where the stale or contradicted Finding is flagged | |
| M9 | Tenant leakage | Number of other-tenant case fields exposed (T7) | ClaimBridge 0 |
| M10 | Handoff recovery | Over K kill-injected runs: % completed, mean recovery time, duplicate outputs | 100%, ~TTL seconds, 0 |
| M11 | Memory gain | Disposition accuracy and confidence on the "B" claims, before vs. after the "A" outcome is recorded | Shows claim C1 |
| M12 | Cost and latency | Tokens and seconds per claim | Report honestly. The graph may be cheaper because prompts are smaller. |

## 4. Harness (`backend/eval/`)

```
make eval            # = python -m eval.run_eval --systems claimbridge,no_memory,baseline
```
1. `make reset`, which reseeds the graph deterministically.
2. For each system, inject all evaluation claims and wait until each is AWAITING_REVIEW, NEEDS_HUMAN, or times out.
3. Read predictions from the graph (ClaimBridge) or the JSON output (baseline).
4. `score.py` computes M1–M9 and M12 per claim and in aggregate, plus a per-trap breakdown.
5. `run_eval.py --chaos` runs the M10 kill-injection loop (K = 20 runs).
6. `run_eval.py --memory-gain` runs the A→B sequence for M11.
7. It writes `eval/results/latest.json` and `eval/results/latest.md`. The UI and README both use these.

## 5. Report format (in the README)

| Metric | ClaimBridge | No-memory | Baseline RAG |
|---|---:|---:|---:|
| Version accuracy | … | … | … |
| Wrong-precedent rate ↓ | … | … | … |
| Missing-evidence F1 | … | … | … |
| Disposition accuracy | … | … | … |
| Unsupported recs ↓ | … | … | … |
| Stale/contradiction flagged | … | … | … |
| Tenant leakage ↓ | … | … | … |
| Handoff recovery | … | n/a | n/a |
| Tokens/claim | … | … | … |

Then add:
- **Per-trap table:** pass/fail per system.
- **Failures:** each ClaimBridge failure with a one-line cause (for example, "Intake mis-extracted the reason from a vague notice").
- **Threats to validity:**
  - The data is synthetic.
  - Ground truth comes from rules we wrote.
  - The sample is small.
  - The baseline was tuned only lightly.
  - None of this shows real-world claim outcomes.

## 6. Avoiding the tautology criticism

A judge may ask: "you wrote the rules and the graph, so of course it matches."

Answer, which goes in the README:
1. The rule engine is separate Python code over the YAML, not the Cypher.
2. The interesting failures happen **before** the graph logic: the LLM must extract the right reason and cited clause from messy, sometimes misleading notice text. M1 and the downstream errors measure that.
3. The comparison isn't "graph vs. nothing." It's the same LLM with or without structured, versioned, self-revising memory. The no-memory ablation separates the two effects.
4. In traps, the most text-similar precedent is the wrong one. That's checked automatically, so a baseline can't pass by luck.

## 7. Day-by-day evaluation milestones
- **Day 1:** ground truth generated, and the trap self-check passes.
- **Day 2:** first full table (even if ugly), and the baseline works.
- **Day 3, morning:** fix the cheap ClaimBridge failures **without** touching ground truth, rerun, freeze the numbers, and record the cached replay.
