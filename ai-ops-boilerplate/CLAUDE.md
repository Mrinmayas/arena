# CLAUDE.md — AI-Ops Automation

Guidance for Claude Code when building or modifying an automation in this repo.
This repo was spun up from the **AI-Ops boilerplate** — keep its conventions.

## What this is
A single, self-contained finance/back-office automation that runs on an operator's
machine via `uv run`. Deterministic Python (Playwright + Excel). **No LLM at runtime** —
the shipped tool must be reproducible and auditable. "Agentic" means built *with* Claude Code.

## Golden rules
1. **Observability is mandatory.** Every run goes through `core.audit` and writes
   `audit_logs/<timestamp>/`. Attribute every action: `audit.automation(...)` by default,
   `audit.human(who, ...)` for anything a person did or approved. Follow the **observability** skill.
2. **Excel: use `core.excel.render()` for all workbook generation.** Never hand-roll
   openpyxl cell-poking — it has repeatedly caused corrupt files, data loss, and stale-formula
   bugs. Raw openpyxl / xlwings-COM is allowed ONLY for the declared escape-hatch cases
   (in-place edit, live recalc, `.xlsm` macros, huge templates) and MUST still use
   `coerce.money` (Decimal) for money. Follow the **excel-automation** skill.
3. **Never commit client data.** `inputs/`, `outputs/`, `audit_logs/`, `runs/` are
   git-ignored. Do not add real client files, secrets, or SSO profiles to git.
4. **Secrets come from `core.secretstore`** (OS keychain), never from source or a committed `.env`.
5. **Tests are mandatory and live in `tests/`.** Include a smoke test and at least one
   **golden-file tie-out** test (assert correctness to the cent). Follow the **test-generation** skill.
6. **Explicit wiring, no magic.** The automation is wired directly in
   `automation/automation.py`. No auto-discovery. A missing/misconfigured step must fail
   loudly, never silently.

## Layout
```
automation/     the automation spine (build_report style; engine opt-in)
core/           vendored reusable core (audit, excel, portals, secretstore, engine)
recorder/       standalone Playwright recorder (dev-time only)
rules/          operator-tunable rules workbook (auto-created)
tests/          smoke + golden-file tie-out tests
inputs/ outputs/ audit_logs/   git-ignored run data
```

## Commands
```
uv sync                       # install core; add extras: --extra browser --extra pdf ...
uv run automate --help        # run the automation
uv run pytest                 # tests
uv run record <url>           # record a portal flow (needs: --extra browser)
```

## Skills
Build using the skills in `.claude/skills/`: **observability**, **excel-automation**,
**portal-login**, **test-generation**, **doc-generation** (README + operator Word from
`PROCESS_STEPS.md`), **workflow-diagram-generation** (draw.io from the same source). Read
the relevant skill before writing that kind of code.

## Docs come from one source
The README run-guide, the operator Word (.docx) guide, and the draw.io workflow diagram
are all **rendered from `PROCESS_STEPS.md`** (schema: `core/docs/SCHEMA.md`) — never
hand-authored independently. Reconcile the process narrative against the code into that
file first, then render. Renderers: `core.docs.word.render_operator_guide` (needs
`--extra docs`) and `core.docs.drawio.render_diagram` (stdlib).
