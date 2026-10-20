# 04 — Agents, Coordination, and Memory

> **Status (updated 17 Oct 2026): planning-era design with as-built changes.**
>
> - **Models and LLM use.** Groq `openai/gpt-oss-120b`, only in Intake for a notice that cites no section. If the LLM is unavailable, nothing is inferred from similarity alone: the claim goes to a person.
> - **Intake escalates (NEEDS_HUMAN) when:** the reason is `UNKNOWN` or low-confidence; the LLM is unavailable; the cited section is not in the governing policy; the cited section does not govern this service or reason; the notice does not name this insurer or plan; or the section's implied reason is not among the notice wording's three nearest reason profiles (a contradiction). On the 23 seeded notices that cite a section the implied reason ranked first or second.
> - **Planner.** Publishes graph templates and reviewed playbook steps. Optional drafts (`PLANNER_DRAFT_AUDIT=1`) are audited and never published as prose. The citation guard checks membership of IDs, which is not entailment: a valid ID cannot make unsupported advice true.
> - **Lease contract.** A write is accepted only while the writer still holds the lease: same owner, same `lease_gen`, not expired by the database's clock, checked in the same query that writes. A lapsed lease cannot be renewed. A restarted worker that reuses a name is a different incarnation (new `lease_gen`). Tests pause a living worker past its lease (`tests/test_stale_workers.py`).
> - **Curator.** Deterministic finding ids, counters derived from linked resolutions, and every memory write fenced through `FencedGraph`. Interrupted after each statement, a replacement converges to the same state (tested).
> - **Policy changes in flight.** A claim is pinned at Intake to the version in force on its service date; publishing a later version never rewrites its outputs (tested at four points in the pipeline).
> - **Human gate (Supervisor module).** `approve`, `record_outcome`, `correct_classification` (operator reclassifies a notice; the claim resumes at Retrieval with everything computed after classification removed), `declare_evidence` / `withdraw_evidence` (documents are declared, never verified; a claim already planned is re-planned).

## 1. Design principles

1. **The graph is the only shared state.** There is no agent-to-agent messaging, no shared session, no queue, and no cache. Each agent reads its input from FalkorDB and writes its output back.
2. **Stateless steps.** Each step starts with an empty context, builds working memory from the graph, does one unit of work, commits, and forgets. That's why any worker can resume any claim.
3. **The LLM handles language; the graph handles facts.** LLMs extract structure from text and phrase explanations. Version selection, applicability, evidence gaps, and memory updates are deterministic Cypher.
4. **Nothing uncited leaves the system.** A guard rejects any recommendation line without a graph citation.
5. **A human approves.** No claim is marked approved by an agent.

## 2. The roster

| # | Agent | Input state → output state | Replicas | LLM? |
|---|---|---|---|---|
| 1 | **Intake** | RECEIVED → CLASSIFIED | 2 | Yes: structured extraction (Haiku, escalating to Sonnet on low confidence) |
| 2 | **Retrieval** | CLASSIFIED → RETRIEVED | 1 | Optional: one-line similarity rationale (Haiku) |
| 3 | **Policy Verifier** | RETRIEVED → VERIFIED | 2 | No for decisions. Haiku phrases the rejection explanations. |
| 4 | **Resolution Planner** | VERIFIED → PLANNED → AWAITING_REVIEW | 1 | Yes: checklist and next-steps wording (Sonnet), constrained by the guard |
| 5 | **Memory Curator** | VERIFIED_OUTCOME → CURATED, plus the version-change job | 1 | Optional: Finding statement wording (Haiku) |
| — | **Supervisor** | Leases, approvals, worker control | 1 | **No** (infrastructure, not an agent) |
| — | **Baseline RAG** | Evaluation only | — | Yes: same model and output schema as the Planner |

## 3. Worker skeleton (`agents/base.py`)

Every agent subclasses one `Worker` and implements `work(ctx) -> StepResult`.

```
loop forever:
    heartbeat()                                   # MERGE WorkerHeartbeat {agent_id}
    claim = try_claim(input_state)                # atomic lease query (05 §Q7)
    if none: sleep(POLL_S); continue
    write_event(claim, "CLAIMED" | "RESUMED", attempt)
    cp = load_checkpoint(claim)                   # resume point, may be None
    ctx = build_context(claim, cp)                # working memory = graph reads only
    start heartbeat thread: every HEARTBEAT_S extend lease (only if still owner)
    try:
        result = work(ctx)                        # tools + optional LLM
        commit(claim, result)                     # ONE Cypher transaction:
                                                  #   write outputs, events, Checkpoint,
                                                  #   set status=next, clear lease
                                                  #   WHERE lease_owner = me   ← fencing
    except Recoverable: release lease, attempt+1
    except Unrecoverable / attempt > 3: status = NEEDS_HUMAN
```

### Correctness guarantees
- **Mutual exclusion:** the claim query is one atomic write (`WHERE lease_owner IS NULL OR lease_until < $now`).
- **Fencing:** `commit` only applies `WHERE c.lease_owner = $me AND c.status = $input_state`. A worker that was presumed dead and wakes up late can't overwrite the new owner's work. Show this in a test.
- **Idempotency:** outputs are `MERGE`d on deterministic keys (`claim_id:step`, `claim_id:seq`), so a retried step can't duplicate nodes.
- **Crash at any point:** before commit, nothing is visible and the lease expires so someone else redoes the step. After commit, the next role picks it up. There is no partial state in between.

### Checkpoint use for long steps
The Planner and Intake can write an **intermediate checkpoint** (for example, "LLM extraction done, validation pending") so a replacement doesn't repeat the expensive LLM call. That's the visible "resumed from checkpoint, skipped 1 LLM call" moment in the demo.

## 4. Agent specifications

### 4.1 Intake
- **Reads:** Claim, DenialNotice text, Evidence summaries, the taxonomy.
- **Does:**
  1. The LLM extracts `{denial_reason_guess, service_category, cited_section, cited_text_snippet, is_emergency_mentioned, in_network_mentioned, confidence}` using a JSON schema.
  2. A cross-check runs a vector search of the notice embedding against `DenialReason` embeddings (05 §Q2). It compares the cited section against `Clause.section` in the governing version.
  3. Agreement means accept. Disagreement means the graph's cited clause wins if found. Otherwise it reruns with Sonnet. If still unresolved, the status is NEEDS_HUMAN.
- **Writes:** `(Claim)-[:DENIED_FOR]->(DenialReason)`, `(DenialNotice)-[:CITES]->(Clause)`, the flags, and a `CLASSIFIED` event with the extraction JSON.

### 4.2 Retrieval
- **Reads:** classified claim.
- **Does:** Q3 graph candidates (same reason, plus lineage neighbors and the SUPERSEDES chain), plus Q2b vector neighbors of the notice text, **only as recall**. It merges them and ranks by graph closeness first, then similarity.
- **Writes:** `(Claim)-[:CONSIDERED {verdict:'CANDIDATE', source:'graph'|'vector', score}]->(Finding)` for the top N (≤ 8), and a `RETRIEVED` event.

### 4.3 Policy Verifier (the most important agent)
- **Reads:** candidates, claim flags, and the governing version.
- **Does, for each candidate (Q4, all in Cypher):**

| Check | Fails as |
|---|---|
| Finding lineage is the claim's cited lineage | `LINEAGE_MISMATCH` |
| Finding `VALID_IN` the claim's governing version | `VERSION_DRIFT` (and returns the superseding clause) |
| Finding status is not CONTRADICTED | `CONTRADICTED` (returns the contradicting Resolution) |
| Finding condition flags (`req_emergency`, `req_in_network`) hold for the claim flags | `CONDITION_UNMET` (returns which condition) |
| Claim filed within the governing timely-filing limit | `NO_VALID_PATH` |

- **Writes:** updates the `CONSIDERED` edges with `verdict: ACCEPTED|REJECTED` and `reason_code`. It also stores the evidence path nodes in the event payload, so explanations are exact. Haiku turns each rejection into one readable sentence, using only the returned fields.

### 4.4 Resolution Planner
- **Reads:** accepted Findings, recommended Playbooks, clause `REQUIRES`, and claim evidence.
- **Does:**
  1. Q5 evidence gap = required (clause + Finding + Playbook step) − submitted.
  2. Disposition: `APPEAL_VIABLE`, `APPEAL_NEEDS_EVIDENCE`, or `NO_BASIS_ESCALATE` (same rule as ground truth).
  3. Sonnet drafts the plain-language checklist from a **typed input** (gap list, playbook steps, rejections). Each output item must reference `cite_ids`.
  4. **Citation guard (`guard.py`):** every item's `cite_ids` must exist in the graph and must have been returned by this claim's verified context. Items that fail are dropped, and failures are counted. If a required item gets dropped, a deterministic template takes over.
- **Writes:** `Recommendation`, `RecItem`s with `CITES` edges, `confidence`, and an `uncertainty` list (for example, "contradicting case exists", "only 2 supporting cases"). The status goes to AWAITING_REVIEW.

### 4.5 Memory Curator
Runs in two modes.

**A) After a verified outcome** (human approves and records the real outcome):
- `MERGE` a Finding keyed on `(reason, lineage, sorted needed evidence, conditions)`.
- Same outcome as the Finding: `support+1`, `wins+1`, and add `VALID_IN` for this version.
- Opposite outcome under the same conditions: add `CONTRADICTED_BY` and recompute confidence. If contradictions ≥ wins, set status `CONTRADICTED`.
- Update `Playbook.uses/wins`.

**B) Policy version change** (`make add-version` or the demo button "Publish 2026 policy"):
- For every clause whose `params` differ from the clause it `SUPERSEDES`, find the Findings `ON_LINEAGE` of the old clause (Q6).
- Do **not** extend `VALID_IN` to the new version. Add `STALE_BECAUSE` pointing to the new clause.
- Set `status = STALE` if the Finding is no longer valid in the **latest** version. It still applies to claims governed by older versions, because applicability is decided by `VALID_IN`, not status.

### 4.6 Supervisor (deterministic)
- **Lease reaper:** every 2 seconds, it finds claims with `lease_until < now` and writes a `LEASE_EXPIRED` event (the reclaim itself happens naturally in Q7). This makes the handoff visible in the timeline.
- **Approval gate:** the only component allowed to move AWAITING_REVIEW → APPROVED, and only through an authenticated API call from the human reviewer UI.
- **Worker control:** list, kill, and start workers (Docker API or PID registry). Kill is a real `SIGKILL`.
- **Stuck detection:** if a claim exceeds the maximum attempts, it moves to NEEDS_HUMAN.

## 5. Memory model

There is no in-process or session memory between agents. Everything persistent is in FalkorDB.

| Memory type | Graph representation | Written by | Read by |
|---|---|---|---|
| **Working** | Assembled per step from the graph and then discarded | — | Each agent |
| **Checkpoint** | `Checkpoint` chain on a claim | All agents | The resuming agent |
| **Episodic** | `CaseEvent` chain, `DenialNotice`, `Evidence`, `Resolution` | All agents and humans | UI timeline, Curator |
| **Semantic** | `Finding` (+ `VALID_IN`, `CONTRADICTED_BY`, `STALE_BECAUSE`) | Curator | Retrieval, Verifier, Planner |
| **Procedural** | `Playbook` and `PlaybookStep` with uses and wins | Seed, Curator | Planner |
| **Per-tenant** | Case subgraph anchored at `Tenant` | Intake (live claims) | Tenant-scoped tools only |
| **Shared (anonymized)** | Findings and Playbooks, which have no tenant edges | Curator | Everyone |

### "Second session is smarter" demo (claim C1)
1. Eval claim A (sleep study retro-auth, which has no Finding yet) gets a cautious, low-confidence plan.
2. A human approves and records OVERTURNED. The Curator creates or strengthens the Finding.
3. Eval claim B (similar) now gets the Finding as an accepted precedent, with higher confidence and a shorter checklist.
4. Restart all containers and run B again. The result is the same, because the memory lives in the graph.

## 6. LLM usage details

> **As built (Phase 2):** the LLM layer is provider-agnostic (`claimbridge/llm/`). `LLM_PLATFORM` selects Groq (default, `openai/gpt-oss-120b` with strict JSON-schema output), OpenAI, Claude (Anthropic SDK `messages.parse`) or `fake` for tests. LLMs are used in two places only:
> - **Intake**, for notices without a section number (`IntakeExtraction`, constrained to the taxonomy);
> - **Planner** wording (`PlanDraft`, citations checked by the guard).
>
> Retrieval, Verifier and Curator make no LLM calls. Findings statements are templated from structure. The table below is the original plan.

| Agent | Model | Output schema | Cost control |
|---|---|---|---|
| Intake | `claude-haiku-5-5`, escalating to `claude-sonnet-5-5` | `IntakeExtraction` (Pydantic) | Cache by `notice_id` hash |
| Retrieval | `claude-haiku-5-5` | `{rationale: str}` | Optional, can be off |
| Verifier | `claude-haiku-5-5` | `{sentence: str}` per rejection | Templates as fallback |
| Planner | `claude-sonnet-5-5` | `PlanDraft {items:[{kind,text,cite_ids}]}` | Cache by context hash |
| Curator | `claude-haiku-5-5` | `{statement: str}` | Template fallback |
| Baseline | `claude-sonnet-5-5` | Same `PlanDraft` plus disposition | Same caps |

- Prompts live in `llm/prompts/<agent>.md`, versioned in git.
- `LLM_MODE=cached` replays the recorded responses (keyed by prompt hash) for reproducible evaluation and a safe demo.
- Prompts give the model **IDs and fields from the graph** and require it to cite those IDs. They never ask it to recall policy rules.

## 7. Failure handling matrix

| Failure | Detection | Result |
|---|---|---|
| Worker crash mid-step | Lease expires | Another replica reclaims and resumes from the checkpoint. The timeline shows `LEASE_EXPIRED → RESUMED (attempt 2)`. |
| Late write from a "dead" worker | Fencing condition fails | The write is ignored and logged as `FENCED_WRITE_REJECTED` |
| LLM error or timeout | Exception | Retry with backoff ×2, then release the lease |
| LLM output fails the schema | Pydantic | One repair retry, then template or NEEDS_HUMAN |
| Uncited recommendation line | Guard | Line dropped and the counter incremented (reported in the evaluation) |
| Contradictory intake signals | Cross-check | Escalate to Sonnet, then NEEDS_HUMAN |
| FalkorDB unavailable | Connection error | Workers back off, and the API returns 503 |

## 8. Concurrency test (stretch, but cheap)
Start 3 replicas of each role, inject 30 claims, and randomly kill one worker every 10 seconds. Assert:
- every claim reaches AWAITING_REVIEW or NEEDS_HUMAN;
- each `(claim, step)` has exactly one committed output;
- the number of fenced writes rejected is greater than 0 (proving fencing worked).

Report the numbers in the README.
