# Excel policy: when render() is mandatory, and the sanctioned exceptions

## The policy

`core.excel.render()` is the **default and mandatory path for all workbook
GENERATION.** Building output cell-by-cell with raw openpyxl is the pattern that
corrupted files, lost sheets, and produced stale-formula bugs — it is not
allowed for generation.

Raw openpyxl / xlwings-COM is allowed **only** for these four declared cases:

1. **In-place edit of an operator's live workbook** — a targeted mutation of a
   workbook a human owns and keeps editing (drop a value into one named cell,
   toggle a flag), where re-rendering the whole sheet would be wrong or
   destructive. Prefer `render()`'s update-in-place mode first (see
   `discipline.md`); reach for raw openpyxl only when the edit is genuinely a
   single-cell poke on a sheet you must not rebuild.
2. **Live COM recalc** — you need Excel's own engine to compute and **cache**
   formula results into the file before a downstream consumer (that can't
   recalc) reads it. openpyxl writes formulas without cached values;
   `render()` deliberately does not recalc.
3. **`.xlsm` macro preservation** — the template carries VBA that must survive.
   `render()`/openpyxl do not round-trip macros faithfully; open with
   `open_workbook(path, keep_vba=True)` for read, and preserve/write macros via a
   path that keeps the `vbaProject.bin`, or drive Excel via COM.
4. **Huge-template surgery** — a workbook so large that materialising a full
   `SheetModel` + re-render is impractical, and only a bounded region needs
   changing.

**Money is `Decimal` via `coerce.money` in these paths too.** The escape hatch is
about *how the bytes are written*, never about dropping the money discipline.
Never write `float(cell.value)`; read with a `core.excel.coerce` helper and write
back a `Decimal`.

**COM is Windows-only.** Any xlwings/`win32com` path must be guarded so the tool
still imports and runs its non-COM paths on macOS/Linux (dev machines, CI). Gate
it behind a capability check and fail loudly with a clear message if COM is
required but unavailable — never silently.

When you do use raw openpyxl, still go through `core.excel.workbook`:
`open_workbook(...)` (context-managed; guaranteed close) and `atomic_save(wb,
path)` (temp file + `os.replace`, Windows-retry) — never bare
`load_workbook(...).save(...)`.

## openpyxl is a partial-fidelity writer — repair after render

Even the mandatory `render()` path uses openpyxl, which **silently drops or
mangles** package parts it doesn't model: cell comments (and their legacy VML),
printer settings, drawings/images, custom XML, sensitivity labels — and it can
leave dangling relationship ids. The visible symptom is Excel's *"we found a
problem with some content… recovered records"* repair dialog on open. Two
stdlib-only repairs (no extra dependency, and they work at the zip/OPC level
because openpyxl is the very thing that loses the parts):

### 1. Dangling relationship ids — `snapshot_rels` + `repair_dropped_rels`

The main offender is **external links**: `externalLinkN.xml` references
`<externalBook r:id="rId1">` but openpyxl rewrites that part's `.rels` keeping
only a different id, so `rId1` no longer resolves and Excel reports corruption.

Snapshot the pristine input's `.rels` **before** the render, then repair the
saved file **after**:

```python
from core.excel import snapshot_rels, repair_dropped_rels, render

orig = snapshot_rels(template_path)          # {rels-part-name: bytes}; {} if unreadable
render(output_path, models)                  # openpyxl may drop rel ids here
n = repair_dropped_rels(output_path, orig)   # merges dropped <Relationship> entries back; returns count patched
```

`repair_dropped_rels(save_path, orig_rels, *, log=None)` re-injects only the
relationship entries whose target is external-mode or still present in the saved
package (so it never resurrects parts openpyxl correctly removed), and merges
rather than replaces (keeping legit new rels like hyperlinks). It also handles
openpyxl's external-link *renumbering* idempotently across repeated in-place runs.
Returns the number of `.rels` parts patched (`0` if nothing needed repair or the
snapshot was empty).

### 2. Dropped parts — `restore_parts`

For comments, printer settings, custom XML, drawings, etc., copy the dropped
parts back from the pristine source **after** the final render:

```python
from core.excel import restore_parts, IMAGE_REL_TYPES

report = restore_parts(source_path, output_path)   # -> RestoreReport
# report.restored / report.skipped ; report.summary()
```

`restore_parts(source, target, *, exclude_rel_types=IMAGE_REL_TYPES, log=None)` is
driven entirely by the source's relationship graph (no hardcoded part names or
sheet numbers): a relationship is restored only when its target part is absent
from the rendered output by path, so parts openpyxl kept (pivot tables, external
links, theme) are left alone. Images and their picture-drawings are excluded by
default (a drawing restored without its images would dangle) — pass a different
`frozenset` to change that. It rewrites the target atomically.

Order when you need both: `render()` → `repair_dropped_rels()` →
`restore_parts()`.
