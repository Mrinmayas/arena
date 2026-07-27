"""A single unit of work in a stage.

A ``Step`` wraps an async function ``fn(step_ctx)``. ``execute`` runs it, retrying on
``RetryableError`` up to ``retries`` times with ``retry_delay`` seconds between
attempts. Any other exception (including ``NonRetryableError``) fails immediately.

Failures are *returned* as a ``StepResult`` with ``status == FAILED``, not raised — the
owning ``Stage`` decides what a failure means for the run. This keeps the engine's only
raised error a build-time misconfiguration (see errors.py).

``Step.execute`` creates a fresh ``StepContext`` per invocation so parallel steps in
the same stage cannot corrupt one another's state.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from .context import RunContext
from .events import Event, EventType
from .outcome import RetryableError


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_WARNING = "succeeded_with_warning"
    FAILED = "failed"


# Imported lazily to break the circular dep: step_context → step (StepStatus/StepResult).
# step_context does NOT import Step, so the forward ref is safe.
if TYPE_CHECKING:
    from .step_context import StepContext

StepFn = Callable[["StepContext"], Awaitable[None]]


@dataclass(slots=True)
class StepResult:
    name: str
    status: StepStatus
    attempts: int
    error: str | None = None
    started: float | None = None
    finished: float | None = None
    warnings: list[str] = field(default_factory=list)
    retryable: bool | None = None  # None on success; True/False on failure

    @property
    def duration_s(self) -> float | None:
        if self.started is None or self.finished is None:
            return None
        return round(self.finished - self.started, 3)


class Step:
    def __init__(
        self,
        name: str,
        fn: StepFn,
        *,
        retries: int = 0,
        retry_delay: float = 2.0,
    ) -> None:
        self.name = name
        self.fn = fn
        self.retries = retries
        self.retry_delay = retry_delay

    async def execute(self, ctx: RunContext, *, stage: str = "") -> StepResult:
        from .step_context import StepContext  # local import avoids circular dep at module level

        await ctx.bus.publish(
            Event(EventType.STEP_STARTED, ctx.run_id, stage=stage, step=self.name)
        )
        started = time.time()
        attempt = 0
        while True:
            attempt += 1
            step_ctx = StepContext(_run_ctx=ctx, stage=stage, step=self.name)
            try:
                await self.fn(step_ctx)
            except RetryableError as exc:
                if attempt <= self.retries:
                    await ctx.bus.publish(
                        Event(EventType.STEP_RETRYING, ctx.run_id, stage=stage, step=self.name,
                              attempt=attempt, level="WARNING", message=str(exc))
                    )
                    await asyncio.sleep(self.retry_delay)
                    continue
                await ctx.bus.publish(
                    Event(EventType.STEP_FAILED, ctx.run_id, stage=stage, step=self.name,
                          attempt=attempt, level="ERROR", message=str(exc),
                          data={"retryable": True})  # retryable flag for subscribers
                )
                return StepResult(self.name, StepStatus.FAILED, attempt, error=str(exc),
                                  started=started, finished=time.time(), retryable=True)
            except Exception as exc:  # noqa: BLE001 — NonRetryableError or unexpected; fail fast
                await ctx.bus.publish(
                    Event(EventType.STEP_FAILED, ctx.run_id, stage=stage, step=self.name,
                          attempt=attempt, level="ERROR", message=str(exc),
                          data={"retryable": False})  # retryable flag for subscribers
                )
                return StepResult(self.name, StepStatus.FAILED, attempt, error=str(exc),
                                  started=started, finished=time.time(), retryable=False)
            else:
                if step_ctx._warnings:
                    await ctx.bus.publish(
                        Event(EventType.STEP_WARNING, ctx.run_id, stage=stage, step=self.name,
                              attempt=attempt, message="; ".join(step_ctx._warnings),
                              data={"escalations": [  # structured items for subscribers
                                  {"kind": "warning", "message": e.message, "items": e.items}
                                  for e in step_ctx._escalations
                              ]})
                    )
                    return StepResult(
                        self.name, StepStatus.SUCCEEDED_WITH_WARNING, attempt,
                        started=started, finished=time.time(),
                        warnings=list(step_ctx._warnings),
                    )
                await ctx.bus.publish(
                    Event(EventType.STEP_SUCCEEDED, ctx.run_id, stage=stage, step=self.name,
                          attempt=attempt)
                )
                return StepResult(self.name, StepStatus.SUCCEEDED, attempt,
                                  started=started, finished=time.time())
