---
version: 1
slug: "frontend-index-html"
primary_target: "frontend/index.html"
related_targets: ["frontend/src"]
---

# Surface: Migration Control Room dashboard

Mode: Operate. Audience: data engineers watching a 1080p recording of the author's demo. Job: follow the whole runbook (capture, full load, catch-up, validate, freeze and drain, cut over) and trust the proof. Constraints: every number from /api/dashboard; mocked AWS labelled as mocked; status never colour-only; legible after video compression.

## Direction contract

THESIS: The migration run is a boarding pass and the jobs are a live gate board; the surface refuses the category default of a grid of equal stat cards on a grey admin ground.

OWN-WORLD: Ink #0B0D10 header bar, panel #E6E8EB ground, white document surfaces with perforated tear lines between segments, steel #6B7178 secondary ink, one alert yellow #FFD400 reserved for "changed just now / act now"; green and red only for in-sync/passed and failed. Condensed caps labels (Barlow Condensed), tabular mono figures for every number (JetBrains Mono), Inter for prose. Square corners, 1.5px ink rules, no shadows, no gradients.

STORY: The viewer reads which runbook stage is live, sees each target's segment on the pass catch up to zero backlog while the source keeps writing, watches jobs land on the gate board, then sees every check pass and the cutover clear.

FIRST VIEWPORT: Ink top bar (name, author credit, source-live chip, run controls and stage-appropriate primary action in yellow). Under it the run pass, full width: stub segment (run number, workers, elapsed, rows/s), a route strip of the six stages sized by real duration with the current stage lit, then one tear-off segment per target with its backlog in large figures and its state. Below, the gate board table of table x target jobs takes two thirds; validation and readiness take the right third.

FORM: Boarding pass and gate board (dealt challenger, catalog vernacular-ephemera-boarding-pass-and-gate-board), chosen by the user over the assigned Departure Board; seed: 53c3f04e74e31364. Signature move: gate-board rows rerank in place by finish time and a changed row or segment holds the alert yellow with a NOW tag until the next change. Motion: layout reranking plus the held highlight, nothing else.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
