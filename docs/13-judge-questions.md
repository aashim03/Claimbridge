# 13 — Questions a judge will ask, and candid answers

Written 17 Oct 2026 against the code as it stands. Each answer says what is true, what proves it, and what is still *not* defensible. Read it before presenting; if an answer here stops being true, change the answer, not the claim. Every participant should be able to explain these in their own words: an AI assistant wrote much of the code, and the rules require the team to understand it.

## 1. What happens with an unfamiliar insurer, an unknown clause or a contradictory notice?

The system models **one** insurer and plan, and it does not guess when a letter doesn't fit. Intake sends the claim to a person (`NEEDS_HUMAN`, with the reason in plain words) when:

- the cited section is not in the governing policy;
- the cited section exists but does not govern this service or denial;
- the notice cites a section number but never names this insurer or plan (a foreign insurer's "Section 4.2" must not be bound to ours);
- the section's implied reason is not among the notice wording's three nearest reason profiles (the letter contradicts itself);
- the reason is `UNKNOWN`, low-confidence, or the LLM is unavailable (similarity alone never establishes a denial).

Proof: `backend/tests/test_intake_consistency.py` (six letters, including a legitimate control that must still pass) and the pre-registered `data/scenarios/generalization.yaml`. A person can then classify the notice and resume the claim (`correct_classification`; the original notice is never edited).

**Not defensible:** these checks are heuristics. The contradiction test compares the notice's wording to nine reason profiles by vector similarity; it separated all 23 legitimate cited notices (rank 1 or 2 of 9) from three contradictory ones I wrote (rank 4 or worse), which is a small sample. A letter *written to pass* the checks is not ruled out. We did not test a second insurer's real notices, only one fictional plan.

## 2. Why does one successful outcome give a support score of 0.667?

It is **not** a probability and the UI says so. The score is a smoothed count, `(wins + 1) / (wins + losses + 2)`: one win and no loss is 0.667, two wins 0.75, one win and one loss 0.5. It is shown with its observed counts ("1 recorded win, 0 contradicted"). When nothing supports a precedent it is **absent** ("none yet"), never "0%". It gates no decision: dispositions come from clause gates and the evidence checklist only.

**Not defensible:** the score is uncalibrated; we have no real appeal outcomes to calibrate it against. A learned checklist item is an association from one recorded case, not proof that the document caused the outcome (the outcome form says so, and lets the reviewer record which documents they actually observed).

## 3. What stops someone supplying another tenant's ID?

In protected mode identity comes from a server-issued credential, never from `X-Tenant-Id` (ignored for tenants). Every claim-level endpoint answers 404 for another tenant's claim: detail, graph, packet, approval, outcome, evidence, filing, even creating a claim in another tenant's name. The cookie is HttpOnly, SameSite=Strict, scoped to `/api`; writes by cookie need a custom header. The event stream re-checks its credential every poll. Proof: `tests/test_access_matrix.py` (24 cases over real HTTP) and `scripts/access-matrix.mjs` (27 checks in a real browser against an isolated instance, including a credential revoked while a page is open and a cookie swapped in another tab).

**Not defensible:** tokens are static secrets, not an identity provider; there is no rate limiting, rotation workflow or audit of logins. **Demo mode is deliberately public:** every visitor gets operator controls. Shared findings reveal aggregate patterns (counts and outcomes); that is not a formal anonymization guarantee and small cohorts leak.

## 4. What if the Curator crashes after updating memory but before committing?

A replacement re-runs the step and converges to the same state. Learned findings have deterministic ids; playbook counters are derived from linked resolutions, not incremented; every memory write goes through `FencedGraph`, which checks the lease in the same query. Tested by interrupting the Curator after **each** statement boundary and comparing the final graph to an uninterrupted run (`test_curator_interrupted_after_every_statement_converges_to_one_correct_result`), and by a stale Curator whose lease lapsed trying to write (`test_stale_curator_cannot_mutate_memory_after_losing_its_lease`).

**Not defensible:** this relies on FalkorDB applying write queries to one graph one at a time (a single instance). It was not tested on a cluster or replicas.

## 5. Can a recommendation cite a real node and still be false?

Yes, in principle, and we say so. The citation guard checks that every cited ID exists in the set the graph returned for the claim; that is **membership, not entailment**. What stops invented advice is a different mechanism: the published plan is built from graph facts and reviewed playbook steps (templates), and a model draft, if enabled, is only audited against them and never published as prose. The evaluation's "items without valid citation IDs" row measures only the ID check and is labelled so.

**Not defensible:** a template is only as true as the data behind it. A precedent learned from one recorded case may overstate causation; the product labels such items "suggested by a precedent: an observed association, not a policy requirement", and the checklist, graph, replay and packet all agree on that wording.

## 6. Which parts can you explain and defend yourself?

Be able to draw and explain, without notes:

- **The graph model:** policy versions and clause lineages with content fingerprints; findings scoped by `VALID_IN`; why a text change (not only a number) invalidates memory; claims pinned to the version in force on the service date.
- **The coordination protocol:** a claim's status says which role may work on it; a lease says who is; leases use the database's clock; each acquisition bumps a fencing token; every write checks owner, token and expiry in the same query that writes; a lapsed lease cannot be renewed. It is at-least-once delivery with fenced commits, **not** exactly-once.
- **What is deterministic and what is the LLM:** the LLM reads a notice that cites no section. Version, applicability, gates, evidence gaps, memory updates and published plans are Cypher and templates.
- **What happens on an outage:** a notice that cites a supported section still works; anything else goes to a person.
- **How memory can be wrong:** version drift (refused with the clause that replaced it), contradiction by later outcomes (weakened, then refused), unmet conditions, a clause that changed text. Tested at four points of an in-flight policy publication: a claim is pinned and its outputs never change.

Do **not** claim: independent validation (the expected answers come from rules written by the same team; the unseen-case set was written by the AI assistant), real-world usefulness (no reviewer has used it), production security or privacy, that a graph database alone causes an accuracy gain (see the access table in the evaluation: rules, inputs, memory and prompts differ), or exactly-once processing.

## 7. Why FalkorDB, and why several workers?

Disable it and the pipeline stops: policy applicability is a traversal, evidence gaps are a query over clause and finding requirements, memory validity is a relationship to policy versions, and the workers coordinate only through it (leases, checkpoints, events). Several workers exist so that any replica can resume any claim from the graph after a failure; the evaluation kills workers at random, and a separate scenario pauses a living worker past its lease and shows its late writes rejected and audited.

## 8. Is the evaluation independent, and what does it prove?

No. The 34 claims are authored synthetic fixtures; the expected answers come from a rule engine written separately from the Cypher but by the same team. The evaluation compares whole systems (see the "what each system can see" table). Where decision correctness is equal between ClaimBridge and the no-memory ablation, memory contributes precedents and a changed checklist, not a measured improvement in decisions. The information-parity baseline (RAG given the same abstract findings) is the comparison that matters most; see the run notes in the promoted report for whether it ran. Nothing measures a real appeal.
