"""Filesystem layout for run history.

Per run, under ``runs/<run_id>/``:
  - ``run.json``  — the full structured record (status, every step result, timings,
    error). This is the audit source of truth for the structured store.
  - ``events.jsonl`` — the append-only event stream, one event per line, for replay.
  - ``artifacts/`` — downloads, transformed files, screenshots (the run workspace).

Globally, under ``runs/``: the ``runs.csv`` / ``steps.csv`` / ``stages.csv`` ledger
(see ledger.py).

``RunStore`` is a thin helper over these paths; the event-to-record mapping lives in
``RunStoreSubscriber``.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from . import ledger
from .schema import (
    RUNS_CSV, RUNS_COLUMNS,
    STAGES_CSV, STAGES_COLUMNS,
    STEPS_CSV, STEPS_COLUMNS,
)

# Anchored to the repo root's ``runs/`` regardless of the working directory.
# store.py → runstore/ → engine/ → core/ → <repo root>
DEFAULT_RUNS_DIR = Path(__file__).resolve().parents[3] / "runs"


class RunStore:
    def __init__(self, runs_dir: Path = DEFAULT_RUNS_DIR) -> None:
        self.runs_dir = runs_dir

    # --- paths -----------------------------------------------------------------
    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def workspace(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "artifacts"

    @property
    def runs_csv(self) -> Path:
        return self.runs_dir / RUNS_CSV

    @property
    def steps_csv(self) -> Path:
        return self.runs_dir / STEPS_CSV

    @property
    def stages_csv(self) -> Path:
        return self.runs_dir / STAGES_CSV

    def state_json(self, run_id: str) -> Path:
        """Path to the incremental resume-state file."""
        return self.run_dir(run_id) / "state.json"

    # --- writes ----------------------------------------------------------------
    def ensure_run_dir(self, run_id: str) -> Path:
        d = self.run_dir(run_id)
        (d / "artifacts").mkdir(parents=True, exist_ok=True)
        return d

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        self.ensure_run_dir(run_id)
        with open(self.run_dir(run_id) / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def write_run_json(self, run_id: str, record: dict[str, Any]) -> None:
        self.ensure_run_dir(run_id)
        (self.run_dir(run_id) / "run.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )

    def write_state(self, run_id: str, record: dict[str, Any]) -> None:
        """Atomically persist the incremental resume state.

        Written on every step/stage terminal event so an interrupted run leaves a
        usable ``state.json``. Atomic (``.tmp`` + ``os.replace``) so a crash mid-write
        never leaves a half-written file that would defeat resume.
        """
        self.ensure_run_dir(run_id)
        path = self.state_json(run_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def read_state(self, run_id: str) -> dict[str, Any]:
        """Load the persisted resume state, or ``{}`` if absent/corrupt."""
        path = self.state_json(run_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def cleanup_workspace(self, run_id: str) -> None:
        """Delete the artifacts directory after a successful production run.

        Keeps run.json, events.jsonl, state.json, and memory/manifest.json for audit;
        only the working-file copies inside artifacts/ are removed.
        """
        shutil.rmtree(self.workspace(run_id), ignore_errors=True)

    def append_run_row(self, row: dict[str, Any]) -> bool:
        return ledger.append_row(self.runs_csv, RUNS_COLUMNS, row)

    def append_step_row(self, row: dict[str, Any]) -> bool:
        return ledger.append_row(self.steps_csv, STEPS_COLUMNS, row)

    def append_stage_row(self, row: dict[str, Any]) -> bool:
        return ledger.append_row(self.stages_csv, STAGES_COLUMNS, row)

    def reconcile(self) -> None:
        """Fold any rows spilled by an earlier locked write back into the ledger."""
        ledger.reconcile(self.runs_csv)
        ledger.reconcile(self.steps_csv)
        ledger.reconcile(self.stages_csv)
