---
name: doc-generation
description: >-
  Generate the operator-facing docs for an automation — the README run-guide and a
  Word (.docx) process guide — from ONE reconciled source of truth, PROCESS_STEPS.md.
  Use when: the developer has a narrative of the process (a meeting transcript, a steps
  MD file, a Teams message, or a discovery Word doc) and wants a README and/or an
  operator Word guide; when discovery is complete and needs a sign-off document; or
  after UAT when clean deploy docs are needed. First RECONCILE the narrative against the
  actual code and surface divergences for a human, THEN render. Prevents docs that
  describe what someone said the tool does rather than what it actually does, and
  README/Word drift.
triggers:
  - readme
  - operator guide
  - process document
  - word doc
  - docx
  - process steps
  - PROCESS_STEPS
  - documentation
  - sign-off
  - run guide
  - reconcile the process
prevents: >-
  Docs that describe intent instead of the shipped code; README and Word guide drifting
  apart; an operator guide written in developer language.
---

# Doc Generation — README + operator Word from one source

The operator's README and their Word guide are **two renderings of one file**:
`PROCESS_STEPS.md` (the reconciled, code-verified description of the process). Never
write them independently — they drift the moment you do. Produce/refresh
`PROCESS_STEPS.md` first, then render.

The workflow diagram is a **third** rendering of the same file — see the
**workflow-diagram-generation** skill. This skill and that one share this source.

## When this runs

- **After discovery (with or without sign-off).** Input is the developer's narrative:
  a meeting transcript, a steps `.md`, a Teams message, or a discovery Word doc. The
  README/Word here is what you take to the operator to get discovery **signed off**.
- **After UAT.** The code is settled; regenerate clean deploy docs from the code +
  the now-accurate `PROCESS_STEPS.md`.

## Step 1 — Reconcile into PROCESS_STEPS.md (do NOT skip)

`PROCESS_STEPS.md` is the single source of truth. Build (or refresh) it by reconciling
the **narrative** against the **code** — the schema and the exact reconciliation
procedure live in `core/docs/SCHEMA.md`. In short:

1. Read the narrative (transcript / MD / Teams / discovery Word) the developer gives you.
2. Read the automation's **code** (`automation/automation.py` and what it calls) to see
   what it *actually* does — which steps are automated (`[AUTO]`), which happen in the
   ERP or by hand (`[ERP]` / `[MANUAL]`), where the decisions and HITL points are.
3. Draft `PROCESS_STEPS.md` in the schema, tagging every step's actor.
4. **Emit a divergence report** — a short list where narrative and code disagree, or
   where one has a step the other lacks (e.g. "narrative says the tool emails the team;
   code has no email step" / "code retries login 3× — not in the narrative"). Present it
   and let a human resolve. This is the self-validation the source of truth requires.
5. Fold the resolutions back into `PROCESS_STEPS.md`.

Only when `PROCESS_STEPS.md` reflects the code do you render.

## Step 2 — Render the README (Step 1 onward; "Step 0" is constant)

The README is the **operator run-guide** — plain language for a preparer, not a
developer. House conventions (match the repo's existing READMEs):

- Open with a one-line what-it-is, then a short blockquote framing it for the operator
  ("A guide for preparers…"), not architecture.
- **`## 0. One-time setup` is constant boilerplate** — it is the same install/auth step
  in every automation (`uv sync`, first-run SSO login, where inputs go). Keep it; the
  process content you generate starts at **Step 1**.
- Walk the run: the `uv run automate …` command, what the operator sees, and the output
  (a table of output tabs/files is the house style).
- A **"Good to know"** section for the caveats and the HITL/review points.
- Keep automated vs. operator actions clearly separated — the reader must know what the
  tool does for them vs. what they do.

Write this section with judgement (it is prose), but every process fact in it must come
from `PROCESS_STEPS.md`.

## Step 3 — Render the operator Word guide (deterministic)

The `.docx` is generated from the **same** `PROCESS_STEPS.md`, so it can never contradict
the README. Use the committed renderer (needs the `docs` extra):

```bash
uv sync --extra docs
```
```python
from core.docs import parse_file
from core.docs.word import render_operator_guide

process = parse_file("PROCESS_STEPS.md")
render_operator_guide(
    process,
    "outputs/operator-guide.docx",
    screenshots_dir="docs/screenshots",  # optional: <screenshot-id>.png per step
)
```

It groups steps by phase, tags each **[Automated]** vs **[You]**, flags HITL steps as
"Review needed", lists decision branches, and embeds a screenshot wherever a step names
one (`- **Screenshot:** login_page`). Screenshots are most valuable at HITL steps — a
picture of exactly what the operator should check before approving.

## Guardrails

- **One source.** If a fact isn't in `PROCESS_STEPS.md`, it doesn't belong in the docs —
  add it to the source first (re-reconciling if it's a code fact).
- **Operator audience for the Word doc.** No code identifiers, no "the async step" — say
  what the person does and what they'll see.
- **Don't invent screenshots or numbers.** Reference a screenshot only if the recorder
  actually captured it; never fabricate example figures in an operator guide.
- Regenerate both after any change to `PROCESS_STEPS.md` — never hand-edit one rendering.
