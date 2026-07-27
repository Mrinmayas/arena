"""Event subscriber that funnels run events into the standard ``logging`` module.

Attached to every run so there is always a textual trail regardless of which UI (if
any) is watching. Maps event types to log levels and lets the host application's
logging configuration decide where the lines actually go.
"""

from __future__ import annotations

import logging

from ..events import Event, EventType

logger = logging.getLogger("aiops.run")

_LEVEL_BY_TYPE = {
    EventType.RUN_FAILED: logging.ERROR,
    EventType.STEP_FAILED: logging.ERROR,
    EventType.STEP_RETRYING: logging.WARNING,
}


def logging_subscriber(event: Event) -> None:
    level = _LEVEL_BY_TYPE.get(event.type, logging.INFO)
    if event.type is EventType.LOG and event.level:
        level = logging.getLevelName(event.level)
        if not isinstance(level, int):
            level = logging.INFO
    parts = [event.run_id, event.type.value]
    if event.step:
        parts.append(f"step={event.step}")
    if event.attempt:
        parts.append(f"attempt={event.attempt}")
    if event.message:
        parts.append(f"- {event.message}")
    logger.log(level, " ".join(parts))
