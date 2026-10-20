# 02 — Graph Data Model

> **Status (updated 17 Oct 2026): the schema below is the original design; these are the as-built changes.**
>
> | Area | As built |
> |---|---|
> | Graph names | `claimbridge` (demo), `claimbridge_eval` (evaluation), `claimbridge_test` (tests), `claimbridge_access` (the browser access matrix). The evaluation refuses to touch the demo graph. |
> | `Claim` lease fields | `lease_owner`, `lease_until` (set and compared with the database's `timestamp()`), **`lease_gen`** (a fencing token incremented on every acquisition), `attempt`, `prev_owner`, `reaped` |
> | `Claim.source` | `historical`, seeded evaluation claims, `manual` (entered in the console, ids `NC-<12 hex>`), `generalization` |
> | `Clause.fingerprint` | a content hash of text, params, evidence, type, governed services and routes. A policy change invalidates a `Finding` when its lineage's fingerprint changes, not only when a numeric parameter does. |
> | `Finding` | conditions `req_emergency`, `req_in_network`; `confidence` is a **smoothed support score** `(wins+1)/(wins+losses+2)`, not a probability; learned findings have deterministic ids `F-L-<lineage>-<16 hex>` so a retry cannot create a second one; `origin` is `seed` or `learned` |
> | `Evidence` | `declared_by`, `declared_at`, `verified` (always false: documents are never read or verified), `reference`, `source` (`filing` or `declared`), and `withdrawn`, `withdrawn_by`, `withdrawn_at` (a withdrawn document is kept and no longer counts) |
> | `Correction` (new) | `(Claim)-[:CORRECTED_BY]->(Correction {correction_id, reason_code, previous_reason, escalation_reason, note, reviewer, ts})`: a person's reclassification of a notice. The `DenialNotice` is never edited. |
> | `Resolution` | `confirmed_evidence`: the documents the reviewer says the decision relied on (null = not observed) |
> | `Recommendation` | `support_state` (`NO_PRECEDENT`, `NO_APPEAL_BASIS`, `RECORDED_OUTCOMES`); a score is shown only for the last |
> | `CaseEvent` types added | `HUMAN_CORRECTION`, `EVIDENCE_DECLARED`, `EVIDENCE_WITHDRAWN`, `FENCED_WRITE_REJECTED` (with `lease_gen` on `LEASE_EXPIRED`) |
> | Evidence gap | each requirement carries `sources`: clause ids (policy requirements) or finding ids (suggestions learned from outcomes). Both the API and the replay build their edges from them. |

Graph name: `claimbridge`. All dates are stored as **integers `YYYYMMDD`**, and timestamps as **epoch milliseconds**. This keeps comparisons trivial and portable in FalkorDB Cypher.

## 1. Three layers, plus coordination

| Layer | Purpose | Changes |
|---|---|---|
| **Knowledge** | What the policy says, per version | Rarely, by adding a new version |
| **Case** | What happened on each claim (per tenant) | Constantly |
| **Memory** | What we learned from verified outcomes, and whether it is still valid | Derived from cases, invalidated by knowledge changes and contradictions |
| **Coordination** | Who is working on what, and where they stopped | Every agent step |

**The core idea:** a `Finding` is tied to the clause **lineage** and **version range** it was learned under, plus the conditions it needs. When a clause changes or a later case disagrees, a traversal finds every affected Finding. Text similarity cannot do this.

## 2. Diagram

```
                       KNOWLEDGE
 (Insurer)-[:OFFERS]->(Plan)-[:HAS_VERSION]->(PolicyVersion)-[:CONTAINS]->(Clause)
                                            (PolicyVersion)-[:SUCCEEDS]->(PolicyVersion)
                                                      (Clause)-[:SUPERSEDES]->(Clause)
                                                      (Clause)-[:GOVERNS]->(ServiceCategory)
                                                      (Clause)-[:REQUIRES]->(EvidenceType)
                                     (DenialReason)-[:TYPICALLY_CITES]->(Clause)

                       CASE (tenant-scoped)
 (Tenant)-[:FILED]->(Claim)-[:GOVERNED_BY]->(PolicyVersion)
                    (Claim)-[:FOR_SERVICE]->(ServiceCategory)
                    (Claim)-[:HAS_NOTICE]->(DenialNotice)-[:CITES]->(Clause)
                    (Claim)-[:DENIED_FOR]->(DenialReason)
                    (Claim)-[:HAS_EVIDENCE]->(Evidence)-[:OF_TYPE]->(EvidenceType)
                    (Claim)-[:RESOLVED_BY]->(Resolution)-[:RELIED_ON]->(Clause)
                                            (Resolution)-[:SUPPORTED_BY]->(Evidence)
                                            (Resolution)-[:FOLLOWED]->(Playbook)

                       MEMORY (tenant-free)
 (Finding)-[:DERIVED_FROM]->(Resolution)
 (Finding)-[:FOR_REASON]->(DenialReason)
 (Finding)-[:ON_LINEAGE]->(Clause)            // the clause it was learned on
 (Finding)-[:VALID_IN]->(PolicyVersion)
 (Finding)-[:NEEDS_EVIDENCE]->(EvidenceType)
 (Finding)-[:RECOMMENDS]->(Playbook)
 (Finding)-[:CONTRADICTED_BY]->(Resolution)
 (Finding)-[:STALE_BECAUSE]->(Clause)         // the new clause that broke it
 (Playbook)-[:FOR_REASON]->(DenialReason)
 (Playbook)-[:HAS_STEP]->(PlaybookStep)-[:NEXT]->(PlaybookStep)
 (PlaybookStep)-[:USES_EVIDENCE]->(EvidenceType)

                       COORDINATION + EXPLANATION
 (Claim)-[:HAS_EVENT]->(CaseEvent)-[:NEXT]->(CaseEvent)
 (Agent)-[:PERFORMED]->(CaseEvent)
 (Claim)-[:HAS_CHECKPOINT]->(Checkpoint)        // one per step, keyed claim_id:step
 (DenialReason)-[:TYPICALLY_CITES {service, priority}]->(Clause)   // routing, per version
 (Claim)-[:CONSIDERED {verdict, reason_code}]->(Finding)    // written by Retrieval/Verifier
 (Claim)-[:RECOMMENDATION]->(Recommendation)-[:HAS_ITEM]->(RecItem)-[:CITES]->(any cited node)
 (Agent)-[:RUNS_ON]->(WorkerHeartbeat)
```

## 3. Node reference

### Knowledge layer

| Label | Key | Properties |
|---|---|---|
| `Insurer` | `insurer_id` | `name` (fictional, e.g. "Lumen Health Assurance") |
| `Plan` | `plan_id` | `name`, `tier` |
| `PolicyVersion` | `version_id` | `label` ("2025"), `effective_from` (int), `effective_to` (int, exclusive, `99991231` if open) |
| `Clause` | `clause_id` | `lineage_id`, `version_id`, `section`, `type` (COVERAGE, EXCLUSION, CONDITION, LIMIT, PROCEDURE), `title`, `text`, `params` (canonical JSON string, used only for change detection), plus the flattened params that queries compare: `limit_days`, `max_sessions`, `referral_exception`, `notify_hours`. `embedding` (vecf32, optional). |
| `ServiceCategory` | `code` | `name` |
| `DenialReason` | `code` | `name`, `description`, `embedding` (vecf32) |
| `EvidenceType` | `code` | `name`, `description` |

`lineage_id` is the stable identity of a clause across versions (for example, `L-MRI-PREAUTH`). `clause_id` is per version (for example, `C-2025-MRI-PREAUTH`).

### Case layer

| Label | Key | Properties |
|---|---|---|
| `Tenant` | `tenant_id` | `display_name` (fictional) |
| `Claim` | `claim_id` | `tenant_id`, `service_date`, `filed_date`, `filing_lag_days` (computed in Python), `amount`, `in_network` (bool), `is_emergency` (bool), `status`, `source` (`historical`, `eval`, `live`), `event_seq`, plus lease fields (§5) |
| `DenialNotice` | `notice_id` | `text`, `issued_date`, `embedding` (vecf32) |
| `Evidence` | `doc_id` | `submitted_date`, `summary` |
| `Resolution` | `resolution_id` | `outcome` (OVERTURNED, UPHELD, PARTIAL), `actions` (JSON), `verified` (bool), `verified_on` (int) |

### Memory layer

| Label | Key | Properties |
|---|---|---|
| `Finding` | `finding_id` | `statement`, condition flags `req_emergency` and `req_in_network` (nullable bool; `null` means no requirement, kept flat so Cypher can compare them), `status` (ACTIVE, STALE, CONTRADICTED), `support` (int), `wins` (int), `confidence` (float), `created_at`, `updated_at` |
| `Playbook` | `playbook_id` | `name`, `uses` (int), `wins` (int) |
| `PlaybookStep` | `step_id` | `order`, `action`. Linked via `(PlaybookStep)-[:USES_EVIDENCE]->(EvidenceType)` when the step needs a document. |

`confidence` is computed, not guessed: `wins / support`, scaled down for each contradiction, and 0 while STALE.

### Coordination and explanation

| Label | Key | Properties |
|---|---|---|
| `Agent` | `agent_id` | `role`, `instance` (container or PID) |
| `WorkerHeartbeat` | `agent_id` | `last_seen`, `current_claim`, `state` |
| `CaseEvent` | `event_id` (= `claim_id:seq`) | `seq`, `type`, `ts`, `agent_id`, `step`, `payload` (JSON) |
| `Checkpoint` | `checkpoint_id` (= `claim_id:step`) | `step`, `state` (JSON), `ts`, `agent_id`, `complete` (false = intermediate, saved mid-step; true = written by the commit) |
| `Recommendation` | `rec_id` | `summary`, `confidence`, `uncertainty` (JSON list), `created_at`, `approved_by`, `approved_at` |
| `RecItem` | `item_id` | `order`, `kind` (EVIDENCE_NEEDED, ACTION, WARNING, REJECTED_PRECEDENT), `text` |

## 4. Claim status machine (stored on `Claim.status`)

```
RECEIVED → CLASSIFIED → RETRIEVED → VERIFIED → PLANNED → AWAITING_REVIEW
                                                              │
                                     human approves ──────────┤
                                                              ▼
                                         APPROVED → (outcome recorded) → VERIFIED_OUTCOME → CURATED
   any step ── unrecoverable / low confidence ──► NEEDS_HUMAN
```

Every transition writes a `CaseEvent`. See [04](04-agents-and-memory.md) for which agent owns which transition.

## 5. Lease fields (on `Claim`)

| Property | Meaning |
|---|---|
| `lease_owner` | `agent_id` or `null` |
| `lease_until` | Epoch ms. Expired when `< now`. |
| `attempt` | Increments on every claim of the same step, so the UI can show "resumed by verifier-2 (attempt 2)". Reset to 0 by each commit. |
| `prev_owner` | The previous lease holder, recorded when a lease is taken over |
| `gates` | List written by the Verifier: `EXCLUSION_NO_BASIS`, `EMERGENCY_REQUIRED`, `FILED_LATE`, `WAITING_NOT_MET` |

**Verified on FalkorDB 4.22:** 16 workers racing for one free claim, over 40 trials, always gave exactly one winner.

Lease fields live as **properties** (not an edge) so the claim operation is a single atomic `MATCH … WHERE … SET`. FalkorDB runs write queries one at a time per graph, so two workers cannot both win. An `OWNS` edge is not needed. Ownership history lives in the `CaseEvent` chain (`CLAIMED`, `RELEASED`, `LEASE_EXPIRED`, `RESUMED`).

## 6. Tenant isolation rules

1. Every `Claim`, `DenialNotice`, `Evidence`, and `Resolution` is reachable only via `(Tenant)-[:FILED]->(Claim)`.
2. Every case-level tool function takes `tenant_id` and anchors its `MATCH` on it.
3. `Finding` and `Playbook` contain **no** tenant data. `statement` is generated from structured fields (reason, lineage, evidence, conditions), never by copying case text.
4. `DERIVED_FROM` points to a Resolution. When the caller isn't that tenant, the API returns only `resolution_id` and `outcome`, never the claim details (trap T7).

## 7. Indexes and constraints

Created by `schema.py` at startup. They are idempotent.

```cypher
CREATE INDEX FOR (c:Claim) ON (c.claim_id)
CREATE INDEX FOR (c:Claim) ON (c.status)
CREATE INDEX FOR (c:Claim) ON (c.tenant_id)
CREATE INDEX FOR (c:Clause) ON (c.clause_id)
CREATE INDEX FOR (c:Clause) ON (c.lineage_id)
CREATE INDEX FOR (v:PolicyVersion) ON (v.version_id)
CREATE INDEX FOR (f:Finding) ON (f.finding_id)
CREATE INDEX FOR (f:Finding) ON (f.status)
CREATE INDEX FOR (r:DenialReason) ON (r.code)
CREATE INDEX FOR (e:EvidenceType) ON (e.code)
CREATE INDEX FOR (t:Tenant) ON (t.tenant_id)
CREATE INDEX FOR (e:CaseEvent) ON (e.event_id)

CREATE VECTOR INDEX FOR (n:DenialNotice) ON (n.embedding)
  OPTIONS {dimension: 384, similarityFunction: 'cosine'}
CREATE VECTOR INDEX FOR (r:DenialReason) ON (r.embedding)
  OPTIONS {dimension: 384, similarityFunction: 'cosine'}
```

Notes from implementation:
- The vector procedure's `score` is a cosine **distance**, so lower means more similar.
- Notice embeddings are computed from the **core text** only (service and stated reason). The letterhead, claim number, dates and appeal footer are stripped first, because they dominated similarity.
- The seed rebuilds the graph from scratch every time, so unique constraints aren't needed in Phase 1. The client offers `create_node_unique_constraint` if we add live writes later.

## 8. Size estimate

| Item | Count |
|---|---|
| PolicyVersions / Clauses | 3 / about 90 (about 25 lineages × 3, with some added or removed) |
| Taxonomy nodes | 9 + 15 + 10 |
| Tenants | 15 |
| Claims (historical + eval) | about 80 |
| Evidence | about 200 |
| CaseEvents | about 800 after the evaluation run |
| Findings / Playbooks | about 15 / about 8 |
| **Total** | about 1,500 nodes and about 4,000 edges |

The graph is small enough to inspect in the FalkorDB browser during the demo and large enough that the traps aren't trivial.

## 9. Why each structural choice matters to judges

| Choice | What it enables | Which claim |
|---|---|---|
| `lineage_id` and `SUPERSEDES` | Detect version drift in one traversal | C2 |
| `Finding-[:VALID_IN]->PolicyVersion` | Scope memory to the versions where it holds | C2 |
| `Finding.req_*` flags and `NEEDS_EVIDENCE` | Refuse precedent when a condition isn't met | C2 |
| `VALID_IN` decides applicability, and `status` only describes the latest version | A Finding that's stale for 2026 still correctly applies to a 2025 claim | C2 |
| `CONTRADICTED_BY` | Memory that revises itself | C2 |
| `Checkpoint` and `CaseEvent` chain | Resume after a crash, and an audit trail | C3 |
| `RecItem-[:CITES]->node` | Every recommendation line is a graph path | C4 |
| Tenant-free memory | Shared learning without leaking cases | C6 |
