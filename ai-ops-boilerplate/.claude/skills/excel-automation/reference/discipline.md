# Discipline: Extract → Transform → Build → Render once

The framework exists to make this the only easy path. Incremental in-place Excel
mutation is what caused corruption and data loss. `render()` is the default and
**mandatory** path for generating a workbook; the only exceptions are the four
declared cases in `escape-hatches.md`.

## 0. Exploring example sheets (do this BEFORE coding)

When learning an existing workbook to replicate it, **a complete exploration
captures both values and formatting.** Formatting is the most commonly missed
half — do not stop at "what values are in the cells." For every region you will
reproduce, record:

- **Values & formulas** — cell contents, which cells are formulas, headers, the
  data start row, and any totals / exception blocks below the data.
- **Formatting (easy to miss — inspect it explicitly):**
  - font family and size (the standardized house font),
  - number / data format (currency, dates, decimals, thousands separators),
  - horizontal **and** vertical alignment,
  - bold / italic,
  - background fill (highlight) colours and what they signify,
  - borders (which cells, which sides/weight),
  - column widths and merged cells.

Inspect formatting programmatically, not by eyeballing — openpyxl exposes it:

```python
from core.excel import open_workbook
with open_workbook(path) as wb:
    c = wb["Recon 4411"]["E3"]
    print(c.value, c.number_format, c.font.name, c.font.size, c.font.bold,
          c.alignment.horizontal, c.alignment.vertical,
          c.fill.fgColor.rgb if c.fill and c.fill.patternType else None,
          {s: getattr(c.border, s).style for s in ("left","right","top","bottom")})
```

Translate every observed format into a named style in the rules workbook's
`Styles` sheet (see `rules-file.md`) and a `CellStyle` on the column — don't
silently drop it. A reproduction that gets the numbers right but loses the fonts,
number formats, highlights, and borders is **not** a faithful reproduction.

## 1. Extract (read once)

Use `read_table(path, sheet=..., header_row=..., start_row=...)`. It opens the
file read-only, pulls the sheet into a pandas DataFrame, and closes it. The input
is never held open while you work.

If the source is an ERP export whose real header sits under a variable preamble,
locate the header row first with `find_header(...)` and feed its `.row` to
`read_table(header_row=...)`. See `inputs.md`.

For a sheet you need keyed by Excel **column letter** (e.g. as a VLOOKUP target),
build that view yourself from the read frame, or read it and rename columns to
letters. The formula evaluator works on letter-keyed frames.

Never hold two workbooks open at once. Never keep the source open across the
transform.

## 2. Transform (pandas only — no Excel here)

All business logic happens on DataFrames in memory:

- **Money → `Decimal`.** Coerce amount columns with `coerce.money`
  (`= to_decimal` quantized to cents with Excel's half-away-from-zero rounding)
  the moment they enter the frame: `df["amt"] = df["amt"].map(coerce.money)`.
  Money that is multiplied, rate-applied, allocated, or tied out to the cent must
  stay `Decimal` — `float` drifts and rounds differently from Excel. Never use
  `coerce.to_number` (float) for amounts. openpyxl accepts `Decimal` and writes
  it as a real number, so Decimal money flows through `render()` unchanged (the
  column is object-dtype in pandas, which is expected).
- **Other numerics → `coerce.to_number`** (float). This is where the old
  `float("N/A")` / `float("1,234.56")` crash is prevented — do it once, up front.
- **Dates → `coerce.to_date`** (handles strings, `datetime`, and Excel integer
  serials). Excel only renders a date if the cell holds a real date value — a
  string lands as text. Then apply a date number format (`date:<CLDR>` or
  `cldr_to_excel_date(...)`). Money columns get an accounting format
  (`accounting()` / `"accounting:$"`).
- Matching, grouping, sorting, subset search — all pandas/numpy.
- Produce one DataFrame per output sheet, with the authoritative values.

There is **no Excel I/O in this phase**. If you find yourself opening a workbook
to compute something, stop — compute it in pandas.

## 3. Build (declare SheetModels)

A `SheetModel` is `name + frame + columns + layout`. Columns map frame keys to
output cells and carry formula templates and styles. See `model.md`.

Formula columns (`FromFormula` / `FormulaTemplate`) are evaluated during
`populate()` (called by `render()` automatically) so the model frame ends up with
authoritative values for every column — including the ones shown as formulas.

## 4. Render (once)

`render(path, models, colmap=...)`:

- Opens the workbook **once**, applies every model, saves atomically, closes.
- **Preserves every sheet you did not pass.** Unrelated operator content survives;
  an integrity guard raises `WorkbookIntegrityError` if a render would drop a
  sheet.
- Replaces each sheet's data region with exactly the model's rows; clears residual
  old rows; relocates blocks below the data region (`PreservedRegion`s) by the
  row delta, freezing their values so stale cross-sheet formulas don't break.

If you need computed cached values in the saved file before a human opens it in
Excel (openpyxl writes formulas without cached results), that is a *recalc*
concern — out of scope for the default path; the values are already correct in
the model, and Excel recalculates formulas on open. Don't add a second write pass
to "fix" it. (If cached values genuinely must be in the file, that is the live-COM
recalc escape hatch — see `escape-hatches.md`.)

## Update an existing sheet vs generate fresh

`render()` supports **both**; prefer updating a template when one exists.

**Update in place (template exists)** — the default and usually correct mode:

- Pass the existing workbook path; all sheets and formatting are preserved.
- Put the column headers in the rows *above* `data_start_row` and keep
  `write_headers=False` (default). Those header rows — values **and** formatting
  (bold, fill, widths, merges) — are kept untouched; clearing starts at
  `data_start_row`.
- Old data cells from `data_start_row` down are deleted before the new rows are
  written — **values and styling both** (no stale fills/borders left on emptied
  rows). New rows are styled fresh from the model, so the model is the single
  source of truth for data-region formatting.
- Blocks below the data (totals, exception areas) are relocated via
  `PreservedRegion`s, with their **full styling** preserved across the move.

Use this whenever the sheet carries anything openpyxl would lose on a rebuild:
header styling, merged cells, frozen panes, column widths, sibling sheets.

> Caveat: `render()` (via openpyxl) is a **partial-fidelity writer** — it silently
> drops cell comments, printer settings, drawings/images, custom XML, and can
> leave dangling relationship ids, so Excel may show a "recovered records" repair
> dialog. Repair the rendered output with `restore_parts` /
> `repair_dropped_rels` (see `escape-hatches.md`). If the template is a macro
> workbook (`.xlsm`), the render path does not preserve VBA — that is a declared
> escape-hatch case.

**Generate fresh** — only when there is no template to honour and you fully own
the output: render to a non-existent path, set `write_headers=True`, and supply
header/data styles via the model. Simpler, but you must define every bit of
formatting yourself.

## Resume safety

`render()`'s atomic save (temp file + `os.replace`) makes re-rendering
idempotent — a resumed step can re-run the whole Extract→Render flow and
converge. Attribute the write through `core.audit` per the observability skill.
