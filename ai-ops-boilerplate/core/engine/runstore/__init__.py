"""Run history persistence: per-run JSON + event stream + a flat CSV ledger.

The CSV ledger (``runs.csv`` / ``steps.csv`` / ``stages.csv``) is intentionally the
lowest-common-denominator format: a layman opens it in Excel, an analyst queries it
with DuckDB or SQLite — no service, no database server. ``run.json`` per run is the
structured audit source of truth; the ledger is the queryable index.

See ``ledger`` for the concurrency-safe append, ``store`` for the layout, and
``RunStoreSubscriber`` (in ``..subscribers``) for the event-to-record mapping.
"""

from __future__ import annotations

from .store import DEFAULT_RUNS_DIR, RunStore

__all__ = ["DEFAULT_RUNS_DIR", "RunStore"]
