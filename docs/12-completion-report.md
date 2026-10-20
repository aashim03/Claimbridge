# 12 — Completion report (17 Oct 2026)

What was done against `11-pending-work-and-completion-plan.md`, with the evidence, what is still not done, and what only the team can do. Nothing here is a score, a ranking or a prize claim.

## Reference run

The evaluation the site, API and README refer to is run **`20261017T183825+0530-3c6ce4`** (promoted to `eval/results/`; the previous results were archived to `eval/archive/`). It is valid: its code, data and prompts did not change during the run, and every LLM call (98) was replayed from a recording. Two earlier runs are kept in `eval/runs/` and are **not** the published numbers: one with the information-parity baseline attempted and rate-limited, one before the scorer was corrected.

| (34 authored synthetic claims) | ClaimBridge | No-memory | Plain RAG | Plain RAG, large embeddings |
|---|---:|---:|---:|---:|
| Decision correctness (excludes precedent recall) | 100% | 100% | 76% | 76% |
| Claims fully correct | 100% | 38% | 24% | 21% |
| Wrong-precedent rate | 0% | 0% | 3% | 0% |
| Recall over precedents the system's corpus can reach | 100% | 0% | 67% | 0% |
| Completed (large baseline: 1 output missing, provider rate limit) | 100% | 100% | 100% | 97% |

Read it with the access table in the report. **Where decision correctness is equal (ClaimBridge and the no-memory ablation), memory adds precedents and a changed checklist, not a measured gain in decisions.** The comparison is of whole systems; it does not show that a database alone causes an accuracy gain. The expected answers come from a rule engine written by the same team: not external validation.

**The comparison that matters most did not run.** *RAG + findings* (the same abstract findings ClaimBridge stores, handed to the baseline) is implemented and tested but was rate-limited: the free Groq tier allows 200,000 tokens a day and the day's earlier work had used them. Until it runs, the gap to plain RAG cannot be separated into "information" and "rules". Run it with `GRAPH=claimbridge_eval python -m claimbridge.cli eval baseline_findings --run <id>` when quota allows (it will be a new run if you want a clean one).

The coordination run is in the report: random kills and a deliberate paused-worker scenario (the late tool write, checkpoint and commit are all rejected and a `FENCED_WRITE_REJECTED` event is recorded).

### Unseen-case check (separately authored, not independent)

19 letters whose expected answers were written before any run, locked by a sha256. The assistant that helped build the system wrote them, so this is **not** an independent check. Result: of the 12 *generalization* letters that could be evaluated, **10** were met; the 2 misses are a real finding: **the contradiction check sent two well-formed ambulance letters to a person** (their wording ranked lower against the reason profiles than any seeded notice did). That is the safe failure direction (a human looks) but it is a false-positive rate of 2 in 12 on unseen letters, and the threshold was set on the seeded notices. It was left as measured rather than tuned on the set that exposed it. Two letters needing a live model call were **not evaluated** (provider unavailable); the 4 known-defect regressions were met. Details: `eval/results/generalization.md`.

## What was done

| Plan item | Status | Evidence |
|---|---|---|
| 4. Evidence provenance in the replay | Done | the API exposes sources and origin; replay, checklist, graph and packet agree; `test_learned_evidence_is_never_a_policy_requirement`, `explain.test.ts`, browser-checked |
| 5. Defensible evaluation | Done except one run | run identity, digests, call ledger, never-overwritten output, invalidation, classified missing outputs, reachable recall, access table, information-parity baseline (not run), generalization set |
| 6. One consistent set of results | Done | promoted run served by `/api/eval`; the page shows run id, access table, missing outputs and per-claim links to raw evidence |
| 7. Sessions and tenant boundaries | Done | 24 HTTP cases; 27 real-browser checks against an isolated instance |
| 8. Expired workers, partial writes, policy in flight | Done | `test_stale_workers.py`, `test_policy_race.py` |
| 9. Human loop | Done | correct-and-resume, declare/withdraw documents, audit; `test_human_loop.py` |
| 10. Memory quality and wording | Done | support score with counts or absent; duplicate and contradicting outcomes tested |
| 11. Runtime and clean install | Done locally | pinned DB image, localhost ports, configurable; a clean-folder copy of the would-be-committed files was built and started side by side; browser smoke 27/27; **remote CI has not run** |
| 12. Documentation | Done | status banners and as-built sections; `13-judge-questions.md` |
| 13. Video | **Not done** | the brief is corrected and `videos/claimbridge/SHOTLIST.md` written; no MP4: FFmpeg is not installed and the workflow wants a preview approval first |
| 14. Repository and submission | **Team-owned** | see below |
| 15. Usefulness | **Team-owned** | no reviewer has used the product |

## Defects found while completing this work (all fixed)

- The live stream never delivered an event through the Next proxy (gzip buffering); the green "live" dot only showed that headers arrived, and the updates that appeared came from polling.
- An open stream outlived a revoked credential; the sign-in gate hung forever if the API was briefly unreachable.
- A cookie changed in another tab could show one identity's data under another's banner.
- A refresh timer from a previous identity threw after sign-out.
- Tenants were shown every policyholder's name in the memory page's selector.
- The audit event for a document change recorded the *new* checklist as the *previous* one.
- A system with no output was credited with an "exact match" for claims needing no evidence.
- A raw provider error exposed an account identifier in the saved output.
- The smoke script clicked a control that did not exist, so its graph check had never tested anything.

## What remains, and who owns it

1. **Verify the repository is public**: open `https://github.com/Atheeq1821/claimbridge` logged out. Not checked from this workspace.
2. **Commit, after reviewing the diff.** Nothing was committed. 451 files would be added or changed; a scan found no credentials in them or in history. `eval/runs/` keeps the earlier runs on purpose.
3. **Run CI on the submitted revision** and read its logs. The workflow exists and was updated; it has never run remotely.
4. **Render, host and link the video** (install FFmpeg, follow the shot list, approve a preview, upload, test logged out).
5. **Register and submit** through the organizer's form; describe each person's real contribution; keep the AI disclosure factual.
6. **Independent evidence:** a teammate-authored unseen set (`generalization.template.yaml`), a few people trying the fictional scenarios, and the information-parity run.
7. **Live deployment**, if wanted: the default demo mode hands every visitor operator controls, so a hosted copy needs `AUTH_MODE=protected`, HTTPS and a reverse proxy. Complete local setup is the documented fallback.

Production readiness and a prize are separate questions from this checklist.
