# Anti-patterns (each is a real failure this framework prevents)

These come from the legacy in-place reconciliation tool that motivated the
framework. When you're tempted to take one of these shortcuts, don't.

## 1. Deleting a sheet to "clean up" → silent data loss

**Bad:** `del wb["Notes"]` ran on every run, destroying operator reconciliation
content that lived on that sheet.

**Do:** `render()` is **preserve-by-default** — it only touches the sheets you
pass as models, and its integrity guard raises `WorkbookIntegrityError` rather
than let a sheet vanish. Never delete a sheet. If you must replace data on a
sheet, model it and let the bounded-replace + `PreservedRegion` machinery handle
it.

## 2. Opening the output workbook many times → corruption

**Bad:** six+ `load_workbook(output) → mutate → save → close` cycles across
sub-tasks, plus a leaked handle (no `wb.close()`). A crash mid-cycle left a
locked or half-written file.

**Do:** Extract→Transform in memory, then **one** `render()` (one open, atomic
save). Read inputs with `read_table` (opens once, closes). Open via
`open_workbook` (context-managed) if you ever need raw access — never bare
`load_workbook`.

## 3. `float(cell.value)` on raw cells → ValueError aborts the run

**Bad:** `float(t_val or 0)` crashed on `"N/A"` or a thousands-separated
`"1,234.56"`.

**Do:** coerce through `core.excel.coerce` — `coerce.to_number(value)` for
ordinary numerics (handles blanks, `N/A`, thousands separators, accounting
negatives, never raises). Coerce numeric columns once in the Transform phase.

## 4. Carrying money as `float` → cent drift, wrong tie-out

**Bad:** `amount = float(cell.value)`, then summing/allocating/rate-applying in
float. `0.1 + 0.2 != 0.3`, and Python's default rounding is half-to-even, so a
reconciliation that must tie to the cent silently disagrees with Excel.

**Do:** money is `Decimal` via `coerce.money` (`= to_decimal` quantized to cents
with `EXCEL_ROUNDING` = half-away-from-zero, matching Excel's `ROUND`). Keep it
Decimal all the way through the model; openpyxl writes Decimal as a real number.
This holds in the raw-openpyxl / COM escape-hatch paths too.

## 5. Reading a formula cell back to get its value → stale/None

**Bad:** write a formula string, then later open with `data_only=True` and read
the cell — openpyxl returns the value Excel last cached, which is `None` for a
formula written this run. The code then half-worked by also recomputing the value
in Python, inconsistently.

**Do:** Python owns the value. Use `FromFormula()` + `FormulaTemplate(...)`: the
framework evaluates the formula in Python (authoritative value in `model.frame`)
and writes the formula string for the operator. Never re-read the cell.

## 6. `delete_rows(start, max_row - start + 1)` → blind clear, wrong on shift

**Bad:** assumes you know where data ends and ignores blocks below it; combined
with reopen cycles, it mangled totals/exception areas when row counts changed.

**Do:** declare `SheetLayout(data_start_row=..., preserved_regions=(...))`. The
renderer computes the real old data length, clears residual rows, and relocates
preserved blocks by the delta.

## 7. Hard-coding the header row of an ERP export

**Bad:** `read_table(header_row=5)` because "the header is on row 5 today". The
next export's preamble is one row taller and every column reads shifted (or
blank), silently.

**Do:** `find_header(ws, anchors=[...])` to locate the header row by the labels
you expect, then feed `.row` into `read_table`. See `inputs.md`.

## 8. Dispatching strategies by scattered `if rule_type == "..."`

**Bad:** matching logic chosen by string equality spread across many passes, with
thresholds hard-coded.

**Do:** register named strategies (`register_strategy`) and select them by name
from the validated rules table (`require_known_strategies`). Put thresholds in the
rules workbook as `FieldSpec`s (a money tolerance coerced with
`coerce.to_decimal`).

## 9. Hand-parsing Excel formulas / using `eval`

**Bad / dangerous:** `eval(formula_string)` or ad-hoc regex per formula.

**Do:** use `HybridEvaluator`. It classifies and evaluates via a sandboxed AST
walker (row-local), pandas merge (VLOOKUP), and column sum (SUM/SUBTOTAL).
Unsupported formulas raise `FormulaEvalError`. Extend by adding a backend behind
the `FormulaEvaluator` protocol — never `eval`.

## 10. Exploring example sheets for values only → formatting silently dropped

**Bad:** reading an example workbook, noting the cell *values*, and reproducing
them with no fonts, number formats, alignment, highlights, or borders. The output
"has the right numbers" but looks nothing like the original and fails review.

**Do:** a complete exploration captures formatting too — font family + size,
number/data format, horizontal **and** vertical alignment, bold, fill colours and
their meaning, borders, widths, merges. Inspect it programmatically via openpyxl
(`cell.font`, `cell.number_format`, `cell.alignment`, `cell.fill`, `cell.border`),
then encode it as named styles on the rules `Styles` sheet + `CellStyle`s on the
columns. See `discipline.md` §0.

## 11. Combinatorial subset search with no bound

**Bad:** `itertools.combinations` over all unmatched rows with no cap —
`C(60,10)` hung the run.

**Do:** bound it with a rules-file setting (e.g. `Max_Subset_Size`), operate on
NumPy arrays from the frame, and warn + continue when no subset is found rather
than hanging or hard-failing.

## 12. Trusting openpyxl's output byte-for-byte → "recovered records" dialog

**Bad:** render an Excel-authored template and ship the file; the operator opens
it and Excel reports corruption and strips their comments / printer settings /
external-link references.

**Do:** openpyxl is a partial-fidelity writer. Snapshot the source's `.rels`
before render and call `repair_dropped_rels` after; call `restore_parts` to bring
dropped parts back. See `escape-hatches.md`. Never hand-edit the zip yourself.
