"""Generic Excel framework — keep data in a model, render to Excel once.

A reusable, project-agnostic toolkit for finance/report automations. Depends
only on the standard library plus openpyxl, pandas, and numpy; it is
self-contained (relative imports throughout) so it can live at any package path
(e.g. ``core/excel/``) and be vendored into any project.

The discipline:

1. **Extract** inputs with :func:`read_table` / :func:`find_header` (read once, close).
2. **Transform** in pandas — all business logic, authoritative values.
3. **Build** a :class:`SheetModel` per output sheet (values + formulas + styles).
4. **Render** once with :func:`render` (one open, atomic save, preserve-by-default).

Operators customise behaviour via an Excel rules workbook loaded with the
:mod:`.rules` module. Excel formulas they author are evaluated in Python by
:class:`HybridEvaluator`, so the value is authoritative while the live formula is
still written to the cell.

Post-render OOXML repair (:func:`restore_parts`, :func:`repair_dropped_rels`)
works around openpyxl's partial-fidelity writer without adding dependencies.
"""

from __future__ import annotations

from . import coerce, rules
from .compat import (
    HeaderMatch,
    find_header,
    repair_dropped_rels,
    snapshot_rels,
)
from .errors import (
    ExcelError,
    FormulaEvalError,
    HeaderNotFoundError,
    RulesValidationError,
    WorkbookIntegrityError,
)
from .formats import (
    ACCOUNTING,
    DATE_ISO,
    accounting,
    cldr_to_excel_date,
    resolve_number_format,
)
from .formula_eval import (
    AggregateEvaluator,
    ColumnMap,
    FormulaClass,
    FormulaEvaluator,
    HybridEvaluator,
    LookupEvaluator,
    RowLocalEvaluator,
    apply_template,
    col_to_index,
    index_to_col,
)
from .model import (
    BOX,
    GREEN_FILL,
    YELLOW_FILL,
    CellStyle,
    Column,
    ColumnRef,
    Computed,
    FormulaTemplate,
    FromFormula,
    Literal,
    PreservedRegion,
    SheetLayout,
    SheetModel,
    get_conditional_style,
    get_strategy,
    populate,
    register_conditional_style,
    register_strategy,
)
from .preserve import IMAGE_REL_TYPES, RestoreReport, restore_parts
from .render import plan_data_ops, render
from .rules import (
    FieldSpec,
    RulesConfig,
    TableColumnSpec,
    cellstyle_from_mapping,
    load_rule_table,
    load_settings,
    load_styles,
    parse_bool,
    require_known_strategies,
)
from .workbook import atomic_save, open_workbook, read_table

__all__ = [
    # subpackages
    "coerce",
    "rules",
    # number formats
    "ACCOUNTING",
    "DATE_ISO",
    "accounting",
    "cldr_to_excel_date",
    "resolve_number_format",
    # errors
    "ExcelError",
    "FormulaEvalError",
    "HeaderNotFoundError",
    "RulesValidationError",
    "WorkbookIntegrityError",
    # workbook I/O
    "open_workbook",
    "atomic_save",
    "read_table",
    # input header detection + openpyxl OPC compatibility repairs
    "find_header",
    "HeaderMatch",
    "repair_dropped_rels",
    "snapshot_rels",
    # formula evaluation
    "FormulaClass",
    "FormulaEvaluator",
    "HybridEvaluator",
    "RowLocalEvaluator",
    "LookupEvaluator",
    "AggregateEvaluator",
    "ColumnMap",
    "apply_template",
    "col_to_index",
    "index_to_col",
    # model
    "CellStyle",
    "YELLOW_FILL",
    "GREEN_FILL",
    "BOX",
    "Column",
    "ColumnRef",
    "Literal",
    "Computed",
    "FromFormula",
    "FormulaTemplate",
    "PreservedRegion",
    "SheetLayout",
    "SheetModel",
    "populate",
    "register_strategy",
    "get_strategy",
    "register_conditional_style",
    "get_conditional_style",
    # render
    "render",
    "plan_data_ops",
    # OOXML part preservation
    "restore_parts",
    "RestoreReport",
    "IMAGE_REL_TYPES",
    # rules
    "FieldSpec",
    "TableColumnSpec",
    "RulesConfig",
    "load_settings",
    "load_rule_table",
    "load_styles",
    "cellstyle_from_mapping",
    "parse_bool",
    "require_known_strategies",
]
