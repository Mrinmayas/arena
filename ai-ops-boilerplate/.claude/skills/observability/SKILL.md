---
name: observability
description: >-
  Use whenever you write or modify an automation's run logic — every action must be
  attributed as automation-performed or human-performed through core.audit. Triggers:
  audit, audit_logs, observability, logging a run, run summary, sign-off, four-eyes,
  human vs automation, "who did what", trace, redact, run_summary.json. Grounds the
  agent in core.audit so every run leaves a reviewer sign-off trail and no action goes
  unattributed. Without it, runs use bare print/logging and a reviewer cannot tell which
  figures the tool produced versus which a person entered or approved.
---

# Observability — attribute every action (automation vs human)

Every automation records what happened through **`core.audit`**. Use it. Do **not** use
bare `print()` / `logging` for run steps: an unattributed log cannot tell a reviewer
which numbers the tool produced versus which a person entered or approved — and for
finance work that attribution *is* the sign-off.

This skill covers the run-audit trail and human/automation attribution. It does not cover
the engine's structured `runs/<run_id>/` store (that is written automatically when you
use the orchestration engine — see AUTHORING.md).

## The one rule: every recorded action has an actor

```
run starts          the tool works          a person acts/approves       run ends
(human: launched) → (automation: …)   →     (human: who + what)     →     (finalize: summary)
```

`core.audit` stamps **every** event with `actor = "automation" | "human"` and writes a
`run_summary.json` that splits the two, so a preparer/reviewer can sign off. Default to
`automation`; attribute every manual step or approval to the person who did it.

## Decision tree

- **Wrapping a run?** → `with audit_run(name, operator=…, redact=…) as audit:` — it
  records the launch as a human action and auto-finalizes (ok, or "failed" on exception).
- **The tool did something?** → `audit.automation("…", step="…", detail={…})`.
- **A person did / approved / edited something** (HITL gate, manual fix, sign-off)? →
  `audit.human(who, "…", step="…")`. This is the four-eyes trail — never skip it.
- **A skipped / degraded / recoverable case?** → `audit.warn("…")`.
- **Money or document numbers in `detail`?** → start the run with `redact=True` (masks
  amount / total / balance / tax / … keys to `[REDACTED]`).
- **Result facts** (tie-out difference, output path)? → `audit.set_outcome(tie_out_diff=0.0, output=…)`.
- **Using the engine?** → the `AuditSubscriber` bridges step/stage events into this same
  trail automatically; you still call `audit.human(...)` for manual gates. See AUTHORING.md.
- **Reading the trail?** → `audit_logs/<ts>/run_summary.json`: `.actions.automation`,
  `.actions.human`, `.counts`, `.status`.

## Minimal shape

```python
from pathlib import Path
from core.audit import audit_run

def run(inputs: Path, outputs: Path, *, operator: str | None = None, redact: bool = False):
    with audit_run("ap_aging", operator=operator, redact=redact) as audit:
        audit.automation(f"reading inputs from {inputs}", step="load")
        data = load(inputs, audit)                       # calls audit.automation(...) inside

        # A human-in-the-loop gate — attribute it to the person:
        audit.human(operator or "operator", "reviewed exceptions and approved", step="review")

        out = render(data, outputs, audit)               # calls audit.automation(...) inside
        audit.set_outcome(output=str(out))
        return out
```

Per run, `audit_logs/<YYYY-MM-DD_HH-MM-SS>/` gets: `audit.log` (human-readable, one line
per event), `events.jsonl` (one JSON per event, each carrying `actor`), and
`run_summary.json` (the automation-vs-human sign-off split, counts, and status).

## Non-negotiables

1. Every automation run goes through `core.audit` — never bare `print`/`logging` for run steps.
2. Default to `audit.automation(...)`. Attribute **every** human action or approval with
   `audit.human(who, ...)` — that split is the reviewer sign-off.
3. Never put secrets, passwords, or tokens in an audit action or `detail`.
4. Use `redact=True` whenever the trail may be shared for review (masks money / doc numbers).
5. Let `audit_run(...)` finalize — it writes `run_summary.json` and marks `ok`/`failed`
   on exception. Don't hand-roll finalization.
6. `audit_logs/` is git-ignored client data — never commit it.
