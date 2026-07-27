"""Tests for the vendored core/excel safety primitives.

Focused on the two things most likely to cause a cent-level tie-out bug or an
ERP-parsing failure: Decimal money coercion, and the preamble-resilient header scan.
"""
from decimal import Decimal

import pytest

from core.excel import coerce, compat
from core.excel.errors import HeaderNotFoundError


def test_money_is_decimal_half_up():
    # Money must be Decimal (never float) and round half-up to the cent.
    assert coerce.money("1,234.567") == Decimal("1234.57")
    assert isinstance(coerce.money("10"), Decimal)


def test_find_header_locates_row_past_preamble():
    # Real ERP exports carry title/blank preamble rows before the header.
    rows = [
        ["Q report", None, None],
        [None, None, None],
        ["Vendor", "Invoice", "Amount"],
        ["ACME", "INV1", 100],
    ]
    m = compat.find_header(rows, anchors=["Vendor", "Amount"])
    assert m.row == 3            # 1-indexed row of the header
    assert m.col("Vendor") == 0  # 0-indexed column offsets
    assert m.col("Amount") == 2


def test_find_header_raises_when_anchors_absent():
    rows = [["a", "b", "c"], ["1", "2", "3"]]
    with pytest.raises(HeaderNotFoundError):
        compat.find_header(rows, anchors=["Vendor", "Amount"])
