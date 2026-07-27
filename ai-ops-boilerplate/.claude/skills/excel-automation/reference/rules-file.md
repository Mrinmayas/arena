# The rules workbook: Excel authoring → validated config

Operators tune behaviour by editing an `.xlsx` rules workbook (familiar to them).
Code loads and **validates** it into a structured config via `core.excel.rules`,
with errors that point at the exact cell.

Anything an operator might reasonably change belongs here, **not** as a Python
constant: file/sheet names, start rows, column-transfer specs, thresholds
(tolerances, caps), matching patterns, GL accounts, and **Excel formula
templates** for output columns.

## Two sheet shapes

1. **Settings (key/value)** — column A = key, column B = value. Loaded by
   `load_settings`.
2. **A rules table** (e.g. `Matching Rules`) — a header row then rows sourced by
   column letter. Loaded by `load_rule_table`.

## Declaring the schema

```python
from core.excel import FieldSpec, TableColumnSpec, coerce, load_settings, load_rule_table

SETTINGS = [
    FieldSpec("Recon_Sheet_Name", required=True, example="Recon 4411"),
    FieldSpec("Recon_Sheet_Start_Row", required=True, coerce=coerce.to_int),
    FieldSpec("Dump_Sheet_Transfer", required=True,
              validate=lambda v: None if ">" in v else "expected e.g. 'D-U>D-U'"),
    FieldSpec("Max_Subset_Size", required=False, coerce=coerce.to_int, default=10),
    FieldSpec("Amount_Tolerance", required=False, coerce=coerce.to_decimal, default="0.01"),
    # Excel formula templates are just text fields:
    FieldSpec("Recon_Sheet_Column_D", required=True),  # =VLOOKUP(B{row},...)
]

settings = load_settings(rules_path, sheet="Vars", fields=SETTINGS)

RULE_COLS = [
    TableColumnSpec("regex", "A"),
    TableColumnSpec("rule_type", "B", required=True),
    TableColumnSpec("order", "C", coerce=coerce.to_int),
    TableColumnSpec("gl_to_use", "D"),
    TableColumnSpec("recon_category", "E"),
    TableColumnSpec("remarks", "F"),
]
rules = load_rule_table(rules_path, sheet="Matching Rules", columns=RULE_COLS,
                        sort_by="order", skip_blank_in="rule_type")
```

A `FieldSpec`/`TableColumnSpec` with no `coerce` defaults to `coerce.to_text`.
For a money tolerance, coerce with `coerce.to_decimal` (not `to_number`) so the
comparison stays exact.

## Friendly errors (the whole point)

A missing/blank/malformed value raises `RulesValidationError` whose message
includes the workbook, sheet, cell, and key, e.g.:

```
Rules.xlsx[Vars]!B7 (Dump_Sheet_Transfer): expected e.g. 'D-U>D-U'
```

At the step boundary, catch `ExcelError` (the base class) and re-raise as the
automation's own non-retryable error — the framework never imports engine types.

## Named strategies, not code

Matching/transform behaviour is selected by **name** from a registry, never by
the operator writing code. Validate that every name in the rules table is
registered:

```python
from core.excel import require_known_strategies

require_known_strategies(rules, field_name="rule_type",
                         known={"pairwise_by_amount", "grouped_by_currency",
                                "subset_match"},
                         sheet="Matching Rules")
```

Register each name with `@register_strategy(name)` (see `model.md`).

## Styles (formatting is operator-configurable too)

Formatting is **not** hard-coded — operators define named styles on a `Styles`
sheet and the code loads them. The header labels are matched against friendly
aliases, so a sheet like this works:

| Name | Font | Size | Bold | Number Format | Align | VAlign | Fill | Border |
|------|------|------|------|---------------|-------|--------|------|--------|
| base | Calibri | 10 | no | | left | center | | |
| money | Calibri | 10 | no | accounting | right | center | | yes |
| header | Calibri | 10 | yes | | center | center | D9E1F2 | yes |
| matched | Calibri | 10 | no | accounting | right | center | FFFF00 | |

```python
from core.excel import load_styles

styles = load_styles(rules_path, sheet="Styles")   # dict[str, CellStyle]

model = SheetModel(
    name="Recon 4411", frame=df,
    columns=[Column("amt", "Amount", letter="E",
                    value=ColumnRef("amt"), style=styles["money"])],
    default_style=styles["base"],            # standardized font/size sheet-wide
    default_header_style=styles["header"],
)
```

Recognised columns (case-insensitive, with aliases): Name/Style, Font, Size,
Bold, Italic, Number Format (a.k.a. Data Format / Format), Align/Horizontal,
VAlign/Vertical, Fill/Background/Highlight, Font Color, Border, Border Style,
Border Color, per-side Border Top/Bottom/Left/Right, Wrap. `load_styles` requires
a `Name` column and raises `RulesValidationError` otherwise. Build a single style
from a dict of these fields with `cellstyle_from_mapping`; parse an operator
truthy token (`yes/true/x/1/✓`) with `parse_bool`.

### Money and dates in the Number Format cell

The `Number Format` cell accepts **friendly tokens** (resolved by
`resolve_number_format`) so operators don't hand-write Excel codes:

| You write… | You get |
|---|---|
| `accounting` | accounting format, no symbol, negatives in parens, zero as dash |
| `accounting:$` or `accounting:£:0` | accounting with symbol / decimals |
| `date:dd-MMM-yyyy` | **CLDR** pattern translated to Excel (`dd-mmm-yyyy`) |
| `#,##0.00%` (anything else) | passed through as a raw Excel code |

**Dates have a value-side requirement too** (Excel stores dates as integer
serials): a date format only renders a date if the cell holds a real date. In the
Transform phase coerce date columns with `coerce.to_date`. Likewise coerce money
columns with `coerce.money` (Decimal). In code you can also use the format
helpers directly: `accounting("$")`, `cldr_to_excel_date("dd-MMM-yyyy")`,
`DATE_ISO`, `ACCOUNTING`.

## Audit snapshot

```python
from core.excel import RulesConfig
RulesConfig(settings=settings, rules=rules).to_yaml(run_dir / "rules_snapshot.yaml")
```

Emit a snapshot per run so rule changes are diffable/versionable even though the
source is a binary `.xlsx`. (`to_yaml` requires PyYAML.)

## Period / placeholder substitution

Keep run-specific substitution (e.g. `{period}` → a date range) in code, applied
to the loaded rule values for the run only — do not write it back to the workbook.
