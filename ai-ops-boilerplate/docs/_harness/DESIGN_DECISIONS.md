# AI-Ops Automation Harness — Design Decisions & Thought Process

*A design journal: how this repo came to be, the constraints that shaped it, the
decisions made (including the ones reversed), and why. Read `AUTHORING.md` for **how**
to build an automation; read this for **why** the harness is shaped the way it is.*

---

## Contents

1. [The idea and the problem it solves](#1-the-idea-and-the-problem-it-solves)
2. [Constraints the sponsor set](#2-constraints-the-sponsor-set)
3. [How the reference automations were studied](#3-how-the-reference-automations-were-studied)
4. [The decisions (with rationale)](#4-the-decisions-with-rationale)
5. [Decisions we reversed — and why](#5-decisions-we-reversed--and-why)
6. [What got built](#6-what-got-built)
7. [The documentation subsystem — one source, three views](#7-the-documentation-subsystem--one-source-three-views)
8. [Positioning: where the value actually is](#8-positioning-where-the-value-actually-is)
9. [What is proven vs. deferred](#9-what-is-proven-vs-deferred)

---

## 1. The idea and the problem it solves

The team had delivered ~20 finance/back-office automations. Each new one still started
from a blank folder — re-deciding the same layout, re-wiring the same audit trail,
re-solving the same portal-login and Excel problems, re-writing the same kind of README.
That setup work is repeated, undifferentiated effort.

**The idea:** a vetted, copy-me **starting point** — an *asset* — that any team standing
up such an initiative can copy *before* they build. Not a framework to depend on; a
skeleton to fork. It carries the directory structure, the audit logic, a Playwright
recorder, tests, a skeletal `CLAUDE.md`, and the house-style skills already in place.

**The value it targets:** roughly **35% of the build team's effort per use case**. A
precise distinction that shaped the whole framing:

- **~35% is the *build team's* saving** (the ~10-developer SWAT team). It is **not** an
  FTE or cost saving.
- **FTE realisation is the *operator-side* outcome** — the 300–500-person operator
  network runs the shipped tools; that is where headcount is realised. The harness
  accelerates *how fast* those tools ship, which pulls FTE realisation forward.

Keeping those two numbers from being conflated is why the solution document leads with
"faster FTE realisation" as a qualitative outcome rather than a cost figure.

> **Not a prototype.** The harness was **reverse-engineered from what already works** in
> ~20 delivered use cases. Its credibility is that it distils proven production tools, not
> that it proposes a clever new architecture.

---

## 2. Constraints the sponsor set

These were given up front and are load-bearing — most of the design follows from them.

| Constraint | What it means | Consequence |
|---|---|---|
| **Discovery is already complete** | The harness is *purely* the build-phase starter. No discovery tooling, no discovery skills, don't design for that phase at all. | The automation is **wired explicitly**; there is no requirements/discovery layer. |
| **Don't trust `common/`** | The shared `common/` folder was built by another developer before there was a real project. Challenge every piece; keep only what the trusted automations actually use; full removal is acceptable. | `common/` was **not** vendored wholesale — it was curated into a slimmer `core/`. |
| **Only explicitly-shared refs are "trusted"** | Imitate only the reference repos the sponsor named; ignore the rest of the monorepo's demo/experimental projects. | The study (§3) was scoped to four repos, not the whole codebase. |
| **Tests always live in the automation's own repo** | The main-branch pattern of central `common_automation/tests/<name>/` is explicitly rejected. | Every scaffold ships an in-repo `tests/`; everything is self-contained per repo. |
| **No GUI by default** | The majority of shipped tools are headless; a Tkinter GUI is per-project, not baseline. | The spine is a headless `run()` + CLI. |
| **"Agentic" means build-time only** | Shipped solutions are deterministic Python (Playwright + Excel). **No runtime LLM / Anthropic API on the operator machine.** "Agentic" = built *with* Claude Code. | No runtime-LLM layer, no API-key handling, no llm-integration skill. |
| **Observability is mandatory** | The human-vs-automation split is a compliance requirement (four-eyes sign-off), not a nice-to-have. | Audit is always-on and uniform; there is no un-audited path. |
| **Per-repo, self-contained, laptop-runnable** | Each deliverable is copied and shipped to operator machines via `uv run`, isolated per client. | Vendored core (not a shared package); safe `.gitignore` as a control. |

---

## 3. How the reference automations were studied

Four trusted reference repos were read in depth (via parallel exploration agents) before
any design was locked:

- **wsa-reconsmart-connector** — flat scripts, raw Playwright, no engine.
- **ar_aging_compiler** — self-contained pure-Python Excel, no browser.
- **duplicate_payment_detector** — standalone Playwright + pandas analysis, no engine.
- **trade_payables_recon** (incl. `ap_aging`) — full Stage/Step engine with resume + HITL.

**The finding that drove the architecture:** these span a wide complexity range, and only
*one* of the four uses the orchestration engine. A single rigid template can't serve both
a 200-line Excel compiler and a multi-stage portal workflow with review gates. So the
harness had to be **layered** — a small always-present spine, with heavier capabilities
opt-in.

Other findings that became design inputs:

- The **recorder** had zero coupling to `common/` → it lifts out cleanly as a standalone
  capability (only a Microsoft-specific API-path regex needed to become config-driven).
- `common/excel/` was pure-Python, zero COM → already cross-platform; **keep**.
- `common/secretstore/` was **Windows-only** (hard-coded Credential Manager) → this
  violated the cross-platform requirement and had to be fixed with a macOS Keychain
  backend.
- `common/portals/` was a decent generic base but imported `RunContext` from the engine →
  had to be **decoupled** so a simple automation can log in without pulling in the engine.
- Two audit systems coexisted: the engine's structured `runs/<run_id>/` store (only when
  the engine is used) and a per-automation `audit_logs/<timestamp>/` OTel-to-file trail
  (the **common baseline** all three non-engine refs used). The baseline became the
  mandatory floor; the runstore became an engine-only addition.
- A second scan of *other* developers' projects confirmed two populations — engine-
  integrated tools vs. standalone GUI tools — and surfaced concrete anti-patterns to
  encode as guardrails (no hard-coded date constants, resolve ERP columns by header not
  index, never mutate input folders, no `from x import *`, rules workbook over Python
  constants, and so on).

---

## 4. The decisions (with rationale)

Each of these is stated as **context → decision → why → consequence**.

### 4.1 Packaging — per-repo template, vendored core

- **Context.** Reusable machinery could be a shared installable package (one Enterprise
  account, technically feasible) or vendored into each repo.
- **Decision.** **Per-repo template**: the harness is a standalone repo copied to start
  each automation; the reusable `core/` is **vendored in**, not imported from a shared
  package.
- **Why.** Deliverables must be self-contained, client-isolated, and runnable on an
  operator laptop with nothing but `uv`. A shared package couples every deliverable's
  lifecycle to a central release; vendoring keeps each repo independently shippable and
  auditable.
- **Consequence.** The known cost is **drift** — a core fix doesn't automatically reach
  already-created repos. That is what `copier update` is meant to solve later (§5, §9);
  today a plain copy is accepted.

### 4.2 One spine, engine opt-in

- **Context.** The complexity range (§3) tempted a two-scaffold design: a `simple`
  scaffold and an `orchestrated` scaffold, chosen at spin-up.
- **Decision.** **One spine.** A single structure defaults to a headless
  `run(inputs, outputs)` + `uv run` CLI; the Stage/Step **engine** (resume, HITL, the
  `runs/` store) is switched **on only when needed** — like a capability layer, not a
  separate scaffold.
- **Why.** Two scaffolds means two things to teach, test, and maintain, and a fork in the
  authoring path from day one. One spine that degrades gracefully to single-stage/no-HITL
  serves the simple case without a second framework.
- **Consequence.** The engine is genuinely optional; a simple compiler ships none of it.
  The orchestrated case wires **one** automation explicitly (a direct `build_automation()`
  call) — no `automations.yaml`, no registry `discover()` scan.

### 4.3 Observability — mandatory and uniform

- **Context.** For controls-sensitive finance work, "who did what" is the reviewer
  sign-off artefact (a four-eyes control), not just logging.
- **Decision.** Every run writes `audit_logs/<timestamp>/`:
  - `audit.log` — human-readable, one line per event.
  - `events.jsonl` — append-only; **every event stamped `actor: automation | human`**,
    plus step/stage, action, status, timestamp, redactable detail.
  - `run_summary.json` — the sign-off split: what the automation did vs. what a human did
    or approved.
  Human events are auto-recorded at boundaries (run trigger; HITL gates). API:
  `audit.automation(...)` by default, `audit.human(who, action)` for anything a person
  did. Implementation is **stdlib logging + JSONL** (always on, zero heavy deps); OTel is
  an optional extra to export spans off-box.
- **Why.** Attribution *is* the compliance value. Making it optional would create an
  un-audited path, which for finance is unacceptable.
- **Consequence.** Whether or not the engine is used, the **same** `audit_logs/` trail is
  produced — the engine bridges its events into the same stream via an `AuditSubscriber`.
  Only the OTel library is optional; the observability capability is not.

### 4.4 Excel — `render()` default, a narrow escape hatch

- **Context.** Raw `openpyxl` cell-poking had repeatedly caused corrupt files, data loss,
  and stale-formula bugs in production. But a genuine minority of tools legitimately need
  raw access (in-place operator-workbook edits, live COM recalc, `.xlsm` macros, surgical
  edits to huge templates).
- **Decision.** `core.excel.render()` (build a pandas model → render **once**, atomic
  save, preserve-by-default) is **mandatory for all workbook generation**. Raw openpyxl /
  xlwings-COM is allowed **only** for the explicitly-declared cases `render()` structurally
  can't express — and money is **`Decimal` (`coerce.money`)** even there. COM paths are
  flagged Windows-only.
- **Why.** This kills the corrupt-file / cent-drift bug class for the common case while
  still accommodating the real exceptions the codebase proves exist. It honours the
  existing `CLAUDE.md` mandate rather than inventing a looser policy.
- **Consequence.** Shared safety utilities — `find_header` (ERP-preamble-resilient header
  detection) and `repair_dropped_rels` (openpyxl external-link corruption on save) — were
  vendored into `core.excel.compat` because they were duplicated across production tools.

### 4.5 No discovery, explicit wiring — legible over clever

- **Context.** The source monorepo used an auto-discovery registry (`automations.yaml` +
  a `discover()` scan).
- **Decision.** Drop it. The automation is wired **directly** in `automation/automation.py`.
  A missing or misconfigured step fails loudly, never silently.
- **Why.** A copy-me starter must be something the next developer reads top-to-bottom, not
  reverse-engineers. Magic registries optimise for a large monorepo; a per-repo template
  optimises for legibility.
- **Consequence.** More explicitness in each repo, which is exactly the point.

### 4.6 Safe `.gitignore` as a security control

- **Context.** The source repo had a real leak: journal-entry run traces
  (`audit_logs/**/trace.jsonl`) were committed to a shared remote because `audit_logs/`
  was not ignored. A global auto-commit `git add .` hook on this machine compounds that
  risk on data repos.
- **Decision.** The shipped `.gitignore` ignores `inputs/`, `outputs/`, `audit_logs/`,
  `runs/`, recordings, and browser profiles **by default** — treated as a control, not a
  convenience. Client financial data must never be committed.
- **Why.** Deny-by-default is the only safe posture when an auto-commit hook can stage
  everything. Secrets come from the OS keychain (`core.secretstore`), never source.
- **Consequence.** A fresh clone won't carry data dirs; `.gitkeep` placeholders keep the
  structure.

### 4.7 Cross-platform by construction

- **Decision.** Pure-Python `openpyxl` / `render()` is the cross-platform default;
  `secretstore` got a macOS Keychain backend + a platform-aware factory (the Windows-only
  original was the single biggest portability bug). xlwings/COM recalc is Windows-only and
  flagged per-automation.
- **Why.** Developers work on Macs; operators may be on Windows. The default lane must
  work on both, with the platform-specific escape hatch clearly marked.

---

## 5. Decisions we reversed — and why

Honest record of the thinking, because the reversals *are* the design process.

- **Two scaffolds → one spine.** Initially planned `simple` + `orchestrated` scaffolds.
  Reversed to a single spine with the engine opt-in, to avoid two divergent structures to
  maintain (§4.2).
- **Vendored core was challenged.** An independent critique argued for a versioned,
  installable `wsa-core` package pinned per repo instead of vendoring, plus `copier` for
  the shell. We kept **vendoring** (it fits the self-contained, client-isolated, laptop-
  runnable model) but adopted the critique's real point: `copier update` is the eventual
  answer to vendored-core drift. Copier is **deferred**, not rejected.
- **Excel dual-policy tightened.** An early "raw openpyxl for standalone tools" idea was
  narrowed to "`render()` mandatory + a narrow, explicitly-declared escape hatch" (§4.4),
  matching the existing hard-won `CLAUDE.md` rule rather than loosening it.
- **Data-exposure remediation deprioritised.** The committed-traces leak (§4.6) is real,
  but the sponsor judged it intra-firm with no client harm and out of scope for this
  asset; history rewrite + force-push to a shared remote is destructive and team-
  coordinated. So the harness *prevents* the pattern going forward (safe `.gitignore`)
  without rewriting existing history.
- **ROI framing corrected.** Early illustrative day-counts ("1 week → 3.5 days") were
  dropped in favour of **~35% build effort saved per use case**, with the build-vs-operator
  distinction made explicit (§1).

---

## 6. What got built

On branch `feature/ai-ops-boilerplate` of the `314495_wsa-automation` repo (a git
worktree; `main` untouched), mirrored to the personal `Mrinmayas/arena` repo. **20/20
tests green.**

**Vendored, generic `core/`** — brand-free, distilled from the trusted production tools:

| Module | Provides |
|---|---|
| `core.audit` | Always-on observability; `actor: automation \| human` on every event; audit.log + events.jsonl + run_summary.json sign-off split; money redaction; stdlib-only, OTel opt-in. |
| `core.excel` | The `render()` framework (pandas model → one atomic write), `Decimal` money, formula seam, plus `compat.py` = `find_header` + `repair_dropped_rels`/`snapshot_rels`. |
| `core.portals` | Generic browser-login base, engine-decoupled: default-channel auto-launch, persistent Entra/Conditional-Access profile, tiered click-flow, teardown. SSO *and* username/password. |
| `core.secretstore` | Credential store with Windows (Credential Manager) **and** macOS (Keychain) backends + a platform-aware factory. |
| `core.engine` | Opt-in orchestration: Automation → Stage → Step, retries, resume, HITL, structured `runs/` store. Bridges events into `core.audit`. |
| `core.docs` | One reconciled `PROCESS_STEPS.md` → README + operator Word guide + draw.io diagram (see §7). |
| `recorder/` | Standalone, config-driven Playwright recorder (dev-time capture). |

**Six build-time skills** in `.claude/skills/` — the differentiated value (§8), each
written against the shipped `core/` and symbol-checked so it teaches the real API:
`observability`, `excel-automation`, `portal-login`, `test-generation`, `doc-generation`,
`workflow-diagram-generation`.

Plus `docs/AUTHORING.md` (the runbook), a skeletal `CLAUDE.md` (house rules for the AI
assistant), the capability-extras `pyproject.toml`, and `docs/solution.html` (the
value-forward, six-page solution document).

---

## 7. The documentation subsystem — one source, three views

Operators live in Word; the build team and operator sign-off need a workflow diagram; the
runbook is a README. Writing those three by hand guarantees they drift apart. So:

**One reconciled `PROCESS_STEPS.md` is the single source of truth**, and the README, the
operator Word guide, and the draw.io diagram are all *rendered* from it.

The non-negotiable first step is **reconciliation**: the process narrative (a transcript,
a steps file, a Teams message, or a discovery Word doc) is diffed **against the actual
shipped code**, a divergence report is produced, a human resolves it, and only then does
anything render. On the Duplicate Payment Detector this surfaced six genuine narrative-vs-
code divergences (e.g. the priority signal reads the code's `Type` column, not the doc's
`Exc Type`; the release step the docstring called "not built" was in fact fully
implemented). That reconciliation is what makes an operator sign-off trustworthy.

**A design lesson worth recording — the diagram layout.** The first draw.io renderer put
every node on a single horizontal row. That was fine for a straight pipeline, but a
decision that fans out to several mutually-exclusive outcomes drew its branch arrows
sideways into adjacent boxes — overlapping arrows, labels landing on top of boxes. The fix
was a small **layered (rank-based) layout**: rank each node by longest path from Start (so
a decision's alternatives share a *column*), then stack same-rank nodes on separate *rows*
so decisions **fan out vertically** (up and down) while the spine stays straight
left→right. The lesson: the bug wasn't in one diagram, it was in the *rule* — fixing the
rule fixes every diagram the skill will ever generate, and a no-overlap geometry test
stops the regression coming back. This is the core argument for a deterministic renderer
over hand-drawing.

---

## 8. Positioning: where the value actually is

A prior-art scan found **no all-in-one competitor**: the fusion of a finance back-office
RPA skeleton + bundled AI skill files, copied per-repo, appears novel. But the individual
pieces — Playwright, openpyxl, RPA templates — are commodity.

**So the durable advantage is not the plumbing. It is the conventions and finance-domain
knowledge, captured as skills an AI assistant follows when generating each new
automation.** That is where maintenance investment should go — the skills and the vetted
`core/` — not into bespoke infrastructure.

This is why the solution document frames the asset for "AI & Automation teams" broadly
(whoever stands up such an initiative), leads with a *proven track record* rather than a
concept pitch, and keeps the build-team saving (~35%) distinct from the operator-side
outcome (faster FTE realisation).

---

## 9. What is proven vs. deferred

**Proven / done:**
- `core/{audit,excel,portals,secretstore,engine,docs}` + `recorder` — vendored, generic,
  committed, pushed. audit/excel/engine/docs are pytest-verified (**20 tests**);
  portals/secretstore are compile- and genericity-verified (live browser/keychain is a
  Mac/CI step).
- Six skills + `AUTHORING.md`, all symbol-checked against `core/`.
- The documentation subsystem, validated end-to-end on the Duplicate Payment Detector
  (README + operator Word + draw.io from one reconciled source).
- Safe `.gitignore`, cross-platform secretstore, `uv.lock` committed for reproducible
  operator installs.
- The solution document (`docs/solution.html`).

**Deferred (deliberately):**
- **Worked-example automation + golden-file tie-out test** (P3) — a real `_report.py`
  using `core.excel.render()` plus a correctness-to-the-cent regression test, proving
  `uv run automate` end-to-end on a laptop. This is the most valuable remaining work.
- **`copier` templatisation** — adopt when several instances exist; its `copier update`
  propagates a core/skill fix into *already-created* repos, solving vendored-core drift at
  the scale where it starts to pay off. A plain copy is sufficient today.

**Known limitation carried forward:** vendored core drifts until copier lands; the leaked
historical traces in the source repo remain (prevention, not remediation, was the chosen
scope).

---

*Prepared as a living design record for the AI-Ops Automation Harness. It reflects the
state of the `feature/ai-ops-boilerplate` branch and the reasoning behind it — including
the decisions that were reversed, because those are part of the thought process.*
*— Mrin Shrivastava · SWAT team*
