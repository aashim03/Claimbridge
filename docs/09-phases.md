# 09 — Phases and Status

| Phase | Name | Target | Exit gate | Status |
|---|---|---|---|---|
| **1** | Foundation and spine | Thu Oct 16 | T1 runs end to end across separate processes with correct rejection | ✅ **Done** |
| 2 | Full agent loop and memory | Fri Oct 17, morning | Plan → approve → learn → stale → contradict. Kill-and-resume through the Supervisor. | ✅ **Done** |
| 3 | Evaluation | Fri Oct 17, afternoon | `make eval` prints ClaimBridge vs. no-memory vs. baseline RAG, failures included | ✅ **Done** |
| 4 | API and UI | Fri evening to Sat morning | Every demo step can be clicked through live | ✅ **Done** |
| 5 | Harden and complete | Sat Oct 17, evening | Review findings fixed and proven by tests and a real browser; one promoted, traceable evaluation run | ✅ **Done locally** (live deployment not done: participant-owned) |
| 6 | Docs, video, submit | Sat Oct 18 | Docs synchronized; working-project video hosted; submitted by 9:00 PM IST | 🔶 Docs synchronized. **Video hosting, public-repo check and submission are the team's.** |

---

## Phase 1 — Foundation and spine ✅

### Deliverables

| # | Deliverable | Where | Result |
|---|---|---|---|
| 1.1 | Repo scaffold, Compose, Makefile, `.env.example` | `docker-compose.yml`, `Makefile`, `backend/pyproject.toml` | `docker compose up -d falkordb`; the `agents` profile runs workers in containers |
| 1.2 | Schema: 21 range indexes and 2 vector indexes | `claimbridge/schema.py` | FalkorDB 4.22 syntax verified |
| 1.3 | Knowledge YAML: 3 versions, 25 lineages (7 change), taxonomies, 10 playbooks, 15 seed Findings | `data/knowledge/` | 74 Clause nodes after expansion |
| 1.4 | Case generator and independent rule engine | `claimbridge/seed/generate.py`, `rules.py`, `notices.py` | 52 historical and 32 evaluation claims (19 traps), deterministic |
| 1.5 | Seed loader | `claimbridge/seed/load.py` | `make reset` takes about 20 seconds (about 500 nodes before any agent runs) |
| 1.6 | Graph tools: Q1, Q2, Q2a, Q2b, Q3, Q4, Q4b, Q5, Q7, Q7b, Q8 | `claimbridge/tools/` | All tested |
| 1.7 | Worker framework: lease, resume, fenced commit, heartbeat, simulated crash | `claimbridge/agents/base.py` | Crash and resume proven |
| 1.8 | Intake, Retrieval and Verifier agents (no LLM yet) | `claimbridge/agents/` | 31/32 claims correct |

### Measured results

- **Pipeline accuracy:** 31/32 evaluation claims match ground truth on version, reason, cited clause, accepted precedents, rejected precedents with codes, gates and missing evidence. This holds with agents as local processes and as Docker containers.
  - The single miss is **EV-N-11**, the deliberately misleading notice. Intake flags it `needs_llm_review`, and Phase 2's Claude extraction targets it.
- **Trap behaviour:** all 17 T1–T6 traps are handled correctly (T7 is checked at the API in Phase 4).
- **Trap self-check:** nearest-neighbour reuse gives the wrong answer on **12/17** traps.
- **Lease atomicity:** 16 parallel claimers × 40 trials always gave exactly 1 winner.
- **Crash and resume:** verifier-1 is killed (`os._exit(137)`) after its applicability pass. Its lease expires, and verifier-2 resumes at attempt 2, reuses the checkpoint, skips the applicability pass, and gives the correct result.
- **Load balancing:** with 2 intake containers, the 32 claims split 16/16 with no coordination beyond the graph.
- **Tests:** `uv run pytest` gives **21 passed**.

### Changes from the original plan
- Clauses live in a single `lineages.yaml` with per-version bodies, instead of one file per version.
- Seed Findings are authored as specs (`findings.yaml`), and the historical cases are generated to support or contradict them. `VALID_IN` is computed from clause params.
- Denial notices come from deterministic templates, not an LLM, so the dataset is exactly reproducible.
- Notice embeddings use only the core text, because the letter boilerplate dominated similarity.
- Checkpoints are one node per step via `HAS_CHECKPOINT`, with a `complete` flag, instead of a `LATEST_CHECKPOINT`/`PREVIOUS` chain.
- `REASON_MISMATCH` was added to Q4 for vector-only candidates.
- Q5 excludes playbook evidence (guidance, not requirements).
- Clause-level gates (`EXCLUSION_NO_BASIS`, `EMERGENCY_REQUIRED`, `FILED_LATE`, `WAITING_NOT_MET`) were added, so "no basis" doesn't depend on precedent.

### How to reproduce
```bash
docker compose up -d falkordb
cd backend && uv sync
uv run python -m claimbridge.cli gate        # Phase 1 gate (traps + crash/resume)
uv run python -m claimbridge.cli run all     # all 32 evaluation claims
uv run python -m claimbridge.cli show EV-T1-01
uv run python -m claimbridge.cli selfcheck
uv run pytest -q
```

---

## Phase 2 — Full agent loop and memory ✅

### Deliverables

| # | Deliverable | Where | Result |
|---|---|---|---|
| 2.1 | Provider-agnostic LLM layer with structured outputs and a recorded-response cache | `claimbridge/llm/` | `LLM_PLATFORM` = `groq` (default), `openai`, `claude` or `fake`. Recordings are kept under `data/llm_cache/`. |
| 2.2 | Intake: LLM classification for notices that don't cite a section | `agents/intake.py` | EV-N-11 (misleading notice) now correct |
| 2.3 | Planner: deterministic disposition, LLM wording, citation guard | `agents/planner.py`, `guard.py`, `tools/recommendation.py` | Every item cites graph nodes |
| 2.4 | Curator mode A: learn, strengthen, contradict, playbook usage | `agents/curator.py`, `tools/memory.py` | Memory gain shown |
| 2.5 | Curator mode B: publish a policy version, then Q6 staleness | `publish_version`, `reset --upto` | Exactly the changed-lineage Findings go stale |
| 2.6 | Supervisor: worker pool, KILL/START/SHUTDOWN commands via the graph, lease reaper, human gate | `supervisor.py` | Kill and resume shown |

### LLM choice: Groq `openai/gpt-oss-120b`
Groq's free tier was chosen for now. Only four Groq models support **strict** JSON-schema output (constrained decoding): `gpt-oss-20b`, `gpt-oss-120b`, `qwen3.8-27b` and `muse-spark-open`. `gpt-oss-120b` is the strongest production one, with 131k context and reasoning-effort control. Intake uses `low` effort and the Planner uses `medium`.

Groq is OpenAI-compatible, so it shares the OpenAI provider code with a different base URL. Claude uses the Anthropic SDK's `messages.parse`. Switching providers is a single env variable, `LLM_PLATFORM`.

### Measured results (`cli gate2`, Groq gpt-oss-120b)
- **Accuracy:** **35/35** evaluation claims match ground truth on version, reason, clause, accepted and rejected precedents, gates, missing evidence and disposition. Every recommendation item cites graph nodes.
- **Citation guard:** 33 recommendations with 148 items, all drafted by the LLM. In this run the guard had nothing to drop or add, because gpt-oss stayed inside `ALLOWED_IDS`. The guard's behaviour on bad drafts is covered by unit tests: uncited, unknown-ID and promise-of-approval items are dropped, and missing required items are added.
- **Memory gain:** EV-M-B1, processed before learning, had no precedent and confidence 0.4. After EV-M-A was approved and recorded OVERTURNED, the Curator learned `F-L-AMBULANCE-1`, valid in 2024–2026. EV-M-B2, with the same facts, then accepted that precedent at confidence 1.0, with the note "only 1 verified case".
- **Contradiction:** EV-N-04's appeal was recorded UPHELD, so F-ER-NECESSITY's confidence went from 1.0 to 0.5. It stays ACTIVE (2 wins, 1 contradiction).
- **Supervisor kill:** the Supervisor killed `verifier-2` while it held EV-T4-02. It then recorded `LEASE_EXPIRED`, `verifier-1` resumed the claim, and the result was correct.
- **Staleness:** publishing 2026 into the 2025 world turned F-MRI-REFERRAL, F-OON-ER, F-PHYSIO-NOTES and F-TIMELY-180 STALE (`STALE_BECAUSE` the new clause). The other 9 Findings carried forward.
- **Tests:** `uv run pytest` gives **30 passed**, using the deterministic `fake` LLM with no network.

### Changes from the plan
- The Planner moves claims straight to AWAITING_REVIEW. `PLANNED` is not used as a separate state.
- Disposition and confidence are deterministic. Confidence is 0.9 for a clause gate, the best accepted precedent's confidence if there is one, and 0.4 otherwise. The LLM only writes wording.
- Seed Findings are restricted to what was knowable in the loaded world (`reset --upto`).
- Control commands (KILL, START, SHUTDOWN) are nodes in the graph, so even operations go through the shared state. Workers also stop when `Control.shutdown_at` is set. This matters on Windows, where killing a parent process doesn't kill its children.
- Claude refusal fallbacks (server-side `fallbacks`) are not enabled yet, because the Claude path hasn't been run against the live API in this project.

### How to reproduce
```bash
uv run python -m claimbridge.cli gate2          # everything above
uv run python -m claimbridge.cli up             # supervised pool (foreground); `down` to stop
uv run python -m claimbridge.cli inject EV-T1-01 && uv run python -m claimbridge.cli show EV-T1-01
uv run python -m claimbridge.cli approve EV-M-A && uv run python -m claimbridge.cli outcome EV-M-A OVERTURNED
uv run python -m claimbridge.cli kill verifier-1
uv run python -m claimbridge.cli reset --upto V2025 && uv run python -m claimbridge.cli publish V2026
```

---

## Phase 3 — Evaluation ✅

### Deliverables

| # | Deliverable | Where | Status |
|---|---|---|---|
| 3.1 | Baseline RAG: same LLM, same documents, vector top-8 in its own relationship-free graph | `evaluation/baseline.py` | ✅ 34/34 |
| 3.2 | Large-embedding baseline check (`mxbai-embed-large-v1`, 1024-dim) | `eval baseline_strong` | ✅ 34/34 |
| 3.3 | No-memory ablation (`CB_NO_MEMORY=1`) | `agents/retrieval.py` | ✅ 34/34 |
| 3.4 | Scorer for M1–M9, M12 and per-trap breakdown; M10 chaos run; M11 memory gain | `evaluation/score.py`, `harness.py` | ✅ |
| 3.5 | Tenant-scoped precedent lookup (Q11) for M9 | `tools/tenancy.py` | ✅ |
| 3.6 | Report: `eval/results/latest.md` and `latest.json` | `cli eval report` | ✅ |

### Results (all 34 claims, Groq `gpt-oss-120b` for every system; full report in `eval/results/latest.md`)

| | ClaimBridge | No-memory | Baseline RAG | Baseline RAG, large embeddings |
|---|---:|---:|---:|---:|
| Claims fully correct | **100%** | 38% (no precedents, by design) | 65% | 65% |
| Disposition accuracy | **100%** | 100% | 79% | 76% |
| Wrong-precedent rate | **0%** | 0% | 15% | 15% |
| Stale or contradicted precedent avoided | **100%** | 100% (uses none) | 56% | 56% |
| …and explained with the right reason | **100%** | 0% | 0% | 0% |
| Unsupported plan items | **0%** | 0% | 5% | 9% |
| Other-tenant case fields exposed (T7) | **0** | 0 | 9 | 15 |
| T6 "no basis" traps correct | **3/3** | 3/3 | 0/3 | 0/3 |
| T4 contradicted-memory traps correct | **2/2** | 2/2 | 0/2 | 0/2 |
| LLM tokens per claim | 2,536 | 1,733 | 3,238 | 3,205 |

**What the numbers say:**
- **Embeddings aren't the bottleneck.** Moving the baseline from `bge-small` (384-dim) to `mxbai-embed-large` (1024-dim) raised precedent recall (81% → 90%) but left full correctness at 65% and the wrong-precedent rate at 15%. Disposition accuracy even dropped (79% → 76%). Its errors are reasoning errors. Its own summaries cite the governing section, yet it:
  - reused the 72-hour emergency precedent under the 48-hour 2026 clause;
  - reused the contradicted sleep-study precedent;
  - treated a 2024 exclusion and an unmet waiting period as appealable;
  - applied 180-day filing precedents to a 90-day rule.
- **What memory adds:** versioned clauses and clause gates alone get every *disposition* right on this dataset, as the no-memory ablation shows. What memory adds is the precedent: which verified win applies, how confident to be, which old one must not be reused and why (100% explained, versus 0% for every other system), and learning from new outcomes.
- **Learning from a new outcome (M11):** ClaimBridge learned `F-L-AMBULANCE-1` from EV-M-A's verified win, and EV-M-B2 reused it (confidence 0.4 → 1.0, scoped to the policy versions where the clause is unchanged). The baseline also reused EV-M-A once that case record was added to its corpus. Plain RAG can pick up new cases too; what it can't do is scope them to policy versions, weigh them against contradictions, or say when they stop applying (the T1 and T4 results).
- **Coordination under failure (M10):** 10 hard kills; 7 interrupted a step in progress and all 7 were resumed by another worker. Mean kill-to-completion was 8.3 s, including the 4 s lease timeout. 12/12 claims were completed and correct, with 0 duplicate outputs.
- **Tests:** 32 passed.

### Notes
- Groq's free tier allows 200K tokens a day for `gpt-oss-120b`, refilling at about 139 tokens a minute. A full evaluation from scratch needs about 400K tokens. Every answer is recorded under `data/llm_cache/groq/`, so `cli eval all` now replays in a few minutes with no LLM calls.
- The OpenAI-compatible provider retries once when a generation breaks off mid-JSON (`json_validate_failed`). This happened once in about 140 baseline calls.

---

## Phase 4 — API and UI ✅

### Deliverables

| # | Deliverable | Where | Result |
|---|---|---|---|
| 4.1 | FastAPI service over the tested graph tools | `backend/claimbridge/api.py` | Overview, claims, case, evidence graph, approve/outcome, memory, tenant-scoped precedents, policy world, agents kill/start, eval, and an SSE stream |
| 4.2 | Visual world chosen on the Impeccable decision page | `PRODUCT.md`, `.impeccable/surfaces/` | "The Citator": drawn citator signals (stop sign = superseded or contradicted, triangle = distinguished, diamond = followed, ring = not relevant), navy ink on paper, Source Serif 4 / Public Sans / JetBrains Mono, 1px rules |
| 4.3 | Landing page for judges | `web/components/landing.tsx` | A real citator card (EV-T6-01, where plain RAG failed), the four treatments, the five-agent pipeline, and live results |
| 4.4 | Caseworker console | `web/components/*` | Docket, case view with evidence graph, memory with policy-world controls and privacy demo, agents with kill/start, evaluation |
| 4.5 | Live updates | `console-shell.tsx`, `/api/stream` | Every page revalidates when the graph changes |
| 4.6 | Containers | `web/Dockerfile`, `docker-compose.yml` (profile `app`) | FalkorDB, seed, API, supervised agent pool, and web on :3100 |

### Verified
- **Demo flows through the API** (the same calls the buttons make):
  - file all 35 claims; all reach review with the pool running;
  - approve EV-M-A and record the outcome OVERTURNED, after which the Curator learns `F-L-AMBULANCE-1`;
  - recording an outcome before approval is refused with a clear message;
  - kill `verifier-2`: the Supervisor kills it, and starting another brings up `verifier-3`.
- **Guard bug found in the UI and fixed:** "no basis" claims showed evidence-gathering steps that contradicted their own holding. The guard now drops those steps, adds a cited escalation step, and states the gate as the summary. There's a new test, and no new LLM calls were needed; recordings replayed.
- **Build and checks:** `next build` passes; every console page prerenders as a static shell and the case page streams. `tsc` and `eslint` are clean. The Impeccable detector reports no findings.
- **Layout:** no horizontal overflow at 390px on any page.
- **Finish review:** an independent finish review (fresh context, screenshots at 1440 and 390) returned **fix** with 8 material findings, and all 8 were addressed: graph labels, citation wording, mobile docket, mobile overflow, section spacing, the stage filter, the disabled primary action, and the recorded landing deviation.
- **Backend tests:** 33 passed.

### Notes
- **Dev origin:** open the dev server at `http://localhost:3100`. Next 16 refuses dev assets to other origins unless they're listed in `allowedDevOrigins`; `127.0.0.1` is now listed.
- **Dev ports:** FalkorDB Browser uses :3000, the web app :3100, the API :8000.

---

## Phase 5 — Harden and complete ✅ (17 Oct 2026)

What the judge review and `11-pending-work-and-completion-plan.md` asked for, and the evidence for each. Detail in `12-completion-report.md`.

| Item | Result | Proof |
|---|---|---|
| Learned evidence mislabelled as a policy requirement | Checklist, graph, replay and packet all say *required by the clause* or *suggested by a precedent: an observed association*; the real failed condition (emergency or network) is named | `test_learned_evidence_is_never_a_policy_requirement`, `web/lib/explain.test.ts` |
| Stale living worker, lease expiry | Lease contract: owner + fencing token (`lease_gen`) + database-clock expiry in the same write; a lapsed lease cannot be renewed | `tests/test_stale_workers.py` (a paused living worker, a same-name restart, a stale Curator) and the deliberate scenario inside the evaluation |
| Curator partial writes | Interrupted after every statement, a replacement converges to the reference state | `test_curator_interrupted_after_every_statement_converges_to_one_correct_result` |
| Policy change in flight | A claim is pinned at Intake; publishing 2026 at four points never changes its outputs | `tests/test_policy_race.py` |
| Sessions and tenant boundaries | 24 HTTP cases and a 27-check real-browser matrix. Found and fixed: the live stream was gzip-buffered by the proxy (no tick ever arrived), an open stream outlived revocation, the gate hung on an unreachable API, and a cookie changed in another tab could show one identity's data under another's banner | `tests/test_access_matrix.py`, `scripts/access-matrix.mjs` |
| Evaluation provenance | One directory per run; code, data and prompt digests; per-call ledger; raw output never overwritten; a changed source invalidates a run and blocks promotion | `tests/test_evaluation_integrity.py` |
| Evaluation fairness | Access table; reachable-recall; abstention, missing output and completion reported apart; the information-parity baseline implemented | see the run notes for whether it ran |
| Generalization | 19 pre-registered unseen letters in three kinds; locked by sha256 | `data/scenarios/generalization.yaml` |
| Intake robustness | Escalates on a foreign insurer, a contradicting section, a section for another service | `tests/test_intake_consistency.py` |
| Human loop | Correct-and-resume; declare and withdraw documents; audit trail; a claim already planned is re-planned | `tests/test_human_loop.py` |
| Memory wording | Support score shown with counts or absent; "good law" retired; outcome form asks what the reviewer *observed* | `tests/test_memory_cases.py` |
| Runtime | Pinned FalkorDB image; localhost-only configurable ports; run directories and video out of the Docker context; the browser smoke script now clicks the controls it reports on | `scripts/browser-smoke.mjs` |

Tests: **118 backend** (real FalkorDB, fake LLM) and 8 frontend unit tests.
