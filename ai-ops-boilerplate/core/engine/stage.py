"""A stage: a named collection of steps that run in parallel.

``Stage.run`` launches all its steps concurrently with ``asyncio.gather``, waits for
every one to reach a terminal outcome, then rolls up to a single ``StageStatus``:
failed if any step failed, succeeded-with-warning if any warned, otherwise succeeded.

The optional ``skip`` set supports resume: steps that already completed successfully
in a prior attempt are excluded from this invocation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .context import RunContext
from .errors import FlowDefinitionError
from .events import Event, EventType
from .outcome import StageStatus
from .step import Step, StepResult, StepStatus


@dataclass
class StageResult:
    name: str
    status: StageStatus
    steps: list[StepResult] = field(default_factory=list)


class Stage:
    def __init__(self, name: str, steps: list[Step]) -> None:
        names = [s.name for s in steps]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise FlowDefinitionError(
                f"Stage {name!r} has duplicate step names: {sorted(dupes)}"
            )
        self.name = name
        self.steps = steps

    async def run(
        self,
        ctx: RunContext,
        *,
        skip: frozenset[str] = frozenset(),
    ) -> StageResult:
        await ctx.bus.publish(Event(EventType.STAGE_STARTED, ctx.run_id, stage=self.name))

        steps_to_run = [s for s in self.steps if s.name not in skip]
        results: list[StepResult] = list(
            await asyncio.gather(*(s.execute(ctx, stage=self.name) for s in steps_to_run))
        )

        if any(r.status is StepStatus.FAILED for r in results):
            status = StageStatus.FAILED
            await ctx.bus.publish(Event(EventType.STAGE_FAILED, ctx.run_id, stage=self.name))
        elif any(r.status is StepStatus.SUCCEEDED_WITH_WARNING for r in results):
            status = StageStatus.SUCCEEDED_WITH_WARNING
            await ctx.bus.publish(Event(EventType.STAGE_SUCCEEDED, ctx.run_id, stage=self.name))
        else:
            status = StageStatus.SUCCEEDED
            await ctx.bus.publish(Event(EventType.STAGE_SUCCEEDED, ctx.run_id, stage=self.name))

        return StageResult(self.name, status, results)
