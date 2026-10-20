# Changes after the judge review

The original 70/100 was an informal review score, not an official result. These changes address defects; they do not establish a 95/100 score or a probability of winning.

| Review finding | Implemented response |
|---|---|
| Tenant header was not an identity boundary | Protected credentials; scoped claims, events and packets; operator-only controls |
| Valid citation could carry invented advice | Publish graph templates and reviewed playbook steps; optional draft audit |
| One outcome produced 100% confidence | Smoothed outcome support, explicitly not a probability |
| Memory changed confidence, not work | Confirmed outcome evidence changes the next checklist and cites the Finding |
| Curator retry double-counted use | Resolution-derived counters, deterministic IDs, lease-fenced mutations |
| Staleness compared only numeric parameters | Fingerprint includes text, evidence, routing and gates |
| Baseline privacy comparison was unfair | Tenant-filter before prompting; access control is not a graph advantage |
| Missing benchmark outputs disappeared | Fixed denominator and completion metric |
| No-memory scoring penalized absent findings | Separate decision correctness from precedent recall |
| Approval implied external submission | Review-only wording and downloadable cited packet |
| Unknown notices forced into taxonomy | UNKNOWN/low-confidence escalation; no similarity-only outage fallback |
| Docker context included dev environments | Root `.dockerignore`; database/API ports bind locally |

Behavioral checks live in `backend/tests/test_hardening.py`. They use real FalkorDB and a fake LLM. The provider-backed benchmark is reported separately.

Remaining limitations: no real insurer/user validation; one authored plan; no arbitrary document ingestion; no formal aggregate privacy guarantee; no insurer submission integration. Explicit section routing is deterministic, not robust against every malicious or contradictory notice. The RAG comparison is a whole-system comparison, not a controlled database ablation.

Participant-owned steps: verify anonymous repository access, host the final video, register and submit the actual team, describe real contributions, and rehearse the core queries. AI-generated claims cannot establish participant ownership or understanding.

## Completion pass (17 Oct, evening)

The remaining items of `11-pending-work-and-completion-plan.md` that an engineer can do alone were done; see `12-completion-report.md` for the evidence and for what remains participant-owned.

| Finding | Response |
|---|---|
| Replay explained learned evidence as a clause mandate | Provenance carried through the API, graph, replay, checklist and packet |
| Fence checked owner only | Owner + fencing token + database-clock expiry in the writing query; tested with a living paused worker |
| Evaluation could not certify one frozen implementation | Per-run directories, digests, a call ledger, never-overwritten output, invalidation, promotion guard |
| Plain RAG was compared on unequal information | Access table, reachable recall and an information-parity baseline |
| Missing outputs were unexplained | Each carries a classified cause; abstention and no-output are separate; no-output earns no credit |
| Sessions and boundaries were unverified in a browser | A 27-check matrix against an isolated protected instance |
| NEEDS_HUMAN was a dead end | Operator correction with audit, resume at Retrieval, nothing stale kept |
| Evidence could not be updated after filing | Declare / withdraw with audit; declared is never verified; the plan is recomputed |
| Support score could read as a probability | Absent when there is nothing to count; counts beside it; wording consistent everywhere |
