# 00 — Master Plan

> **Status (updated 17 Oct 2026): planning-era document, kept for context.** Several goals below were met, several were deliberately narrowed after review, and some claims were retired. The current truth lives in the README, `10-review-changes.md`, `11-pending-work-and-completion-plan.md` and `12-completion-report.md`.
>
> Retired or reworded: "memory makes the next decision better" is shown as *a recorded outcome changes the next checklist*, not as a measured gain in decisions (the static decision metric shows no gain over the no-memory ablation); "independent rule engine" is a separately implemented rule engine by the same team, not external validation; the model, the framework (Next.js, not Vite) and the evaluation protocol changed. No scoring promise (such as 95/100) or prize claim is made anywhere.

## 1. One-line pitch

**ClaimBridge is an AI caseworker for denied health-insurance claims. It remembers verified resolutions, knows when prior knowledge no longer applies, and explains every recommendation through its evidence graph.**

It is not an insurance chatbot, and it does not approve claims automatically. A human approves every recommendation.

## 2. The problem

A denied claim involves a policy version, specific clauses, a denial reason, the evidence submitted, the evidence missing, and the history of similar cases. Generic RAG retrieves the paragraph that *looks* most similar. It cannot tell:

- whether that paragraph belongs to the policy version in force on the service date;
- whether a past winning appeal relied on a condition (emergency, in-network, physician letter) that this claim lacks;
- whether a later case contradicted that past win;
- what the case looked like when another agent stopped working on it.

## 3. What we will prove (the winning claims)

Each claim is shown live in the demo and measured in the evaluation.

| # | Claim | How it is shown |
|---|---|---|
| C1 | **Memory makes the next decision better.** A Finding learned from a verified case is reused on a later case. | Demo step 5 and the "with memory / without memory" evaluation |
| C2 | **Memory knows when it is wrong.** Version drift, unmet conditions, and contradictions block reuse of a precedent. | Traps T1–T5 and the stale-finding metric |
| C3 | **Coordination survives failure.** Kill any agent mid-case and another resumes from the graph checkpoint. | Kill button in the UI and the handoff-recovery metric |
| C4 | **Every recommendation is traceable.** Each item cites a graph path, and the system makes unsupported claims structurally impossible. | Path viewer and an unsupported-recommendation rate of 0% |
| C5 | **The graph is necessary.** Plain vector RAG on the same data fails the traps. | Baseline comparison table |
| C6 | **Memory is tenant-safe.** Raw cases stay scoped per policyholder, and shared memory is anonymized. | Trap T7 |

## 4. Scope

### In scope (MVP)
- One fictional insurer and one plan, with **3 policy versions** (2024, 2025, 2026).
- About 25 clause lineages, 9 denial reasons, 15 evidence types, and 10 service categories.
- About 50 historical claims with verified outcomes, plus about 30 evaluation claims (including 7 trap types).
- 5 agent workers plus a deterministic supervisor, coordinated only through FalkorDB.
- Episodic, semantic (Finding), procedural (Playbook), checkpoint, and tenant memory.
- Web UI: inbox, case detail with a graph path, memory browser, worker ops (kill button), and evaluation results.
- A plain RAG baseline and an evaluation harness with a results table.
- Docker Compose setup, a live deployment, a demo video, and the README.

### Out of scope (explicitly)
- Real PDF or OCR ingestion. Clauses are authored as structured data.
- Fraud detection, adjudication, legal advice, and pricing.
- Real insurer data or real people.
- Authentication beyond a tenant selector for the demo.

### Stretch (only after the MVP is frozen)
1. ~~An MCP server that exposes the graph tools~~ (done: `backend/claimbridge/mcp_server.py`, see the README).
2. A concurrency stress test (N workers per role, M claims) with a duplicate-work counter.
3. A blog post for the side prize.

## 5. Modules

| # | Module | Priority | Doc |
|---|---|---|---|
| M1 | Graph schema, seed data, and generator | P0 | [02](02-data-model.md), [03](03-dataset-and-traps.md) |
| M2 | Graph tools library (Cypher functions) | P0 | [05](05-cypher-queries.md) |
| M3 | Worker framework (poll, lease, checkpoint, commit, heartbeat) | P0 | [04](04-agents-and-memory.md) |
| M4 | The 5 agents: Intake, Retrieval, Verifier, Planner, Curator | P0 | [04](04-agents-and-memory.md) |
| M5 | Supervisor (lease reaper, approval gate, worker control) | P0 | [04](04-agents-and-memory.md) |
| M6 | Explanation engine (paths, rejections, uncertainty) | P0 | [04](04-agents-and-memory.md), [05](05-cypher-queries.md) |
| M7 | API (FastAPI, plus an SSE event stream) | P0 | [06](06-api-and-ui.md) |
| M8 | UI (React) | P0 | [06](06-api-and-ui.md) |
| M9 | Baseline RAG and evaluation harness | P0 | [07](07-evaluation.md) |
| M10 | Tenant isolation | P1 | [02](02-data-model.md), [04](04-agents-and-memory.md) |
| M11 | Deployment, README, video, and submission | P0 | [01](01-architecture.md), [08](08-demo-and-submission.md) |
| M12 | MCP server | Done (read-only catalogue over stdio) | [01](01-architecture.md) |

## 6. Timeline

Today is **Thu Oct 16**. The deadline is **Sat Oct 18, 11:59 PM IST**. We plan to **submit by 9:00 PM IST**, leaving a 3-hour buffer.

All times below are IST.

### Day 1: Thu Oct 16, "the spine works end to end"

| Block | Work | Exit criterion |
|---|---|---|
| D1-1 | Repo scaffold, Docker Compose (FalkorDB, API), Python project, environment variables | `docker compose up` and a FalkorDB browser reachable |
| D1-2 | Schema setup script: indexes and constants. Hand-author the policy versions and clauses (YAML). | `seed_knowledge.py` loads 3 versions, about 25 lineages, and the taxonomies |
| D1-3 | Case generator, ground-truth rule engine, and trap scenarios | `seed_cases.py` loads about 50 historical claims, about 30 evaluation claims, and `ground_truth.json` |
| D1-4 | Graph tools: `select_version`, `find_candidates`, `check_applicability`, `evidence_gap`, `claim_lease`, plus unit tests against the seed | All tool tests pass, and T1 is rejected by Cypher alone |
| D1-5 | Worker framework and the Intake, Retrieval, and Verifier agents (LLM stubs allowed) | One claim moves from RECEIVED to VERIFIED through 3 separate processes |

**End of Day 1 gate:** one trap case runs end to end in a terminal with correct rejections. If this isn't working, nothing else starts.

### Day 2: Fri Oct 17, "memory, handoff, and proof"

| Block | Work | Exit criterion |
|---|---|---|
| D2-1 | Planner (citation guard) and Curator (Finding/Playbook upsert, staleness, contradiction) | Full lifecycle up to AWAITING_REVIEW, and the Curator runs after approval |
| D2-2 | Supervisor: lease reaper, approval gate, worker start/kill API | Kill the Verifier mid-case, and a second Verifier finishes from the checkpoint |
| D2-3 | Real LLM calls (Claude, structured outputs) in Intake and Planner, plus embeddings for denial text | All 30 evaluation claims process without manual help |
| D2-4 | Baseline RAG and evaluation harness, first results table | `make eval` prints the table, including failures |
| D2-5 | API and SSE stream, UI skeleton (inbox, case detail) | A claim moving through the agents updates in the browser live |

**End of Day 2 gate:** C1–C5 can each be shown, even if the UI looks rough.

### Day 3: Sat Oct 18, "polish, ship, submit"

| Block | Work | Exit criterion |
|---|---|---|
| D3-1 | UI: graph path viewer, memory browser, ops panel, evaluation page | Every demo step clicks through |
| D3-2 | Tenant isolation (T7), and fix the evaluation failures worth fixing | Final evaluation numbers recorded |
| D3-3 | Deploy (one VM with Docker Compose, or FalkorDB Cloud plus a host) | Live URL works from another device |
| D3-4 | **Feature freeze at 1:00 PM IST.** README, graph model diagram, query doc, AI disclosure | README complete by 4:00 PM |
| D3-5 | Record the demo video (≤ 3–4 min), then submit | **Submitted by 9:00 PM IST** |
| D3-6 | Buffer: blog post (side prize) if time allows | |

### Team split (if more than one person)
- **Person A (graph and agents):** M1–M6.
- **Person B (UI and API):** M7, M8, deployment.
- **Person C (evaluation and data):** M1 dataset and traps, M9, the README.
- **Person D (story):** demo script, video, blog post, testing every demo step.

If you're solo, follow the timeline as written and use the cut lines below aggressively.

## 7. Cut lines (drop in this order if behind)

1. Stretch items (stress test, blog post).
2. Memory browser page. Show Findings inside case detail instead.
3. Tenant isolation UI. Keep the enforced query and show it in a test.
4. Playbook success-rate math. Use static Playbooks linked to Findings.
5. Live deployment. Fall back to local setup instructions plus the video, which the rules allow.

**Never cut:** the Verifier rejections, the kill-and-resume handoff, the citation guard, the baseline table, and the README graph model and queries.

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Synthetic data too easy, so the baseline also passes | C5 collapses | Traps are designed so the nearest text match is wrong (see [03](03-dataset-and-traps.md)) |
| LLM extraction is flaky | Wrong denial reason, wrong path | Structured outputs, taxonomy validation, a graph or embedding cross-check, and a fallback "needs human" state |
| Lease and concurrency bugs | Duplicate work, demo failure | One atomic Cypher claim query, idempotent writes keyed by `(claim, step)`, tests on Day 1 |
| Ground truth tautology (graph and rules share logic) | Judges question the evaluation | The rule engine runs over Python dataclasses independently of Cypher, and the evaluation also measures LLM extraction (see [07](07-evaluation.md)) |
| Deployment eats time | Missing live URL | Single-VM Compose, deploying on Day 3 morning, local fallback allowed |
| Over-claiming | Credibility loss | State plainly that this is synthetic and that a human approves everything |
| Not able to explain AI-written code | Rejection risk under the rules | Each person owns and reads their modules, and the README explains the design in our words |

## 9. Definition of done

- [ ] `docker compose up` gives FalkorDB, the API, 5 worker types, the supervisor, and the UI.
- [ ] Seed scripts load the knowledge layer, historical cases, evaluation cases, and ground truth deterministically.
- [ ] All 7 trap types behave as specified in [03](03-dataset-and-traps.md).
- [ ] Killing any worker mid-case results in completion by another worker with no duplicate events.
- [ ] Every recommendation line has a graph citation, and the guard blocks uncited output.
- [ ] A Finding learned from one approved case changes the outcome of a later case.
- [ ] A contradiction downgrades a Finding, and a new policy version marks dependent Findings STALE.
- [ ] The evaluation table compares ClaimBridge and the baseline, including failures.
- [ ] The README has setup steps, the graph model diagram, the Cypher queries, the track, and the AI-assistance disclosure.
- [ ] The demo video and live URL (or local instructions) are submitted.
