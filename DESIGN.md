---
name: ClaimBridge
description: Monochrome product. Near-black panels, hairline borders, one periwinkle accent, and a drawn signal for every verdict.
colors:
  paper: "#09090b"
  wash: "#111114"
  wash-2: "#18181c"
  ink: "#ededef"
  ink-2: "#a1a1aa"
  ink-3: "#7e7e88"
  rule: "#26262c"
  rule-2: "#3a3a42"
  link: "#8fa8ff"
  accent-ink: "#0a0a12"
  neg: "#f26d6d"
  neg-wash: "#2a1517"
  caution: "#e8b04a"
  caution-wash: "#2a2111"
  pos: "#4cc38a"
  pos-wash: "#10261b"
  neutral: "#7d7d87"
typography:
  display:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "clamp(40px, 7vw, 76px)"
    fontWeight: 600
    lineHeight: 1.02
    letterSpacing: "-0.045em"
  headline:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "clamp(28px, 3.4vw, 40px)"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.035em"
  page-title:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.03em"
  section-title:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  ui:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.5
  label:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 500
    lineHeight: 1.5
    letterSpacing: "0.06em"
  mono:
    fontFamily: "Geist Mono, ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "-0.01em"
rounded:
  control: "8px"
  panel: "12px"
  hero: "16px"
  dot: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "20px"
  xl: "32px"
  section: "48px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    height: "32px"
  button-accent:
    backgroundColor: "{colors.link}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.control}"
    height: "32px"
  button-secondary:
    backgroundColor: "{colors.wash}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "32px"
  panel:
    backgroundColor: "{colors.wash}"
    rounded: "{rounded.panel}"
---

# Design System: ClaimBridge

## Overview

A monochrome product, not a brand page. The surface is near-black (`paper`), content sits in `wash` panels with one-pixel hairlines (`rule`), and a single periwinkle accent (`link`) marks the thing you can act on or the thing that is happening now. Everything else is neutral grey on black. Colour is reserved for meaning: **a verdict is never a colour alone**, it is a drawn shape, a colour and a word together.

The product is a review tool for a caseworker and a proof for a judge. The design's job is to make the reasoning legible: which clause governs, which precedent was followed or refused and why, what is missing, what an agent just did. So the density is high, the type is small and exact, and motion is spent only on the one thing that earns it: the animated graph replay.

**Direction B ("Monochrome product, dark")** was chosen from three mockups built on real claim data. The earlier light, serif "Citator" direction is retired.

## Colors

- **Ground and panels:** `paper` for the page, `wash` for a panel, `wash-2` for a raised or hovered surface. Hairlines are `rule`; stronger edges `rule-2`.
- **Text:** `ink` for content, `ink-2` for supporting text, `ink-3` for metadata (all pass AA on `paper`; `ink-3` is for non-essential metadata only).
- **Accent:** `link` is the only brand colour. It marks the primary action in a screen (`button-accent`), live state, the focused graph node, and a learned (not policy) relationship. Text on it is `accent-ink`.
- **Signals:** `pos` (followed), `caution` (distinguished), `neg` (refused), `neutral`. Each is paired with a shape (diamond, triangle, octagon, ring) and a word.

### Named Rules

- **The Shape Rule.** A treatment is shape + colour + word. Never colour alone; the verdicts are the core content.
- **The One Accent Rule.** One accent colour, used for action and "now". If two things on a screen are accent-coloured, one of them is wrong.
- **The Dark Without Glow Rule.** No gradients on content, no drop shadows on panels. The only gradient is the logo mark; the only glow is the live token travelling along a graph edge.

## Typography

Geist for everything, Geist Mono for IDs (`F-MRI-REFERRAL`, `C-2026-MRI-PREAUTH`), queries and numbers that must align. Headings carry tight negative tracking (-0.025em to -0.045em); body text is 14px; interface text is 13px; labels are 11px, uppercase, tracked. Numerals use `tabular-nums` wherever they are compared.

### Named Rules

- **The ID Rule.** An identifier is always mono, and always secondary to the plain-language words that explain it ("Superseded by §4.2 (2026)" first, `C-2026-MRI-PREAUTH` after).

## Layout

- **Console shell:** a 220px sidebar (Docket, Memory, Agents, Evaluation; live status and policy world at the foot) and a 56px top bar with a claim-ID box (`/` focuses it, `g` then `1`..`4` navigates). On a phone the sidebar becomes a drawer.
- **Docket:** a segmented stage control, a dense table in a panel, and a 340px preview drawer for the selected claim on wide screens (below 1280px a row opens the case).
- **Case page:** header (claim, key facts) with the action card beside it; the holding card (the answer first); then tabs: **Graph replay** (default), Plan, Precedents, Evidence, Agent record.
- **Graph replay:** the claim on the left, then policy and evidence, then precedents and the plan, then grounds; an inspector panel on the right. Below 820px the stage scrolls sideways and says so.
- **Rhythm:** sections carry more space above than below (48px / 12px). Content is capped at a readable measure (72-80ch).

## Elevation & Depth

Flat. Depth comes from tone (`paper` < `wash` < `wash-2`) and hairlines, not shadow. The one exception is the landing page's framed product window, which sits in a large soft shadow to read as a screen.

## Shapes

8px controls, 12px panels, 16px for the landing hero frame, full-round only for status dots and the live token. Signal shapes are 1.6px-stroked or filled geometry at 11-22px.

## Components

### Buttons
Primary is `ink` on `paper` (white button). Accent is `link` with `accent-ink` text, used once per screen for the next action ("File claim", "File and watch"). Secondary is a `wash` panel with a hairline. Danger is red text on `wash`. Ghost is text only. All 32px; busy state shows a spinner and disables the button.

### Fields
`paper` fill, `rule` border, 8px radius, 36px tall, accent caret and an accent border on focus. Switches are 32x18px pills.

### Citator Signal (signature)
The drawn verdict mark: a diamond (followed), triangle (distinguished), octagon (refused), ring (neutral/unknown). Stamped once on arrival (a 520ms scale-in), never looping.

### Graph Replay (signature)
An SVG replay of one claim's processing: nodes appear as each agent commits its step, edges draw in, a small accent token travels along the new edge, the verdict glyph stamps onto a precedent. Controls: Play/Pause, Step, Replay, and one button per agent. Click a node and the inspector pins what that node contributed to *this* claim, with its Cypher. Policy requirements and learned suggestions are drawn differently (solid vs dotted accent edge, "required" vs "suggested"). Respects `prefers-reduced-motion` (the replay starts at its end and animations are skipped).

### Docket Table, Cite Chip, Section Head, Panels
Rows are 12px-padded with a hairline between; the selected row has a 2px accent edge. A cite chip is a mono ID in a `wash-2` pill that turns accent when its precedent is hovered. A section head is a title with a hairline beneath. A panel is `wash`, 12px radius, one hairline.

### Empty and Error States
Dashed hairline panel with a plain sentence that says what to do next. Errors are one red line under the control that caused them. A claim waiting for a person says *why*, in the agents' own words.

## Do's and Don'ts

### Do
- State the reason next to every refusal, and the origin next to every checklist item (*required by the clause* or *suggested by a precedent: an observed association, not a policy requirement*).
- Show a support score only with its counts, and show *none yet* instead of 0%.
- Keep "synthetic, fictional, a person approves" visible on every screen.
- Let motion explain sequence: an edge draws where an agent handed work on.

### Don't
- Don't use colour alone for a verdict, or a second accent colour.
- Don't add gradients, glows or shadows to content panels.
- Don't write "good law", "confidence" or "approval probability"; the vocabulary is *applies*, *support score* and *recorded outcomes*.
- Don't present a hand-entered or recorded replay as a live model call; label cached and recorded runs as such.
- Don't invent customers, testimonials, partners or real-world outcomes.
