"""Per-step execution context — parallel-safe, created fresh each invocation.

``StepContext`` is what step functions receive instead of ``RunContext``. A fresh
instance is created by ``Step.execute`` for every attempt, so two steps in the same
stage running concurrently each get their own context and cannot corrupt one another's
state (no shared mutable ``_current_step`` or similar field).

The context exposes:
- Run identity and shared resources forwarded from ``RunContext``.
- ``log`` / ``warn`` bound to this step's stage and name so events carry full context.
- ``warn()`` records a non-blocking warning; after the function returns, ``Step.execute``
  inspects ``_warnings`` and promotes the result to ``SUCCEEDED_WITH_WARNING``.
- ``put`` / ``get`` / ``memory`` for working memory: backed by ``WorkingMemory`` when
  attached, otherwise the in-memory bag on ``RunContext``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .events import Event, EventType
from .outcome import Escalation

if TYPE_CHECKING:
    from .context import RunContext
    from .memory import WorkingMemory


@dataclass
class StepContext:
    _run_ctx: "RunContext"
    stage: str
    step: str
    _warnings: list[str] = field(default_factory=list, repr=False)
    _escalations: list[Escalation] = field(default_factory=list, repr=False)

    # --- forwarded run-level properties ----------------------------------------

    @property
    def run_id(self) -> str:
        return self._run_ctx.run_id

    @property
    def automation(self) -> str:
        return self._run_ctx.automation

    @property
    def workspace(self):
        return self._run_ctx.workspace

    @property
    def secrets(self):
        return self._run_ctx.secrets

    @property
    def bus(self):
        return self._run_ctx.bus

    @property
    def headless(self) -> bool:
        return self._run_ctx.headless

    @property
    def config(self):
        return self._run_ctx.config

    @property
    def sharepoint(self):
        return self._run_ctx.sharepoint

    # --- step-level operations -------------------------------------------------

    async def log(self, message: str, level: str = "INFO") -> None:
        """Emit a log line tagged with this step's stage and name."""
        await self.bus.publish(
            Event(EventType.LOG, self.run_id, stage=self.stage, step=self.step,
                  level=level, message=message)
        )

    def warn(self, message: str, items: list[Any] | None = None) -> None:
        """Record a non-blocking warning; step ends SUCCEEDED_WITH_WARNING."""
        self._warnings.append(message)
        self._escalations.append(
            Escalation("warning", self.stage, self.step, message, items or [], time.time())
        )

    # --- working memory ---------------------------------------------------------

    @property
    def memory(self) -> "WorkingMemory | None":
        """Direct access to the run's WorkingMemory (None when not attached)."""
        return self._run_ctx.memory

    def put(self, key: str, value: Any) -> None:
        self._run_ctx.put(key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return self._run_ctx.get(key, default)
