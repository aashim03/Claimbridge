# Track assessment: Track 02 (primary) and Track 01

Written for the team on 2026-10-18, before submission. It is candid on purpose; it is not marketing copy. Everything marked "met" has a file, a test or a command you can run. Nothing here changes an evaluation number or claims an accuracy win.

## 1. What ClaimBridge is

ClaimBridge is a review workspace for denied health-insurance claims, built on fictional data. Five fixed worker roles (intake, retrieval, verifier, planner, curator) hand each claim to one another only through FalkorDB: the claim's status says which role may work on it, a lease says which worker currently does, and every write is fenced against that lease. The graph also holds versioned memory: precedents ("Findings") that are valid only in the policy versions whose clause text did not change, so a 2025 win is refused for a 2026 claim and the reviewer can see the exact broken edge. A person approves every recommendation. New in this submission: one read-only tool catalogue, served over MCP and used by an investigator agent that chooses tools to explain a claim, plus a graph algorithm (`algo.BFS` and `algo.pageRank`) that shows what a clause change would reach.

## 2. Track 02: Agent Memory and Coordination (primary)

| Focus item | Status | Evidence | Remaining gap |
|---|---|---|---|
| Episodic memory | **met** | Ordered `CaseEvent` chain per claim plus `Checkpoint` nodes, written in the same query as the status change (`tools/coordination.py`); shown in Case → Agent record; `tests/test_coordination.py::test_events_chain_and_checkpoint`. Investigator runs are stored too (`(Investigation)-[:CALLED]->(ToolCall)-[:RETURNED]->…`, `tests/test_investigator.py::test_a_sensible_sequence_passes_the_guard_and_is_remembered`). | It records what agents did, not dialogue. No retention or summarising policy. |
| Semantic memory | **met** | Findings keyed by (reason, clause lineage, evidence, conditions) with `VALID_IN`, `STALE_BECAUSE`, `CONTRADICTED_BY` (`tools/memory.py`); `tests/test_phase2.py::test_memory_gain_learns_and_reuses`, `tests/test_hardening.py::test_text_only_policy_change_invalidates_memory`, `tests/test_memory_cases.py`. | Built from a small synthetic outcome set. The support score is a smoothed count (0.667 after one win), not a calibrated probability. The evaluation shows equal decision correctness with and without memory, so memory adds precedents and a changed checklist, not a measured gain in decisions. |
| Procedural memory | **partly** | Playbooks with `uses`/`wins` counted from verified outcomes (`record_playbook_use`); Memory → Playbooks. | The steps are authored in YAML. Only the counters learn; the system does not invent a new playbook. |
| Persistent conversation history | **partly** | There is no chat. What persists is the audit trail (`CaseEvent`) and the stored investigator traces: `GET /api/claims/{id}/investigations`. | No multi-turn user conversation memory. Say "persistent agent-run history", not "conversation history". |
| Shared state and handoffs between agents | **met** | Status as the handoff, `claim_lease`, fenced `commit`, heartbeats and a lease reaper. `tests/test_coordination.py` (lease race, fencing), `tests/test_stale_workers.py` (a living stale worker cannot write; a Curator interrupted after every statement converges), `tests/test_pipeline.py::test_verifier_crash_is_resumed_from_checkpoint`; Agents page "kill a worker". | The roles are fixed workflow steps; they do not negotiate. One FalkorDB, one host. |
| High-concurrency reads/writes | **partly** | `test_lease_race_has_exactly_one_winner`: 16 threads, 10 trials, exactly one winner each time; the chaos step of the evaluation. FalkorDB runs writes to one graph one at a time, which is what makes the lease atomic. | No load or throughput benchmark. Concurrency is shown for correctness at small scale, not performance. |
| Separate memory per user or tenant | **met, with a caveat** | Case-level reads anchor on the tenant (`tools/tenancy.py`); `tests/test_access_matrix.py` and `tests/test_hardening.py` run over real HTTP; the catalogue, the MCP server (one fixed tenant) and the investigator are tenant-scoped (`tests/test_catalogue_mcp.py::test_tenant_cannot_read_another_tenants_claim`, `tests/test_investigator.py::test_another_tenant_cannot_investigate_the_claim`). | Findings are deliberately shared across tenants and anonymous; this is not a formal anonymisation guarantee. Isolation is enforced in application queries on a `tenant_id` property in one graph, not by the database. |

## 3. Track 01: Agents That Act on Connected Data (second track)

| Focus item | Status | Evidence | Remaining gap |
|---|---|---|---|
| Multi-hop reasoning | **met** | The path claim → policy version → clause lineage (`SUPERSEDES`) → precedent → verdict, walked hop by hop with the first broken edge marked (`tools/trace.py`; `tests/test_trace.py`; Case → *Show the path through the graph*). The blast radius walks up to six hops from a clause (`tools/blast.py`, hand-computed in `tests/test_blast.py`); on the demo data the farthest real reach is 3 to 4 hops. | The multi-hop reasoning is deterministic Cypher. The model does not plan hops, and the graph is small. |
| Graph queries and algorithms as agent tools | **partly** | `catalogue.py`: 8 read-only tools; `policy_blast_radius` runs `algo.BFS` and `algo.pageRank` (present in the pinned FalkorDB 4.22.1, checked with `CALL dbms.procedures()`). The investigator chooses among them (`investigator.py`), tested with a scripted model (`tests/test_investigator.py`, 19 tests). | **Real-model runs are recorded** for EV-T1-01, EV-M-B2 and EV-T3-01 (`data/llm_cache/groq/investigator-*.json`; 5 rounds and about 7,900 tokens each). Two of five attempts failed their last round (a provider structured-output error) and fell back to a labelled template brief before a clean run was recorded. The UI replays the recordings, so no key is needed to see them. The algorithms give hop distances and a rank; they do not change which claims are affected (the Cypher in `trace.clause_impact` finds the same set), and on this synthetic graph the ranking mostly follows the counts. `algo.BFS` follows edges in one direction, so the dependency edges are copied into a throwaway scratch graph first. |
| Tool selection through MCP | **met** | `mcp_server.py` serves the catalogue over stdio as one fixed tenant, read-only. `tests/test_catalogue_mcp.py` (11 tests): tool listing with schemas, every tool on a seeded claim, unknown id, another tenant's claim, bad arguments, no write tool, graph unchanged, an unreachable database, and the real `cli mcp` command as a subprocess. Also run through `docker compose run --rm -T --quiet-build mcp` and the MCP Inspector ([screenshot](screenshots/mcp-inspector-tools.png)). | The client's own model does the choosing, and a run with Claude Desktop was recorded for the demo video: it called `get_claim`, `find_candidates`, `check_applicability` and `explain_path` and explained the `VERSION_DRIFT` refusal. The investigator calls the same registry in process, not over MCP. |
| Actions based on what the graph shows | **partly** | The five workers act on graph state (status, leases, verdicts) and every decision waits at the human gate (`tests/test_coordination.py`, `tests/test_human_loop.py`). The investigator reads, explains and compares; its only write is its own trace. | **Deliberately partial.** The investigator has no action tool. The plan asked for one gated `request_human_review`; it was **not built**: moving a claim to `NEEDS_HUMAN` would pull it out of the normal review queue and the only way back is a reclassification, so on a correct case such as EV-T1-01 it would break the demo for no gain. A person decides; the agent informs. |
| Explainable results | **met** | Citation guard on advice (`guard.py`), edge-by-edge paths, and an investigation brief whose every id and number must appear in a tool result of the same run or the brief is replaced by a template (`investigator.check_brief`; the injection and invention cases are in `tests/test_investigator.py`). Each step in the UI expands to its raw tool result. | The guard checks identifiers, numbers and directive wording, not that every sentence is entailed by the results. |

## 4. The hackathon's own rule checks

- **FalkorDB is essential.** Remove it and nothing runs: the policy version for a service date, applicability, the evidence gap, memory validity, lease acquisition and fencing, and the audit chain are all queries against it, and the new blast-radius tool is a FalkorDB algorithm. A relational schema could store the same rows and NetworkX could run `BFS` on an export, so the honest claim is not "only a graph can do this". The claim is that one live store coordinates the agents, holds validity as traversable edges, runs the algorithm where the data is and serves it over MCP. The removal test is about architecture, not about a speed or accuracy advantage, and none is claimed.
- **Graph data model in the README:** yes (two mermaid diagrams; full model in `docs/02-data-model.md`).
- **Cypher queries and algorithms listed:** yes, `docs/05-cypher-queries.md` (Q1 to Q17, including `algo.BFS` and `algo.pageRank`), linked from the README.
- **Synthetic data:** yes; every insurer, policy, person and outcome is fictional.
- **Participants can explain it:** owner-only. `docs/13-judge-questions.md` has prepared answers; every team member should be able to walk the lease, the fence and the version check without notes.
- **Demo video and local setup:** local setup is `docker compose --profile app up -d --build` and works from a fresh copy with no `.env`. **There is no live deployment.** Say so plainly. The demo video is on YouTube and linked at the top of the README.
- **Public repo:** the remote is `github.com/Atheeq1821/claimbridge`; it is public (checked through the GitHub API on 2026-10-18).
- **First commit versus the 15 October start:** the first commit is `91de48a`, 2026-10-17 00:45:35 +05:30, after 2026-10-15 00:01 IST. There are only five commits, and the first alone adds 116 files and about 11,000 lines, so be ready to explain how it was produced.
- **Tracks named at submission:** name both (Track 02 primary, Track 01).
- **AI disclosure:** the README has a "Limits and AI assistance" section. It was not edited here.

## 5. Honest scores

**Track 02: strong.** Coordination is real and tested hard (fenced writes, stale workers, crash and resume, tenant isolation over HTTP), and the version-aware memory is a distinctive idea with a clear demo. It is held back from "excellent" by the evaluation, which shows no decision-correctness gain over the no-memory ablation.

**Track 01: credible.** The three gaps are now closed in code: one tool catalogue, a model-driven investigator that picks from it, a FalkorDB algorithm as a tool, and an MCP server. It is not "strong" because the agent is new and thin, the investigator has no action, and its quality depends on a rate-limited free model (see below).

Biggest weaknesses a judge could poke at:

1. **Track 02.** No live URL (local Docker only), and the evaluation shows equal decision correctness with and without memory (memory adds precedents and a changed checklist, not a measured gain). The information-parity baseline (RAG + findings) was not run because the free Groq daily limit ran out; the 34 cases and their expected answers were written by the same team.
2. **Track 01.** Investigator quality depends on a rate-limited free model: two of five real-model attempts failed their last round and fell back to a labelled template brief. The recorded runs replay without a key; on a claim with no recording and no key the panel says "Graph-only" and never "AI agent". The "actions" item is only partly met by design, and the algorithms add hop distance and a rank rather than new answers on a small synthetic graph.
3. **Both.** The five workers are fixed workflows, not tool-choosing agents. The only tool-choosing agent was written on the last day and is a small part of the code base.

## 6. Do not claim

- That the graph causes better accuracy, or that memory improves decision correctness (the evaluation shows equal correctness; memory adds precedents).
- That the investigator ran live in the demo: it is a recorded run of the real model, replayed. Say "recorded run".
- That BFS or PageRank find something a count cannot; they add hop distance and an indirect-dependence rank.
- That the investigator or MCP server takes actions. They are read-only, and the investigator cannot request human review.
- That the system covers conversation memory, or that it was load-tested.
- That a deployment exists, or that CI has passed on a remote runner.
- That declared documents are verified, or that the support score is an approval probability.
- That tenant separation is a formal anonymisation guarantee.
- That the 2026 policy knowledge is real, or the ground truth independent.

## 7. Status at submission

Done: the changes are committed and pushed to a public repository; the real-model recordings are committed so a judge with no key can replay them; the demo video is recorded, uploaded and linked from the README (it includes a Claude Desktop run over MCP).

Still the owner's: submit through the organizer's form naming **both** tracks (the rules page says you may enter any or all tracks), describe each participant's contribution, and keep the AI disclosure in the README factual.

## Appendix: what was verified, and how

All of this ran on 2026-10-18 on one Windows machine with Docker Desktop and FalkorDB 4.22.1. The checks below ran without an API key (model-dependent paths used their no-key fallback); the real-model investigator runs were made afterwards with a key and recorded.

| Check | Result |
|---|---|
| Backend `uv run pytest -q` before any change | 124 passed in 14 min 37 s |
| Backend `uv run pytest -q` with the new tests | **160 passed** in 17 min 2 s, 0 failed (the final run on 2026-10-18; 124 existing tests plus the new ones) |
| New tests | 35: `tests/test_blast.py` (5), `tests/test_catalogue_mcp.py` (11), `tests/test_investigator.py` (19) |
| Web | `npm run lint` clean; `npm test` 8/8; `npm run build` ok; `npx tsc --noEmit` clean (after the build, which generates the route types it needs) |
| `scripts/browser-smoke.mjs` (real Chrome) | 39/39 on the running stack, including the Investigate flow at 1440 px wide and at 390 px wide and the blast radius on Memory |
| Fresh copy | working tree copied without `.env`, `node_modules`, `.venv`, `.next`, caches and `.git` (513 files) into an empty folder; `docker compose --profile app up -d --build` built and went healthy (API 200, UI 200); the same smoke passed 39/39 against it, which includes investigating EV-T1-01; one MCP tool call through `docker compose run --rm -T --quiet-build mcp` returned `VERSION_DRIFT` for EV-T1-01 and refused another tenant's claim |
| MCP Inspector | v2.11.0 connected to `uv run python -m claimbridge.cli mcp`, `tools/list` returned 8 tools marked read-only ([screenshot](screenshots/mcp-inspector-tools.png)) |
| Real-model investigator runs, token report | **done**: EV-T1-01 (6,952 prompt + 921 completion tokens, 5 rounds), EV-M-B2 (6,901 + 801), EV-T3-01 (6,964 + 809). Recordings are committed in `data/llm_cache/groq/`. Two of five attempts hit a provider structured-output error in the last round and used the labelled template fallback before a clean run |
| Secret scan | no key-shaped string in the working tree or any commit; `.env` was never committed |

Screenshots: [Investigate panel](screenshots/investigate-panel.png), [at 390 px](screenshots/investigate-panel-390px.png), [blast radius](screenshots/blast-radius.png), [MCP Inspector](screenshots/mcp-inspector-tools.png).

**What a judge sees with no key.** The stack builds and runs. A bundled notice classifies from recorded responses. A new notice with no recording goes to *needs a person* with the reason "LLM unavailable; similarity alone cannot establish the denial reason". *Investigate* on EV-T1-01 (once it is filed and planned) replays the recorded real-model run and says "replayed from a recording". On a claim with no recording it runs the same tools in a fixed order and the panel says **Graph-only (LLM unavailable)** with 0 tokens; it never says AI agent. A recording only replays when the claim is in the state it had when recorded. MCP needs no key at all.

**Found and fixed on the way:** `docker compose --profile app up -d --build` failed on a clone without `.env` (every service required it); `tsc --noEmit` failed on a clean checkout before `next build` (CI ran it before the build); a first `docker compose run mcp` printed build progress onto the MCP stream (fixed with `--quiet-build`); an unclassified claim's brief said "no required evidence is missing" when no requirements were known yet.
