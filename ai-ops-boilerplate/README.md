# AI-Ops Automation Harness

A vetted, **copy-me template** for building finance/back-office automations fast — the
proven skeleton, audit trail, portal & Excel machinery, documentation/diagram generators,
and house-style AI skills already in place. Reverse-engineered from ~20 delivered use cases.

> Deterministic Python (Playwright + Excel), runs on an operator's machine via `uv`.
> "Agentic" means built **with** Claude Code — there is **no LLM at runtime**.

## What you get

- **Boilerplate spine** — one explicit `run(inputs, outputs)` entry point + a `uv run automate` CLI (no auto-discovery magic).
- **Audit logging** — always-on; every event attributed **automation vs human** (the four-eyes sign-off trail).
- **Excel generation** — the `render()` framework, `Decimal` money, ERP-resilient header detection.
- **Portal / Playwright automation** — persistent Entra / Conditional-Access profile, tiered click-retry, and a **session teardown** (clears the web session, keeps the device profile).
- **Playwright recorder** — standalone, config-driven flow capture.
- **Orchestration engine (opt-in)** — Stage/Step, retries, resume, human-in-the-loop, a `runs/` store.
- **Docs from one source** — a README run-guide, an operator **Word** guide, and a **draw.io** workflow diagram, all rendered from one reconciled `PROCESS_STEPS.md`.
- **Test-case generation** — golden-file tie-out (correctness to the cent), safety-property, engine e2e.
- **Six build-time AI skills** in `.claude/skills/` — the house-style captured as reusable instructions.

→ **Full catalogue** (with the run-time artefacts and the exact Playwright teardown behaviour): **[`docs/_harness/CAPABILITIES.md`](docs/_harness/CAPABILITIES.md)**

## Use this template

1. Click **Use this template** on GitHub (or copy the repo).
2. **Make it your automation's repo** — promote the run-guide to be the landing README:
   ```
   rm README.md && mv README.automation.md README.md
   ```
   then fill in its placeholders. (This harness page is meant to be replaced by *your automation's* run-guide.)
3. `uv sync` — add capabilities as needed, e.g. `uv sync --extra browser --extra pdf`.
4. Build — house rules in [`CLAUDE.md`](CLAUDE.md), the runbook in [`docs/AUTHORING.md`](docs/AUTHORING.md), and the skills in `.claude/skills/`.

## Two READMEs, by design

Two audiences read a README at two different moments, so the harness ships two:

| File | Audience | When |
|---|---|---|
| **`README.md`** (this page) | A developer **evaluating/adopting** the harness | On GitHub, before "Use this template" |
| **`README.automation.md`** | The **operator** + the dev of *your* automation | After you promote it to `README.md` (step 2) — clean, shippable, delivered to the operator |

The run-guide is kept pristine on purpose: it's what you hand the operator. Promoting it
(step 2) makes it the landing page of *your* automation, while this harness page stays
available under `docs/_harness/`.

## For adopters & reviewers

- **What it produces** — [`docs/_harness/CAPABILITIES.md`](docs/_harness/CAPABILITIES.md)
- **Why it's built this way** (design journal) — [`docs/_harness/DESIGN_DECISIONS.md`](docs/_harness/DESIGN_DECISIONS.md) (also `.html` / `.docx`)
- **Solution & technical reference** — `docs/_harness/solution.html`, `docs/_harness/ai-ops-harness.html`

---
*AI-Ops Automation Harness · Mrin Shrivastava · SWAT team.*
