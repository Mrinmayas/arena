"""Outcome model: error types, status enums, and the Escalation record.

``RetryableError`` and ``NonRetryableError`` are raised by step functions to signal
the orchestrator how to treat a failure — retry transient problems, halt immediately
on permanent ones.

``StageStatus`` and ``RunStatus`` extend the ``StepStatus`` vocabulary to cover the
stage and run levels, including the ``SUCCEEDED_WITH_WARNING`` state that flows upward
through the hierarchy.

``Escalation`` is the record produced whenever a step calls ``warn()`` or fails; it
carries enough context for a human (or a future delivery subscriber) to act on it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RetryableError(Exception):
    """Transient step failure — safe to retry up to the step's configured limit."""


class NonRetryableError(Exception):
    """Permanent step failure — retrying cannot help; fail immediately."""


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_WARNING = "succeeded_with_warning"
    FAILED = "failed"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_WARNING = "succeeded_with_warning"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Escalation:
    """A record raised when a step warns or fails.

    ``kind`` is ``"warning"`` for non-blocking issues (step still succeeded) and
    ``"error"`` for step failures. ``items`` carries any structured data the step
    wanted to surface (e.g. the list of unreconciled records).
    """

    kind: str
    stage: str
    step: str
    message: str
    items: list[Any] = field(default_factory=list)
    ts: float = field(default_factory=time.time)
