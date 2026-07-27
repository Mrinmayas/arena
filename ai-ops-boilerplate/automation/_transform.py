"""Read and classify raw input files. Replace the stub body with real logic.

See the python-logic-generation and excel-automation skills. Parse inputs into a
pandas model here; do the business logic in pure functions so tests can exercise it
without Excel I/O.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def load(inputs: Path, audit: Any) -> dict:
    files = sorted(p for p in inputs.glob("*") if p.is_file())
    audit.automation(f"found {len(files)} input file(s)", step="load",
                     detail={"files": [f.name for f in files]})
    # TODO: parse into a pandas model (read_table) and classify per the rules workbook.
    return {"input_files": [str(f) for f in files]}
