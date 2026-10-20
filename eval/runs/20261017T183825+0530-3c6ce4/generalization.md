# Generalization check (pre-registered)

`generalization.yaml` · expectations locked at sha256 `c4332af7c3a18864` · run 2026-10-17T18:41:45+05:30.

**Written by the AI assistant that helped build the system, before any run, from the policy text. Separately authored, not independent. Sample is small and synthetic.**

| Kind | Met | What it shows |
|---|---:|---|
| generalization | 10/12 (1 not evaluated: provider unavailable) | Unseen letters, expectations set before any run: the only rows that speak to generalization. |
| known-defect-regression | 4/4 | Written after defects were found and fixed: regression tests, not generalization. |
| design-intent | 1/1 (1 not evaluated: provider unavailable) | Behaviour the design already aimed for; the author knew the intended answer. |

## generalization

| Case | Probes | Result | Detail |
|---|---|---|---|
| GEN-01 | last day of the 2025 policy | met | — |
| GEN-02 | first day of the 2026 policy | met | — |
| GEN-03 | filed exactly at the 2026 timely-filing limit (90 days) | met | — |
| GEN-04 | filed one day past the 2026 timely-filing limit | met | — |
| GEN-05 | enrolled exactly the required 9 months under the 2026 policy | met | — |
| GEN-06 | one month short of the 2026 waiting period | met | — |
| GEN-07 | negation (it is NOT a prior-authorization denial) | not evaluated (provider unavailable) | expected a recommendation, got status NEEDS_HUMAN (LLM unavailable; similarity alone cannot establish the denial reason) |
| GEN-08 | negation of two other reasons, duplicate claim | met | — |
| GEN-09 | paraphrase with no section and no keyword from the taxonomy | met | — |
| GEN-10 | emergency out-of-network ambulance, a service the precedent was not learned on | **MISSED** | expected a recommendation, got status NEEDS_HUMAN (the cited section implies OUT_OF_NETWORK, but the notice wording reads like WAITING_PERIOD; confirm which is right) |
| GEN-11 | the same ambulance transport, but not an emergency | **MISSED** | expected a recommendation, got status NEEDS_HUMAN (the cited section implies OUT_OF_NETWORK, but the notice wording reads like WAITING_PERIOD; confirm which is right) |
| GEN-12 | durable equipment, a precedent learned in 2025 that is still valid in 2026 | met | — |
| GEN-13 | policy text changed (12 sessions), both documents now on file | met | — |

## known-defect-regression

| Case | Probes | Result | Detail |
|---|---|---|---|
| GEN-14 | the section number says prior authorization, the wording says coding | met | — |
| GEN-15 | a section that governs a different service | met | — |
| GEN-16 | another insurer's letter | met | — |
| GEN-17 | a section that does not exist | met | — |

## design-intent

| Case | Probes | Result | Detail |
|---|---|---|---|
| GEN-18 | unrelated text, no denial | met | — |
| GEN-19 | an instruction hidden in the notice | not evaluated (provider unavailable) | expected a recommendation, got status NEEDS_HUMAN (LLM unavailable; similarity alone cannot establish the denial reason) |

Expected answers and the reasoning behind each are in the YAML file (`because`).

