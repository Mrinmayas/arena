# Formulas: the value/formula seam

Operators author Excel formulas in the rules file (it's the language they know).
The framework **evaluates them in Python** so the value is authoritative, and
**also writes the live formula string** into the cell for the operator. These two
halves are explicit on every `Column` so neither happens silently.

## The four valid Column combinations

| `value`              | `formula`   | meaning |
|----------------------|-------------|---------|
| set (`ColumnRef`/`Literal`/`Computed`) | `None` | plain value written to the cell |
| `None`               | set         | formula only; **logic must not read this cell back** |
| set **and** formula  | set         | **the seam**: formula in the cell, value owned by the model |
| `FromFormula()`      | set         | formula authored; framework evaluates it to fill the value |

The authoritative values are exposed only via `model.frame`. The formula string
is emitted only by `render()`. There is deliberately **no API** that reads an
openpyxl formula cell back to obtain a value — that was the stale-value bug.

## What the evaluator supports (`HybridEvaluator`)

The evaluator (`core.excel.formula_eval`) classifies each template
(`classify(formula) -> FormulaClass`) and routes it to an in-house backend.
`{row}` means "this row" (`apply_template` substitutes the concrete row number).

- **`ROW_LOCAL`** — same-row scalars: `IF`, `ROUND`, `ABS`, `AND`, `OR`, `NOT`,
  `MIN`, `MAX`, arithmetic (`+ - * /`, unary `-`), comparisons (`= <> < <= > >=`).
  e.g. `=IF(U{row}="Debit",T{row},T{row}*-1)`. Evaluated by a sandboxed AST
  walker (`RowLocalEvaluator`, **no `eval`**). Arithmetic operands are coerced
  with `to_number`, so dirty cells don't crash.
- **`LOOKUP`** — exact-match `=VLOOKUP(key{row},'Sheet'!C1:C2,idx,0)` → pandas
  merge/map (`LookupEvaluator`). The lookup sheet must be provided via
  `ColumnMap(sheet_frames=...)`, keyed by Excel column letter. Approximate match
  (4th arg `1`/`TRUE`) is not supported. First match wins on duplicate keys.
- **`AGGREGATE`** — `=SUM(C1:C2)` / `=SUBTOTAL(9,C1:C2)` over **one** column →
  column sum, broadcast (`AggregateEvaluator`). Per-group totals (e.g. a
  reconciliation group sum) are a **model `Computed` strategy**, not an Excel
  range — don't try to express grouping in a flat range.

Anything else classifies as `UNSUPPORTED` and raises `FormulaEvalError` naming
the offending token. To extend coverage, add a backend behind the
`FormulaEvaluator` protocol (`supports(formula)` + `eval_column(...)`) — don't
reach for `eval` or write per-formula special cases in the automation.

## Money note

The AST arithmetic in `RowLocalEvaluator` runs on **float** (via `to_number`) —
appropriate for a presentational formula column the operator will see recalc in
Excel. Do **not** route authoritative money through a `FromFormula` arithmetic
column and then rely on that float downstream; keep the authoritative amount as a
`Decimal` model column (`ColumnRef` / `Computed`) and, if the operator also wants
to *see* a formula, use the seam (`value` + `formula` both set) so the Decimal
stays the source of truth.

## Why not a library / recalc?

A spike confirmed the `formulas` library pulls heavy deps (scipy), emits
warnings, and still needs a full workbook model for cross-sheet VLOOKUP. The
in-house hybrid is lighter and fits the DataFrame model. A LibreOffice/xlwings
recalc backend can be slotted behind the same `FormulaEvaluator` interface later
if cached values in the file ever matter (that is the live-COM escape hatch in
`escape-hatches.md`); it is not needed for correctness.

## Contract you must uphold

The evaluator assumes the frame is **typed** (numeric columns already numeric —
`to_number`/`money` applied in Transform). The evaluator's arithmetic coercion is
a safety net, not a substitute — a bare `IF(...)` branch returns the column as-is.
