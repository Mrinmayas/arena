"""Engine error types.

Kept tiny on purpose: step failures are carried as ``StepResult.error`` strings
rather than raised, so the only thing the engine itself raises is a misconfigured
automation (caught at build time, not during a run).
"""

from __future__ import annotations


class EngineError(Exception):
    """Base error for orchestration-engine problems."""


class FlowDefinitionError(EngineError):
    """Raised when an automation is built incorrectly (e.g. duplicate step names)."""
