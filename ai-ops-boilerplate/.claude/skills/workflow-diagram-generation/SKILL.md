---
name: workflow-diagram-generation
description: >-
  Generate a workflow diagram (draw.io / .drawio) for an automation from the reconciled
  PROCESS_STEPS.md — the same single source of truth the README and operator Word guide
  render from. Use when someone wants a visual of the process for the build team or for
  operator sign-off, a flow/swimlane-free diagram, a .drawio/diagrams.net file, or a
  PNG/SVG to paste into a deck. Reconcile the process against the code FIRST (shared with
  doc-generation), then render. Prevents a hand-drawn diagram that drifts from the code
  and from the written docs.
triggers:
  - workflow diagram
  - flow diagram
  - drawio
  - draw.io
  - diagrams.net
  - process diagram
  - flowchart
  - visio
  - diagram for sign-off
  - process map
prevents: >-
  A hand-drawn diagram that contradicts the code and the written docs; a diagram that
  can't be regenerated when the process changes.
---

# Workflow Diagram Generation — draw.io from one source

The diagram is a **rendering of `PROCESS_STEPS.md`**, the same reconciled source the
README and operator Word guide come from (see the **doc-generation** skill). Render it —
do not draw it by hand. A hand-drawn diagram drifts from the code the first time a step
changes; a rendered one is regenerated in seconds.

## Step 1 — Reconcile into PROCESS_STEPS.md (shared step)

If `PROCESS_STEPS.md` doesn't exist yet, produce it exactly as the **doc-generation**
skill describes: reconcile the developer's narrative against the code, emit a divergence
report, let a human resolve it, fold the resolutions in. The schema and the reconciliation
procedure are in `core/docs/SCHEMA.md`. Do not draw a diagram from a narrative that hasn't
been checked against the code — the whole point of the diagram is that the build team and
the operator trust it.

## Step 2 — Render the diagram (deterministic, stdlib only)

```python
from core.docs import parse_file
from core.docs.drawio import render_diagram

process = parse_file("PROCESS_STEPS.md")
render_diagram(
    process,
    "docs/workflow.drawio",
    subtitle="Daily · ~1 working-day review window",  # optional; defaults to the context line
)
```

Open the `.drawio` in diagrams.net or the VS Code **Draw.io Integration** extension, then
**File → Export** to PNG/SVG/PDF for a deck or a sign-off pack.

## What the renderer guarantees (the agreed conventions)

These are baked into `render_diagram` — you get them for free, and they are the
non-negotiables the team agreed on:

- **Left → right** main spine, one column per step (columns are ranked by longest path
  from Start, so a step's column reflects how far along the flow it is). **No
  swimlanes** — shape + colour + a **legend** box carry the meaning instead.
- **Shapes:** step = rounded rectangle, **decision = rhombus**, start/end = ellipse.
- **Decisions fan out vertically.** A decision's mutually-exclusive targets land in the
  same column and are **stacked on separate rows** — one continues along the spine, the
  others branch **up and down** — so the arrows never overlap and the branch labels
  ("Yes" / "No" / "A · …") sit on the vertical connector segments, off the boxes.
  Exception paths (`Reject` / `Park` / `Release` / …) become terminal boxes on their own
  rows in the same column. (An earlier one-row layout drew these branches sideways into
  adjacent boxes, which overlapped arrows and dropped labels onto boxes — the ranked
  layout is what fixes that; don't hand-tweak coordinates to work around it.)
- **Orthogonal edges**, **numbered step labels** (`3. Assess each set`).
- **Colour by actor** so build and ops read it the same way: **blue = automated**,
  **orange = the operator ("You")**, yellow rhombus = decision, green ellipse =
  start/end, red = exit. The **legend labels every colour** — identity is never
  colour-alone (accessibility + print/CVD safe).
- **HITL steps** get a **dashed border** and a `⏸ review` marker — the reviewer's eye
  lands on exactly the points where a human must decide or approve.

## Making the diagram richer

Everything the diagram shows comes from `PROCESS_STEPS.md`. To improve the diagram,
improve the source:

- Mark real branch points with `- **Decision:**` + indented `- <label> -> <target>`
  bullets. Targets of `Step N` continue/jump on the spine; anything else (`Reject`,
  `Park`, `Release`, free text) becomes a labelled exit box below.
- Mark human review points with `- **HITL:** yes` so they're badged.
- Keep step titles short and imperative — they're the node labels.

## Guardrails

- **Never hand-edit the `.drawio`** to fix a wrong step — fix `PROCESS_STEPS.md` and
  re-render, or the diagram silently drifts from the README, the Word guide, and the code.
- If `PROCESS_STEPS.md` has no decisions, you get a clean straight-through spine — that's
  correct, not a bug. Don't add fake branches for visual interest.
- Two measures of "done": it opens in diagrams.net without error, and every box traces
  back to a step in the source.
