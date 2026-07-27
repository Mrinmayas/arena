---
name: excel-automation
description: >-
  Use when writing or modifying Python that reads, manipulates, or generates
  Excel (.xlsx / .xlsm) files in this repo — automation steps that build a
  working file, apply formulas/formatting, detect a header row inside an ERP
  export, or are driven by an operator-editable rules workbook. Triggers:
  openpyxl, xlwings, COM, workbook, worksheet, cell, xlsx, xlsm, macros, "rules
  file", "Vars sheet", "Matching Rules", formula template, VLOOKUP/SUBTOTAL,
  accounting format, header detection, reconciliation output, tie-out. Grounds
  the agent in the core/excel framework so it does NOT hand-roll openpyxl
  cell-poking (which has repeatedly caused corrupt files, data loss, and
  stale-formula bugs) and does NOT carry money as float.
---

# Excel automation in this repo

There is a purpose-built framework at **`core/excel/`**. Use it. Do **not**
write fresh `openpyxl.load_workbook` / cell-by-cell mutation logic to *generate*
a workbook — that path produced corrupt files, lost an operator's sheet, and
stale-value bugs (see `reference/anti-patterns.md`).

`render()` is the **default and mandatory path for all workbook generation.** Raw
openpyxl / xlwings-COM is allowed *only* for the four declared escape-hatch cases
in `reference/escape-hatches.md`, and money is still `Decimal` via
`coerce.money` even there.

This skill covers only the Excel layer. Observability (`core.audit`), wiring
(`automation/automation.py`), and tests live in their own skills.

## The one rule: keep values in a pandas model, render to Excel once

```
Extract  →  Transform  →  Build model  →  Render once
read_table   pandas         SheetModel      render()
find_header  (money =        (values +       (one open,
(read once)   coerce.money;   formulas +      atomic save,
              Decimal)        styles)         preserve-by-default)
```

Python owns the authoritative values. Money is carried as `Decimal`
(`coerce.money`), never `float`. Excel formulas an operator authored are
**evaluated in Python** (so the value is real and usable downstream) while the
live formula string is still written into the cell for the operator. The
framework never reads a formula cell back to get its value.

## Decision tree

- **Reading an ERP export whose header sits under a variable preamble** (title
  banner, filter echo, blank spacers)? → `find_header(...)` to locate the header
  row by anchor labels, then `read_table`. See `reference/inputs.md`.

- **Exploring an existing/example workbook to replicate it?** → Capture **both
  values AND formatting** (font, size, number format, alignment H+V, bold, fill,
  borders, widths). Formatting is the most-missed half — inspect it explicitly.
  See `reference/discipline.md` §0.

- **About to call `openpyxl` directly / loop over cells writing values to
  generate output?** → STOP. Build a `SheetModel` and call `render()`. See
  `reference/discipline.md`.

- **In-place edit of an operator's live workbook, live COM recalc, `.xlsm` macro
  preservation, or huge-template surgery?** → These are the *only* sanctioned
  raw-openpyxl / xlwings-COM cases. Read `reference/escape-hatches.md` first —
  money still uses `coerce.money`.

- **A column whose value is *also* shown as an Excel formula** (e.g. a VLOOKUP
  the operator wants to see)? → It's "the seam". See `reference/formulas.md` and
  `reference/model.md`.

- **Operator-editable behaviour (thresholds, patterns, GL accounts, column
  mappings, formula templates, styles)?** → It belongs in the rules workbook,
  loaded and validated via `core.excel.rules`. See `reference/rules-file.md`.

- **Defining output columns / styles / preserved regions?** →
  `reference/model.md`.

- **Excel reported the rendered file as corrupt / "recovered records" dialog?**
  → openpyxl dropped OOXML parts or relationship ids. See
  `reference/escape-hatches.md` (`snapshot_rels` + `repair_dropped_rels`,
  `restore_parts`).

- **Need the exact public signatures?** → `reference/api.md`.

- **Unsure why a rule exists / tempted to take a shortcut?** →
  `reference/anti-patterns.md` (each entry is a real failure this framework
  prevents).

## Minimal shape

```python
import pandas as pd
from core.excel import (
    read_table, render, SheetModel, SheetLayout, Column, ColumnRef,
    FromFormula, FormulaTemplate, ColumnMap, coerce,
)

# 1. Extract (read once, file closed immediately)
gl = read_table(src_path, sheet="Ledger", header_row=1, start_row=2)

# 2. Transform — all logic in pandas; money is Decimal, other numerics are float
gl["amount"] = gl["amount"].map(coerce.money)          # Decimal, cents, Excel rounding
gl["qty"]    = gl["qty"].map(coerce.to_number)         # ordinary float is fine here
gl["date"]   = gl["date"].map(coerce.to_date)          # real dates so a date format renders
out = gl[["date", "doc_no", "amount"]].copy()

# 3. Build the model (values + formula columns + styles + layout)
model = SheetModel(
    name="Recon 4411",
    frame=out,
    columns=[
        Column("date",   "Date",   letter="A", value=ColumnRef("date")),
        Column("doc_no", "Doc No", letter="B", value=ColumnRef("doc_no")),
        Column("ref",    "Ref",    letter="D",
               value=FromFormula(),
               formula=FormulaTemplate("=VLOOKUP(B{row},'GL Dump'!P:S,4,0)")),
    ],
    layout=SheetLayout(data_start_row=3),
)

# 4. Render once into the template workbook (preserves all other sheets)
render(output_path, [model],
       colmap=ColumnMap(sheet_frames={"GL Dump": dump_letter_frame}))
```

## Non-negotiables

1. `render()` for all generation — one open, one close, atomic save, via
   `core.excel.render` / `core.excel.workbook` only. Never
   `load_workbook(...).save(...)` in a loop of sub-tasks. Raw openpyxl / COM only
   for the four escape hatches in `reference/escape-hatches.md`.
2. Preserve-by-default — `render()` only touches sheets you pass it. Never delete
   a sheet to "clean up".
3. Money is `Decimal` via `coerce.money` (or `coerce.to_decimal`), never
   `float(cell.value)` and never `coerce.to_number` for amounts. This holds in
   the escape-hatch paths too.
4. Coerce every raw numeric/date cell through `core.excel.coerce` — never bare
   `float(cell.value)`, which aborts a run on `"N/A"` or `"1,234.56"`.
5. Never read a formula cell back for its value — the value lives in the model
   (`FromFormula()` + `FormulaTemplate`).
6. Operator-tunable values (thresholds, accounts, formula templates, styles) live
   in the rules workbook with a `FieldSpec` schema, not as Python constants.
