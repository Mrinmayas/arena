"""The in-memory representation that gets rendered to Excel once.

Design principle: **Python owns the authoritative values.** A :class:`SheetModel`
carries a pandas DataFrame of authoritative values plus a list of :class:`Column`
specs that say, per output column, how the cell is produced and styled.

The value/formula seam is first-class on :class:`Column`:

* ``value`` is the authoritative Python value source (used by all downstream logic).
* ``formula`` is the *presentational* Excel string written to the cell.

The four valid combinations:

==================  ===========  =====================================================
``value``           ``formula``  meaning
==================  ===========  =====================================================
set                 ``None``     plain computed value written to the cell
``None``            set          live formula only; logic must not read this cell back
set + ``formula``   set          **the seam**: formula in the cell, value owned in model
``FromFormula()``   set          formula authored; framework evaluates it for the value
==================  ===========  =====================================================

The authoritative values are exposed only as a DataFrame (``model.frame``); the
formula string is emitted only by the renderer. There is deliberately no API that
reads an openpyxl formula cell back to obtain a value — that path is what caused
the stale-value bugs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Union

import pandas as pd

from .formula_eval import ColumnMap, FormulaEvaluator, HybridEvaluator


# ── styling ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CellStyle:
    """Declarative cell style. Mapped to openpyxl by the renderer.

    Colours are RGB/ARGB hex strings without ``#`` (e.g. ``"FFFF00"`` for yellow).
    Covers the standard reconciliation needs: font family + size, number/data
    format, horizontal and vertical alignment, bold/italic, background fill
    (highlight), and borders.
    """

    number_format: str | None = None  # Excel number/data format, e.g. "#,##0.00"
    font_name: str | None = None  # font family, e.g. "Calibri"
    font_size: float | None = None
    bold: bool = False
    italic: bool = False
    font_color: str | None = None  # text colour
    fill: str | None = None  # solid background fill (highlight)
    border: bool = False  # box border on all four sides
    border_style: str | None = None  # "thin" (default) | "medium" | "thick" | …
    border_color: str | None = None
    # Per-side borders. When set, override the uniform box on that side with the
    # named side style (e.g. "thin", "medium", "double"). Use for partial borders
    # such as an accounting total's top-thin / bottom-double underline.
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    align: str | None = None  # horizontal: "left" | "center" | "right"
    valign: str | None = None  # vertical: "top" | "center" | "bottom"
    wrap: bool = False

    def merge(self, other: "CellStyle | None") -> "CellStyle":
        """Return self overlaid with ``other`` (a base + per-column/conditional).

        Non-None fields in ``other`` win; boolean flags union (once ``True``,
        stays ``True``). You therefore cannot turn a base flag *off* via a merge
        — set the base without it instead.
        """
        if other is None:
            return self

        def pick(a, b):
            return b if b is not None else a

        return CellStyle(
            number_format=pick(self.number_format, other.number_format),
            font_name=pick(self.font_name, other.font_name),
            font_size=pick(self.font_size, other.font_size),
            bold=self.bold or other.bold,
            italic=self.italic or other.italic,
            font_color=pick(self.font_color, other.font_color),
            fill=pick(self.fill, other.fill),
            border=self.border or other.border,
            border_style=pick(self.border_style, other.border_style),
            border_color=pick(self.border_color, other.border_color),
            border_top=pick(self.border_top, other.border_top),
            border_bottom=pick(self.border_bottom, other.border_bottom),
            border_left=pick(self.border_left, other.border_left),
            border_right=pick(self.border_right, other.border_right),
            align=pick(self.align, other.align),
            valign=pick(self.valign, other.valign),
            wrap=self.wrap or other.wrap,
        )


# Reusable tokens (extend as automations need them).
YELLOW_FILL = CellStyle(fill="FFFF00")
GREEN_FILL = CellStyle(fill="00B050")
BOX = CellStyle(border=True)


# ── value sources ──────────────────────────────────────────────────────────--
@dataclass(frozen=True)
class ColumnRef:
    """Take values verbatim from DataFrame column ``key``."""

    key: str


@dataclass(frozen=True)
class Literal:
    """A constant broadcast to every row."""

    value: Any


@dataclass(frozen=True)
class Computed:
    """Values produced by a registered strategy ``fn(frame) -> Series``."""

    strategy: str


@dataclass(frozen=True)
class FromFormula:
    """Marker: the authoritative value is obtained by evaluating ``formula``."""


ValueSource = Union[ColumnRef, Literal, Computed, FromFormula]


@dataclass(frozen=True)
class FormulaTemplate:
    """An Excel formula template; ``{row}`` is substituted at render time."""

    template: str
    write_to_cell: bool = True


# ── columns & layout ─────────────────────────────────────────────────────────
@dataclass
class Column:
    key: str  # logical name; the DataFrame column holding authoritative values
    header: str
    letter: str | None = None  # explicit target column letter; else positional
    value: ValueSource | None = None
    formula: FormulaTemplate | None = None
    style: CellStyle | None = None
    header_style: CellStyle | None = None
    conditional_style: str | None = None  # name into the conditional-style registry
    width: float | None = None

    def __post_init__(self) -> None:
        if self.value is None and self.formula is None:
            raise ValueError(
                f"Column {self.key!r} must declare a value source, a formula, or both"
            )
        if isinstance(self.value, FromFormula) and self.formula is None:
            raise ValueError(
                f"Column {self.key!r} uses FromFormula() but has no formula template"
            )

    @property
    def writes_formula(self) -> bool:
        return self.formula is not None and self.formula.write_to_cell


@dataclass(frozen=True)
class PreservedRegion:
    """A block below the data region to keep across a render.

    ``mode="freeze_values"`` captures evaluated values so stale cross-sheet
    formula references don't break when the region is relocated by a row delta.
    ``mode="verbatim"`` copies cells (values/formulas/fills) as-is.
    """

    start_row: int
    end_row: int | None = None  # None ⇒ to the last populated row
    mode: str = "freeze_values"


@dataclass(frozen=True)
class SheetLayout:
    header_rows: tuple[int, ...] = (1,)
    data_start_row: int = 2
    preserved_regions: tuple[PreservedRegion, ...] = ()
    write_headers: bool = False  # True for fresh sheets; False keeps a template's headers


@dataclass
class SheetModel:
    """One output sheet: authoritative values + column specs + layout.

    ``default_style`` is the standardized base applied to every data cell (e.g. a
    house font + size + number format); a column's own ``style`` and any
    conditional style are merged on top. ``default_header_style`` does the same
    for header cells.

    ``extra_cells`` holds fixed-position writes outside the data region —
    ``(row, letter, value, style)`` tuples applied verbatim after data ops. Use
    for cells like a subtotal row (row 1) that must be rewritten each run but
    fall above ``data_start_row`` and are therefore not touched by the clear pass.
    """

    name: str
    frame: pd.DataFrame
    columns: list[Column]
    layout: SheetLayout = field(default_factory=SheetLayout)
    default_style: CellStyle | None = None
    default_header_style: CellStyle | None = None
    extra_cells: list[tuple[int, str, Any, "CellStyle | None"]] = field(default_factory=list)

    def __post_init__(self) -> None:
        seen_letters: dict[str, str] = {}
        for col in self.columns:
            if col.letter and col.letter in seen_letters:
                raise ValueError(
                    f"Sheet {self.name!r}: columns {seen_letters[col.letter]!r} and "
                    f"{col.key!r} both target letter {col.letter!r}"
                )
            if col.letter:
                seen_letters[col.letter] = col.key

    def letter_frame(self) -> pd.DataFrame:
        """A view keyed by Excel column letter, for evaluator input / lookups.

        Built from columns that have both a ``letter`` and a key present in the
        authoritative frame.
        """
        data = {
            col.letter: self.frame[col.key]
            for col in self.columns
            if col.letter and col.key in self.frame.columns
        }
        return pd.DataFrame(data, index=self.frame.index)


# ── strategy registries ────────────────────────────────────────────────────--
_STRATEGIES: dict[str, Callable[[pd.DataFrame], pd.Series]] = {}
_COND_STYLES: dict[str, Callable[[Mapping[str, Any]], CellStyle | None]] = {}


def register_strategy(name: str) -> Callable:
    """Register a Computed-value strategy ``fn(frame) -> Series``."""

    def deco(fn: Callable[[pd.DataFrame], pd.Series]) -> Callable:
        _STRATEGIES[name] = fn
        return fn

    return deco


def get_strategy(name: str) -> Callable[[pd.DataFrame], pd.Series]:
    if name not in _STRATEGIES:
        raise KeyError(
            f"unknown strategy {name!r}; registered: {sorted(_STRATEGIES)}"
        )
    return _STRATEGIES[name]


def register_conditional_style(name: str) -> Callable:
    """Register a conditional style ``fn(row_mapping) -> CellStyle | None``."""

    def deco(fn: Callable[[Mapping[str, Any]], CellStyle | None]) -> Callable:
        _COND_STYLES[name] = fn
        return fn

    return deco


def get_conditional_style(name: str) -> Callable[[Mapping[str, Any]], CellStyle | None]:
    if name not in _COND_STYLES:
        raise KeyError(
            f"unknown conditional style {name!r}; registered: {sorted(_COND_STYLES)}"
        )
    return _COND_STYLES[name]


# ── value population ─────────────────────────────────────────────────────────
def populate(
    model: SheetModel,
    *,
    evaluator: FormulaEvaluator | None = None,
    colmap: ColumnMap | None = None,
) -> SheetModel:
    """Fill the authoritative frame from each column's value source, in place.

    Resolves ``Literal``/``Computed`` columns, then evaluates ``FromFormula``
    columns against the sheet's letter-frame (+ ``colmap`` for cross-sheet
    lookups). ``ColumnRef`` columns are assumed already present in the frame.
    After this call ``model.frame`` holds an authoritative value for every key.
    """
    evaluator = evaluator or HybridEvaluator()
    colmap = colmap or ColumnMap()
    frame = model.frame

    # Pass 1 — non-formula value sources.
    for col in model.columns:
        v = col.value
        if isinstance(v, Literal):
            frame[col.key] = v.value
        elif isinstance(v, Computed):
            frame[col.key] = get_strategy(v.strategy)(frame).reindex(frame.index)
        elif isinstance(v, ColumnRef):
            if v.key not in frame.columns:
                raise KeyError(
                    f"Sheet {model.name!r} column {col.key!r}: ColumnRef({v.key!r}) "
                    f"not found in frame"
                )
            if v.key != col.key:
                frame[col.key] = frame[v.key]

    # Pass 2 — formula-derived values (letter-frame reflects pass-1 results).
    letters = model.letter_frame()
    for col in model.columns:
        if isinstance(col.value, FromFormula):
            frame[col.key] = evaluator.eval_column(
                col.formula.template, letters, colmap, sheet_name=model.name
            ).reindex(frame.index)

    return model
