# Model cookbook: SheetModel / Column / CellStyle / SheetLayout

All from `core.excel`.

## CellStyle (declarative; renderer maps to openpyxl)

Covers the full standard formatting set: font family + size, number/data format,
horizontal **and** vertical alignment, bold/italic, background highlight, borders
(uniform box or per-side).

```python
CellStyle(
    number_format="#,##0.00",   # Excel number/data format string
    font_name="Calibri",        # font family (standardized font)
    font_size=10,
    bold=False, italic=False,
    font_color="FF0000",        # text colour, RGB hex (no '#')
    fill="FFFF00",              # solid background fill / highlight, RGB hex
    border=False,               # box border on all four sides
    border_style="thin",        # "thin" (default) | "medium" | "thick" | …
    border_color=None,
    border_top=None, border_bottom=None,   # per-side override (e.g. an
    border_left=None, border_right=None,    # accounting total's double underline)
    align="right",              # horizontal: left | center | right
    valign="center",            # vertical: top | center | bottom
    wrap=False,
)
```

Reusable tokens: `YELLOW_FILL`, `GREEN_FILL`, `BOX`.

`style.merge(other)` overlays `other` on `style`: non-None fields in `other` win,
boolean flags union (once `True`, stays `True` — you cannot turn a base flag off
via a merge; set the base without it instead). This is how a standardized base
composes with per-column and conditional styles (the renderer does this for you).

### Standardized base style (sheet-wide)

`SheetModel(default_style=..., default_header_style=...)` applies a base style to
every data / header cell; a column's own `style` and any conditional style are
merged on top. Use this for "one house font and size across the sheet":

```python
base = CellStyle(font_name="Calibri", font_size=10)
SheetModel(name="Recon 4411", frame=df, columns=[...],
           default_style=base, default_header_style=base.merge(CellStyle(bold=True)))
```

Prefer loading these styles from the rules workbook (see `rules-file.md`) so they
are operator-configurable rather than hard-coded.

**Conditional styling** is a *registered* predicate, not a DSL:

```python
from core.excel import register_conditional_style, CellStyle, YELLOW_FILL

@register_conditional_style("matched_yellow")
def _matched(row):                 # row is the row's dict
    return YELLOW_FILL if row.get("matched") else None

Column("amount", "Amount", letter="E",
       value=ColumnRef("amount"), conditional_style="matched_yellow")
```

## Value sources

- `ColumnRef("frame_key")` — take values verbatim from that frame column.
- `Literal(value)` — constant broadcast to every row.
- `Computed("strategy_name")` — values from a registered strategy `fn(frame)->Series`.
- `FromFormula()` — value obtained by evaluating the column's `formula`.

Register a Computed strategy (e.g. a per-group sum — the right way to do what an
Excel SUM-over-a-group range cannot):

```python
from core.excel import register_strategy

@register_strategy("group_sum")
def _group_sum(frame):
    return frame.groupby("match_group")["amount"].transform("sum")
```

Keep money as `Decimal` inside a strategy too — `groupby().transform("sum")` over
a Decimal column sums exactly.

## Column

```python
Column(
    key="amount",                 # frame column holding authoritative values
    header="Amount",
    letter="E",                   # explicit target column; omit for positional
    value=ColumnRef("amount"),    # or Literal / Computed / FromFormula
    formula=FormulaTemplate("=VLOOKUP(B{row},'GL Dump'!P:S,9,0)"),  # optional
    style=CellStyle(number_format="#,##0.00"),
    header_style=None,            # optional per-column header override
    conditional_style="matched_yellow",  # optional, overrides style per row
    width=14,                     # optional column width
)
```

A Column with neither `value` nor `formula` raises at construction. `FromFormula`
without a `formula` raises. Two columns targeting the same `letter` raise.

`Column.writes_formula` is `True` when a `FormulaTemplate` is present and its
`write_to_cell` is `True` (set `write_to_cell=False` to evaluate a formula for the
value but *not* write the string into the cell).

## SheetLayout & PreservedRegion

```python
SheetLayout(
    header_rows=(1, 2),     # rows never overwritten (e.g. a subtotal row + headers)
    data_start_row=3,       # first row of the replaceable data region
    write_headers=False,    # True only for a fresh sheet; False keeps template headers
    preserved_regions=(
        PreservedRegion(start_row=87, end_row=95, mode="freeze_values"),
    ),
)
```

`PreservedRegion` is a block *below* the data region (totals, an exception area)
that must survive and shift by the data-row delta. `mode="freeze_values"`
captures evaluated values + full styling so relocating it doesn't leave stale
cross-sheet formula references; `mode="verbatim"` copies cells as-is.

`SheetModel.extra_cells` holds fixed-position writes *outside* the data region —
`(row, letter, value, style)` tuples applied verbatim after the data ops. Use for
a cell above `data_start_row` that must be rewritten each run (e.g. a header-row
subtotal) and is therefore not touched by the data-region clear.

## SheetModel & populate

```python
model = SheetModel(name="Recon 4411", frame=df, columns=[...], layout=SheetLayout(...))
```

`render()` calls `populate(model, evaluator=..., colmap=...)` for you, filling
`Computed` and `FromFormula` columns so `model.frame` holds authoritative values
for every key. Call `populate()` yourself only if you need the values before
rendering (e.g. for a tie-out assertion or an audit log).

`model.letter_frame()` returns a view keyed by Excel column letter — used as
evaluator input and as a lookup target for other sheets' VLOOKUPs.
