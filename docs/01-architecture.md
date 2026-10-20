# 01 — Architecture

> **Status (updated 17 Oct 2026): planning-era architecture with as-built deltas.**
>
> - **Models:** Groq `openai/gpt-oss-120b` by default (switchable with `LLM_PLATFORM=groq|openai|claude`; `fake` for tests). Not Claude Haiku/Sonnet. The LLM only classifies a notice that cites no section; published plans are graph templates and reviewed playbook steps.
> - **Web:** Next.js 16 + Tailwind 4 + SWR (not Vite/shadcn/react-force-graph). The evidence graph is a custom SVG replay.
> - **Processes:** Docker Compose profile `app` = `falkordb`, `seed` (resets the demo graph on start), `agents` (the Supervisor and its worker pool), `api` (FastAPI, bound to 127.0.0.1), `web` (port 3100). FalkorDB's ports are bound to localhost only.
> - **Access:** `AUTH_MODE=demo` (public sandbox) or `protected` (server-issued tokens, tenant-scoped); see `06-api-and-ui.md`.
> - **Coordination:** database-clock leases, a monotonic fencing token (`lease_gen`) and expiry checked in the same query that writes; see `04-agents-and-memory.md` and `backend/claimbridge/tools/__init__.py`.
> - **Evaluation:** one directory per run with provenance; see `07-evaluation.md`.

## 1. Big picture

```
                         ┌──────────────────────────────────────────┐
                         │                FalkorDB                  │
                         │   graph: claimbridge                     │
                         │   knowledge │ cases │ memory │ coord.    │
                         └───▲─────▲─────▲─────▲─────▲─────▲────────┘
                             │     │     │     │     │     │   Cypher only
   ┌──────────┐  ┌───────────┴┐ ┌──┴─────┴┐ ┌─┴─────┴┐ ┌──┴──────┐ ┌──────────┐
   │  Intake  │  │ Retrieval  │ │Verifier │ │Planner │ │ Curator │ │Supervisor│
   │ worker×N │  │ worker×N   │ │worker×N │ │worker×N│ │worker×1 │ │ (no LLM) │
   └────┬─────┘  └────────────┘ └─────────┘ └───┬────┘ └────┬────┘ └────┬─────┘
        │ Claude (extract)                       │ Claude    │ Claude    │ start/kill
        ▼                                        ▼ (wording) ▼ (wording) ▼ workers
   ┌─────────────────────────────────────────────────────────────────────────┐
   │ FastAPI: REST + SSE (reads the graph, writes submissions and approvals) │
   └──────────────────────────────────▲──────────────────────────────────────┘
                                      │
                               ┌──────┴──────┐        ┌───────────────────┐
                               │  React UI   │        │ Eval harness + RAG│
                               └─────────────┘        │ baseline (offline)│
                                                      └───────────────────┘
```

**Key principle:** agents never talk to each other directly. They read and write the graph, and the graph is the blackboard. There is no shared session, queue, or cache, so any process can die at any moment without losing state.

## 2. Tech stack

| Concern | Choice | Why |
|---|---|---|
| Graph DB | **FalkorDB** (Docker locally, FalkorDB Cloud optional) | Required, fast Cypher, and native vector index |
| Backend language | Python 3.12 | Official `falkordb` client and the Anthropic SDK |
| Graph client | `falkordb` (Python) | Official |
| API | FastAPI + Uvicorn, SSE via `sse-starlette` | Simple, async, typed |
| Validation | Pydantic v2 | Structured LLM output and API models |
| LLM | Claude (`claude-sonnet-5-5` for Intake and Planner, `claude-haiku-5-5` for cheap classification and wording) | Structured outputs and quality |
| Embeddings | Local `fastembed` (`BAAI/bge-small-en-v1.5`, 384-dim) | No extra API key, deterministic, works offline |
| Baseline vector store | FalkorDB vector index on `Chunk` nodes in a **separate graph** (`baseline`) that has no relationships | Same infrastructure, with no graph help for the baseline |
| Frontend | React + Vite + TypeScript, Tailwind, shadcn/ui | Fast to build |
| Graph viewer | `react-force-graph-2d` (or Cytoscape.js) | Path highlighting |
| Process model | One container per worker role, scaled with `docker compose --scale` | A real kill shows real handoff |
| Tests | pytest | Tool and trap tests |
| Tasks | `Makefile` (or `justfile`) | `make seed`, `make eval`, `make demo` |

> The baseline uses its own FalkorDB graph so that "same database, no relationships" is a fair comparison: only the graph reasoning differs.

## 3. Repository layout

```
claimbridge/
├─ docker-compose.yml
├─ Makefile
├─ .env.example                 # ANTHROPIC_API_KEY, FALKORDB_HOST/PORT, LEASE_TTL_S ...
├─ README.md                    # submission README (setup, graph model, queries, AI disclosure)
├─ docs/                        # these planning docs
├─ data/
│  ├─ knowledge/
│  │  ├─ plan.yaml              # insurer, plan, versions
│  │  ├─ clauses_2024.yaml
│  │  ├─ clauses_2025.yaml
│  │  ├─ clauses_2026.yaml
│  │  ├─ taxonomy.yaml          # denial reasons, evidence types, service categories
│  │  └─ playbooks.yaml
│  ├─ scenarios/traps.yaml      # named trap cases with fixed IDs
│  └─ generated/                # cases.jsonl, ground_truth.json (committed for reproducibility)
├─ backend/
│  ├─ claimbridge/
│  │  ├─ config.py
│  │  ├─ db.py                  # FalkorDB connection, graph handles
│  │  ├─ schema.py              # indexes, vector index, constants
│  │  ├─ tools/                 # graph tools = documented Cypher (M2)
│  │  │  ├─ versions.py
│  │  │  ├─ retrieval.py
│  │  │  ├─ applicability.py
│  │  │  ├─ evidence.py
│  │  │  ├─ memory.py           # findings, playbooks, staleness, contradiction
│  │  │  ├─ coordination.py     # leases, checkpoints, events
│  │  │  └─ explain.py          # path extraction
│  │  ├─ llm/
│  │  │  ├─ client.py           # Claude wrapper + JSON-schema outputs + retries
│  │  │  ├─ prompts/            # one file per agent
│  │  │  └─ embed.py
│  │  ├─ agents/
│  │  │  ├─ base.py             # Worker skeleton (poll/lease/resume/work/commit/heartbeat)
│  │  │  ├─ intake.py
│  │  │  ├─ retrieval.py
│  │  │  ├─ verifier.py
│  │  │  ├─ planner.py
│  │  │  └─ curator.py
│  │  ├─ supervisor.py
│  │  ├─ guard.py               # citation guard
│  │  └─ api/                   # FastAPI routers
│  ├─ seed/
│  │  ├─ seed_knowledge.py
│  │  ├─ generate_cases.py
│  │  ├─ rules.py               # independent ground-truth rule engine
│  │  └─ seed_cases.py
│  ├─ eval/
│  │  ├─ baseline_rag.py
│  │  ├─ run_eval.py
│  │  └─ score.py
│  └─ tests/
└─ frontend/
   └─ src/ (pages: Inbox, CaseDetail, Memory, Ops, Eval)
```

## 4. Process model (Docker Compose)

| Service | Image | Replicas | Notes |
|---|---|---|---|
| `falkordb` | `falkordb/falkordb` | 1 | Ports 6379 (DB) and 3000 (browser). Persistent volume. |
| `api` | backend | 1 | FastAPI on 8000 |
| `intake` | backend, `python -m claimbridge.agents.intake` | 2 | |
| `retrieval` | backend | 1 | |
| `verifier` | backend | 2 | Two replicas, so killing one shows handoff |
| `planner` | backend | 1 | |
| `curator` | backend | 1 | |
| `supervisor` | backend | 1 | Has the Docker socket (or a PID registry) for start/kill |
| `ui` | frontend (nginx) | 1 | Port 80 |

**How the kill button works:** the API asks the supervisor to kill a worker. In Compose the supervisor runs `docker kill <container>`. Locally without Docker it sends `SIGKILL` to the worker's PID from a registry. Both paths are real crashes: no graceful shutdown, and the lease is left dangling until it expires.

Every worker writes a `WorkerHeartbeat` (see [02](02-data-model.md)), so the UI's ops page shows which workers are alive straight from the graph.

## 5. Configuration

| Key | Default | Meaning |
|---|---|---|
| `LEASE_TTL_S` | 20 | Lease length. Kept short so the demo handoff is visible. |
| `HEARTBEAT_S` | 5 | How often a worker extends its lease and heartbeat |
| `POLL_S` | 1 | Idle poll interval |
| `STEP_DELAY_S` | 0 (demo: 2) | Artificial delay so the audience can watch states change |
| `LLM_MODE` | `live` / `cached` | `cached` replays recorded LLM outputs for a deterministic demo and evaluation |
| `GRAPH` / `BASELINE_GRAPH` | `claimbridge` / `baseline` | Graph names |

`LLM_MODE=cached` is a demo-safety feature: if the API rate-limits during recording, the demo still runs. Say so honestly in the README.

## 6. Deployment

**Recommended:** one small Linux VM (2 vCPU / 4 GB) running the same `docker-compose.yml` behind Caddy for HTTPS. One artifact, no platform-specific glue, and the kill demo works the same way as locally.

**Alternative:** FalkorDB Cloud for the database, with the API and workers on Railway/Render/Fly, and the UI on Vercel. More moving parts, and the kill button needs a platform API, so use it only if a VM is not available.

**Public demo safety:**
- Rate-limit claim submission.
- Use a cap on LLM spend (default to `cached` mode for public visitors and `live` for the "Run live" button).
- Provide a "Reset demo" endpoint that reseeds the graph.

## 7. MCP server and investigator (implemented)

`backend/claimbridge/catalogue.py` holds one registry of eight read-only tools (`get_claim`, `select_version`, `find_candidates`, `check_applicability`, `evidence_gap`, `explain_path`, `what_rests_on_clause`, `policy_blast_radius`). `mcp_server.py` serves it over MCP stdio as one fixed tenant against its own graph, and `investigator.py` lets an LLM choose from the same registry in-process. What an MCP client can do and what the investigator can do are therefore identical, and neither can write a decision. Tenant scope comes from the server start-up configuration or the API identity, never from a tool argument.

## 8. Security and privacy notes

- All people, claims, and the insurer are fictional. There is a banner in the UI and a note in the README.
- Tenant scoping is enforced in the tool layer: every case-level query takes `tenant_id`. Findings and Playbooks contain no tenant link (see [02](02-data-model.md) §6).
- No secrets in the repo, only `.env.example`.
