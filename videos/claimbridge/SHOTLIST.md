# Working-project video: shot list (status: NOT rendered)

**Status, plainly.** Nothing here is a finished video. The scaffold, brief and captures exist; no MP4 has been rendered or hosted. Rendering needs FFmpeg on PATH (`winget install --id Gyan.FFmpeg -e`; `hyperframes doctor` reports it missing) and the HyperFrames workflow wants a preview approval before the final render. Hosting the file and pasting a logged-out-accessible URL into the submission is the team's step.

**Scope decision.** One 90-second, caption-led, silent cut (a judge may watch muted). The 3-minute live-demo script in `docs/08-demo-and-submission.md` is the longer version. No official maximum length was found.

**Rules for every shot.** Record the real running app, never a mock-up. Keep the "synthetic, fictional, a person approves" banner visible. Say *recorded replay* on any shot that replays a recorded model response. Show only numbers from the promoted evaluation run (`eval/results/latest.md`), with its run id on screen. No success rate, customer or real-world outcome that the repo does not contain.

**Before recording:** `docker compose --profile app up -d --build`, then `node scripts/browser-smoke.mjs` (it files the two scenario claims and proves the controls work). Browser at 1440x900, dark theme.

| # | Time | Shot (what to do) | Caption |
|---|---|---|---|
| 1 | 0:00-0:07 | Landing page; the framed replay plays by itself | "A denied claim, worked by five agents that share only a graph. Synthetic data." |
| 2 | 0:07-0:22 | Docket, open `EV-T1-01`, Graph replay plays: version pinned, clause, three precedents ruled on | "The 2025 precedent is refused: the 2026 clause replaced it." |
| 3 | 0:22-0:32 | Click the refused precedent node; the inspector shows why and the Cypher | "Click any node: what it contributed to this claim." |
| 4 | 0:32-0:47 | Evidence tab on `EV-M-B2` (after the outcome flow): the bill is marked *suggested by a precedent* | "A recorded outcome changed the next checklist. An association, not proof." |
| 5 | 0:47-0:57 | Docket: New claim, Insert sample notice, File and watch | "Enter your own claim and watch the agents work it." |
| 6 | 0:57-1:07 | A claim with a nonexistent section stops with its reason; reclassify and resume | "When it cannot read a letter it asks a person; it does not guess." |
| 7 | 1:07-1:20 | Agents page: kill a worker holding a lease; RESUMED appears | "Kill a worker mid-step: another resumes from the graph." |
| 8 | 1:20-1:30 | Evaluation page: run id, the access table, decision correctness row | "Read the access table before the numbers. Whole systems, not a database-only claim." |

**Honest closing card (0:30 of the 90s may be trimmed):** "Prototype. Fictional data. Separately authored tests, not independent validation. Source and setup: the repository."

**Capture notes.** The earlier automated capture attempt was blocked (HTTP 403); use the real browser via `scripts/cdp.mjs` or screen recording. `assets/*.png` are older stills from before the redesign; recapture them rather than reuse.
