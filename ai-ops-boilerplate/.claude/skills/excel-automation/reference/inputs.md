# Reading ERP inputs: header detection

ERP exports rarely put the column headers on row 1. They prepend a **variable
preamble** — a title banner, the filter/date range that was applied, a company
line, blank spacers — so the real header row drifts run to run. Hard-coding
`header_row=5` breaks the next time the preamble is one row taller.

`find_header` (in `core.excel.compat`, re-exported from `core.excel`) locates the
header row by scanning for **anchor labels** you know appear on it.

## Signature

```python
find_header(source, anchors, *, max_scan_rows=25, require_all=True,
            normalize=None) -> HeaderMatch
```

- `source` — an openpyxl worksheet (anything exposing `iter_rows`) **or** a plain
  iterable of row sequences (so the scan is unit-testable without a live
  workbook).
- `anchors` — a distinctive *subset* of the column labels expected on the header
  row (enough to identify it unambiguously). Comparison is normalised: text,
  stripped, case-folded — so casing/whitespace differences don't matter.
- `max_scan_rows` — how many leading rows to scan (default `DEFAULT_SCAN_ROWS`
  = 25). Raise it if a report's preamble is deeper.
- `require_all` — `True` (default) raises `HeaderNotFoundError` unless *every*
  anchor matches; `False` returns the best-matching row even if partial.

Returns a `HeaderMatch`:

- `.row` — **1-based** index of the located header row (feed straight into
  `read_table(header_row=...)`).
- `.columns` — `{normalised label -> 0-based column index}` (first occurrence
  wins on duplicate labels).
- `.values` — the raw header-row cell values (tuple).
- `.col(label) -> int | None` — **0-based** column index for a label, or `None`.
- `.require(label) -> int` — same, but raises `KeyError` if absent.

Raises `HeaderNotFoundError` (a subclass of `ExcelError`, carrying `.anchors` and
`.matched`) when `require_all` and not all anchors matched, or if there were no
rows to scan.

## Usage — find the header, then read the table

```python
from core.excel import find_header, read_table, open_workbook

with open_workbook(src_path, read_only=True) as wb:
    match = find_header(wb["Sheet1"], anchors=["Doc No", "Posting Date", "Amount"])

df = read_table(src_path, sheet="Sheet1",
                header_row=match.row, start_row=match.row + 1)
```

Note the index bases: `.row` is 1-based (it *is* the Excel row number and what
`read_table` wants), while `.col(...)` is 0-based (a position into a Python row
tuple / a DataFrame's columns). Don't mix them.

## Column indices when you scan rows directly

If you iterate rows yourself rather than going through `read_table`, use `.col`
to resolve positions robustly against column reordering:

```python
rows = list(ws.iter_rows(min_row=match.row + 1, values_only=True))
amt_i = match.require("Amount")        # 0-based
amounts = [coerce.money(r[amt_i]) for r in rows]   # money → Decimal, always
```

Coerce every extracted cell through `core.excel.coerce` at this boundary — money
with `coerce.money`, other numerics with `coerce.to_number`, dates with
`coerce.to_date`. This is the point where a raw `float("N/A")` would otherwise
crash the run.
