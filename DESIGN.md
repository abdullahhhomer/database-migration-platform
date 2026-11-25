---
name: Migration Control Room
description: A live database migration read as a boarding pass and a departure gate board.
colors:
  ink: "#0b0d10"
  slate: "#1c2127"
  slate-2: "#2a3038"
  steel: "#5d636b"
  steel-light: "#9aa0a7"
  panel: "#e6e8eb"
  surface: "#ffffff"
  hair: "#d3d6da"
  hair-strong: "#b9bdc3"
  toggle-ink: "#e9ebee"
  toggle-rule: "#4a515a"
  rule-on-slate: "#6b727b"
  alert: "#ffd400"
  alert-hover: "#ffe14d"
  alert-wash: "#ffe680"
  ok: "#1d7448"
  ok-wash: "#e4f3ea"
  ok-on-slate: "#7fd6a6"
  bad: "#b3392a"
  bad-wash: "#fbe6e2"
  bad-deep: "#5e1a12"
  bad-on-slate: "#ff9b8c"
  warn: "#7a5200"
typography:
  display:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "54px"
    fontWeight: 700
    lineHeight: 0.95
    letterSpacing: "0em"
    fontFeature: "tnum"
  display-figure:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "52px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0em"
    fontFeature: "tnum"
  headline:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "26px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.06em"
  title-segment:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "0.05em"
  title-panel:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "20px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "0.07em"
  title-stage:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "18px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.05em"
  body:
    fontFamily: "Inter Variable, Inter, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  body-sm:
    fontFamily: "Inter Variable, Inter, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.35
  button:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "15.5px"
    fontWeight: 700
    letterSpacing: "0.08em"
  status:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "14px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.07em"
  label:
    fontFamily: "Barlow Condensed, Arial Narrow, sans-serif"
    fontSize: "13.5px"
    fontWeight: 600
    letterSpacing: "0.1em"
  data:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "15px"
    fontWeight: 700
    letterSpacing: "-0.01em"
    fontFeature: "tnum"
  data-sm:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "14px"
    fontWeight: 500
    letterSpacing: "-0.01em"
    fontFeature: "tnum"
rounded:
  none: "0px"
spacing:
  hairline-gap: "2px"
  xs: "6px"
  sm: "10px"
  md: "14px"
  lg: "18px"
  gap: "20px"
  page: "28px"
  mobile-gutter: "16px"
components:
  button-primary:
    backgroundColor: "{colors.alert}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.none}"
    padding: "8px 16px"
    height: "38px"
  button-primary-hover:
    backgroundColor: "{colors.alert-hover}"
    textColor: "{colors.ink}"
  button-quiet:
    backgroundColor: "{colors.slate}"
    textColor: "{colors.surface}"
    typography: "{typography.button}"
    rounded: "{rounded.none}"
    padding: "8px 16px"
    height: "38px"
  toggle:
    backgroundColor: "{colors.slate}"
    textColor: "{colors.toggle-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.none}"
    padding: "6px 12px"
    height: "34px"
  toggle-selected:
    backgroundColor: "{colors.toggle-ink}"
    textColor: "{colors.ink}"
  status-tag:
    textColor: "{colors.steel}"
    typography: "{typography.status}"
    rounded: "{rounded.none}"
    padding: "3px 9px"
  now-tag:
    backgroundColor: "{colors.alert}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "3px 8px"
  source-chip-live:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.surface}"
    rounded: "{rounded.none}"
    padding: "7px 14px"
  source-chip-frozen:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.alert}"
    rounded: "{rounded.none}"
    padding: "7px 14px"
  source-chip-unknown:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.steel-light}"
    rounded: "{rounded.none}"
    padding: "7px 14px"
  run-stub:
    backgroundColor: "{colors.slate}"
    textColor: "{colors.surface}"
    padding: "18px 20px"
    width: "250px"
  segment:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    padding: "16px 20px 18px 34px"
  segment-lit:
    backgroundColor: "{colors.alert-wash}"
  stage-now:
    backgroundColor: "{colors.alert}"
    textColor: "{colors.ink}"
    padding: "12px 14px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "14px 18px 18px"
  panel-head-lit:
    backgroundColor: "{colors.alert-wash}"
    padding: "12px 18px"
  gate-row-lit:
    backgroundColor: "{colors.alert-wash}"
    padding: "9px 14px"
  gate-row-failed:
    backgroundColor: "{colors.bad-wash}"
  notice-bad:
    backgroundColor: "{colors.bad-wash}"
    textColor: "{colors.bad-deep}"
    padding: "10px 14px"
  notice-ok:
    backgroundColor: "{colors.ok-wash}"
    textColor: "{colors.ink}"
    padding: "10px 14px"
---

# Design System: Migration Control Room

## Overview

**Creative North Star: "The Boarding Pass and the Gate Board"**

The migration run is a printed boarding pass: a dark slate stub carrying the run number and its facts, torn off along a punched perforation from a white pass that shows the six-stage route and one tear-off segment per target. Under it, the jobs are a live departure gate board: rows of table × target that rerank in place as they run and land. The system borrows the vernacular of travel ephemera (ink header bar, condensed gate lettering, die-cut notches, punched hole columns) and refuses the category default of a grid of equal stat cards on a grey admin ground.

Density is high and deliberate: an operator's screen, read as a still frame in a compressed 1080p recording. Everything is flat paper on a cool grey ground, held together by square corners and 1.5px ink rules. Colour is almost entirely absent; one alert yellow announces "changed just now / act now", and green and red appear only where a check passed or failed. The signature motion is a gate change: a row reranks, and whatever changed holds yellow with a NOW tag for eight seconds.

The system is light-only (`color-scheme: light`); the ink top bar and slate stub are the only dark surfaces and are part of the document, not a theme.

**Key Characteristics:**
- Boarding pass + gate board, not stat cards.
- Ink, slate, steel and white do all the structural work; yellow is a signal, never decoration.
- Square corners, 1.5px ink rules, perforations and punched holes instead of shadows.
- Condensed caps for every label and name, mono tabular figures for data, condensed display figures for the hero numbers.
- Every state reads as a still image: unknown, stale, running, held-change, failed and ready.

## Colors

A cool neutral printed-paper palette with one hot signal colour and two strictly semantic colours.

### Primary
- **Gate Alert Yellow** (alert): the only accent. Reserved for "changed just now / act now": the current runbook stage, the single stage-appropriate primary action (none once a cutover has completed), the NOW tag, the solid status cell of a lit gate-board row, the frozen-source chip, the brand mark, focus outlines and text selection. Its hover step is **Lamp Yellow** (alert-hover).
- **Held-Change Wash** (alert-wash): the softer yellow behind a lit segment, a lit gate-board row and a lit panel head. Chosen strong enough to survive video compression; never lighter.

### Secondary (semantic only)
- **Signal Green** (ok) with **Green Wash** (ok-wash): passed, in sync, landed, done, ready. On the slate stub it lifts to **Signal Green on Slate** (ok-on-slate).
- **Signal Red** (bad) with **Red Wash** (bad-wash) and **Deep Red Ink** (bad-deep): failed, error, not ready, unreachable API. On the slate stub it lifts to **Signal Red on Slate** (bad-on-slate).
- **Hold Amber Ink** (warn): text-only tone for "buffering / waiting for full load".

### Neutral
- **Departure Ink** (ink): the top bar, all primary text, every 1.5px rule, meter and timeline fills, the "streaming" producer state.
- **Stub Slate** (slate) and **Slate Divider** (slate-2): the run stub and control bar; the brand-line separator.
- **Steel** (steel): secondary ink on light grounds, darkened from the world's original #6B7178 for contrast (6.0:1 on white, 4.9:1 on the panel ground). Column headers, captions, stage notes, idle tags.
- **Light Steel** (steel-light): secondary ink on ink and slate grounds; also the "Source unknown" chip.
- **Concourse Grey** (panel): the page ground, empty meter and timeline tracks, die-cut notch fill.
- **Pass White** (surface): every document surface (pass, segments, panels, table header).
- **Hairline** (hair) and **Strong Hairline** (hair-strong): 1px row dividers, field dividers, perforation and punch dots.
- **Control greys** (toggle-ink, toggle-rule, rule-on-slate): selected toggle fill, toggle outline, quiet-button and stub-tag outline on dark grounds.

### Named Rules
**The One Signal Rule.** Yellow means exactly one thing: changed just now, or act now. It never decorates, never fills a chart series, never marks a brand moment beyond the mark itself. At most one yellow primary button is on screen, and none after a cutover completes.

**The Meaning-Only Green Rule.** Green and red carry pass/in-sync and fail meaning only. The live-source chip is white and the producer "streaming" state is ink, so green never means "active" or "live".

**The Never-Colour-Alone Rule.** Every coloured state is paired with a word and, in tags, an icon (check, cross, clock, dashed circle, spinner, pause).

## Typography

**Display Font:** Barlow Condensed (with Arial Narrow, sans-serif), self-hosted at 500/600/700
**Body Font:** Inter Variable (with Inter, system-ui, sans-serif), self-hosted
**Label/Mono Font:** JetBrains Mono (with ui-monospace, monospace), self-hosted at 500/700

**Character:** Condensed caps are the gate lettering: every name, label, tag and button speaks in them. JetBrains Mono gives every data figure a fixed, tabular cadence like a flap display, and Inter carries the few sentences of explanation.

### Hierarchy
- **Display** (Barlow Condensed 700, 54px, 0.95, tabular): the run number on the stub ("#1").
- **Display Figure** (Barlow Condensed 700, 52px, 1, tabular): the large backlog count or load percent in each target segment.
- **Headline** (Barlow Condensed 700, 26px, uppercase, 0.06em): the product name in the top bar.
- **Title** (Barlow Condensed 700, uppercase): segment names at 24px / 0.05em, panel heads at 20px / 0.07em, route stage names at 18px / 0.05em, sub-heads and timeline target names at 15px / 0.08–0.1em.
- **Body** (Inter 400, 15px, 1.5): explanations, empty states and notices, capped at 62–72ch. Secondary prose runs at 14–14.5px.
- **Button** (Barlow Condensed 700, 15.5px, uppercase, 0.08em): actions; toggles use 600 at 15px / 0.04em.
- **Status** (Barlow Condensed 700, 14px, uppercase, 0.07em): outlined state tags.
- **Label** (Barlow Condensed 600, 13.5px, uppercase, 0.1em): field labels, column headers, setup labels, the NOW tag (700).
- **Data** (JetBrains Mono, tabular numerals, -0.01em): gate-board cells at 15px regular, segment facts at 15px 700, stub facts at 16px, infra facts at 17px 700, stage durations at 20px 700, progress percents and log times at 14px.

### Named Rules
**The Two Figure Voices Rule.** The two hero figures (run number, segment backlog/percent) are set in Barlow Condensed 700 with tabular numerals, matching the gate lettering. Every other number (table cells, LSNs, timings, rates, counts) is JetBrains Mono with tabular numerals. Never set a hero figure in mono or a table figure in the condensed face.

**The Video Floor Rule.** Anything that carries a mechanic (a state, a figure, an instruction) is at least 14px; condensed caps labels are at least 13.5px. The surface is judged from a compressed 1080p recording.

## Layout

A single full-width column of documents on the concourse-grey ground, max width 1920px, 28px page padding and a 20px gap between every document.

1. **Top bar** (sticky, ink): brand row at 14px × 28px padding, then the slate control bar (10px × 28px) holding the setup toggles on the left and the actions on the right.
2. **Run pass**, full width: a 250px stub, an 18px perforation, then the pass body: the route strip (six stops, each stop's width weighted by its real measured duration with a 6% minimum) above one segment per target in equal columns.
3. **Work area**: gate board at 1.75fr beside a side column (minimum 380px) holding Proof and Cutover; once a cutover starts, Cutover moves above Proof. The gate board scrolls inside a 600px cap so proof and cutover share the first scroll stop.
4. **Lower row**: Timeline, Run history and Pipeline at 1.3fr / 1fr / 1.1fr.

Responsive behaviour:
- **Under 1500px:** the work area stacks; the side column becomes two equal columns.
- **Under 1360px:** the lower row becomes two columns with Timeline spanning both.
- **Under 980px:** single column with a 16px gutter. The stub sits above the pass, the perforation turns horizontal (an 18px band of 16px-spaced holes), segments stack with a dashed hairline tear between them, segment facts go two-up, the source chip hides, readiness and log rows wrap their detail under the name.

## Elevation & Depth

Completely flat. There are no shadows and no gradients for depth; layering is printed, not lifted. Depth is conveyed by the ink/slate vs white vs grey ground contrast, by 1.5px ink rules around every document, and by the die-cut notches and punched holes that read as paper. The only `box-shadow` in the system is the 4px ink keyline behind the yellow focus outline, which is a ring, not elevation.

### Named Rules
**The Printed Paper Rule.** Surfaces never float. If something needs emphasis it gets the alert wash or an ink rule, never a shadow.

**The Punched-Hole Exception.** `radial-gradient` is used only to draw perforation and punch holes (3–3.5px dots in strong hairline); it is never used as a colour fade.

## Shapes

Square corners everywhere (0px). The one curve in the system is the semicircular die-cut notch (22px circle, ink-ruled, panel-filled) at the top and bottom of the perforation between the stub and the pass, clipped to a half so the pass reads as a ticket.

- **Ink rule:** 1.5px solid ink around the pass, every panel, every panel head, notices, the route strip base and the footer.
- **Outlined tags and buttons:** 1.5px in currentColor.
- **Hairlines:** 1px hair for row and stop dividers; 1px strong hairline for table header bases, timeline axes and the vertical dividers between segment fact fields.
- **Perforation:** a vertical column of 3.5px holes every 16px between stub and pass.
- **Punched columns:** each target segment after the first tears off along its own column of 3px holes every 16px down its left edge.
- **Meters:** flat 10px bars (6px × 90px inline in the gate board), ink fill on grey track; timeline tracks 12px, history tracks 14px.

## Components

### Buttons
Square, condensed and loud only when it is time to act.
- **Shape:** square corners (0px), 1.5px border, 38px minimum height, 8px × 16px padding, 8px icon gap with a 15px line icon.
- **Primary:** gate alert yellow fill and border with ink text. Only the one stage-appropriate action is primary (start, validate, cut over or roll back), and none once a cutover has completed.
- **Quiet:** transparent on slate with white text and a rule-on-slate outline; the outline turns white on hover.
- **Hover / Focus:** primary lifts to lamp yellow; colour transitions run 160ms on the ease-out curve. Focus is a 2px yellow outline offset 2px over a 4px ink keyline.
- **Disabled / Busy:** 40% opacity and not-allowed cursor; a busy button keeps full opacity and appends an ellipsis to its label.

### Toggles (setup)
- **Style:** transparent on slate, toggle-ink text, 1.5px toggle-rule outline, 34px tall, 6px × 12px padding; numeric worker toggles use JetBrains Mono 14px at 38px minimum width.
- **State:** pressed/checked fills toggle-ink with ink text. The whole setup fieldset dims to 55% while a run or cutover is active.

### Status Tags
- **Style:** outlined in currentColor (1.5px), 3px × 9px, condensed 700 caps 14px, always with a 15px icon: check (ok), cross (bad), clock (warn), spinning loader (running), pause (idle).
- **Tones:** green for done/in sync/landed/ready, red for failed/error/not ready, ink for running/streaming, amber ink for buffering, steel for idle.

### NOW Tag
Solid alert yellow, ink text, condensed 700 caps 13.5px at 0.1em, 3px × 8px. Appears beside whatever changed and disappears when the hold ends.

### Source Chip
Outlined condensed caps chip in the top bar with a 9px square pulse and a mono writes/s figure. **Live:** white, pulse blinks in two steps every 1.6s. **Frozen:** alert yellow. **Unknown:** light steel with "– writes/s", shown whenever the API is unreachable.

### Run Pass (signature)
The stub (slate, 18px × 20px) carries the run label, the display run number, a status tag recoloured for slate, and a two-up fact list. The route strip shows six stops (index, name, state word with check/cross, mono duration, two-line note); the current stop fills solid alert yellow. Each target segment shows name and role, NOW and status tags, the display figure with a caption, then either a load meter or four mono facts (Lag, Applied, Rate, Last LSN) split by vertical strong hairlines.

### Panels
- **Corner Style:** square (0px), 1.5px ink rule.
- **Background:** pass white; the head gets the alert wash when the panel's content changed.
- **Head:** 12px × 18px, ink rule below, condensed 700 20px title with steel meta at 13.5px on the right.
- **Internal Padding:** 14px 18px 18px.
- **Empty state:** a dashed-circle (or ban/alert) icon beside a sentence that explains what will appear and why.

### Gate Board (signature)
Table of table × target jobs: status, table, target (condensed caps), progress meter + mono percent, rows "n / total", rows/s, time, landed. Sticky white header in label type over a strong hairline; 9px × 14px cells over hairline rows. Rows rank failed → running (by progress) → pending → landed (newest first) and rerank in place with a 450ms ease-out position animation. A changed row takes the alert wash and its status cell goes solid alert yellow with a NOW tag; a failed row sits on red wash.

### Notices and Unknown/Stale States
Full-width ruled bar, 10px × 14px, icon + sentence. **Unknown** (the API never answered): nothing is lit, every figure is a dash, the stub reads "No data", the chip reads "Source unknown" in light steel, and every control is disabled. **Stale** (failing after data loaded): the last data stays on screen under a red notice and every control is disabled.

## Do's and Don'ts

### Do:
- **Do** reserve alert yellow (#ffd400) for the current stage, the single primary action, the NOW tag, the lit row's status cell and the frozen-source chip.
- **Do** hold a change for 8 seconds with the alert wash (#ffe680) plus a NOW tag, and treat the first data arrival as an arrival, not a change.
- **Do** rerank gate-board rows in place with a 450ms ease-out layout move; fade washes over 700ms.
- **Do** set the run number and segment hero figures in Barlow Condensed 700 with tabular numerals, and every other figure in JetBrains Mono with tabular numerals.
- **Do** frame every document with a 1.5px ink rule on square corners, and separate pass parts with perforations, die-cut notches and punched hole columns.
- **Do** pair every status colour with a word and an icon.
- **Do** keep mechanic-carrying text at 14px or larger and condensed caps labels at 13.5px or larger.
- **Do** show unknown and stale states honestly: dashes and "Source unknown" when nothing is known, last data plus a stale notice when the API drops later, and disabled controls in both.

### Don't:
- **Don't** use green for "live", "active" or "streaming"; the live chip is white and streaming is ink.
- **Don't** add shadows, rounded corners or colour gradients; the only gradient is the punched-hole dot pattern.
- **Don't** light more than one primary action, or any after a cutover has completed.
- **Don't** build the surface from a grid of equal stat cards.
- **Don't** use steel lighter than #5d636b for secondary text on white or the panel ground.
- **Don't** add motion beyond the reranking, the held highlight, meter/timeline fills, the live pulse and running spinners; all of it collapses under reduced motion.
