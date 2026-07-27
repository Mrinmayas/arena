# Golden-file tie-out — the standard to add

This is the highest-value test for a finance automation and the pattern most
automations in this repo are currently missing. It exists here as the standard to
add. Read this before writing your first tie-out test.

## What it is

A **golden file** is a committed, known-good copy of the automation's output. A
**tie-out test** re-runs the automation on a committed sample input and asserts the
freshly produced numbers equal the golden file's numbers — to the cent.

```
tests/
  conftest.py
  fixtures/
    sample_input.xlsx        # a committed, synthetic input (no client data)
  golden/
    expected_report.xlsx     # the known-good output, produced once and reviewed
  test_tieout.py
```

## Why float compare and structural asserts are not enough

- `assert produced == golden` on raw cell values compares floats and will flake on
  binary-float artifacts (`0.1 + 0.2 != 0.3`).
- `pytest.approx(expected, abs=0.01)` *hides* the exact class of bug you care about:
  a one-cent allocation or rounding drift.
- Asserting the report's shape (row count, headers, a Total column exists) passes
  even when a refactor silently changed a rounding mode, dropped a filter row, or
  mis-allocated a cent. The shape is right; the money is wrong.

The fix: compare as `Decimal`, coercing **both** sides through `core.excel.coerce.money`
(2 dp, Excel half-up rounding), with tolerance exactly `Decimal("0.00")`.

## Worked shape

```python
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from core.excel import coerce

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN   = Path(__file__).parent / "golden"
CENT     = Decimal("0.00")   # zero tolerance — a tie-out ties or it doesn't

# The money columns whose values are the reconciliation's contract.
MONEY_COLS = ("D", "E", "F", "G")


def _money_cells(ws, cols):
    """Yield (coord, Decimal) for every money cell below the header row."""
    for row in range(2, ws.max_row + 1):
        for col in cols:
            yield f"{col}{row}", coerce.money(ws[f"{col}{row}"].value)


def test_report_ties_out_to_the_cent(tmp_path):
    # Run the real automation on the committed sample inputs; run() returns the produced path.
    from automation.automation import run
    out = run(FIXTURES, tmp_path)

    # data_only=True reads the last-saved computed values, not formula strings.
    produced = load_workbook(out, data_only=True)["Report"]
    golden   = load_workbook(GOLDEN / "expected_report.xlsx", data_only=True)["Report"]

    got = dict(_money_cells(produced, MONEY_COLS))
    exp = dict(_money_cells(golden, MONEY_COLS))

    assert got.keys() == exp.keys(), "produced report changed shape vs golden"
    drift = {c: (got[c], exp[c]) for c in exp if abs(got[c] - exp[c]) > CENT}
    assert not drift, f"tie-out drift (produced vs golden): {drift}"
```

Notes:
- `data_only=True` returns cached computed values, so it only works if the workbook was
  saved by something that recalculated formulas. If your renderer writes formula strings
  and never recalcs, either (a) also assert the tie-out total that your code computed in
  Python before rendering, or (b) render values, not formulas, for the columns you tie out.
- Report the *set* of drifting cells (not just the first) so a failure shows the whole
  blast radius.

## Producing and maintaining the golden

1. Build the sample input by hand (or generate it) — small, synthetic, and covering the
   tricky cases (an accounting-negative, an `N/A`, a thousands-separated amount, a value
   that sits on a band boundary).
2. Run the automation once, eyeball the output against a manual calculation, and only
   then copy it to `tests/golden/`.
3. Commit input and golden together. Never put real client figures in either.
4. When an intended change moves the numbers, regenerate the golden **in the same PR**
   and show the number diff in the description. A golden that changes without review is
   no protection at all.

## Tie-out asserts you can add without a golden workbook

If the automation computes a reconciliation total in Python (the usual case), assert it
directly — this catches drift even before a golden exists:

```python
def test_ledger_ties_to_zero():
    result = reconcile(sample_ledger(), sample_aging())
    assert result.difference == Decimal("0.00")   # third-party AR must tie to the GL
```
