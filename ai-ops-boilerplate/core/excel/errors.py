"""Error types for the Excel framework.

These are deliberately orchestration-agnostic — the framework never imports any
runner/engine or run-context module. An automation step that uses the framework
is expected to catch :class:`ExcelError` and re-raise it as its own
non-retryable error at the step boundary.

The headline feature is :class:`RulesValidationError`, which carries the
sheet/cell/key coordinate of the offending value so operators get a message
like ``Rules.xlsx[Vars]!B7 (Dump_Sheet_Transfer): ...`` instead of a
bare ``ValueError``.
"""

from __future__ import annotations


class ExcelError(Exception):
    """Base class for all Excel-framework errors."""


class RulesValidationError(ExcelError):
    """A value in the rules workbook is missing or malformed.

    Carries the location so the message points the operator at the exact cell.
    """

    def __init__(
        self,
        message: str,
        *,
        workbook: str | None = None,
        sheet: str | None = None,
        cell: str | None = None,
        key: str | None = None,
    ) -> None:
        self.message = message
        self.workbook = workbook
        self.sheet = sheet
        self.cell = cell
        self.key = key
        super().__init__(self._format())

    def _format(self) -> str:
        loc = ""
        if self.workbook:
            loc += self.workbook
        if self.sheet:
            loc += f"[{self.sheet}]"
        if self.cell:
            loc += f"!{self.cell}"
        if self.key:
            loc += f" ({self.key})"
        loc = loc.strip()
        return f"{loc}: {self.message}" if loc else self.message


class FormulaEvalError(ExcelError):
    """A formula could not be classified or evaluated by any backend."""

    def __init__(self, message: str, *, formula: str | None = None) -> None:
        self.message = message
        self.formula = formula
        super().__init__(
            f"{message} (formula: {formula!r})" if formula else message
        )


class HeaderNotFoundError(ExcelError):
    """A header row matching the required anchor labels could not be located.

    Raised by :func:`.compat.find_header` when a source workbook's
    header cannot be found within the scanned band (e.g. the ERP preamble is
    deeper than expected or the report layout changed). Carries the anchors it
    was looking for and how many it managed to match.
    """

    def __init__(
        self,
        message: str,
        *,
        anchors: "tuple[str, ...] | None" = None,
        matched: int | None = None,
    ) -> None:
        self.anchors = anchors
        self.matched = matched
        super().__init__(message)


class WorkbookIntegrityError(ExcelError):
    """A render would have lost or corrupted workbook content.

    Raised by the render integrity guard when a sheet would disappear (the
    failure mode that previously caused silent data loss), or when a model
    targets a sheet absent from the template without ``create_missing=True``.
    """
