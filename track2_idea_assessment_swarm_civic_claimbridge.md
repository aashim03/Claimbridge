# FalkorDB Hackathon — Track 2 Idea Assessment

## Purpose

This document compares three project ideas for **Track 2: Agent Memory and Coordination** of the WeMakeDevs × FalkorDB hackathon, in this order:

1. Swarm Relief
2. CivicResolve
3. ClaimBridge

The assessments are practical judgments, not official judging scores or guarantees of winning. A strong idea still needs a working implementation, measurable results, and a clear demonstration that FalkorDB is essential to the product.

---

# 1. Swarm Relief

## Concept

**Swarm Relief** is a disaster-response simulation in which specialized agents coordinate using one persistent world graph.

During a simulated flood, for example:

- Drone/scout agents report blocked roads and affected locations.
- Shelter agents update capacity and occupancy.
- Logistics agents plan deliveries and routes.
- A coordination agent assigns and tracks tasks.
- If an agent crashes or stops responding, another agent recovers its unfinished work from the shared graph.

Observations should have timestamps, sources, confidence levels, and expiry times. This helps the system distinguish current information from stale reports.

## Problem it addresses

During a disaster, information can become outdated or contradictory. Separate teams may duplicate work, route supplies through blocked roads, or lose context when responsibilities change.

Swarm Relief explores whether shared, persistent graph memory can reduce these failures in a controlled simulation.

## Why it fits Track 2

It can demonstrate all the core memory and coordination behaviors:

- **Episodic memory:** a history of observations, events, and agent actions.
- **Semantic memory:** the current believed state of roads, shelters, and tasks.
- **Procedural memory:** strategies that worked in previous simulated scenarios.
- **Persistent memory:** agents can resume after a restart.
- **Shared state and handoffs:** agents read and update common tasks and observations.
- **Failure recovery:** abandoned tasks can be reclaimed after an agent's lease expires.
- **Graph-backed explanations:** the system can show which observations and road connections led to a routing decision.

## Suggested graph model

| Node | Purpose |
|---|---|
| `Agent` | A scout, shelter, logistics, or coordination agent |
| `Location` | A road junction, shelter location, or affected area |
| `Road` | A connection between locations and its current status |
| `Shelter` | Capacity, occupancy, and availability |
| `Task` | A rescue, delivery, inspection, or scouting task |
| `Observation` | A time-stamped report from an agent |
| `Playbook` | A strategy and its measured outcomes |
| `Action` | An auditable action taken by an agent |

Possible relationships include:

- `Location → ROAD → Location`
- `Agent → OBSERVED → Observation → ABOUT → Road/Location/Shelter`
- `Task → AT → Location`
- `Task → CLAIMED_BY → Agent`
- `Task → HANDED_OFF → Agent`
- `Playbook → USED_IN → Task`

## What would make the demo impressive?

1. Show a flood scenario on a map.
2. Have one agent report a blocked road.
3. Make logistics agents reroute based on that update.
4. Show that a task has exactly one active owner.
5. Stop an agent while it owns a task.
6. Let another agent reclaim the task after the lease expires and continue it.
7. Restart the simulation and show that the graph preserves state.
8. Introduce a conflicting or stale observation and show how the system handles uncertainty instead of blindly trusting it.

## Evaluation plan

Compare graph-coordinated agents with a baseline that uses message passing or independent agents without shared persistent graph memory.

Measure:

- Tasks completed successfully.
- Duplicate task assignments.
- Deliveries or routes sent through blocked roads.
- Time to recover work after an agent failure.
- Decisions made using stale information.
- Critical locations reached or supplied in the simulation.

Report the test setup, number of scenarios, and failures. Do not claim that the prototype improves real disaster response unless that has actually been evaluated.

## Strengths

- High and immediately understandable social value.
- Strong visual demonstration potential.
- Natural multi-agent coordination, shared state, and recovery behavior.
- Good opportunity to show FalkorDB traversals and graph-backed reasoning.
- A simulation allows controlled tests with known expected outcomes.

## Risks and weaknesses

- Multi-agent concurrency and recovery can be difficult to implement reliably in a short hackathon.
- A polished map can disguise a shallow backend if decisions are scripted.
- Shortest-path routing alone is not sufficient: blocked roads, capacity, priority, and uncertain observations matter.
- A simulated result is not proof of real-world disaster-response effectiveness.

## Practical assessment

**Estimated competitive potential: 8.5/10**

This is the strongest choice for a visual, social-impact demonstration. Its main risk is implementation complexity. The team should prioritize a reliable end-to-end simulation over a large number of agents or elaborate map features.

---

# 2. CivicResolve

## Concept

**CivicResolve** is a shared-memory system for coordinating civic complaints from initial report to verified resolution.

Example complaints include:

- Potholes.
- Broken streetlights.
- Water leaks.
- Waste collection problems.
- Damaged public infrastructure.

Multiple reports about the same underlying incident can be linked together. Agents route the issue, track ownership, preserve handoff context, and reopen the incident if later evidence contradicts a claim that it was fixed.

## Problem it addresses

Civic complaints can be duplicated, sent to the wrong department, lose context during handoffs, or be marked resolved without confirmation. The product aims to preserve incident history and coordinate the work needed to resolve each case.

This proposal is a new idea for this assessment, rather than a verified existing product or a confirmed hackathon entry.

## Why it fits Track 2

- **Episodic memory:** reports, inspections, work orders, and updates are retained.
- **Semantic memory:** several reports can be recognized as describing one incident.
- **Procedural memory:** the system can record which resolution workflows worked for which issue types.
- **Persistent memory:** a new agent can continue an unresolved incident.
- **Shared state and handoffs:** departments and agents share ownership and progress.
- **Conflict detection:** a new report that an issue persists can contradict a previous resolution.
- **Graph-backed reasoning:** reports connect to locations, public assets, departments, work orders, and outcomes.

## Suggested graph model

| Node | Purpose |
|---|---|
| `Report` | An individual citizen complaint |
| `Incident` | The underlying issue that one or more reports describe |
| `Location` | The geographic location of the issue |
| `Asset` | A streetlight, road segment, drain, or other public asset |
| `Department` | The responsible public-service department |
| `Agent` | A classification, routing, coordination, or verification agent |
| `WorkOrder` | The inspection or repair activity |
| `Observation` | Evidence that the issue exists or has changed |
| `Resolution` | The recorded outcome and verification evidence |

Possible relationships include:

- `Report → DUPLICATE_OF → Report`
- `Report → ABOUT → Incident`
- `Incident → AT → Location`
- `Incident → AFFECTS → Asset`
- `Incident → ASSIGNED_TO → Department`
- `WorkOrder → FOR → Incident`
- `Agent → CLAIMED_BY / HANDED_OFF_TO → Agent`
- `Resolution → VERIFIED_BY → Observation`

The final schema should use consistent relationship directions and a concurrency-safe ownership model.

## What would make the demo impressive?

1. Submit three simulated complaints about the same water leak.
2. Link the reports to one incident while preserving each original report.
3. Route the incident to a responsible department and create a work order.
4. Let an agent record an inspection and hand off the task.
5. Stop the agent and show another agent resuming the work from the graph.
6. Record a purported repair.
7. Introduce a new observation showing that the leak remains active.
8. Reopen the incident and show the evidence path behind the decision.

The key demonstration is not just duplicate detection. It is the ability to preserve incident memory, coordinate ownership, and revise the current state when new evidence arrives.

## Evaluation plan

Compare graph-coordinated incident handling with a simple ticket workflow or agents that do not share persistent graph memory.

Measure:

- Duplicate incidents incorrectly created.
- Correctness of incident merging.
- Duplicate work orders or assignments.
- Successful recovery after an agent failure.
- Incorrectly closed incidents.
- Correct reopening when new evidence contradicts a resolution.
- Time to route and resume an incident.

Use synthetic data or permitted public data. Avoid presenting simulated performance as a measured improvement in a real municipal service.

## Strengths

- Socially useful and easy to explain.
- A clear story from complaint to resolution.
- Natural graph relationships among reports, incidents, locations, departments, and work.
- More manageable than a full disaster-response simulator if the scope is limited to one issue type.
- Good opportunities for measurable tests and a polished interface.

## Risks and weaknesses

- It could look like ordinary ticket-management software with an AI interface.
- Incident deduplication can be unreliable if reports have ambiguous locations or descriptions.
- Real civic-service data and department workflows may be difficult to obtain or standardize.
- If handoffs, persistent memory, and conflict handling are scripted, the core Track 2 contribution will be weak.

## Practical assessment

**Estimated competitive potential: 8.5/10**

CivicResolve is a strong new candidate if the team wants a socially relevant problem with a clear end-to-end workflow. To compete well, focus on shared memory, incident lifecycle, recovery, and contradiction handling—not merely complaint classification or routing.

---

# 3. ClaimBridge

## Concept

**ClaimBridge** is an insurance case-memory and resolution assistant. It connects policy wording, claim details, denial reasons, required evidence, previous cases, and verified outcomes.

When a new claim is denied or a policyholder asks a complex question, the system finds relevant prior cases, checks whether the facts and policy terms are comparable, identifies missing evidence, and generates a documented resolution checklist for a human reviewer or policyholder.

The aim is to help people understand and address claim issues—not to automatically promise claim approval or replace an insurer's formal decision process.

## Problem it addresses

Insurance claims can involve multiple policy clauses, documents, denial reasons, and previous interactions. A generic chatbot may retrieve a relevant paragraph but fail to connect the policy version, specific denial reason, missing evidence, prior resolution, and current case state.

ClaimBridge treats a claim as a case that evolves over time and can be resumed by another agent without losing context.

## Why it fits Track 2

- **Episodic memory:** the full history of claim events, submissions, denials, and reviews.
- **Semantic memory:** verified patterns connecting denial reasons, policy conditions, evidence requirements, and outcomes.
- **Procedural memory:** documented workflows for resolving specific categories of claim issues.
- **Persistent memory:** agents resume the same case across sessions.
- **Shared state and handoffs:** retrieval, policy verification, resolution, and memory-curation agents work on one case.
- **Temporal reasoning:** the system distinguishes policy versions and facts that were true at different times.
- **Graph-backed explanations:** recommendations trace back to applicable clauses, evidence, and relevant historical cases.

## Suggested graph model

| Node | Purpose |
|---|---|
| `Policy` | A policy and its version |
| `Clause` | A coverage term, exclusion, or condition |
| `Claim` | A claim and its current status |
| `DenialReason` | The recorded reason for denial |
| `Evidence` | A required or submitted document |
| `Resolution` | A verified correction, appeal, resubmission, or outcome |
| `Agent` | The agent responsible for a step or handoff |
| `Finding` | A reusable lesson derived from verified cases |
| `CaseEvent` | A time-stamped event in the case history |

Possible relationships include:

- `Claim → GOVERNED_BY → Policy`
- `Policy → CONTAINS → Clause`
- `Claim → DENIED_FOR → DenialReason`
- `Claim → REQUIRES / HAS_EVIDENCE → Evidence`
- `Claim → RESOLVED_BY → Resolution`
- `Resolution → SUPPORTED_BY → Evidence`
- `Finding → DERIVED_FROM → Resolution`
- `Agent → REVIEWED / UPDATED / HANDED_OFF → Claim`

Use explicit policy-version and effective-date information. Similarity between cases is not sufficient to establish that the same resolution applies.

## What would make the demo impressive?

1. Load a controlled synthetic dataset of policies, claims, denials, evidence, and verified outcomes.
2. Submit a new denied claim.
3. Have the case-retrieval agent find related historical cases and explain why they are similar.
4. Have the policy-verification agent check the applicable policy version and clauses.
5. Have the resolution agent identify missing evidence and propose next steps.
6. Restart the application or hand the case to another agent.
7. Show that the new agent resumes from the existing graph state.
8. Introduce an outdated policy rule or contradictory finding and show that the system flags it instead of blindly reusing an old resolution.
9. Display the complete reasoning path and source evidence for the proposed action.

The strongest demonstration is that historical memory improves the next decision while policy and evidence checks prevent the agent from overgeneralizing from earlier cases.

## Evaluation plan

Compare the graph-backed agent against a basic RAG baseline using the same policies and synthetic case dataset.

Measure:

- Denial-reason classification accuracy.
- Precision and recall for retrieving genuinely relevant historical cases.
- Accuracy of required-evidence checklists.
- Correctness of policy-version selection.
- Unsupported recommendation rate.
- Detection of stale or contradictory findings.
- Correct handoff and recovery of an unfinished case.
- Source-evidence correctness.

Include difficult cases where the closest historical case is not applicable. Report errors as well as successes.

## Strengths

- Clear business value for policyholders and claims teams.
- Strong use of multi-hop graph reasoning across policies, clauses, evidence, denial reasons, and outcomes.
- Natural multi-agent workflow with case handoffs.
- Potentially distinctive persistent memory based on verified resolutions.
- Good opportunities to compare graph-based reasoning with a basic RAG baseline.

## Risks and weaknesses

- Real claim records are sensitive and difficult to use in a hackathon.
- Synthetic data must be sufficiently varied to avoid a trivial demonstration.
- A previous successful appeal does not prove a new claim should be approved.
- Outdated policy terms, missing evidence, or fabricated precedent could lead to harmful recommendations.
- The scope can expand quickly into document processing, policy interpretation, legal reasoning, fraud detection, and adjudication.

For the hackathon, use synthetic policyholders and claims, plus public policy wording only where its use is permitted. In a real deployment, use appropriate authorization, privacy safeguards, tenant isolation, and carefully controlled access to historical records. Do not expose one policyholder's raw case details to another.

## Practical assessment

**Estimated competitive potential: 9/10 after tight scoping**

ClaimBridge is the strongest business-oriented candidate in this assessment, but only if the team can create a credible evaluation dataset quickly. Its differentiator should be:

> An AI caseworker that remembers verified resolutions, knows when prior knowledge no longer applies, and explains each recommendation through its evidence graph.

Do not pitch it as simply an insurance chatbot or an automatic claim-approval system.

---

# 4. Comparison and recommendation

The following scores are qualitative estimates of the ideas as refined above, not official judging scores or probabilities of winning.

| Criterion | Swarm Relief | CivicResolve | ClaimBridge |
|---|---:|---:|---:|
| Track 2 alignment | 5/5 | 5/5 | 5/5 |
| Social usefulness | 5/5 | 5/5 | 4/5 |
| Demo impact | 5/5 | 4/5 | 4/5 |
| Differentiation potential | 4/5 | 4/5 | 5/5 |
| Evaluation potential | 4/5 | 4/5 | 5/5 |
| Four-day feasibility | 3/5 | 4/5 | 3/5 |
| **Overall estimated potential** | **8.5/10** | **8.5/10** | **9.0/10** |

## Which one should the team choose?

### Choose Swarm Relief if:
- The team can implement reliable agent coordination and recovery.
- A visual, live simulation is a major strength.
- You want the clearest disaster-response social-impact narrative.

### Choose CivicResolve if:
- You want a practical civic problem with a manageable end-to-end workflow.
- You can demonstrate incident merging, ownership, handoffs, and reopening after contradictory evidence.
- You want a balance between social value, feasibility, and visible graph behavior.

### Choose ClaimBridge if:
- The team is comfortable with backend workflows, policy documents, and evaluation.
- You can generate a varied synthetic dataset with known expected answers.
- You can demonstrate that historical memory helps while policy-version and evidence checks prevent incorrect reuse.

## Final recommendation

**My first choice is ClaimBridge, provided the team can validate the core workflow early. My fallback is Swarm Relief.**

ClaimBridge offers the most distinctive opportunity to show persistent, evidence-backed case memory, but its data and evaluation risks are substantial. Swarm Relief is the safer choice if you can build a deterministic simulation more quickly than a credible claims dataset. CivicResolve is a strong alternative if the team wants a narrower civic workflow with less simulation complexity.

No idea has a guaranteed chance of winning. Execution quality, a clear graph-dependent capability, credible evaluation, and a reliable demo will matter more than the score assigned during idea selection.

---

# 5. Five checks before committing

- [ ] **Persistent memory:** Does the second session make a better or more informed decision because of the first?
- [ ] **Real coordination:** Do multiple agents share state and hand off work, rather than simply exchanging chat messages?
- [ ] **Graph necessity:** Does removing FalkorDB break a central reasoning or coordination capability?
- [ ] **Measurable evidence:** Can the team compare the system against a credible baseline and show failure cases?
- [ ] **Explainability:** Can a judge inspect the graph path, source evidence, current state, and remaining uncertainty behind a decision?

If the selected project cannot demonstrate these behaviors, prioritize fixing the core workflow before adding more features or polishing the interface.

## Scope discipline for the four-day build

1. **Day 1:** Create the graph schema, seed data, and a working end-to-end workflow.
2. **Day 2:** Implement the memory-dependent decision and agent handoff.
3. **Day 3:** Test recovery, stale or conflicting information, and the baseline comparison.
4. **Day 4:** Stabilize the demo, document the graph model and queries, disclose AI coding assistance, and prepare the submission.

Keep the first working demo small and deterministic. Add complexity only after the graph-backed memory and coordination behavior works reliably.
