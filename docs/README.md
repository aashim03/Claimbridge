# ClaimBridge — Project Docs

> An AI caseworker that remembers verified resolutions, knows when prior knowledge no longer applies, and explains every recommendation through its evidence graph.

**Hackathon:** Graph Hacks: Context for AI Agents (WeMakeDevs × FalkorDB)
**Tracks:** 02 — Agent Memory and Coordination (primary) and 01 — Agents That Act on Connected Data
**Window:** Oct 15, 12:01 AM IST → **Oct 18, 11:59 PM IST** (2026)

## Read in this order

| # | Doc | What it answers |
|---|---|---|
| 00 | [Master plan](00-master-plan.md) | Goals, scope, timeline, cut lines, risks, and the definition of done |
| 01 | [Architecture](01-architecture.md) | Modules, tech stack, repo layout, deployment, and process model |
| 02 | [Data model](02-data-model.md) | Graph schema: nodes, relationships, properties, indexes, and the three layers |
| 03 | [Dataset and traps](03-dataset-and-traps.md) | Synthetic data, policy versions, trap cases, and ground-truth generation |
| 04 | [Agents and memory](04-agents-and-memory.md) | The 5 agents and the supervisor, the state machine, leases, handoff, and memory types |
| 05 | [Cypher queries](05-cypher-queries.md) | Every load-bearing query, documented as the rules require |
| 06 | [API and UI](06-api-and-ui.md) | REST endpoints, live events, and UI screens |
| 07 | [Evaluation](07-evaluation.md) | RAG baseline, metrics, harness, and how results are reported |
| 08 | [Demo and submission](08-demo-and-submission.md) | Demo video script, pitch, submission checklist, and blog post plan |
| 09 | [Phases and status](09-phases.md) | The build phases and what each delivered |
| 10 | [Review changes](10-review-changes.md) | What the judge review found and how each finding was answered |
| 11 | [Pending work plan](11-pending-work-and-completion-plan.md) | The completion checklist (updated 17 Oct) |
| 12 | [Completion report](12-completion-report.md) | What was done, the evidence, and what only the team can do |
| 13 | [Judge questions](13-judge-questions.md) | Candid answers, including what is not defensible |
| 14 | [Track assessment](14-track-assessment.md) | Both tracks focus item by focus item, the rule checks, honest scores and the do-not-claim list |

> Docs 00-05 are planning-era documents with an *as-built* banner at the top; 06 and 07 have a current section above the original design. Where they disagree, the code and the README are right.

## Non-negotiables (from the official rules)

- FalkorDB is the primary database and does real work. The product must break without it.
- All data is synthetic or public. No private or personal data.
- Main coding starts after Oct 15, 12:01 AM IST.
- AI coding assistants are allowed **but must be disclosed**, and the team must be able to explain the graph model, queries, architecture, and decisions.
- The submission includes:
  - public repo
  - README with setup instructions and the graph model
  - Cypher queries used
  - demo video
  - live deployment (or full local setup)
  - track(s) entered
