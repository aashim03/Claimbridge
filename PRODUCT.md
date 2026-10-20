# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Next.js (App Router, TypeScript) frontend, chosen by the user. It calls a Python FastAPI service that wraps the existing, tested graph tools, Supervisor and agents (user chose FastAPI + Next.js over rewriting in TypeScript). FalkorDB is the database. The deploy target is one Docker Compose stack (FalkorDB, API, supervised agent pool, web).

## Users

- **Primary: an insurance caseworker or patient advocate** who works a queue of denied health-insurance claims. For each claim they need to know which policy terms govern it, whether a past winning appeal really applies, what evidence is missing, and what to do next. They approve every recommendation and later record the real outcome.
- **Evaluating audience: hackathon judges** (WeMakeDevs × FalkorDB, Track 02 Agent Memory and Coordination). They click through the live app, often briefly, to check that the agents, memory and graph are real and load-bearing.

## Product Purpose

ClaimBridge is an AI caseworker for denied health-insurance claims. Five agents coordinate only through a FalkorDB graph to:
- classify the denial;
- pin the policy version in force;
- retrieve and verify precedents;
- plan an evidence-backed response;
- learn from verified outcomes.

Success means a caseworker gets a correct, cited plan and never acts on a precedent that no longer applies, and a judge can see why in the graph.

## Positioning

**Memory that knows when it's wrong.** Lessons from verified resolutions (Findings) are scoped to the policy versions and conditions they were learned under. They are rejected with a stated reason when a clause changed (version drift), when they concern a different clause, when later cases contradict them, or when their conditions aren't met.

**The graph decides; the LLM only writes wording.** Every plan item cites graph nodes, and anything uncited is dropped. Agents share no session and can be killed mid-step; another replica resumes from the graph.

## Operating Context

- **Claim lifecycle:**
  RECEIVED → (Intake) CLASSIFIED → (Retrieval) RETRIEVED → (Verifier) VERIFIED → (Planner) AWAITING_REVIEW → human approval → real outcome recorded → (Curator) CURATED. Claims can also go to NEEDS_HUMAN.
- **Workers:** Intake, Retrieval, Verifier, Planner, Curator, plus a deterministic Supervisor that runs the pool, executes kill/start commands and records expired leases.
- **Policy world:** fictional insurer Lumen Health Assurance, plan LumenCare Silver, versions 2024/2025/2026, 25 clause lineages. Publishing a new version marks dependent memory stale.
- **Demo flow:**
  - inject trap claims (T1–T7);
  - watch agents move them;
  - open a case to see accepted and rejected precedents on the evidence graph;
  - kill a worker;
  - approve and record an outcome, and watch memory learn;
  - publish the 2026 policy and watch Findings go stale;
  - read the evaluation results.
- **Main tool for the judges:** a live URL if one is deployed; otherwise the documented local setup. The FalkorDB Browser is also available locally.

## Capabilities and Constraints

- **Backend:** Python 3.11, `backend/claimbridge`, with the CLI and tested tools.
- **Data:** in `data/`, all synthetic and fictional.
- **LLM layer:** provider-agnostic (`LLM_PLATFORM` groq|openai|claude|fake; default Groq `openai/gpt-oss-120b`). Responses are recorded and replayed (`LLM_MODE=cached`). Groq's free tier is limited to 200K tokens a day, so public visitors should mostly replay.
- **Terminology:** claim, denial notice, policy version, clause, lineage, Finding (precedent), Playbook, disposition (APPEAL_VIABLE / APPEAL_NEEDS_EVIDENCE / NO_BASIS_ESCALATE), verdict codes (ACCEPTED, VERSION_DRIFT, LINEAGE_MISMATCH, CONTRADICTED, CONDITION_UNMET, REASON_MISMATCH), gates, lease, checkpoint.
- **Tenancy:** case detail is tenant-scoped; Findings are anonymous and shared.
- **Undecided:** the final hosting provider. A read-only MCP server exists (see the README). Authentication exists (`AUTH_MODE=protected`); demo mode is a deliberately public sandbox.

## Brand Commitments

- **Name:** ClaimBridge.
- **Tagline:** "An AI caseworker that remembers verified resolutions, knows when prior knowledge no longer applies, and explains every recommendation through its evidence graph."
- **Required disclaimers:** the app must state plainly that all data is synthetic and fictional and that recommendations require human approval. It must never present itself as approving claims or giving legal advice.

## Evidence on Hand

- **Evaluation results:** the promoted run, `eval/results/latest.md` (run `20261017T183825+0530-3c6ce4`, 34 authored synthetic claims). Decision correctness is equal for ClaimBridge and its no-memory ablation, so memory adds precedents and a changed checklist, not a measured gain in decisions; plain RAG is lower on decisions, but it sees different information and decides differently, so this is a whole-system comparison, not proof that a database alone causes the gap. The information-parity baseline did not run. Quote numbers only with the run id and these caveats.
- **Coordination:** random kills and a deliberate paused-worker scenario with the late writes rejected and audited, in the same report.
- **Memory:** one recorded synthetic outcome changes the next checklist; a smoothed support score, never a probability.
- **Docs and data:** design docs in `docs/`, ground truth in `data/generated/`.
- **What doesn't exist:** no real customers, testimonials, partners, logos, pricing or real-world outcome data. Never invent them.

## Product Principles

1. **Show the reasoning, not just the answer.** Every recommendation is traceable to graph nodes, and every rejected precedent says why.
2. **The human decides.** The product recommends; approval and outcomes are explicit human acts.
3. **Honest over impressive.** Synthetic data, failures and limits are stated. Numbers come from the evaluation, not from marketing.
4. **Coordination is visible.** Agents, leases, kills and resumes are first-class things to look at, not hidden plumbing.
5. **Memory has a shelf life.** Validity, staleness and contradiction are always visible next to a precedent.

## Accessibility & Inclusion

No product-specific standard was set beyond WCAG 2.2 AA for the console. Status must never be conveyed by color alone, because verdicts and dispositions are the core content.
