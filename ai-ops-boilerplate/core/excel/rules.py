"""Excel-authored rules → validated config.

Operators edit an ``.xlsx`` rules workbook (the format they're comfortable with);
this module parses and validates it into a structured :class:`RulesConfig`, with
errors that point at the exact offending cell, e.g.::

    Rules.xlsx[Vars]!B7 (Dump_Sheet_Transfer): expected a column-range spec

It deliberately uses a small in-house declarative validator rather than pydantic:
the hard part is attaching the *cell coordinate* to each error (which pydantic's
field-path model doesn't help with), and the team values minimal dependencies on
Python 3.14.

Each automation declares its own :class:`FieldSpec` list (for the key/value
settings sheet) and :class:`TableColumnSpec` list (for a rules table such as
``Matching Rules``). A YAML snapshot can be emitted for audit / version history.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import coerce
from .errors import RulesValidationError
from .formats import resolve_number_format
from .model import CellStyle
from .workbook import open_workbook


# ── declarative specs ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FieldSpec:
    """A single expected key in a key/value settings sheet (col A=key, B=value)."""

    key: str
    required: bool = True
    coerce: Callable[[Any], Any] | None = None  # default: coerce.to_text
    validate: Callable[[Any], str | None] | None = None  # error message or None
    default: Any = None
    example: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class TableColumnSpec:
    """A column in a rules table, sourced by Excel column letter."""

    name: str  # logical key in the resulting row dict
    letter: str  # source column letter ("A", "B", …)
    required: bool = False
    coerce: Callable[[Any], Any] | None = None
    validate: Callable[[Any], str | None] | None = None


@dataclass
class RulesConfig:
    """Validated rules: settings (key/value) + an ordered list of rule rows."""

    settings: dict[str, Any] = field(default_factory=dict)
    rules: list[dict[str, Any]] = field(default_factory=list)

    def to_yaml(self, path: str | Path) -> Path:
        """Write an audit snapshot. Requires PyYAML."""
        import yaml  # local import keeps PyYAML optional at import time

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(
                {"settings": self.settings, "rules": self.rules},
                fh,
                sort_keys=True,
                allow_unicode=True,
            )
        return path


# ── loaders ──────────────────────────────────────────────────────────────────
def load_settings(
    path: str | Path,
    *,
    sheet: str,
    fields: list[FieldSpec],
    data_start: int = 2,
    workbook_name: str | None = None,
) -> dict[str, Any]:
    """Read and validate a key/value sheet (column A=key, column B=value)."""
    path = Path(path)
    wb_name = workbook_name or path.name
    raw: dict[str, tuple[Any, int]] = {}
    with open_workbook(path, data_only=False) as wb:
        if sheet not in wb.sheetnames:
            raise RulesValidationError(
                f"missing required sheet {sheet!r}", workbook=wb_name, sheet=sheet
            )
        ws = wb[sheet]
        for r in range(data_start, (ws.max_row or 0) + 1):
            key = ws.cell(r, 1).value
            if coerce.is_blank(key):
                continue
            raw[str(key).strip()] = (ws.cell(r, 2).value, r)

    result: dict[str, Any] = {}
    for f in fields:
        if f.key not in raw:
            if f.required:
                hint = f" (example: {f.example})" if f.example else ""
                raise RulesValidationError(
                    f"required key is missing{hint}",
                    workbook=wb_name,
                    sheet=sheet,
                    key=f.key,
                )
            result[f.key] = f.default
            continue
        value, row = raw[f.key]
        coerced = (f.coerce or coerce.to_text)(value)
        if f.validate:
            msg = f.validate(coerced)
            if msg:
                raise RulesValidationError(
                    msg, workbook=wb_name, sheet=sheet, cell=f"B{row}", key=f.key
                )
        result[f.key] = coerced
    return result


def load_rule_table(
    path: str | Path,
    *,
    sheet: str,
    columns: list[TableColumnSpec],
    header_row: int = 1,
    sort_by: str | None = None,
    skip_blank_in: str | None = None,
    workbook_name: str | None = None,
) -> list[dict[str, Any]]:
    """Read and validate a rules table sourced by column letters.

    ``skip_blank_in`` names a logical column; rows blank in that source cell are
    skipped (e.g. skip rows with no rule type). ``sort_by`` orders the result.
    """
    from .formula_eval import col_to_index

    path = Path(path)
    wb_name = workbook_name or path.name
    rows: list[dict[str, Any]] = []
    with open_workbook(path, data_only=False) as wb:
        if sheet not in wb.sheetnames:
            raise RulesValidationError(
                f"missing required sheet {sheet!r}", workbook=wb_name, sheet=sheet
            )
        ws = wb[sheet]
        skip_letter = None
        if skip_blank_in:
            skip_letter = next(c.letter for c in columns if c.name == skip_blank_in)
        for r in range(header_row + 1, (ws.max_row or 0) + 1):
            if skip_letter and coerce.is_blank(
                ws.cell(r, col_to_index(skip_letter)).value
            ):
                continue
            record: dict[str, Any] = {}
            for spec in columns:
                cell = ws.cell(r, col_to_index(spec.letter))
                value = cell.value
                if spec.required and coerce.is_blank(value):
                    raise RulesValidationError(
                        f"{spec.name} is required but blank",
                        workbook=wb_name,
                        sheet=sheet,
                        cell=f"{spec.letter}{r}",
                        key=spec.name,
                    )
                coerced = (spec.coerce or coerce.to_text)(value)
                if spec.validate:
                    msg = spec.validate(coerced)
                    if msg:
                        raise RulesValidationError(
                            msg,
                            workbook=wb_name,
                            sheet=sheet,
                            cell=f"{spec.letter}{r}",
                            key=spec.name,
                        )
                record[spec.name] = coerced
            rows.append(record)

    if sort_by:
        rows.sort(key=lambda row: row.get(sort_by))
    return rows


# ── config-driven cell styles ────────────────────────────────────────────────
_TRUE_TOKENS = {"y", "yes", "true", "t", "1", "x", "✓"}

# Operator-friendly header text → CellStyle field. Matched case-insensitively.
_STYLE_ALIASES: dict[str, str] = {
    "name": "_name", "style": "_name", "style name": "_name",
    "font": "font_name", "font name": "font_name", "font family": "font_name",
    "size": "font_size", "font size": "font_size",
    "bold": "bold", "italic": "italic",
    "number format": "number_format", "numberformat": "number_format",
    "format": "number_format", "data format": "number_format",
    "align": "align", "alignment": "align", "horizontal": "align",
    "halign": "align", "h align": "align", "horizontal alignment": "align",
    "valign": "valign", "vertical": "valign", "v align": "valign",
    "vertical alignment": "valign",
    "fill": "fill", "background": "fill", "background color": "fill",
    "background colour": "fill", "highlight": "fill",
    "font color": "font_color", "font colour": "font_color",
    "text color": "font_color", "text colour": "font_color",
    "border": "border", "borders": "border",
    "border style": "border_style", "border color": "border_color",
    "border top": "border_top", "border bottom": "border_bottom",
    "border left": "border_left", "border right": "border_right",
    "top border": "border_top", "bottom border": "border_bottom",
    "left border": "border_left", "right border": "border_right",
    "wrap": "wrap", "wrap text": "wrap",
}


def parse_bool(value: Any) -> bool:
    """Parse an operator-entered truthy token (yes/true/x/1/✓) to ``bool``."""
    return coerce.to_text(value).strip().lower() in _TRUE_TOKENS


def _hex(value: Any) -> str | None:
    s = coerce.to_text(value).lstrip("#").upper()
    return s or None


# openpyxl line styles, keyed case-insensitively → canonical spelling. An
# operator-entered border style is normalised through this; anything unknown
# becomes None (a dropped border) rather than crashing the render at Side(style=).
_BORDER_STYLES: dict[str, str] = {
    s.lower(): s for s in (
        "thin", "medium", "thick", "double", "hair", "dotted", "dashed",
        "dashDot", "dashDotDot", "mediumDashed", "mediumDashDot",
        "mediumDashDotDot", "slantDashDot",
    )
}


def _border_side(value: Any) -> str | None:
    s = coerce.to_text(value).strip()
    return _BORDER_STYLES.get(s.lower()) if s else None


def cellstyle_from_mapping(d: dict[str, Any]) -> CellStyle:
    """Build a :class:`~.model.CellStyle` from CellStyle-field keys.

    Keys are CellStyle field names (``font_name``, ``font_size``, ``bold``,
    ``number_format``, ``align``, ``valign``, ``fill``, ``font_color``,
    ``border``, ``border_style``, ``border_color``, the per-side
    ``border_top`` / ``border_bottom`` / ``border_left`` / ``border_right``,
    ``wrap``); missing keys fall back to the style default. Border style names
    are normalised case-insensitively; unknown names drop to ``None``.
    """
    align = coerce.to_text(d.get("align")).lower() or None
    valign = coerce.to_text(d.get("valign")).lower() or None
    size = d.get("font_size")
    return CellStyle(
        number_format=resolve_number_format(coerce.to_text(d.get("number_format")) or None),
        font_name=coerce.to_text(d.get("font_name")) or None,
        font_size=coerce.to_number(size) if not coerce.is_blank(size) else None,
        bold=parse_bool(d.get("bold")),
        italic=parse_bool(d.get("italic")),
        font_color=_hex(d.get("font_color")),
        fill=_hex(d.get("fill")),
        border=parse_bool(d.get("border")),
        border_style=_border_side(d.get("border_style")),
        border_color=_hex(d.get("border_color")),
        border_top=_border_side(d.get("border_top")),
        border_bottom=_border_side(d.get("border_bottom")),
        border_left=_border_side(d.get("border_left")),
        border_right=_border_side(d.get("border_right")),
        align=align,
        valign=valign,
        wrap=parse_bool(d.get("wrap")),
    )


def load_styles(
    path: str | Path,
    *,
    sheet: str,
    header_row: int = 1,
    workbook_name: str | None = None,
) -> dict[str, CellStyle]:
    """Load named cell styles from an operator-editable ``Styles`` sheet.

    The sheet has a header row whose labels are matched (case-insensitively)
    against friendly aliases — e.g. a ``Name`` / ``Font`` / ``Size`` / ``Bold`` /
    ``Number Format`` / ``Align`` / ``VAlign`` / ``Fill`` / ``Font Color`` /
    ``Border`` layout. Each subsequent row defines one named style; reference the
    name from a column's ``style`` or use it as a sheet ``default_style``.
    """
    path = Path(path)
    wb_name = workbook_name or path.name
    styles: dict[str, CellStyle] = {}
    with open_workbook(path, data_only=False) as wb:
        if sheet not in wb.sheetnames:
            raise RulesValidationError(
                f"missing required sheet {sheet!r}", workbook=wb_name, sheet=sheet
            )
        ws = wb[sheet]
        # Map column index → CellStyle field via the header aliases.
        field_by_col: dict[int, str] = {}
        for c in range(1, (ws.max_column or 0) + 1):
            label = coerce.to_text(ws.cell(header_row, c).value).strip().lower()
            if label in _STYLE_ALIASES:
                field_by_col[c] = _STYLE_ALIASES[label]
        if "_name" not in field_by_col.values():
            raise RulesValidationError(
                "Styles sheet must have a 'Name' column",
                workbook=wb_name,
                sheet=sheet,
            )
        for r in range(header_row + 1, (ws.max_row or 0) + 1):
            mapping = {
                field: ws.cell(r, c).value for c, field in field_by_col.items()
            }
            name = coerce.to_text(mapping.pop("_name", None))
            if not name:
                continue
            styles[name] = cellstyle_from_mapping(mapping)
    return styles


def require_known_strategies(
    rules: list[dict[str, Any]],
    *,
    field_name: str,
    known: set[str],
    sheet: str | None = None,
    workbook_name: str | None = None,
) -> None:
    """Validate every rule's strategy name is in the registered ``known`` set."""
    for row in rules:
        name = row.get(field_name)
        if name and name not in known:
            raise RulesValidationError(
                f"unknown strategy {name!r}; registered: {sorted(known)}",
                workbook=workbook_name,
                sheet=sheet,
                key=field_name,
            )
