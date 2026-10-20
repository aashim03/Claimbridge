# ClaimBridge: pending work and completion plan

Prepared on 17 October 2026. This is a planning handoff, not an implementation report. No application changes are authorized by this document; the current request is to document the remaining work only.

> **Update, 17 Oct 2026 (evening): the engineering items below were completed.** Evidence and the remaining team-owned items are in [12-completion-report.md](12-completion-report.md). Items 13 (video), 14 (repository and submission) and 15 (independent usefulness) are not done and are the team's. The information-parity baseline in item 5 is implemented but did not run (provider daily limit). The checklist in section 18 is ticked accordingly. The text of this plan is otherwise left as written.

## 1. Honest current assessment

ClaimBridge has a working synthetic demonstration, substantive FalkorDB integration, version-aware memory, bounded workers, a review console, and meaningful automated checks. It is **not yet a finished submission**, and it is not a production insurance product.

The highest-value remaining work is to make the evidence trustworthy, correct the replay's explanation of learned evidence, verify the final access/recovery behavior, and finish the public submission package. Another visual redesign is not the immediate priority.

The earlier 70/100 was an informal assessment. There is no verified official numerical rubric supporting a promise of 95+/100. Completing this checklist can improve submission quality; it cannot guarantee a score or first prize. Technical reliability, demonstrated usefulness, originality, communication, and competing entries still matter.

Status vocabulary used below:

- **Confirmed gap:** missing artifact or behavior observed in the current repository.
- **Verification pending:** implemented behavior needs targeted validation; this is not a claim that it is broken.
- **Product limitation:** outside the current bounded prototype; either address it or describe the scope honestly.
- **Participant-owned:** requires the team's real identity, account, contribution statement, or submission action.

Priority definitions: **P0** before presenting the affected claim or submitting; **P1** strengthens the working product and demonstration; **P2** longer-term product work, not a prerequisite invented by this review.

## 2. What is already implemented

Do not rebuild these features from scratch. Verify and finish them.

| Area | Existing work | Remaining qualification |
|---|---|---|
| Graph workflow | Intake, Retrieval, Verifier, Planner, Curator and Supervisor use FalkorDB state | These are bounded workflow roles, not independently reasoning general agents |
| Policy applicability | Service-date version, clause lineage, conditions, contradiction and fingerprint checks | Concurrent policy changes need further validation |
| Published plans | Graph/templates constrain advice; arbitrary model prose is not published | Replay descriptions still contain incorrect provenance wording |
| Outcome memory | Confirmed outcomes update findings and subsequent evidence checklists | Observed evidence is an association, not proof of necessity or causality |
| Support score | Smoothed outcome support replaces immediate 100% confidence | Not calibrated approval probability; UI wording needs consistency |
| Access control | Protected credentials, scoped endpoints, operator actions, HttpOnly sessions | Browser/session boundary tests and operational hardening remain |
| Curator retries | Deterministic finding IDs, resolution-derived counters, fenced mutations | Broader expired-worker and partial-write races need validation |
| Unknown notices | UNKNOWN/low-confidence escalation and conservative outage behavior | Human correction/resume flow is missing |
| Review output | Downloadable cited Markdown packet | No actual insurer submission or document verification |
| Evaluation | Fixed denominator, separate decision correctness, tenant-filtered RAG, memory and chaos runs | Fairness, provenance, missing baseline outputs and publication remain unresolved |
| Delivery | Docker setup, CI definition, local browser smoke script | Clean checkout and remote CI not yet certified |
| Submission material | README and demo/submission guide revised; video scaffold and screenshots prepared | Finished video, public access and actual submission remain pending |

For change details, see [10-review-changes.md](10-review-changes.md).

## 3. Verification evidence and its limits

These are earlier observed results, not checks performed for this documentation-only request:

- Backend suite: **53 passed**, with four warnings, before the final completion-scoring change. That last change still needs relevant regression verification.
- Frontend: lint, TypeScript check and production build passed at the previously checked revision. Docker web build also passed after correcting a UTF-8 BOM in the snapshot JSON.
- Browser artifact: [smoke.json](../artifacts/browser/smoke.json) records **nine passing views**, including two mobile views, no horizontal overflow and no recorded JavaScript errors. This is shallow rendering coverage, not full user-flow or security coverage.
- New evaluation is in [eval/review/latest.json](../eval/review/latest.json), with raw outputs under `eval/review/raw/`. The report's timestamp is `2026-10-17T17:13:43`; it does not carry an explicit timezone suffix.
- The public-facing canonical results are still under `eval/results/`. Do not assume the newer review report is what the running API or website serves.

### Provisional review metrics

| System | Completion | Decision correctness | All-correct metric |
|---|---:|---:|---:|
| ClaimBridge | 100% | 100% | 100% |
| No-memory | 100% | 100% | 38.2% |
| Small-embedding RAG | 100% | Approximately 76% | 23.5% |
| Large-embedding RAG | 85.3% | 67.6% | 17.6% |

These are 34 authored synthetic cases, not independent real-world validation. The all-correct metric includes precedent matching, which a no-memory system cannot do by design. **The static decision metric currently shows no gain over no-memory.** The separate memory intervention shows a checklist change, not a measured improvement in actual appeal outcomes.

Five large-baseline outputs are missing: `EV-N-11`, `EV-N-12`, `EV-N-13`, `EV-M-A`, `EV-M-B1`. Missing outputs are penalized, but their cause must be reported rather than treated automatically as reasoning failures.

The chaos report records 12/12 completed and correct claims, ten worker kills, zero duplicate step outputs and approximately seven seconds mean recovery. It records **zero rejected fenced writes**, so it does not by itself prove that a stale living worker was prevented from writing.

## 4. P0: correct evidence provenance in the graph replay

**Status:** confirmed gap. **Files:** `web/lib/replay-engine.ts`, `web/lib/api.ts`; compare the source-aware output from `backend/claimbridge/tools/evidence.py` and `backend/claimbridge/api.py`.

The backend distinguishes policy-required evidence from evidence associated with a learned finding. The replay still constructs clause-to-evidence edges for all evidence and uses wording implying that all items are policy requirements. This can turn an observed itemized bill into a fictitious policy obligation.

Steps:

1. Carry each requirement's `sources` through the frontend API types.
2. Construct replay relationships from actual source IDs. A learned finding must point to its associated evidence; do not manufacture a clause requirement.
3. Separate policy requirements from suggestions learned from resolved cases in labels, details and narration.
4. Replace the generic emergency-only explanation for condition failures with the actual failed condition, including network status where applicable.
5. Replace legal-sounding language such as “good law” with applicability language appropriate to fictional insurance findings.
6. Compare the checklist, live graph, replay and downloaded packet for the same claim.
7. Add a focused regression for the learned-bill case and a non-emergency condition failure.

**Done when:** `EV-M-B2` cites the learned Finding for the bill, never presents it as a clause mandate, and all four representations agree. Unchanged policy requirements still cite their clauses.

## 5. P0: make the evaluation defensible

**Status:** confirmed reporting/methodology gaps. **Files:** `backend/claimbridge/evaluation/{baseline,harness,score}.py`, `backend/claimbridge/report.py`, `eval/review/`, `eval/results/`.

### 5.1 Freeze and identify the evaluated system

1. Finish intended correctness changes before starting the final benchmark.
2. Capture the source revision or complete source digest, dataset digest, configuration, model, embedding model, prompt versions and cache policy **at run start**.
3. Use a unique run ID and preserve the original raw predictions. Record start/end times with timezones.
4. Do not edit source while the run is in progress. Detect source changes and mark the run invalid if necessary.
5. Associate each token/cost record with the exact request/cache entry used in that run; do not infer it from the latest entry for a claim/task.
6. Distinguish fresh provider responses, cached provider responses and fake-model tests. The current review report identifies `llm_mode` as `cached`.

**Why:** current hashes are captured when results are saved, and source changed during the earlier evaluation. Different hashes occur across its systems. The existing artifacts cannot certify one frozen implementation.

### 5.2 Resolve the information-access confound

1. List exactly which clauses, raw tenant cases and abstract findings each system can access.
2. Preserve tenant filtering for every baseline.
3. Add a comparison where RAG receives the same permitted abstract finding facts as ClaimBridge, or explicitly separate comparisons by information access.
4. Check whether ground-truth precedent IDs can actually be recovered from the baseline's permitted corpus. Do not penalize inability to cite an inaccessible record as pure retrieval weakness.
5. Report decision accuracy, evidence accuracy, applicable-memory retrieval and completion separately.
6. Retain no-memory as an ablation, but explain its 100% static decision correctness beside its lower precedent-inclusive score.
7. Describe the comparison as whole-system unless rules, inputs, memory, prompts and compute are controlled closely enough to isolate a narrower cause.

**Done when:** a reader can understand whether a performance difference comes from information access, deterministic rules, retrieval, prompts, provider availability or graph operations. Do not advertise the current gap as proof that FalkorDB alone improves accuracy.

### 5.3 Account for missing outputs and scoring semantics

1. Inspect raw errors for the five missing large-baseline claims; distinguish provider limits/timeouts, parser failures and model failures.
2. Use the same documented retry/budget policy for comparable systems.
3. Preserve the incomplete run. If rerunning, issue a new run ID rather than silently replacing failed predictions.
4. Verify the last scoring change: a completed result needs a disposition and must not be `NEEDS_HUMAN` under the current metric definition.
5. Report appropriate escalation separately. Safe abstention on unsupported inputs should not be confused with a crash, even if counted as incomplete in a particular benchmark.
6. Check stale-avoidance denominators so missing outputs do not receive credit for avoiding a wrong citation.
7. Retain the accurate label “items without valid citation IDs”; a valid ID alone does not establish semantic entailment.
8. Replace report wording that describes a synthetic recorded outcome as a “real outcome.” Describe the ground-truth rule engine as separately implemented, not externally independent validation.

**Done when:** totals, denominators, missing reasons and metric definitions reconcile with raw outputs, and the final scorer is verified.

### 5.4 Add evidence beyond authored happy paths

1. Ask a teammate to author unseen cases without copying expected results from implementation rules.
2. Include contradictory section references, unknown reasons, negation, non-emergency/network variants, boundary service dates and policy text/evidence changes.
3. Establish expected answers before running the system; record review disagreements.
4. Keep this set separate from fixtures used while fixing the product.
5. Report sample size and failures honestly. A small independent synthetic set remains synthetic.

**Done when:** the submission includes at least one clearly separated generalization check, or explicitly states that none was performed.

## 6. P0: publish one consistent set of results

**Status:** confirmed gap. Depends on section 5.

1. Archive existing `eval/results/` with a clear revision/run identifier.
2. Promote only the reviewed final report and its matching raw outputs into the canonical location.
3. Rebuild/restart the relevant application services so the results endpoint serves those artifacts.
4. Compare the endpoint, results page, README, submission description and video numerically.
5. Show run identity, date, data scope, cache mode and limitations alongside the results.
6. Remove stale headline percentages and unsupported causal claims from older documentation or label those documents historical.

**Done when:** every public surface refers to the same run, and a judge can navigate from a number to raw evidence. Do not simply copy the provisional review report to make this box green.

## 7. P0: validate protected sessions and tenant boundaries

**Status:** implementation exists; browser and lifecycle verification pending. **Files:** `backend/claimbridge/auth.py`, `api.py`, frontend session gate and API client.

1. Use an isolated protected instance with an operator and two tenant identities, all containing only synthetic data.
2. Test login failure, successful login, logout, reload and account switching in the real browser.
3. Confirm that cached claims, graphs and packets disappear when switching identities.
4. Request another tenant's known claim ID through detail, graph, packet, events and mutation endpoints; verify the documented denial behavior.
5. Spoof `X-Tenant-Id` and verify that credentials still determine identity.
6. Test operator-only actions directly through HTTP as a tenant; hidden navigation is insufficient.
7. Test missing/invalid credentials, cookie mutation headers and malformed protected configuration.
8. Inspect an already-open event stream after logout, credential revocation or session expiry. Define and verify its intended lifetime.
9. Review aggregate findings, global worker metadata and internal cross-tenant retrieval against the intended sharing policy. Document what is shared; do not claim every graph fact is tenant-private.
10. For any HTTPS deployment, verify secure cookie and proxy behavior in that environment.

**Done when:** a repeatable browser/API matrix passes, no previous identity's data survives account switching, and shared metadata boundaries are explicit. This does not establish formal anonymization or production security.

## 8. P0: prove expired-worker and policy-change behavior

**Status:** targeted verification pending; not a demonstrated exploit. **Files:** `backend/claimbridge/tools/__init__.py`, `tools/coordination.py`, `agents/base.py`, `agents/curator.py`, `tools/versions.py`.

The generic fence currently checks lease owner; some commit/heartbeat paths do not explicitly check expiry. Curator mutation fencing is stronger. Hard-killing a process does not test a paused process that later wakes up.

1. Pause a worker after acquiring a lease, let the lease expire, then resume it before and after another worker takes ownership.
2. Assert that expired work cannot mutate state, append outputs or commit checkpoints contrary to the chosen lease contract.
3. Check same-owner reuse after restart. Use a lease generation/fencing token if worker-name equality cannot distinguish acquisitions.
4. Validate that mutation and fencing checks are atomic at the graph operation boundary.
5. Interrupt curator work between individual statements, retry, and verify one logical finding, correct counters and repaired relationships.
6. Publish a policy change while verification/planning is in flight. Define whether the claim uses a pinned version or revalidates, then assert that every output follows that rule.
7. Rerun chaos testing and add a deliberate rejected-stale-write scenario; retain audit evidence.

**Done when:** tests exercise a living stale worker, partial curator writes and concurrent policy publication, rather than inferring these guarantees from the existing kill test.

## 9. P1: complete the human review loop

**Status:** confirmed product gaps. Do not expand into arbitrary PDF ingestion just to make the interface look complete.

### Human correction and resume

1. Add a clear reason for `NEEDS_HUMAN` and show the information needed to proceed.
2. Define which authenticated role may correct intake fields.
3. Preserve the original notice and append the correction, reviewer identity and time to the audit history.
4. Invalidate affected downstream outputs and resume from the appropriate checkpoint.
5. Test that an unauthorized user cannot correct a case and that repeated corrections do not retain stale advice.

**Done when:** an unknown notice can be reviewed and safely resumed, or the product explicitly explains that escalation ends the supported demo workflow.

### Evidence updates after filing

1. Define the supported evidence metadata fields and who can add/remove them.
2. Add an authenticated update flow with an audit record; distinguish declaring evidence present from verifying a document.
3. Recompute evidence gaps and affected recommendations after an update.
4. Preserve the distinction between policy-mandated and learned suggested evidence.
5. Test a case moving from missing evidence to review-ready without losing its history.

**Done when:** a reviewer can resolve the checklist in the app, or that limitation is stated clearly. File upload/OCR remains separate scope.

## 10. P1: strengthen memory quality and wording

**Status:** partly implemented; broader validation and presentation pending.

1. Show observed supporting/contradicting counts beside the smoothed support score.
2. Prefer an explicit “no supporting outcomes yet” state over language that could make 0% look like an appeal success estimate.
3. Remove awkward universal “Could be wrong if” phrasing when the item is actually a definition of the support score.
4. Make outcome confirmation explicit about which evidence the reviewer actually observed; avoid implying that inferred required evidence caused the outcome.
5. Demonstrate duplicate confirmation, contradictory outcome, changed evidence requirement and changed policy text cases.
6. Verify that learned recommendations remain conditional and withdraw or weaken appropriately when contradicted or invalidated.
7. Describe the memory intervention accurately: a recorded association changes a later checklist. Actual usefulness needs external evaluation.

**Done when:** UI, packet, graph and demo consistently distinguish observation, applicability, policy requirement and uncertainty.

## 11. P0: finish runtime and clean-install verification

**Status:** builds passed earlier; final environment verification pending.

1. Review the existing uncommitted changes and preserve work before changing runtime state.
2. Verify active Docker port mappings. Compose was changed to bind database/browser/API ports locally, but the existing database container had not been recreated at the last runtime check.
3. Recreate only the necessary services in a planned window, preserving required volumes. Do not use volume deletion as routine troubleshooting.
4. Investigate the reported orphan role containers before removing anything; establish whether they are active workers against the demo graph.
5. Rehearse initial startup from a fresh checkout using `.env.example`, including model download requirements and unavailable provider behavior.
6. Verify no-provider recorded demo replay and honest escalation for an uncached new notice.
7. Run evaluation against an isolated graph. Seed/reset operations must not unexpectedly wipe the rehearsed demo state.
8. Run final backend tests, frontend lint/type/build and actual browser action flows after all intended edits.
9. Fix the smoke script's graph-play selector if it does not match the rendered control. A passing screenshot does not establish that animation controls worked.
10. Run the GitHub workflow on the submitted revision and inspect its logs; the existence of YAML is not a passing CI run.
11. Check lockfiles and image versions for reproducibility. Consider excluding video work products from the root Docker build context as they grow.

Future verification commands, **not executed as part of this document**:

```powershell
# From backend; FalkorDB must already be available.
uv sync --frozen
uv run pytest -q

# From web.
npm run lint
npx tsc --noEmit
npm run build

# From the repository root, against the running local app.
node scripts/browser-smoke.mjs
```

The documented benchmark command is `uv run python -m claimbridge.cli eval all` from `backend`. Set a dedicated `GRAPH` value first; evaluation resets its configured graph. Confirm available CLI options before choosing final run/output settings.

**Done when:** a second person can reproduce the documented demo without access to the developer's existing containers, environment secrets or unexplained local state.

## 12. P0: synchronize documentation and participant claims

**Status:** confirmed documentation drift. **Files:** `README.md`, `docs/00` through `docs/09`, `docs/README.md`, root idea/assessment documents.

1. Mark planning-era documents as historical or update them to the actual implementation.
2. Reconcile model/provider names, deterministic planner behavior, fingerprint inputs, support formula, privacy boundaries and current evidence scenario.
3. Update the core Cypher walkthrough to match executable queries, including fences and source provenance.
4. Correct old evaluation claims, including privacy comparisons, unsupported-text claims and percentages.
5. Update documentation navigation to include the review changes and this pending-work plan.
6. Check rendered UTF-8 text; distinguish actual encoding damage from PowerShell display artifacts before rewriting files.
7. Keep AI assistance disclosure and participant contributions factual. Each teammate should review and be able to explain the parts credited to them.
8. Check current organizer requirements at submission time; do not infer requirements from an old project plan.

**Done when:** the README, architecture, query examples, evaluation report and demo describe the same product.

## 13. P0: produce the actual working-project video

**Status:** confirmed missing deliverable. **Location:** `videos/claimbridge/`.

What exists: a HyperFrames scaffold, brief, frame direction, local screenshots and media records. Automated page capture attempts were blocked with HTTP 403; separate Chrome screenshots were captured successfully. These are inputs, **not a completed video**. There is no verified final MP4 or public video link.

Steps:

1. Resolve the difference between the 90-second video brief and the longer demonstration script. Choose one scope and duration deliberately; no official maximum was established in the earlier rules review.
2. Correct the brief's palette assumptions to match the actual dark product UI.
3. Write a concise storyboard showing problem, policy drift rejection, memory before/after, worker recovery and an inspectable result.
4. Record actual interactions and state changes where needed. Still screenshots alone are weak evidence that the workflow operates.
5. Use the corrected provenance UI and final evaluation numbers only.
6. Build the scenes and captions; distinguish fictional outcomes, cached runs and live actions.
7. Check readable text, timing, clipping, safe margins and visual consistency. A silent captioned video is acceptable as a production choice if understandable.
8. Follow the selected video workflow's preview/approval requirements before final rendering; this planning document grants no rendering or publishing action.
9. Render, watch the entire output and verify that all shown behavior matches the submitted revision.
10. Host the final file, verify logged-out access and paste the actual URL into submission materials.

**Done when:** a judge can open and watch a finished video demonstrating the working project. A scaffold, failed capture, screenshot directory or local MP4 without the required accessible link does not complete this item.

## 14. P0: public repository and submission

**Status:** unverified or not completed; participant-owned final steps.

Official references: [hackathon overview](https://www.wemakedevs.org/hackathons/falkordb) and [rules](https://www.wemakedevs.org/hackathons/falkordb/rules). The earlier review recorded an October 15–18, 2026 event window ending at 11:59 PM IST on October 18, teams of 1–4, central FalkorDB use, public code, setup/graph documentation, core queries, a working-project video, deployment or complete local setup, track identification and AI disclosure. Recheck organizer updates before submitting. No official weighted 100-point rubric was established.

1. Review the exact files to commit. Exclude credentials, `.env` variants containing secrets, caches, irrelevant artifacts and oversized generated media; keep sanitized `.env.example`.
2. Inspect repository history for accidentally committed credentials before making code public. Rotate actual exposed credentials if any are found; do not assume a leak without evidence.
3. Commit the reviewed project and reference the exact revision in evaluation/submission materials.
4. Verify anonymous access to `https://github.com/Atheeq1821/claimbridge`. An earlier unauthenticated 404 leaves visibility unverified; it does not prove why access failed.
5. Confirm README setup, graph model and executable core-query links work from that public revision.
6. Select Track 02 unless the team deliberately chooses additional eligible tracks after checking the rules.
7. Choose a verified live deployment or the fully rehearsed local setup alternative. A live URL was not established as mandatory when complete local setup is supplied.
8. If deploying, use synthetic data, correct access mode, HTTPS and intentional public controls. Re-test the hosted environment rather than relying on local checks.
9. Supply the actual team members, contribution statement and AI disclosure. Do not fabricate participant work or eligibility history.
10. Add the accessible video link and any required project fields, submit through the organizer's form, and retain the confirmation.
11. Verify links from a logged-out browser after submission.

**Done when:** submission confirmation exists, every required link is accessible and the submitted materials correspond to the tested revision. A prepared README is not a submitted entry.

## 15. P1: demonstrate usefulness and prepare for judge questions

**Status:** product validation gap. No real insurer/user study has been established.

1. Ask a small number of independent reviewers to complete the fictional policy and memory scenarios without coaching.
2. Record task completion, misunderstood labels, time spent locating evidence and concrete feedback. Describe the sample honestly.
3. Ask whether the extra learned evidence item is useful or creates unnecessary work; do not assume a changed checklist is automatically an improvement.
4. Fix high-impact confusion, or disclose it if time is insufficient.
5. Rehearse explanations of why FalkorDB is load-bearing: version applicability, evidence paths, memory invalidation, persistent checkpoints and worker coordination.
6. Prepare direct answers to: why multiple workers; what uses an LLM; what is deterministic; what happens on outage; how memory can be wrong; how tenants share safe abstractions; why the benchmark is limited.
7. Demonstrate at least one failure/abstention honestly, rather than showing only ideal seeded cases.

**Done when:** the team can explain both the technical mechanism and its practical limitations without relying on self-authored “best product” claims.

## 16. P2: production roadmap, outside the hackathon completion gate

These are real limitations, not additional official submission requirements:

- Managed identity, credential rotation/revocation, rate limits and operational audit controls.
- Formal privacy design for shared findings, small cohorts and aggregate inference.
- Encryption, retention/deletion, backup/restore, monitoring and incident handling.
- Verified document intake/OCR, malicious-document handling and evidence authenticity.
- Broader policy ingestion, multiple insurers, reliable change review and jurisdiction-specific workflows.
- Real reviewer correction tools, notification/reminder delivery and external submission integrations.
- Independently reviewed domain accuracy, user research and outcome-based benefit measurement.
- Load testing, bounded queues, provider budgets and measured operational reliability.

Do not label the current application production-ready merely because the hackathon checklist is complete.

## 17. Recommended execution order

| Order | Work | Dependency / reason |
|---|---|---|
| 1 | Correct graph replay provenance | Prevents a false policy explanation in every demo |
| 2 | Validate tenant sessions, stale workers and policy changes | Establishes whether strong reliability claims are justified |
| 3 | Fix evaluation design, missing-output accounting and run provenance | Needed before credible headline numbers |
| 4 | Freeze source, verify scorer, run final evaluation | Produces traceable evidence |
| 5 | Publish matching results and synchronize docs | Prevents contradictory claims across surfaces |
| 6 | Clean-install, browser action and CI checks | Verifies the submitted revision is reproducible |
| 7 | Record/render/host the working-project video | Requires stable behavior and final results |
| 8 | Verify public repository and submit | Completes the actual entry |
| 9 | Human correction/evidence loop and external feedback | High-value product improvements if time permits |

If time is short, reduce feature scope. Do not cut provenance correctness, honest evaluation caveats, required public artifacts or submission verification to add decorative features.

## 18. Final acceptance checklist

- [x] Learned evidence is never mislabeled as a policy requirement.
- [x] Protected browser sessions and tenant/operator boundaries are verified.
- [x] Expired-worker behavior and in-flight policy changes have targeted evidence, or unsupported guarantees are removed.
- [x] Final scoring changes are verified; missing results and safe abstentions are explained.
- [ ] Final evaluation has a frozen source/data/config identity and honest baseline access rules. (Frozen identity and access table: done. The information-parity baseline did not run.)
- [ ] README, results UI, reports and video use the same reviewed numbers. (README and results UI refer to the promoted run; the video does not exist yet.)
- [ ] Clean checkout startup and the final CI revision pass. (Clean-folder startup rehearsed; remote CI not run.)
- [x] Runtime ports, containers and demo reset behavior match the documentation.
- [x] Core queries and graph model documentation match executable code (as-built tables at the top of docs 02 and 05; the source is authoritative).
- [ ] Finished working-project video is accessible without team credentials.
- [ ] Public repository access is verified anonymously.
- [ ] Team contributions, AI disclosure and track are accurate.
- [ ] Organizer form is submitted and confirmation retained.
- [x] Remaining prototype limitations are visible, with no unsupported 95+/100 or winning claims.

Completing these boxes establishes a reviewable hackathon submission within its stated scope. Production readiness and a prize remain separate questions.
