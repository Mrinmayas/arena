"""Excel number-format helpers: accounting money + CLDR-driven dates.

Operators think in two languages this module bridges:

* **Money** should be *accounting* formatted (symbol flush-left, negatives in
  parentheses, zero as a dash, decimals aligned). :func:`accounting` builds the
  Excel format code so nobody hand-writes ``_($* #,##0.00_);...``.
* **Dates** are easiest to specify as a **CLDR pattern** (``dd-MMM-yyyy``), the
  standard most people know. Excel uses a *different* token language
  (``dd-mmm-yyyy``); :func:`cldr_to_excel_date` translates. (Excel also stores
  dates as integer serials — see :func:`.coerce.to_date`, which must
  be used on the *values* so a date format actually renders a date, not text.)

:func:`resolve_number_format` lets a rules-workbook cell hold a friendly token —
``accounting``, ``accounting:$``, ``accounting:£:2``, or ``date:dd-MMM-yyyy`` —
or a raw Excel code, and returns the Excel code to store on the cell.
"""

from __future__ import annotations

# Common ready-made codes.
DATE_ISO = "yyyy-mm-dd"
ACCOUNTING = '_(* #,##0.00_);_(* \\(#,##0.00\\);_(* "-"??_);_(@_)'


def accounting(symbol: str = "", decimals: int = 2) -> str:
    """Return an Excel *accounting* number-format code.

    >>> accounting()            # no symbol
    '_(* #,##0.00_);_(* \\\\(#,##0.00\\\\);_(* "-"??_);_(@_)'
    >>> accounting("$")          # currency symbol flush-left
    '_($* #,##0.00_);_($* \\\\(#,##0.00\\\\);_($* "-"??_);_(@_)'
    """
    dec = f".{'0' * decimals}" if decimals > 0 else ""
    num = f"#,##0{dec}"
    dash = '"-"' + ("?" * decimals if decimals else "")
    sym = symbol
    return (
        f"_({sym}* {num}_);"
        f"_({sym}* \\({num}\\);"
        f"_({sym}* {dash}_);"
        f"_(@_)"
    )


# CLDR date-field symbol → Excel token, by run length.
def _map_cldr_token(ch: str, n: int) -> str:
    if ch == "y":
        return "yy" if n == 2 else "yyyy"
    if ch == "M":
        return {1: "m", 2: "mm", 3: "mmm"}.get(n, "mmmm")
    if ch == "d":
        return "dd" if n >= 2 else "d"
    if ch == "E":  # day of week
        return "dddd" if n >= 4 else "ddd"
    if ch == "H" or ch == "h":  # hour
        return "hh" if n >= 2 else "h"
    if ch == "m":  # minute (Excel disambiguates m as minute by context after h)
        return "mm" if n >= 2 else "m"
    if ch == "s":  # second
        return "ss" if n >= 2 else "s"
    if ch == "a":  # AM/PM
        return "AM/PM"
    return ch * n


_CLDR_SYMBOLS = set("yMdEHhmsa")


def cldr_to_excel_date(pattern: str) -> str:
    """Translate a CLDR date/time pattern to an Excel number-format code.

    Supports the common subset: y, M, d, E, H/h, m, s, a, plus literal
    separators and ``'quoted'`` literals. Month (``M``) and minute (``m``) are
    distinct in CLDR; Excel reuses ``m`` for both and disambiguates by context,
    which is correct for date-only and standard datetime patterns.

    >>> cldr_to_excel_date("dd-MMM-yyyy")
    'dd-mmm-yyyy'
    >>> cldr_to_excel_date("yyyy-MM-dd")
    'yyyy-mm-dd'
    """
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch in _CLDR_SYMBOLS:
            j = i
            while j < n and pattern[j] == ch:
                j += 1
            out.append(_map_cldr_token(ch, j - i))
            i = j
        elif ch == "'":  # quoted literal
            close = pattern.find("'", i + 1)
            if close == -1:
                out.append(pattern[i + 1 :])
                break
            out.append('"' + pattern[i + 1 : close] + '"')
            i = close + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def resolve_number_format(spec: str | None) -> str | None:
    """Resolve a friendly format token to an Excel number-format code.

    Accepts:

    * ``"accounting"`` / ``"accounting:$"`` / ``"accounting:£:0"`` — money;
    * ``"date:<CLDR>"`` — a CLDR date pattern, translated to Excel tokens;
    * any other string — treated as a raw Excel code and returned unchanged.
    """
    if spec is None:
        return None
    s = str(spec).strip()
    if not s:
        return None
    low = s.lower()
    if low == "accounting":
        return accounting()
    if low.startswith("accounting:"):
        parts = s.split(":")
        symbol = parts[1] if len(parts) > 1 else ""
        decimals = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 2
        return accounting(symbol, decimals)
    if low.startswith("date:"):
        return cldr_to_excel_date(s[len("date:") :])
    return s
