"""Column definitions for the flat CSV ledger.

The ledger is the layman-facing surface: ``runs.csv`` and ``steps.csv`` open directly
in Excel (double-click) and are queried in place by DuckDB
(``SELECT * FROM 'runs/runs.csv'``) or imported by SQLite. Column order here is the
on-disk column order, so keep additions at the end to avoid reshuffling existing files.

Timestamps are ISO-8601 UTC strings (human-readable in Excel, sortable as text, and
parseable by DuckDB/SQLite).
"""

from __future__ import annotations

from datetime import datetime, timezone

RUNS_CSV = "runs.csv"
STEPS_CSV = "steps.csv"
STAGES_CSV = "stages.csv"

RUNS_COLUMNS = [
    "run_id",
    "automation",
    "status",
    "started_utc",
    "finished_utc",
    "duration_s",
    "steps_total",
    "steps_failed",
    "error",
    "host",
    "triggered_by",
    "stages_total",
    "warnings",
]

STEPS_COLUMNS = [
    "run_id",
    "step",
    "status",
    "attempts",
    "started_utc",
    "finished_utc",
    "duration_s",
    "error",
    "stage",
    "warnings",
]

STAGES_COLUMNS = [
    "run_id",
    "stage",
    "status",
    "started_utc",
    "finished_utc",
    "duration_s",
    "steps_total",
    "steps_warned",
    "steps_failed",
]


def iso_utc(epoch: float | None) -> str:
    """Format an epoch timestamp as an ISO-8601 UTC string, or '' if None."""
    if epoch is None:
        return ""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds")
