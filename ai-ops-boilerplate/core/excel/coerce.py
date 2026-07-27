"""Safe value coercion helpers.

A leaf module (no intra-package imports) used by the rules loader, the formula
evaluator, and the model. Its reason for existing is the recurring crash where
``float(cell_value)`` aborts a whole run on a non-numeric cell such as ``"N/A"``
or a thousands-separated ``"1,234.56"``.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# Cell values that mean "no number here" rather than an error.
_BLANK_TOKENS = {"", "N/A", "NA", "#N/A", "-", "—", "NULL", "NONE"}

# Excel's ROUND() rounds half *away from zero*; Python's built-in round() is
# half-to-even and subject to float-repr artifacts. Use this when money math
# must match the manual Excel result to the cent.
EXCEL_ROUNDING = ROUND_HALF_UP
_CENTS = Decimal("0.01")  # the common money() quantizer, cached


def _clean_numeric_string(value: str) -> tuple[str | None, bool]:
    """Strip a raw cell string to a parseable numeric body + sign.

    Returns ``(cleaned, negative)``; ``cleaned`` is ``None`` for blank/``N/A``
    tokens. Strips surrounding whitespace and thousands separators and unwraps
    parenthesised accounting negatives (``"(1,234.56)"`` -> ``"1234.56"``, neg).
    Shared by :func:`to_number` and :func:`to_decimal` so they can't drift.
    """
    s = value.strip()
    if s.upper() in _BLANK_TOKENS:
        return None, False
    cleaned = s.replace(",", "").replace(" ", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    return cleaned, negative


def _quantizer(places: int) -> Decimal:
    """The quantize exponent for ``places`` dp (cents cached as the common case)."""
    return _CENTS if places == 2 else Decimal(1).scaleb(-places)


def to_number(value: Any, default: float = 0.0) -> float:
    """Coerce a cell value to ``float``, never raising on dirty input.

    Handles real numbers, blanks/``None``, common not-applicable tokens, and
    strings with thousands separators or surrounding whitespace. Anything that
    still cannot be parsed returns ``default``.

    >>> to_number("1,234.56")
    1234.56
    >>> to_number("N/A")
    0.0
    >>> to_number(None)
    0.0
    """
    if value is None:
        return default
    if isinstance(value, bool):
        # Avoid treating True/False as 1/0 silently — almost always a mistake.
        return default
    if isinstance(value, (int, float)):
        return float(value)
    cleaned, negative = _clean_numeric_string(str(value))
    if cleaned is None:
        return default
    try:
        result = float(cleaned)
    except ValueError:
        return default
    return -result if negative else result


def to_decimal(
    value: Any, default: Decimal = Decimal("0"), *, places: int | None = None
) -> Decimal:
    """Coerce a cell value to an exact ``Decimal``, never raising on dirty input.

    Use this (not :func:`to_number`) for money that is multiplied, divided,
    rate-applied, or allocated, or anywhere you must match Excel's ``ROUND`` to
    the cent — float arithmetic drifts and rounds differently there.

    Parses via the *string* form so decimal literals stay exact:
    ``to_decimal("0.1")`` is ``Decimal("0.1")``, not the binary-float
    ``Decimal(0.1)`` (= ``0.1000000000000000055...``). Handles the same dirty
    inputs as :func:`to_number` (blanks, ``N/A`` tokens, thousands separators,
    accounting negatives); ``bool`` and unparseable input return ``default``.
    When *places* is given, the result is quantized with :data:`EXCEL_ROUNDING`
    (a value too large to quantize within the decimal context is returned
    unquantized rather than raising).

    >>> to_decimal("1,234.56")
    Decimal('1234.56')
    >>> to_decimal("0.1") + to_decimal("0.2")
    Decimal('0.3')
    >>> to_decimal("2.675", places=2)
    Decimal('2.68')
    """
    result = _to_decimal_raw(value, default)
    if places is not None:
        try:
            result = result.quantize(_quantizer(places), rounding=EXCEL_ROUNDING)
        except InvalidOperation:
            # Magnitude exceeds the decimal context precision (e.g. a garbage
            # huge value). Honor the never-raise contract: hand back the value
            # unquantized rather than aborting the run.
            pass
    return result


def _to_decimal_raw(value: Any, default: Decimal) -> Decimal:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, Decimal):
        return value if value.is_finite() else default
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # Go through repr (str) so an already-clean float renders exactly
        # (str(0.1) == "0.1"); guard NaN/inf which Decimal would otherwise keep.
        if not math.isfinite(value):
            return default
        return Decimal(str(value))
    cleaned, negative = _clean_numeric_string(str(value))
    if cleaned is None:
        return default
    try:
        result = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return default
    if not result.is_finite():  # e.g. the strings "Inf"/"NaN" parse but aren't numbers
        return default
    return -result if negative else result


def money(value: Any) -> Decimal:
    """Money convenience: :func:`to_decimal` quantized to cents (2 dp, Excel rounding)."""
    return to_decimal(value, places=2)


def is_blank(value: Any) -> bool:
    """True for ``None``, float NaN, or a string that is empty/whitespace after stripping."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def to_text(value: Any, default: str = "") -> str:
    """Coerce a cell value to a stripped string; ``None``/blank → ``default``.

    Dates are rendered with ``isoformat`` so they round-trip predictably rather
    than via ``str(datetime(...))``.
    """
    if value is None:
        return default
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()
    return s if s != "" else default


def to_date(value: Any, *, dayfirst: bool = False) -> "datetime | None":
    """Coerce a cell value to a ``datetime``, or ``None`` if it isn't a date.

    Handles the three forms a date arrives in:

    * a real ``date``/``datetime`` — returned as-is;
    * an **Excel serial number** (int/float) — Excel stores dates as integers, so
      a "date" column read from a workbook may be a number; converted via Excel's
      1899-12-30 epoch;
    * a string — parsed with pandas (``dayfirst`` controls D/M vs M/D ambiguity).

    Coercing date columns through this in the Transform phase is what makes them
    display as real dates (rather than text) once a date number format is applied.
    """
    if value is None or is_blank(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, (int, float)):
        from openpyxl.utils.datetime import from_excel

        try:
            result = from_excel(value)
        except (ValueError, OverflowError):
            return None
        return result if isinstance(result, datetime) else None
    import pandas as pd

    ts = pd.to_datetime(str(value).strip(), dayfirst=dayfirst, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.to_pydatetime()


def to_int(value: Any, default: int | None = None) -> int | None:
    """Coerce to ``int`` via :func:`to_number`, rounding to nearest;
    blank/unparseable → ``default``."""
    if is_blank(value):
        return default
    n = to_number(value, default=float("nan"))
    if n != n:  # NaN
        return default
    return int(round(n))
