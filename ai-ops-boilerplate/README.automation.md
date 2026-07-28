# AI-Ops Automation

<one-line: what this tool does>. Runs locally via `uv run`; produces `<output>` from files in `inputs/`.

> Built from the **AI-Ops boilerplate**. Deterministic Python — no LLM at runtime.

## 0. One-time setup (Windows / PowerShell)
1. `winget install Python.Python.3.12`
2. `winget install astral-sh.uv`
3. Close and reopen the terminal.
4. `uv sync`  — add capabilities as needed, e.g. `uv sync --extra browser --extra pdf`

## 1. How to run
1. Drop this period's files into `inputs/`.
2. `uv run automate --inputs inputs --outputs outputs`
3. Find the report in `outputs/`, and the audit trail in `audit_logs/<timestamp>/`.

## 2. What it produces
| Artifact | What it is |
|---|---|
| `outputs/<report>` | The deliverable. |
| `audit_logs/<ts>/run_summary.json` | What the **automation** did vs what a **human** did/approved (sign-off trail). |
| `audit_logs/<ts>/audit.log` | Human-readable, line-per-event. |
| `audit_logs/<ts>/events.jsonl` | Structured events, each stamped with `actor`. |

## 3. For developers
- What the harness gives you (capability catalogue): `docs/_harness/CAPABILITIES.md`.
- House rules: `CLAUDE.md`. Build skills: `.claude/skills/`.
- `uv run pytest` runs the smoke + golden-file tie-out tests.
- To record a portal flow during development: `uv run record <url>` (needs `--extra browser`).

## Troubleshooting
| Symptom | What to do |
|---|---|
| `uv: command not found` | Reopen the terminal after setup step 2, or re-run the winget install. |
| No output produced | Check `audit_logs/<ts>/run_summary.json` — its `status` and last events show where it stopped. |
