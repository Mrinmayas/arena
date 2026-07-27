"""The automation spine.

Single-stage by default; the orchestration engine (multi-step + resume + human-in-the-loop)
is an OPT-IN layer added only when needed (copier: needs_engine). The one automation is
wired here explicitly — no auto-discovery.

Fill in `_transform` (read + classify inputs) and `_report` (render output via
core.excel.render, per the excel-automation skill).
"""
from __future__ import annotations

from pathlib import Path

from core.audit import audit_run

from . import _report, _transform

AUTOMATION_NAME = "ai_ops_automation"  # copier replaces with the real slug


def run(inputs: Path, outputs: Path, *, operator: str | None = None,
        redact: bool = False) -> Path:
    """Run the automation end-to-end, fully audited."""
    outputs.mkdir(parents=True, exist_ok=True)
    with audit_run(AUTOMATION_NAME, operator=operator, redact=redact) as audit:
        audit.automation(f"reading inputs from {inputs}", step="load")
        data = _transform.load(inputs, audit)

        audit.automation("rendering report", step="report")
        out_path = _report.render(data, outputs, audit)

        audit.set_outcome(output=str(out_path),
                          input_count=len(data.get("input_files", [])))
        audit.automation(f"wrote {out_path.name}", step="done")
        return out_path
