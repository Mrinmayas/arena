# PROCESS_STEPS.md — the schema

`PROCESS_STEPS.md` is the **single source of truth** for an automation's process. It is
produced by reconciling the developer's narrative (transcript / MD / Teams / discovery
Word) against the **actual code**, and — once the divergences are resolved with a human —
it is what the README, the operator Word guide, and the drawio diagram all render from.
Keep it current: if the code changes, re-reconcile this file before regenerating docs.

## Format

```markdown
# <Automation name> — Process Steps
> <one-line context: cadence, trigger, review window>

## Phase 1 — <phase title>

### Step 1 — <short imperative title>  `[AUTO · Playwright]`
Free-text description of what happens (one or more lines).
- **HITL:** yes
- **Decision:** Is the user valid in the system?
  - Yes -> Step 3
  - No -> Reject
- **Screenshot:** login_page
- **Note:** anything worth flagging (automation note, future work)

### Step 2 — <title>  `[ERP]`
...
```

## Rules

- **Heading levels are structural.** `#` = the process title (drop the trailing
  "— Process Steps"); `> …` = one-line context; `## Phase N — <title>` = a phase
  (the "Phase N —" prefix is stripped); `### Step N — <title>` = a step. Steps are
  numbered globally and in order.
- **Actor tag** in backticks at the end of the step title: one or more of
  `AUTO`, `ERP`, `MANUAL`, optionally with a tool after `·` or `/`
  (e.g. `[AUTO · Playwright]`, `[AUTO · Python]`, `[ERP / AUTO]`, `[MANUAL]`).
  A step is **automated** if `AUTO` is present; otherwise it is a person's step.
  This drives the diagram's colour and the operator doc's "what the tool does vs.
  what you do" split.
- **Optional per-step metadata** (each on its own `- **Key:** value` line):
  - `**HITL:**` — `yes`/`no`. Marks a human review / decision point. The operator
    guide highlights these; the diagram badges them; screenshots are most useful here.
  - `**Decision:**` — a yes/no or multi-way question. Its presence makes the step a
    **decision (rhombus)** in the diagram. Follow it with indented branch bullets:
    `  - <label> -> <target>` where target is `Step N`, `Reject`, `Park`, `End`, or
    free text.
  - `**Screenshot:**` — a recorder capture id to embed in the operator Word guide.
  - `**Note:**` — any note (automation caveat, future-automation opportunity).

## Reconciliation (how this file is produced)

1. Read the developer's narrative (transcript / MD file / Teams message / discovery Word).
2. Read the automation's **code** to see what it actually does.
3. Draft this file, tagging each step's actor(s) and marking decisions/HITL — and emit a
   **divergence report** where narrative and code disagree, or where one describes a step
   the other lacks.
4. A human resolves the divergences; adjust this file accordingly.
5. Only then render the README, operator Word guide, and drawio from it.
