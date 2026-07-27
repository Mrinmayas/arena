"""Run events and the bus that carries them.

Events are the *only* coupling between executing automations and anything that
watches them. An ``Automation`` and its ``Step`` s publish events to an ``EventBus``;
subscribers (a structured logger, the run-store writer, the audit bridge, a live GUI,
a future web dashboard) consume them. The engine never imports a UI library or a
storage backend — it only knows how to publish ``Event`` s.

A subscriber may be a plain function or a coroutine function. The bus tolerates a
subscriber that is slow or raises: its failure is swallowed so one bad subscriber
can never break the run or starve the others.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    RUN_SUCCEEDED = "run_succeeded"
    RUN_FAILED = "run_failed"
    STAGE_STARTED = "stage_started"
    STAGE_SUCCEEDED = "stage_succeeded"
    STAGE_FAILED = "stage_failed"
    STEP_STARTED = "step_started"
    STEP_RETRYING = "step_retrying"
    STEP_SUCCEEDED = "step_succeeded"
    STEP_FAILED = "step_failed"
    STEP_WARNING = "step_warning"
    ESCALATION = "escalation"
    LOG = "log"


@dataclass(frozen=True, slots=True)
class Event:
    """A single thing that happened during a run.

    ``type`` and ``run_id`` are always set. ``stage``/``step`` are set for stage- and
    step-scoped events; ``attempt`` for retry/failure; ``level``/``message`` for logs
    and failures; ``data`` carries anything extra a subscriber may want.
    """

    type: EventType
    run_id: str
    ts: float = field(default_factory=time.time)
    stage: str | None = None
    step: str | None = None
    attempt: int | None = None
    level: str | None = None
    message: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


# A subscriber receives every event. Returning a coroutine is allowed; the bus awaits it.
Subscriber = Callable[[Event], Awaitable[None] | None]


class EventBus:
    """In-process async publish/subscribe over ``Event`` s.

    This is the swap point for "desktop now, web later": the same ``publish``
    contract feeds a Tk queue today and an ``asyncio.Queue`` per SSE client later,
    with no change to automation code.
    """

    def __init__(self) -> None:
        self._subs: list[Subscriber] = []

    def subscribe(self, sub: Subscriber) -> None:
        self._subs.append(sub)

    async def publish(self, event: Event) -> None:
        for sub in self._subs:
            try:
                result = sub(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001  # nosec B110 — a subscriber must never break the run
                pass
