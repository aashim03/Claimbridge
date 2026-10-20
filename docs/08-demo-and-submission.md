# Submission and demonstration guide

Tracks: **02 — Agent Memory and Coordination** (primary) and **01 — Agents That Act on Connected Data**. Name both at submission, and confirm with the organizers (Discord) that one project may enter two tracks. See [14-track-assessment.md](14-track-assessment.md).

## Organizer requirements

Checked October 17, 2026 against [official rules](https://www.wemakedevs.org/hackathons/falkordb/rules) and [track focus](https://www.wemakedevs.org/hackathons/falkordb).

Required: central FalkorDB use, public source, README with setup and graph model, core queries, a working-project video, and deployment or complete local setup. Name the entered track. Teams have at most four people. Main implementation must be within the event window; synthetic data is permitted. Disclose AI assistance. Participants must understand and meaningfully contribute to or verify the work. Deadline: **October 18, 2026, 11:59 PM IST**.

The published pages have no numerical judging weights. Our review score is not an official assessment. No official four-minute video cap was found; the duration below is an editorial choice.

## Suggested three-minute live demo

| Time | Show | Demonstrate |
|---|---|---|
| 0:00–0:20 | Docket | Current terms, relevant outcomes and an auditable checklist. Fictional data only. |
| 0:20–0:55 | EV-T1-01 graph and plan | Reject the 2025 MRI referral precedent under the 2026 clause. Show VERSION_DRIFT and source IDs. |
| 0:55–1:45 | B1, outcome A, then B2 | Confirm attestation and itemized bill on A's overturned outcome. B2 now asks about the missing bill and cites learned memory. One win is an association, not causal proof. |
| 1:45–2:15 | Agents and recovery | Kill a leased worker, start a replacement, show RESUMED and one committed step. A kill after commit interrupts no work. |
| 2:15–2:35 | Policy publish | Changed fingerprints invalidate findings; old-version validity remains. Rewind resets synthetic state. |
| 2:20–2:35 | New claim, and a notice it cannot read | Enter a claim, watch the replay; a nonexistent section stops with its reason and a person reclassifies and resumes. |
| 2:35–2:50 | Protected tenant session | Another tenant's claim returns 404. Tenant cannot control workers. Demo mode deliberately grants fictional operator access. |
| 2:50–3:00 | Evaluation and source | Actual measured results, no-memory decision metric, limits and reproducible local setup. |

Label provider recordings as recorded/cached. Graph queries and workers still execute, but a replay is not a fresh model call. A review packet is not sent to an insurer.

## Submission text

**ClaimBridge — versioned memory for claim review.** Five workers share FalkorDB as persistent state. Intake pins the governing policy and classifies a notice. Retrieval proposes findings; Cypher verifies version, lineage, conditions and contradictions. The planner publishes a cited checklist from graph facts. A reviewer records an outcome and the evidence observed; the curator updates reusable findings. Leases, checkpoints and fenced, idempotent writes support recovery after a crash.

The demo uses one fictional plan and synthetic claims. It shows policy invalidation, an outcome changing the next checklist, and recovery without duplicate learning. We compare complete systems against tenant-filtered RAG and a no-memory ablation, retain failed outputs in the denominator, and disclose that structured rules and retrieval differ. No real-world appeal outcomes are claimed.

## AI disclosure

The original README reports Claude Code assistance. OpenAI Codex subsequently implemented review fixes, tests, evaluation changes and documentation, and prepared demo materials. Runtime classification defaults to Groq gpt-oss-120b; published plans use graph templates. Do not claim the team authored or manually verified components unless true. Each participant should describe their actual contribution and explain it during judging.

## Team-owned final checks

- Verify `https://github.com/Atheeq1821/claimbridge` opens without login. Public access has not been established by this workspace.
- Render, upload and link the video (see `videos/claimbridge/SHOTLIST.md`; FFmpeg is needed and a preview should be approved first). No video exists yet.
- Check local setup from a clean checkout, or deployment from another device.
- Confirm registration, track, event-window eligibility and actual contribution disclosure.
- Submit before the deadline, allowing time for upload/form failures.

## Questions to rehearse

- Why FalkorDB? Domain relationships and working coordination state live there; disabling it stops the pipeline.
- What is learned? Scoped findings with resolution provenance, evidence associations and observed conditions.
- What changes with policy? Content fingerprints determine invalidation and carry-forward; old-version validity is retained.
- What does support mean? Smoothed recorded outcomes, not a calibrated approval forecast.
- Is evaluation independent? Separate Python truth logic, but the same authors and synthetic domain; not external validation.
- What remains? Real user validation, broad policy ingestion, document verification and production privacy operations.
