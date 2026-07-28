# What this harness produces

A catalogue of what you get by starting from this template — the capabilities the
harness hands you, and the artefacts an automation built from it produces. (For *your
automation's* run-time outputs, see the top-level `README.md` §2.)

## Capabilities the harness gives you

| Capability | What you get | Where |
|---|---|---|
| **Boilerplate code / project skeleton** | A single legible spine: `automation/automation.py` with one explicit `run(inputs, outputs)` entry point, a `uv run automate` CLI, and `_transform.py` / `_report.py` stubs. Explicit wiring — no auto-discovery magic. | `automation/` |
| **Audit logging capability** | Always-on observability. Every run writes a timestamped `audit_logs/<ts>/` trail, with **every event attributed `actor: automation \| human`** — the four-eyes sign-off artefact. Stdlib-only; OpenTelemetry export is an optional extra. | `core/audit/` |
| **Excel generation** | The `render()` framework (build a pandas model → one atomic write, preserve-by-default), `Decimal` money via `coerce.money`, ERP-preamble-resilient `find_header`, and `repair_dropped_rels` for the openpyxl save-corruption bug. Cross-platform (pure-Python); COM/xlwings is a flagged Windows-only escape hatch. | `core/excel/` |
| **Portal / browser (Playwright) automation** | A generic browser-login base: auto-launch the default channel, a **persistent Entra / Conditional-Access profile**, tiered click-retry, SSO *and* username/password login — plus a **session-teardown** step (see the callout below). | `core/portals/` |
| **Playwright recorder** | A standalone, config-driven recorder to capture a portal flow during development (`uv run record <url>`). Portal-agnostic. | `recorder/` |
| **Orchestration engine (opt-in)** | When a workflow needs it: `Automation → Stage → Step`, retries, resume, human-in-the-loop gates, and a structured `runs/<run_id>/` store. Its events bridge into the same `core.audit` trail. | `core/engine/` |
| **Process & operator documentation** | From one reconciled `PROCESS_STEPS.md`: a **README run-guide** and an **operator-friendly Word (.docx) guide** (steps tagged automated vs. you, HITL flags, embedded screenshots). | `core/docs/` + `doc-generation` skill |
| **Workflow diagram generation** | A **draw.io** workflow diagram rendered from that same `PROCESS_STEPS.md`: ranked left→right layout, decisions that fan out cleanly, actor colours, HITL badges, a legend. | `core/docs/drawio.py` + `workflow-diagram-generation` skill |
| **Test-case generation** | Guidance + patterns for a mandatory `tests/` suite: pure-function, **golden-file tie-out (correctness to the cent)**, safety-property, and engine end-to-end tests. | `tests/` + `test-generation` skill |
| **Secret handling** | Credentials from the OS keychain — Windows Credential Manager **and** macOS Keychain — via a platform-aware factory. Never from source or a committed `.env`. | `core/secretstore/` |
| **Data-safety controls** | A `.gitignore` that keeps `inputs/`, `outputs/`, `audit_logs/`, `runs/`, recordings, and browser profiles out of version control by default — client data is never committed. | `.gitignore` |
| **Build-time AI skills** | Six house-style skills an AI assistant follows when generating each automation: `observability`, `excel-automation`, `portal-login`, `test-generation`, `doc-generation`, `workflow-diagram-generation`. | `.claude/skills/` |

## Artefacts a built automation produces at run time

| Artefact | What it is |
|---|---|
| `outputs/<report>` | The deliverable. |
| `audit_logs/<ts>/run_summary.json` | What the **automation** did vs. what a **human** did/approved (sign-off trail). |
| `audit_logs/<ts>/audit.log` | Human-readable, line-per-event. |
| `audit_logs/<ts>/events.jsonl` | Structured events, each stamped with `actor`. |
| `runs/<run_id>/` | *(engine automations only)* structured, resumable run store. |
| `PROCESS_STEPS.md` → README · operator `.docx` · `.drawio` | The reconciled process source and its three rendered views. |

## Playwright: yes — the structure includes a teardown "finally"

Confirming the specific question: **yes**, a browser automation built on `core.portals`
ships with a session teardown, and it's reconciled with the persistent-profile pattern:

- On `close()` the portal runs `reset_session()` **before** tearing the context down — the
  equivalent of a `finally` block. It **clears cookies and `localStorage`/`sessionStorage`**
  so the next run logs in fresh, then closes the browser context (which disposes the
  browser). It is **best-effort and never raises** — cleanup must not mask the run's outcome.
- The **on-disk profile (`user_data_dir`) is deliberately KEPT**, not deleted: Entra /
  Conditional-Access treats it as a compliant device, and a throwaway profile would be
  blocked. So the *web session* is cleared each run, but the *device profile* persists.
- The low-level launcher (`core/portals/browser.py`) also closes the context and browser
  inside a real `try/finally`, so the browser is closed even if the flow errors.

> In short: **clear the web session (cookies + storage), close the browser, keep the
> device profile** — implemented in `core/portals/browser_portal.py` (`reset_session` +
> `close`) and `core/portals/browser.py` (the `finally`).
