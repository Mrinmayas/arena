"""The per-run context handed to every step.

``RunContext`` is the single object a step function receives. It carries:
  - identity (``run_id``, ``automation``) and the ``workspace`` directory where the
    run may write downloads, transformed files, screenshots, etc.;
  - an optional ``secrets`` provider — any object a step needs for credential lookup
    (e.g. ``core.secretstore.SecretStore``). The engine treats it opaquely and never
    imports a concrete secret store, so it stays stdlib-only and reusable; the caller
    wires one in via ``run_automation(..., secrets=...)`` when needed;
  - the ``EventBus`` so steps can ``await ctx.log(...)``;
  - the resolved automation ``config`` and a ``headless`` flag — the *same* automation
    runs headless for batch or with a visible browser + live view for a human;
  - ``WorkingMemory`` (or a small in-memory bag) so one step can pass a result (e.g. a
    downloaded file path) to a later step without globals.

The context deliberately holds no portal/browser handle: portals are opened by steps
and own their own lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .events import Event, EventBus, EventType

if TYPE_CHECKING:
    from .memory import WorkingMemory


@dataclass
class RunContext:
    run_id: str
    automation: str
    workspace: Path
    bus: EventBus
    # Opaque credential provider (e.g. core.secretstore.SecretStore); None if unused.
    secrets: Any = None
    config: Any = None
    headless: bool = True
    sharepoint: Any = None
    # Persisted working memory (None falls back to the in-memory _bag).
    memory: "WorkingMemory | None" = field(default=None, repr=False)
    arguments: dict[str, Any] = field(default_factory=dict, repr=False)
    debug: bool = False
    # In-memory bag used only when no WorkingMemory is attached.
    _bag: dict[str, Any] = field(default_factory=dict, repr=False)

    def put(self, key: str, value: Any) -> None:
        """Stash a value for a later step to read with :meth:`get`."""
        if self.memory is not None:
            self.memory.put_value(key, value)
        else:
            self._bag[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Read a value stashed by an earlier step's :meth:`put`."""
        if self.memory is not None:
            return self.memory.get_value(key, default)
        return self._bag.get(key, default)

    async def log(self, message: str, level: str = "INFO") -> None:
        """Emit a run-level log line (not bound to any step or stage).

        Step-level logs with stage/step context go through ``StepContext.log``.
        """
        await self.bus.publish(
            Event(EventType.LOG, self.run_id, level=level, message=message)
        )
