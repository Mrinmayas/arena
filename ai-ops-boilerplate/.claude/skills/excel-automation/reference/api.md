# Public API — `core.excel`

Import from `core.excel`. Signatures below are verified against the committed
`core/excel/` source.

## Workbook I/O (`workbook.py`)

```python
open_workbook(path, *, read_only=False, data_only=False, keep_vba=False)  # contextmanager → Workbook
atomic_save(wb, path, *, replace_attempts=5, replace_delay=0.1) -> Path    # temp file + os.replace; no .tmp left
read_table(path, *, sheet=None, header_row=1, start_row=None, data_only=True) -> pd.DataFrame
```

## Input header detection + OPC repairs (`compat.py`)

```python
find_header(source, anchors, *, max_scan_rows=25, require_all=True, normalize=None) -> HeaderMatch
DEFAULT_SCAN_ROWS                                # 25
HeaderMatch(row, columns, values)                # row is 1-based; columns/col() are 0-based
  .col(label) -> int | None                      # 0-based column index, or None
  .require(label) -> int                         # 0-based; raises KeyError if absent

snapshot_rels(path) -> dict[str, bytes]          # capture .rels before render; {} if unreadable
repair_dropped_rels(save_path, orig_rels, *, log=None) -> int   # re-inject dropped rel ids; returns count patched
```

## Coercion (`coerce.py`)

```python
coerce.to_number(value, default=0.0) -> float                      # general numerics; "1,234.56", "N/A", "(123)", blanks. NOT money.
coerce.to_decimal(value, default=Decimal("0"), *, places=None) -> Decimal   # exact; parses via str so 0.1 stays exact
coerce.money(value) -> Decimal                                     # to_decimal quantized to 2dp with Excel rounding — USE FOR ALL MONEY
coerce.EXCEL_ROUNDING                                              # ROUND_HALF_UP (Excel's half-away-from-zero)
coerce.to_date(value, *, dayfirst=False) -> datetime | None        # str / datetime / Excel serial
coerce.to_int(value, default=None) -> int | None
coerce.to_text(value, default="") -> str                           # dates → isoformat
coerce.is_blank(value) -> bool
```

## Number formats (`formats.py`)

```python
ACCOUNTING                                        # ready-made accounting code (no symbol)
DATE_ISO                                          # "yyyy-mm-dd"
accounting(symbol="", decimals=2) -> str          # Excel accounting code
cldr_to_excel_date(pattern) -> str                # "dd-MMM-yyyy" -> "dd-mmm-yyyy"
resolve_number_format(spec) -> str | None          # "accounting"/"accounting:$:0"/"date:<CLDR>"/raw
```

## Formula evaluation (`formula_eval.py`)

```python
FormulaClass            # ROW_LOCAL | LOOKUP | AGGREGATE | UNSUPPORTED
ColumnMap(sheet_frames: dict[str, pd.DataFrame] = {})   # letter-keyed lookup targets

HybridEvaluator(backends=None)
  .classify(formula) -> FormulaClass
  .supports(formula) -> bool
  .eval_column(formula, frame, colmap, *, sheet_name) -> pd.Series

RowLocalEvaluator() / LookupEvaluator() / AggregateEvaluator()   # backends, same protocol
apply_template(template, row) -> str             # substitute {row}
col_to_index(letter) -> int ; index_to_col(index) -> str
```

`FormulaEvaluator` is a Protocol: `supports(formula)` + `eval_column(...)`.

## Model (`model.py`)

```python
CellStyle(number_format, font_name, font_size, bold, italic, font_color, fill,
          border, border_style, border_color,
          border_top, border_bottom, border_left, border_right,
          align, valign, wrap)
  .merge(other) -> CellStyle        # overlay other; non-None wins, bools union
YELLOW_FILL, GREEN_FILL, BOX                     # reusable CellStyle tokens

ColumnRef(key) | Literal(value) | Computed(strategy) | FromFormula()   # ValueSource
FormulaTemplate(template, write_to_cell=True)

Column(key, header, letter=None, value=None, formula=None,
       style=None, header_style=None, conditional_style=None, width=None)
  .writes_formula                                # True when formula present and write_to_cell
PreservedRegion(start_row, end_row=None, mode="freeze_values")  # or "verbatim"
SheetLayout(header_rows=(1,), data_start_row=2, preserved_regions=(), write_headers=False)
SheetModel(name, frame, columns, layout=SheetLayout(),
           default_style=None, default_header_style=None, extra_cells=[])
  .letter_frame() -> pd.DataFrame                # view keyed by Excel column letter

populate(model, *, evaluator=None, colmap=None) -> SheetModel   # render() calls this for you
register_strategy(name) / get_strategy(name)                    # Computed: fn(frame)->Series
register_conditional_style(name) / get_conditional_style(name)  # fn(row_dict)->CellStyle|None
```

## Render (`render.py`)

```python
render(path, models, *, evaluator=None, colmap=None,
       create_missing=False, skip_populate=False) -> Path
plan_data_ops(models) -> list[CellOp]            # pure; the header+data plan (testable)
```

## OOXML part preservation (`preserve.py`)

```python
restore_parts(source, target, *, exclude_rel_types=IMAGE_REL_TYPES, log=None) -> RestoreReport
RestoreReport(restored=[], skipped=[])           # .summary() -> str
IMAGE_REL_TYPES                                   # frozenset excluded by default (images + drawings)
```

## Rules (`rules.py`)

```python
FieldSpec(key, required=True, coerce=None, validate=None, default=None, example=None, description=None)
TableColumnSpec(name, letter, required=False, coerce=None, validate=None)
RulesConfig(settings={}, rules=[]).to_yaml(path) -> Path        # requires PyYAML

load_settings(path, *, sheet, fields, data_start=2, workbook_name=None) -> dict
load_rule_table(path, *, sheet, columns, header_row=1, sort_by=None,
                skip_blank_in=None, workbook_name=None) -> list[dict]
load_styles(path, *, sheet, header_row=1, workbook_name=None) -> dict[str, CellStyle]
cellstyle_from_mapping(d) -> CellStyle           # CellStyle-field keys -> CellStyle
parse_bool(value) -> bool                        # yes/true/x/1/✓ -> True
require_known_strategies(rules, *, field_name, known, sheet=None, workbook_name=None) -> None
```

## Errors (`errors.py`)

```python
ExcelError                       # base; catch this at the step boundary
RulesValidationError(message, *, workbook, sheet, cell, key)   # str → "wb[sheet]!cell (key): msg"
FormulaEvalError(message, *, formula)
HeaderNotFoundError(message, *, anchors, matched)              # raised by find_header
WorkbookIntegrityError                                         # render integrity guard
```
