"""Render the output workbook.

STUB — replace with `core.excel.render(...)`. Per the excel-automation skill,
workbook GENERATION must go through core.excel.render() (build a pandas model, render
once, atomic save) — not hand-rolled openpyxl. core.excel is vendored in a later
boilerplate phase; until then this stub writes a placeholder so the spine runs and the
smoke test has something to assert.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


def render(data: dict, outputs: Path, audit: Any) -> Path:
    # TODO: build SheetModel(s) from `data` and call core.excel.render(path, [model]).
    out = outputs / f"report_{datetime.now():%Y%m%d_%H%M%S}.txt"
    out.write_text(
        "PLACEHOLDER OUTPUT — replace automation/_report.render() with core.excel.render().\n"
        f"Input files seen: {data.get('input_files', [])}\n",
        encoding="utf-8",
    )
    audit.warn("using placeholder _report.render() — wire up core.excel.render()",
               step="report")
    return out
