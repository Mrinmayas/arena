# Authoring a new automation

How to build a new finance automation from this boilerplate. Read this once; then let
the skills in `.claude/skills/` guide each part.

## 1. Spin up a new repo

Copy this boilerplate into a new repo (via `copier`, or a plain copy), then answer the
spin-up questions (see `copier.yml`): the automation's `project_slug`, the `client`, and
which capabilities it needs — `browser` (portal automation), `pdf` (statement/TB parsing),
`sharepoint`, `engine` (multi-step orchestration), and whether it needs the Excel
escape-hatch (in-place edit / COM / macros).

Install only what the automation uses:

```
uv sync                                   # core (pandas, openpyxl)
uv sync --extra browser --extra pdf       # add capabilities as needed
```

## 2. Layout

```
automation/     your logic: automation.py (the run() spine) + _transform.py + _report.py
core/           vendored, DO NOT hand-edit: audit, excel, portals, secretstore, engine
recorder/       dev-time Playwright recorder (uv run record <url>)
rules.xlsx      operator-tunable values (auto-created)
tests/          smoke + golden tie-out tests (mandatory)
inputs/ outputs/ audit_logs/ runs/   git-ignored run data
```

Keep `core/` pristine — update it via `copier update`, not local edits, so fixes
propagate. Everything you write lives under `automation/` and `tests/`.

## 3. Write the logic

The entrypoint is `automation/automation.py::run(inputs, outputs, *, operator, redact)`
(run via `uv run automate`). Fill in:

- **`_transform.py`** — read and classify the input files into a pandas model. Use
  `core.excel.read_table` and `core.excel.compat.find_header` for ERP exports with
  preamble rows; parse money with `core.excel.coerce.money` (Decimal, never float).
- **`_report.py`** — build a `SheetModel` and render **once** with `core.excel.render()`.
  → Follow the **excel-automation** skill. Do not hand-roll openpyxl.

## 4. Observability is not optional

Every step is attributed through `core.audit`: `audit.automation(...)` for what the tool
does, `audit.human(who, ...)` for anything a person did or approved. The `run()` spine
already opens the audit run; you just record actions. → **observability** skill.

## 5. Optional capabilities

- **Portal login** — subclass `core.portals.BrowserPortal` (SSO, persistent profile) or
  use the username/password template; credentials come from `core.secretstore`, never
  from code. Run headed so the operator completes SSO/MFA. → **portal-login** skill.
- **Engine** — if the automation is multi-step with resume / human-in-the-loop, build it
  as `core.engine` `Automation([Stage([Step(...)])])` and call `run_automation(...)`.
  You get the `runs/<run_id>/` store plus the same `audit_logs/` trail for free.

## 6. Test it (mandatory)

Ship at least a smoke test and one **golden-file tie-out** test that fails on one cent of
drift (Decimal compare). Add safety-property tests for invariants that must never break.
→ **test-generation** skill. `uv run pytest`.

## 7. Ship checklist

- [ ] `uv run pytest` is green (smoke + a tie-out test).
- [ ] `README.md` filled in (operator setup + how to run).
- [ ] No client data, secrets, or SSO profiles committed (they're git-ignored — keep it that way).
- [ ] Runs on a clean machine via `uv sync && uv run automate`.
- [ ] Code is on a branch / PR, not left uncommitted.
