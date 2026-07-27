"""An automation: an ordered sequence of stages that run strictly sequentially.

Stages run one at a time; the first failed stage halts the run (fail-fast). The run
status rolls up from stage statuses.

The optional ``resume_state`` argument supports restarting a failed run from the
failed step. Its shape matches the ``state.json`` written by the run-store subscriber::

    {
        "stages": {
            "stage_name": {
                "status": "succeeded",
                "steps": {"step_name": "succeeded"}
            }
        }
    }

Stages marked succeeded/succeeded_with_warning are skipped entirely; the first
non-succeeded stage runs with its already-succeeded steps excluded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context import RunContext
from .events import Event, EventType
from .outcome import RunStatus, StageStatus
from .stage import Stage, StageResult

_DONE_STATUSES = {"succeeded", "succeeded_with_warning"}


def _status_of(entry: Any) -> str:
    """A step's prior status from either the minimal string form or the rich dict
    form written to ``state.json`` (``{"status": ..., "attempts": ...}``)."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get("status", "")
    return ""


@dataclass
class AutomationResult:
    name: str
    run_id: str
    status: RunStatus
    stages: list[StageResult] = field(default_factory=list)


class Automation:
    def __init__(self, name: str, stages: list[Stage]) -> None:
        self.name = name
        self.stages = stages

    async def run(
        self,
        ctx: RunContext,
        *,
        resume_state: dict | None = None,
    ) -> AutomationResult:
        await ctx.bus.publish(
            Event(EventType.RUN_STARTED, ctx.run_id, data={"automation": self.name})
        )

        prior_stages: dict[str, Any] = (resume_state or {}).get("stages", {})
        results: list[StageResult] = []

        for stage in self.stages:
            stage_prior = prior_stages.get(stage.name, {})

            # Skip stages that already completed successfully in a prior attempt.
            if isinstance(stage_prior, dict):
                prior_status = stage_prior.get("status", "")
            else:
                prior_status = str(stage_prior)
            if prior_status in _DONE_STATUSES:
                continue

            # Build skip set: steps that already succeeded within this stage.
            skip: frozenset[str] = frozenset()
            if isinstance(stage_prior, dict):
                skip = frozenset(
                    step_name
                    for step_name, step_entry in stage_prior.get("steps", {}).items()
                    if _status_of(step_entry) in _DONE_STATUSES
                )

            result = await stage.run(ctx, skip=skip)
            results.append(result)

            if result.status is StageStatus.FAILED:
                await ctx.bus.publish(
                    Event(EventType.RUN_FAILED, ctx.run_id, level="ERROR",
                          message=f"Stage {stage.name!r} failed")
                )
                return AutomationResult(self.name, ctx.run_id, RunStatus.FAILED, results)

        if any(r.status is StageStatus.SUCCEEDED_WITH_WARNING for r in results):
            run_status = RunStatus.SUCCEEDED_WITH_WARNING
        else:
            run_status = RunStatus.SUCCEEDED

        await ctx.bus.publish(Event(EventType.RUN_SUCCEEDED, ctx.run_id))
        return AutomationResult(self.name, ctx.run_id, run_status, results)
