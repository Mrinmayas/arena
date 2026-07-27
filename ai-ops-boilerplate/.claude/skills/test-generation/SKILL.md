---
name: test-generation
description: >-
  Write tests for a finance/back-office automation in this repo. Use when adding
  or reviewing tests, when an automation ships with zero tests, or when a
  reconciliation/output could drift at the cent level. Teaches the four test
  shapes this repo uses — pure-function, golden-file tie-out, safety-property,
  and engine end-to-end — grounded in the committed tests/ suite. Prevents the
  two failures that bite finance automations: shipping an untested automation,
  and a cents-level drift that passes structural asserts but corrupts the output.
triggers:
  - test
  - pytest
  - golden file
  - tie-out
  - tie out
  - regression
  - safety property
  - conftest
  - fixture
  - "uv run pytest"
prevents: >-
  Shipping an automation with no tests; a cent-level numeric drift that
  structural asserts never catch.
---

# Test Generation

Tests for an automation live **in the automation's own repo**, under `tests/`, and
run with `uv run pytest`. They import `core` and `automation` exactly the way the
tool imports them at runtime — no packaging tricks, no mocks of your own code.

## The one rule

**Every automation ships a smoke test AND at least one tie-out (golden-file) test
that FAILS on a single cent of drift.** A reconciliation that only asserts "the
report has 7 rows and a Total column" is not tested — structural asserts do not
catch a cents-level error, and cents-level errors are exactly what a finance
automation exists to prevent. Compare produced numbers to a committed known-good
output as `Decimal`, to the cent, tolerance `0.00`.

No automation is "done" with zero tests. This is the anti-pattern this skill fixes.

## How the suite is wired (do not re-invent)

`tests/conftest.py` puts the repo root on `sys.path` so imports match runtime:

```python
import sys
from pathlib import Path
# core/ and automation/ import the same way they do when the tool runs for real.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

That is the whole `conftest.py`. With it in place, tests just `from core.excel import coerce`
and `from automation import ...`. Run everything with `uv run pytest`.

## Decision tree — which shape do I write?

```
Is the thing under test a pure calc / parse (no file I/O, no Excel, no network)?
  └─ YES → PURE-FUNCTION test. Feed synthetic dict/DataFrame in, assert value out.
           Fastest, most of your tests. (see test_excel.py)

Does it produce a workbook / report whose NUMBERS must be correct to the cent?
  └─ YES → GOLDEN-FILE TIE-OUT test. Run automation on a committed sample input,
           compare produced cells against a committed golden workbook, Decimal,
           tolerance 0.00. THE highest-value test for finance. (see reference/golden-tie-out.md)

Is there an invariant that must NEVER break regardless of input?
  └─ YES → SAFETY-PROPERTY test. Assert the invariant directly
           (input never mutated; money is Decimal; a confirmed real duplicate is
           never auto-dismissed).

Is the automation orchestrated through core.engine (stages/steps)?
  └─ YES → ENGINE END-TO-END test. Assert the run succeeds AND both audit trails
           are written. (see test_engine.py)
```

Most automations need all four. At minimum: one smoke (does it run at all) + one tie-out.

## Shape 1 — Pure-function test

Put the business logic in a pure function; test it with synthetic data, no Excel I/O.
This is why `core.excel.coerce` and `core.excel.compat` are leaf modules — they are
trivially testable. Mirror `tests/test_excel.py`:

```python
from decimal import Decimal
from core.excel import coerce, compat

def test_money_is_decimal_to_the_cent():
    # Money is Decimal (never float) and rounds half-up like Excel's ROUND().
    assert coerce.money("1,234.567") == Decimal("1234.57")
    assert isinstance(coerce.money("10"), Decimal)

def test_find_header_survives_erp_preamble():
    rows = [
        ["Q report", None, None],   # ERP title banner
        [None, None, None],          # blank spacer
        ["Vendor", "Invoice", "Amount"],
        ["ACME", "INV1", 100],
    ]
    m = compat.find_header(rows, anchors=["Vendor", "Amount"])
    assert m.row == 3               # 1-indexed header row
    assert m.col("Amount") == 2     # 0-indexed column offset
```

Your own logic (band bucketing, allocation, tie-out math) goes the same way: extract
it into a function that takes plain data, then assert exact values.

## Shape 2 — Golden-file tie-out (the highest-value pattern; currently the gap)

Record a known-good output workbook once, commit it under `tests/golden/`, commit a
matching sample input under `tests/fixtures/`, then on every run re-produce the output
and compare **to the cent** with `Decimal`. Full worked shape in
`reference/golden-tie-out.md`. Minimal skeleton:

```python
from pathlib import Path
from decimal import Decimal
from openpyxl import load_workbook
from core.excel import coerce
from automation.automation import run   # this repo's entrypoint: run(inputs_dir, outputs_dir) -> Path

CENT = Decimal("0.00")  # tie-outs must match exactly; tolerance is zero cents

def test_report_ties_out_to_golden(tmp_path):
    out = run(Path("tests/fixtures"), tmp_path)   # returns the produced workbook path

    produced = load_workbook(out, data_only=True)["Report"]
    golden   = load_workbook("tests/golden/expected_report.xlsx", data_only=True)["Report"]

    for row in range(2, golden.max_row + 1):          # skip header row
        for col in ("D", "E", "F"):                    # the money columns
            got = coerce.money(produced[f"{col}{row}"].value)
            exp = coerce.money(golden[f"{col}{row}"].value)
            assert abs(got - exp) <= CENT, f"drift at {col}{row}: {got} vs {exp}"
```

Why golden and not just structural asserts: a reconciliation's whole job is that the
numbers tie. A refactor that shifts a rounding mode, drops a filter, or mis-allocates
by one cent leaves the shape intact and the money wrong — only a cent-exact compare
against a frozen good output catches it. Coerce **both** sides through `coerce.money`
so the compare is `Decimal`-vs-`Decimal`, never float-vs-float.

## Shape 3 — Safety-property test

Assert invariants that must hold for *every* input. Examples:

```python
def test_input_files_are_never_mutated(tmp_path):
    inputs = tmp_path / "in"; inputs.mkdir()
    src = inputs / "in.xlsx"; make_sample(src)
    before = src.read_bytes()
    run(inputs, tmp_path / "out")
    assert src.read_bytes() == before   # an automation never edits its own input

def test_confirmed_duplicate_is_never_auto_dismissed():
    # A human-confirmed real duplicate must survive every downstream filter.
    dupes = detect_duplicates(rows_with_one_confirmed_dupe())
    assert any(d.confirmed for d in dupes)   # invariant, not a value

def test_money_columns_are_decimal():
    report = compute(sample_rows())
    assert all(isinstance(v, Decimal) for v in report.amounts)
```

A safety-property test is worth more than ten value tests because it pins the one
thing that must never regress no matter how the code is refactored.

## Shape 4 — Engine end-to-end

For automations orchestrated through `core.engine`, assert the run succeeds **and**
that both trails are written: the structured `runs/<run_id>/run.json` store and the
`audit_logs/<ts>/run_summary.json` human-vs-automation trail. Mirror `tests/test_engine.py`:

```python
import asyncio, json
from core.engine import Automation, Stage, Step, run_automation

def _build_demo() -> Automation:
    async def do_work(ctx):              # step fns are `async def fn(ctx)`
        ctx.put("count", 3)              # ctx.put/ctx.get are sync
        await ctx.log("did the work")    # ctx.log is a COROUTINE — always await it
    return Automation("demo", [Stage("main", [Step("do_work", do_work)])])

def test_engine_runs_and_writes_both_trails(tmp_path):
    result = asyncio.run(run_automation(
        _build_demo(),
        runs_dir=tmp_path / "runs",
        audit_root=str(tmp_path / "audit_logs"),
        operator="alice",
    ))
    assert "succeed" in str(result.status).lower()

    run_dirs = [p for p in (tmp_path / "runs").iterdir() if p.is_dir()]
    assert (run_dirs[0] / "run.json").exists()

    audit_dirs = [p for p in (tmp_path / "audit_logs").iterdir() if p.is_dir()]
    summary = json.loads((audit_dirs[0] / "run_summary.json").read_text())
    assert summary["counts"]["automation"] >= 1   # steps/stages bridged
    assert summary["counts"]["human"] >= 1         # operator launch recorded
```

For a non-engine `run()`-style automation the equivalent smoke test drives
`core.audit` directly and asserts `audit_logs/<ts>/run_summary.json` exists with an
`ok` status (see `tests/test_audit.py` for the `audit_run(...)` context manager).

## Non-negotiables

1. **A tie-out test exists and fails on one cent of drift.** Compare produced vs golden
   as `Decimal` (coerce both sides through `coerce.money`), tolerance `0.00`. This is
   the gap in most automations — close it.
2. **Every automation ships a smoke test.** "Runs end-to-end on the sample input and
   writes its audit trail" — no automation is done at zero tests.
3. **Money is `Decimal`, asserted as `Decimal`.** Never `pytest.approx` a money value;
   float tolerance hides exactly the cent-level bug you are testing for.
4. **Tests import `core`/`automation` via `conftest.py`'s `sys.path` insert** — same as
   runtime. Do not mock your own modules; do not add a package shim.
5. **Fixtures and goldens are committed, synthetic, and client-free.** Put sample inputs
   in `tests/fixtures/`, known-good outputs in `tests/golden/`. Never commit real client
   data (`inputs/`, `outputs/`, `audit_logs/`, `runs/` are git-ignored — keep it that way).
6. **Regenerate a golden only on a reviewed, intended change**, and diff the numbers in
   the PR. A golden updated silently is the same as having no golden.
7. **Engine step fns are `async def fn(ctx)`; `ctx.log` is awaited, `ctx.put/get` are not.**
   Assert both `runs/<run_id>/run.json` and `audit_logs/<ts>/run_summary.json` for an
   orchestrated run.
8. **Assert at least one safety invariant** that must never break (input not mutated;
   confirmed exception never auto-dismissed; money stays `Decimal`).
