"""Event subscriber that persists a run: per-run JSON + event stream + CSV ledger.

One instance per run. It listens to the bus and:
  - mirrors every event to ``runs/<run_id>/events.jsonl``;
  - tracks per-stage and per-step timing/status as events arrive;
  - on run completion, writes ``run.json`` (structured audit truth) and appends rows
    to the CSV ledger (``runs.csv``, ``steps.csv``, and ``stages.csv``).

It also captures escalation records from ``STEP_WARNING`` and ``STEP_FAILED`` events
and writes them to ``escalations.jsonl``.

After finalising records, if the run succeeded and is not in debug mode, the
working-memory ``files/`` directory and the run workspace are cleaned up.

A run that emits ``STAGE_*`` events is recorded in the hierarchical form (stages →
steps); a run with no stages falls back to a flat ``run.json`` and the two-CSV ledger
without the stage columns. The stage-only columns (``stage``, ``warnings``,
``stages_total``) are written only for staged runs, so tools that read by column name
are unaffected.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..events import Event, EventType
from ..runstore.schema import iso_utc
from ..runstore.store import DEFAULT_RUNS_DIR, RunStore

if TYPE_CHECKING:
    from ..memory import WorkingMemory


# Events after which the incremental resume state (state.json) is re-persisted.
_STATE_EVENTS = frozenset({
    EventType.STAGE_STARTED,
    EventType.STAGE_SUCCEEDED,
    EventType.STAGE_FAILED,
    EventType.STEP_STARTED,
    EventType.STEP_SUCCEEDED,
    EventType.STEP_WARNING,
    EventType.STEP_FAILED,
    EventType.RUN_SUCCEEDED,
    EventType.RUN_FAILED,
})


# ---------------------------------------------------------------------------
# Internal state dataclasses
# ---------------------------------------------------------------------------

@dataclass
class _StepState:
    name: str
    stage: str = ""
    started: float | None = None
    finished: float | None = None
    attempts: int = 0
    status: str = "running"
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    retryable: bool | None = None


@dataclass
class _StageState:
    name: str
    started: float | None = None
    finished: float | None = None
    status: str = "running"
    step_names: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Subscriber
# ---------------------------------------------------------------------------

class RunStoreSubscriber:
    def __init__(
        self,
        run_id: str,
        automation: str,
        *,
        runs_dir=DEFAULT_RUNS_DIR,
        triggered_by: str = "cli",
        host: str | None = None,
        memory: "WorkingMemory | None" = None,
        debug: bool = False,
        arguments: dict[str, Any] | None = None,
        resume_state: dict[str, Any] | None = None,
    ) -> None:
        self.run_id = run_id
        self.automation = automation
        self.triggered_by = triggered_by
        self.host = host or socket.gethostname()
        self.store = RunStore(runs_dir)
        self._memory = memory
        self._debug = debug
        self._arguments = arguments or {}

        self._started: float | None = None
        self._finished: float | None = None
        self._status: str = "running"
        self._error: str | None = None

        self._order: list[str] = []
        self._steps: dict[str, _StepState] = {}

        self._stage_order: list[str] = []
        self._stages: dict[str, _StageState] = {}

        self._escalations: list[dict[str, Any]] = []

        # On resume, preload the stages/steps that completed in a prior attempt so the
        # resumed run's run.json and ledger reflect the whole run, not just the re-run
        # portion. The current attempt's events overwrite these in place.
        if resume_state:
            self._preload(resume_state)

    def _preload(self, state: dict[str, Any]) -> None:
        for stage_name in state.get("stage_order", []):
            self._stage(stage_name)
        for stage_name, stage in state.get("stages", {}).items():
            st = self._stage(stage_name)
            st.started = stage.get("started")
            st.finished = stage.get("finished")
            st.status = stage.get("status", "running")
            for step_name, step in stage.get("steps", {}).items():
                if isinstance(step, str):  # tolerate the minimal string form
                    step = {"status": step}
                s = self._step(step_name, stage=stage_name)
                s.started = step.get("started")
                s.finished = step.get("finished")
                s.attempts = step.get("attempts", 0)
                s.status = step.get("status", "running")
                s.error = step.get("error")
                s.warnings = list(step.get("warnings", []))
                s.retryable = step.get("retryable")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _step(self, name: str, stage: str = "") -> _StepState:
        if name not in self._steps:
            self._steps[name] = _StepState(name, stage=stage)
            self._order.append(name)
            if stage and stage in self._stages:
                self._stages[stage].step_names.append(name)
        return self._steps[name]

    def _stage(self, name: str) -> _StageState:
        if name not in self._stages:
            self._stages[name] = _StageState(name)
            self._stage_order.append(name)
        return self._stages[name]

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    def __call__(self, event: Event) -> None:
        self.store.append_event(self.run_id, _event_dict(event))

        if event.type is EventType.RUN_STARTED:
            self._started = event.ts

        elif event.type is EventType.STAGE_STARTED and event.stage:
            st = self._stage(event.stage)
            st.started = event.ts

        elif event.type in (EventType.STAGE_SUCCEEDED, EventType.STAGE_FAILED) and event.stage:
            st = self._stages.get(event.stage)
            if st:
                st.finished = event.ts
                # Status is derived from step outcomes at finalise time — see _stage_status()

        elif event.type is EventType.STEP_STARTED and event.step:
            s = self._step(event.step, stage=event.stage or "")
            s.started = event.ts
            s.attempts = max(s.attempts, 1)
            # A (re-)execution invalidates any terminal detail from a prior attempt —
            # critical on resume, where this step was preloaded as failed and is now
            # re-running. Without this reset a now-succeeded step keeps its stale error.
            s.status = "running"
            s.error = None
            s.retryable = None
            s.warnings = []

        elif event.type is EventType.STEP_RETRYING and event.step:
            s = self._step(event.step, stage=event.stage or "")
            if event.attempt:
                s.attempts = event.attempt

        elif event.type is EventType.STEP_SUCCEEDED and event.step:
            s = self._step(event.step, stage=event.stage or "")
            s.finished = event.ts
            s.status = "succeeded"
            s.attempts = event.attempt or s.attempts

        elif event.type is EventType.STEP_WARNING and event.step:
            s = self._step(event.step, stage=event.stage or "")
            s.finished = event.ts
            s.status = "succeeded_with_warning"
            s.attempts = event.attempt or s.attempts
            if event.message:
                s.warnings = event.message.split("; ")
            self._escalations.append({
                "kind": "warning",
                "stage": event.stage,
                "step": event.step,
                "message": event.message,
                "ts": event.ts,
                "items": (event.data or {}).get("escalations", []),
            })

        elif event.type is EventType.STEP_FAILED and event.step:
            s = self._step(event.step, stage=event.stage or "")
            s.finished = event.ts
            s.status = "failed"
            s.attempts = event.attempt or s.attempts
            s.error = event.message
            s.retryable = (event.data or {}).get("retryable")
            self._escalations.append({
                "kind": "error",
                "stage": event.stage,
                "step": event.step,
                "message": event.message,
                "ts": event.ts,
            })

        elif event.type in (EventType.RUN_SUCCEEDED, EventType.RUN_FAILED):
            self._finished = event.ts
            self._status = "succeeded" if event.type is EventType.RUN_SUCCEEDED else "failed"
            self._error = event.message
            self._finalize()

        # Persist resume state incrementally on every stage/step transition so an
        # interrupted run leaves a usable state.json behind.
        if event.type in _STATE_EVENTS:
            self._persist_state()

    # ------------------------------------------------------------------
    # Finalise
    # ------------------------------------------------------------------

    def _finalize(self) -> None:
        duration = (
            round(self._finished - self._started, 3)
            if self._started and self._finished
            else None
        )
        all_steps = [self._steps[n] for n in self._order]
        steps_failed = sum(1 for s in all_steps if s.status == "failed")
        steps_warned = sum(1 for s in all_steps if s.status == "succeeded_with_warning")
        is_staged = bool(self._stages)

        # Memory snapshot before potential cleanup
        mem_snapshot = self._memory.snapshot() if self._memory else None

        # Persist escalations
        if self._escalations:
            esc_path = self.store.run_dir(self.run_id) / "escalations.jsonl"
            with open(esc_path, "w", encoding="utf-8") as f:
                for esc in self._escalations:
                    f.write(json.dumps(esc) + "\n")

        # run.json: hierarchical for staged runs; flat for stage-less runs
        if is_staged:
            self._write_hierarchical_run_json(all_steps, mem_snapshot, duration)
            self._write_stages_csv(all_steps)
        else:
            self._write_flat_run_json(all_steps, duration)

        # runs.csv
        run_row: dict[str, Any] = {
            "run_id": self.run_id,
            "automation": self.automation,
            "status": self._status,
            "started_utc": iso_utc(self._started),
            "finished_utc": iso_utc(self._finished),
            "duration_s": duration,
            "steps_total": len(all_steps),
            "steps_failed": steps_failed,
            "error": self._error or "",
            "host": self.host,
            "triggered_by": self.triggered_by,
        }
        if is_staged:
            run_row["stages_total"] = len(self._stages)
            run_row["warnings"] = steps_warned
        self.store.append_run_row(run_row)

        # steps.csv
        for s in all_steps:
            step_row: dict[str, Any] = {
                "run_id": self.run_id,
                "step": s.name,
                "status": s.status,
                "attempts": s.attempts,
                "started_utc": iso_utc(s.started),
                "finished_utc": iso_utc(s.finished),
                "duration_s": (
                    round(s.finished - s.started, 3) if s.started and s.finished else None
                ),
                "error": s.error or "",
            }
            if is_staged:
                step_row["stage"] = s.stage
                step_row["warnings"] = len(s.warnings)
            self.store.append_step_row(step_row)

        # Delete working-memory files and workspace after a successful production run;
        # debug mode keeps everything for inspection.
        if not self._debug and self._status == "succeeded":
            if self._memory:
                self._memory.cleanup()
            self.store.cleanup_workspace(self.run_id)

    # ------------------------------------------------------------------
    # run.json writers
    # ------------------------------------------------------------------

    def _write_flat_run_json(self, all_steps: list[_StepState], duration: float | None) -> None:
        """Flat format — used for stage-less runs."""
        self.store.write_run_json(
            self.run_id,
            {
                "run_id": self.run_id,
                "automation": self.automation,
                "status": self._status,
                "started_utc": iso_utc(self._started),
                "finished_utc": iso_utc(self._finished),
                "duration_s": duration,
                "host": self.host,
                "triggered_by": self.triggered_by,
                "error": self._error,
                "steps": [_step_dict(s) for s in all_steps],
            },
        )

    def _write_hierarchical_run_json(
        self,
        all_steps: list[_StepState],
        mem_snapshot: dict[str, Any] | None,
        duration: float | None,
    ) -> None:
        """Hierarchical format for staged (Automation) runs."""
        steps_by_stage: dict[str, list[_StepState]] = {n: [] for n in self._stage_order}
        for s in all_steps:
            if s.stage in steps_by_stage:
                steps_by_stage[s.stage].append(s)

        stages_json = []
        for stage_name in self._stage_order:
            st = self._stages[stage_name]
            stage_steps = steps_by_stage.get(stage_name, [])
            stages_json.append({
                "name": stage_name,
                "status": self._stage_status(stage_steps),
                "started_utc": iso_utc(st.started),
                "finished_utc": iso_utc(st.finished),
                "duration_s": self._stage_dur(st),
                "steps": [_step_dict(s) for s in stage_steps],
            })

        self.store.write_run_json(
            self.run_id,
            {
                "run_id": self.run_id,
                "automation": self.automation,
                "status": self._status,
                "started_utc": iso_utc(self._started),
                "finished_utc": iso_utc(self._finished),
                "duration_s": duration,
                "host": self.host,
                "triggered_by": self.triggered_by,
                "error": self._error,
                "arguments": self._arguments,
                "escalations": self._escalations,
                "memory_snapshot": mem_snapshot,
                "stages": stages_json,
            },
        )

    def _write_stages_csv(self, all_steps: list[_StepState]) -> None:
        steps_by_stage: dict[str, list[_StepState]] = {n: [] for n in self._stage_order}
        for s in all_steps:
            if s.stage in steps_by_stage:
                steps_by_stage[s.stage].append(s)

        for stage_name in self._stage_order:
            st = self._stages[stage_name]
            stage_steps = steps_by_stage.get(stage_name, [])
            self.store.append_stage_row({
                "run_id": self.run_id,
                "stage": stage_name,
                "status": self._stage_status(stage_steps),
                "started_utc": iso_utc(st.started),
                "finished_utc": iso_utc(st.finished),
                "duration_s": self._stage_dur(st),
                "steps_total": len(stage_steps),
                "steps_warned": sum(1 for s in stage_steps if s.status == "succeeded_with_warning"),
                "steps_failed": sum(1 for s in stage_steps if s.status == "failed"),
            })

    @staticmethod
    def _stage_status(steps: list[_StepState]) -> str:
        if any(s.status == "failed" for s in steps):
            return "failed"
        if any(s.status == "succeeded_with_warning" for s in steps):
            return "succeeded_with_warning"
        return "succeeded"

    @staticmethod
    def _stage_dur(st: _StageState) -> float | None:
        if st.started and st.finished:
            return round(st.finished - st.started, 3)
        return None

    # ------------------------------------------------------------------
    # Resume state
    # ------------------------------------------------------------------

    def _persist_state(self) -> None:
        """Write the current per-stage/per-step completion to state.json.

        The shape mirrors what ``Automation.run`` consumes as ``resume_state``: each
        stage carries a status and a map of its steps to rich status records. A stage
        is reported ``"running"`` until all its known steps have reached a terminal
        outcome, at which point its status rolls up from those steps.

        No-op for stage-less runs: they are not resumable, so writing a stage-less
        state.json on every step event would be pure waste.
        """
        if not self._stage_order:
            return

        steps_by_stage: dict[str, list[_StepState]] = {n: [] for n in self._stage_order}
        for name in self._order:
            s = self._steps[name]
            steps_by_stage.setdefault(s.stage, []).append(s)

        stages: dict[str, Any] = {}
        for stage_name in self._stage_order:
            st = self._stages[stage_name]
            stage_steps = steps_by_stage.get(stage_name, [])
            terminal = stage_steps and all(
                s.status in ("succeeded", "succeeded_with_warning", "failed")
                for s in stage_steps
            )
            stages[stage_name] = {
                "status": self._stage_status(stage_steps) if terminal else "running",
                "started": st.started,
                "finished": st.finished,
                "steps": {
                    s.name: {
                        "status": s.status,
                        "stage": s.stage,
                        "attempts": s.attempts,
                        "started": s.started,
                        "finished": s.finished,
                        "error": s.error,
                        "warnings": s.warnings,
                        "retryable": s.retryable,
                    }
                    for s in stage_steps
                },
            }

        self.store.write_state(self.run_id, {
            "run_id": self.run_id,
            "automation": self.automation,
            "updated_utc": iso_utc(self._finished or self._started),
            "stage_order": list(self._stage_order),
            "stages": stages,
        })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _step_dict(s: _StepState) -> dict[str, Any]:
    return {
        "step": s.name,
        "stage": s.stage,
        "status": s.status,
        "attempts": s.attempts,
        "started_utc": iso_utc(s.started),
        "finished_utc": iso_utc(s.finished),
        "duration_s": (
            round(s.finished - s.started, 3) if s.started and s.finished else None
        ),
        "error": s.error,
        "warnings": s.warnings,
        "retryable": s.retryable,
    }


def _event_dict(event: Event) -> dict[str, Any]:
    return {
        "type": event.type.value,
        "ts": event.ts,
        "iso": iso_utc(event.ts),
        "stage": event.stage,
        "step": event.step,
        "attempt": event.attempt,
        "level": event.level,
        "message": event.message,
        "data": event.data,
    }
