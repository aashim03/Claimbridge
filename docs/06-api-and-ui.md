# 06 — API and UI

> **Status: the "as built" section is current; the sections below it are the original design (historical).**
>
> **As built.** The API is `backend/claimbridge/api.py` (FastAPI). The web app is `web/` (Next.js 16, App Router, Tailwind 4, SWR). The browser calls `/api/*` on the web origin and Next rewrites those calls to the API.
>
> ### Access model
>
> | Mode | Who | How |
> |---|---|---|
> | `AUTH_MODE=demo` (default) | everyone | A public synthetic sandbox: every visitor sees every fictional policyholder and can use operator controls. Never load private records. |
> | `AUTH_MODE=protected` | signed-in users | Operator-provisioned opaque tokens (32+ chars) in `AUTH_CREDENTIALS_JSON`, each mapped to a subject and a role (`admin` or `tenant` with a `tenant_id`). Invalid configuration fails closed (503). |
>
> - The console signs in with `POST /api/session` and keeps an **HttpOnly, SameSite=Strict, `Path=/api`** cookie (`Secure` when `COOKIE_SECURE=1`); API clients send `Authorization: Bearer`. Cookie-authenticated writes also need the console's `X-ClaimBridge-Request: 1` header.
> - **Identity comes from the credential only.** `X-Tenant-Id` is ignored for tenants (an operator may use it to view the shared memory "as" a policyholder).
> - Every API response names the signed-in subject (`X-ClaimBridge-Subject`). A tab that sees a response for a different subject than the one it is showing discards it and re-checks who it is, so a cookie changed in another tab can never leave one identity's data under another's banner.
> - A tenant can read and act on **its own claims only** (detail, graph, packet, evidence declaration); other tenants' claims answer 404. Operator-only: agent control, world reset/publish, recording outcomes, reclassifying a notice, withdrawing documents.
>
> **Shared with every signed-in user:** the abstract memory (findings, playbooks, policy versions), aggregate counts of it, worker count and LLM mode in `/api/overview`, and the aggregate evaluation report. **Private to a tenant:** its claims, notices, graphs, packets, evidence, corrections and events. Small cohorts can reveal patterns: shared findings are not a formal anonymization guarantee.
>
> ### Endpoints
> - **Session:** `GET|POST|DELETE /api/session`
> - **Overview and catalog:** `GET /api/overview`, `GET /api/catalog`
> - **Claims:** `GET /api/claims`, `POST /api/claims/new` (enter a claim by hand), `POST /api/claims/sample-notice`, `POST /api/claims/inject`, `GET /api/claims/{id}`, `/graph`, `/packet` (cited Markdown review record; never an insurer submission)
> - **Human steps:** `POST /api/claims/{id}/approve`, `/outcome {outcome, confirmed_evidence}`, `/correct {denial_reason, note}` (operator), `POST /api/claims/{id}/evidence {type, reference}` and `DELETE /api/claims/{id}/evidence/{doc_id}` (operator)
> - **Memory:** `GET /api/memory`, `GET /api/memory/findings/{id}/precedents`
> - **Policy world:** `POST /api/world {action: reset | reset_2025 | publish, version}` (operator)
> - **Agents:** `GET /api/agents`, `POST /api/agents/{id}/kill`, `POST /api/agents/start {role}` (operator). Kill and start become `Command` nodes the Supervisor executes.
> - **Evaluation:** `GET /api/eval` (the promoted run), `GET /api/eval/raw/{system}/{claim}` (operator: one claim's raw prediction, expected answer and model answer)
> - **Live updates:** `GET /api/stream`
>
> ### Live stream lifetime
> The stream emits a `tick` whenever the graph's activity changes. It re-checks the caller's credential on **every poll** and ends with an `auth` event if the credential is revoked, removed, misconfigured or older than 8 hours (`SESSION_SECONDS`). Signing out clears the cookie and the page closes its stream; the server cannot see a cookie being cleared, so revocation is what ends a stream it still holds. A tenant's stream carries only its own latest-event timestamp. Responses carry `Cache-Control: no-store, no-transform`: without `no-transform` a proxy that gzips (Next's does) buffers the stream and no tick ever arrives.
>
> ### Screens
> - **`/`:** landing page with a recorded replay of `EV-T1-01`.
> - **`/console`:** the docket (stage filter, scenario filing, **New claim**, a preview drawer per claim).
> - **`/console/claims/[id]`:** holding and support score, then tabs: **Graph replay** (animated, clickable), Plan, Precedents, Evidence (policy requirements vs suggestions learned from outcomes; declare and withdraw documents), Agent record. A claim waiting for a person shows why and, for an operator, a reclassify form.
> - **`/console/memory`, `/console/agents`, `/console/evaluation`:** memory by treatment and the policy-world controls; workers, leases and the coordination ledger; the promoted evaluation run with its identity, what each system can see, missing outputs and per-claim links to raw evidence.
>
> **Visual world:** monochrome dark product UI (Direction B), recorded in `PRODUCT.md` and `DESIGN.md`.
>
> **Two rules the UI keeps.** (1) A learned item is never worded as a policy requirement: the checklist, graph, replay and packet all say *required by the clause* or *suggested by a precedent: an observed association, not a policy requirement*. (2) A support score is shown with its observed counts and is **absent**, never "0%", when there is nothing to count.

# Original design (historical)

The text below is the first plan. It is kept for context; where it disagrees with the section above, the section above is right.

## 1. API (FastAPI)

Base path `/api`. Every case-level endpoint takes the `X-Tenant-Id` header (the demo tenant selector), except reviewer and ops endpoints, which use `X-Role: reviewer|ops` for the demo.

### Claims
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/claims` | Submit a denied claim (structured fields, notice text, evidence list). Creates it as RECEIVED. |
| `POST` | `/claims/from-scenario/{scenario_id}` | Inject a named evaluation or trap claim (demo button) |
| `GET` | `/claims?status=` | Inbox list (tenant-scoped; reviewers see all) |
| `GET` | `/claims/{id}` | Claim, current status, lease owner, attempt |
| `GET` | `/claims/{id}/timeline` | `CaseEvent` chain with agent, step, and payload |
| `GET` | `/claims/{id}/explanation` | Q10 subgraph as `{nodes, edges, highlights}` |
| `GET` | `/claims/{id}/recommendation` | Recommendation, items, citations, confidence, uncertainty |
| `POST` | `/claims/{id}/approve` | Reviewer approves (Supervisor gate) |
| `POST` | `/claims/{id}/outcome` | Reviewer records the real outcome, which triggers the Curator |

### Memory
| Method | Path | Purpose |
|---|---|---|
| `GET` | `/memory/findings?status=` | Findings with support, wins, confidence, valid versions, and stale/contradiction links |
| `GET` | `/memory/findings/{id}` | Detail, including derived resolutions (tenant-safe, Q11) |
| `GET` | `/memory/playbooks` | Playbooks with steps and win rate |
| `GET` | `/memory/learned-since?ts=` | Q12 |
| `POST` | `/policy/publish/{version_id}` | Load a new policy version and run Curator mode B (Q6) |

### Ops
| Method | Path | Purpose |
|---|---|---|
| `GET` | `/ops/workers` | Q13 heartbeat view |
| `POST` | `/ops/workers/{agent_id}/kill` | Supervisor sends `SIGKILL` / `docker kill` |
| `POST` | `/ops/workers/{role}/start` | Start a replica |
| `POST` | `/ops/reset` | Reseed the demo graph |

### Evaluation
| Method | Path | Purpose |
|---|---|---|
| `GET` | `/eval/latest` | Latest results JSON produced by `make eval` |

### Investigator and graph algorithms

| Endpoint | What it does |
|---|---|
| `GET /api/tools` | The read-only tool catalogue (name, description, JSON schema) shared with the MCP server |
| `POST /api/claims/{id}/investigate` | Run the investigator. Body optional: `{"mode": "auto" \| "graph_only"}`. `auto` lets a model choose tools if one is available, else falls back to the fixed order and says "Graph-only (LLM unavailable)". Unknown id gives 404, another tenant's claim gives 404, a malformed or oversized body gives 400, and a model-using run beyond 6 a minute per identity gives 429 (graph-only runs are never limited) |
| `GET /api/claims/{id}/investigations` | Stored traces for the claim, newest first, each with its steps and raw tool results |
| `GET /api/blast/lineages` | Clause lineages ranked by dependent memory (`algo.pageRank`) |
| `GET /api/blast/clause/{clause_id}` | What a clause change reaches, with hop distances (`algo.BFS`) |

UI: Case → **Investigate** (button, plain-language steps each expandable to the raw result, brief, outcome label, tokens, and the existing *Show the path through the graph* view for precedent steps) and Memory → **Which clauses carry the most memory**.

### Live events
`GET /api/stream` is a Server-Sent Events stream. The API polls the graph every 500 ms for new `CaseEvent`s and heartbeat changes, then pushes them. The UI never polls separately. Using polling here (instead of having workers push) keeps the "graph is the only shared state" rule intact.

## 2. UI screens

Stack: React, Vite, TypeScript, Tailwind, shadcn/ui, and `react-force-graph-2d`. There's a fixed top banner: **"Synthetic demo data. Recommendations require human approval."**

### 2.1 Inbox (home)
- Columns or swimlanes by status: RECEIVED → CLASSIFIED → RETRIEVED → VERIFIED → AWAITING_REVIEW → CURATED, plus NEEDS_HUMAN.
- Each card shows the claim ID, service, denial reason, current lease owner (an agent avatar), and the attempt count.
- Cards animate between lanes live from SSE. This is the "agents coordinating through the graph" shot.
- Buttons: **Inject scenario ▾** (T1–T7, normal), **Reset demo**.

### 2.2 Case detail
Three panes:
1. **Left: timeline.** CaseEvents with agent badges. `LEASE_EXPIRED`, `RESUMED (attempt 2)`, and `FENCED_WRITE_REJECTED` are highlighted.
2. **Center: evidence graph.** Q10 rendered as a graph:
   - green for accepted path (claim → version → clause → Finding → Resolution);
   - red for rejected precedent, with the reason code on the edge (`VERSION_DRIFT → C-2026-MRI-PREAUTH`);
   - grey for context.
   Clicking a node shows its properties and clause text.
3. **Right: recommendation.**
   - Disposition badge, confidence, and an uncertainty list.
   - Checklist items. Each has a citation chip that highlights its node in the graph.
   - A "Rejected precedents" section with plain-language reasons.
   - **Approve** and **Record outcome** (reviewer role).

### 2.3 Memory
- Findings table: status pill (ACTIVE, STALE, CONTRADICTED), support/wins, confidence bar, `VALID_IN` version chips.
- A "Learned since restart" panel (Q12).
- **Publish 2026 policy** button. Watch Findings turn STALE live (Q6).
- Playbooks with step lists and win rates.

### 2.4 Ops
- Worker grid by role: alive/dead, current claim, last heartbeat.
- **Kill** button per worker, and a **Chaos mode** toggle (random kill every N seconds, stretch).
- Lease table: claim, owner, expires in, attempt.

### 2.5 Evaluation
- Results table: ClaimBridge vs. baseline per metric (from [07](07-evaluation.md)).
- Per-trap breakdown with pass/fail, plus a link to each case.
- A failures list, shown openly.

## 3. Demo-mode helpers
- `STEP_DELAY_S=2` so state changes are watchable.
- `LLM_MODE=cached` for a deterministic recording. A "Run live" toggle shows real calls.
- A pinned order of scenario buttons that matches the video script in [08](08-demo-and-submission.md).
