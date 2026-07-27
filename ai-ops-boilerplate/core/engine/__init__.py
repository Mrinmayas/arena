"""Lightweight, UI-agnostic orchestration engine (opt-in) for the AI-Ops boilerplate.

The engine is a self-contained, stdlib-only framework for composing an automation as
an ``Automation → Stage → Step`` hierarchy and running it with structured observability.
Using it is optional: a simple ``build_report``-style automation needs only
``core.audit``; reach for the engine when a run has parallel steps, retries, resume, or
multiple stages worth recording.

The pieces:
  - ``Event`` / ``EventType`` / ``EventBus`` (events): the only coupling between a
    running automation and anything observing it.
  - ``RunContext`` (context): the per-run shared state (secrets, workspace, bus, memory).
  - ``StepContext`` (step_context): per-step context, fresh per invocation, parallel-safe.
  - ``Step`` / ``StepResult`` / ``StepStatus`` (step): one retryable unit of work.
  - ``Stage`` / ``StageResult`` (stage): a parallel group of steps.
  - ``Automation`` / ``AutomationResult`` (automation): a sequential list of stages.
  - ``WorkingMemory`` (memory): persisted per-run key/value + file store.
  - ``RetryableError`` / ``NonRetryableError`` / ``Escalation`` / ``StageStatus`` /
    ``RunStatus`` (outcome): the outcome model.
  - ``ArgSpec`` / ``validate_arguments`` (args): the optional argument schema.
  - ``run_automation`` / ``resume_automation`` / ``mint_run_id`` (runner): the
    composition root that wires subscribers and executes a ready ``Automation``.

The core modules never import a UI toolkit, a storage backend, or an audit sink. Wiring
an actual run (subscribers, run id, workspace) lives in ``runner`` — the composition
root — so the core stays pure. Supporting packages: ``runstore`` (the structured
``runs/<run_id>/`` store) and ``subscribers`` (the event sinks, including the
``core.audit`` bridge and the optional OpenTelemetry export).
"""

from __future__ import annotations

from .args import ArgSpec, ArgumentValidationError, validate_arguments
from .automation import Automation, AutomationResult
from .context import RunContext
from .errors import EngineError, FlowDefinitionError
from .events import Event, EventBus, EventType, Subscriber
from .memory import WorkingMemory
from .outcome import (
    Escalation,
    NonRetryableError,
    RetryableError,
    RunStatus,
    StageStatus,
)
from .runner import mint_run_id, resume_automation, run_automation
from .stage import Stage, StageResult
from .step import Step, StepFn, StepResult, StepStatus
from .step_context import StepContext

__all__ = [
    # Hierarchy
    "Automation",
    "AutomationResult",
    "Stage",
    "StageResult",
    "Step",
    "StepFn",
    "StepResult",
    "StepStatus",
    "StepContext",
    "RunContext",
    # Argument schema
    "ArgSpec",
    "ArgumentValidationError",
    "validate_arguments",
    # Working memory
    "WorkingMemory",
    # Outcome model
    "Escalation",
    "NonRetryableError",
    "RetryableError",
    "RunStatus",
    "StageStatus",
    # Events
    "Event",
    "EventBus",
    "EventType",
    "Subscriber",
    # Errors
    "EngineError",
    "FlowDefinitionError",
    # Composition root
    "run_automation",
    "resume_automation",
    "mint_run_id",
]
