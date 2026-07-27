"""Bridge from the engine's EventBus to ``core.audit`` — the boilerplate's always-on
human-vs-automation trail.

An orchestrated automation should leave the SAME ``audit_logs/<ts>/`` record as a
simple, un-orchestrated one, so a reviewer reads one trail regardless of how the tool
was built. ``AuditSubscriber`` forwards engine events to a ``core.audit.AuditRun``:

  - stage/step successes            → ``audit.automation(..., status="ok")``
  - stage/step warnings             → ``audit.warn(...)``
  - stage/step failures             → ``audit.automation(..., status="error")``
  - WARNING/ERROR-level log lines    → ``audit.warn(...)``  (INFO logs are not mirrored,
                                        to keep the human-facing trail readable)

The engine's own ``runs/<run_id>/`` store remains the richer structured record; the two
coexist by design — this bridge only adds the reviewer-facing sign-off trail.

The ``core.audit`` import is soft: if the boilerplate's ``core.audit`` package is not
importable (e.g. the engine is used standalone), this subscriber degrades to a no-op
and the run-store + logging subscribers still function. In the boilerplate ``core.audit``
is always present, so this is a first-class, wired-by-default subscriber.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..events import Event, EventType

if TYPE_CHECKING:  # pragma: no cover - typing only
    from core.audit import AuditRun

try:  # soft dependency — the engine must work without the boilerplate's core.audit
    from core.audit import AuditRun as _AuditRun
except Exception:  # noqa: BLE001 - any import failure means "audit not available"
    _AuditRun = None  # type: ignore[assignment]


def audit_available() -> bool:
    """True if ``core.audit`` could be imported (so an audit trail can be produced)."""
    return _AuditRun is not None


def _label(event: Event) -> str:
    """A stable step/stage label for the audit ``step`` field."""
    return event.step or event.stage or "run"


class AuditSubscriber:
    """EventBus subscriber that mirrors engine events into a ``core.audit.AuditRun``.

    Pass an existing :class:`~core.audit.AuditRun` (e.g. one the automation spine
    already opened) *or* let the subscriber create its own. When it creates its own —
    or when ``own=True`` — it also finalizes the run on the terminal event, so callers
    that let the subscriber own the ``AuditRun`` need do nothing further.

    ``__call__`` is synchronous; the EventBus only awaits coroutine subscribers.
    """

    def __init__(
        self,
        audit: "AuditRun | None" = None,
        *,
        name: str | None = None,
        audit_root: str = "audit_logs",
        operator: str | None = None,
        redact: bool = False,
        own: bool | None = None,
    ) -> None:
        if audit is None:
            if _AuditRun is None:
                # core.audit unavailable — degrade to a no-op subscriber.
                self._audit = None
                self._own = False
            else:
                self._audit = _AuditRun(
                    name or "automation",
                    audit_root=audit_root,
                    operator=operator,
                    redact=redact,
                )
                self._own = True if own is None else own
        else:
            self._audit = audit
            self._own = False if own is None else own

        self._warned = False
        self._finalized = False

    @property
    def audit(self) -> "AuditRun | None":
        """The underlying AuditRun (None when core.audit is unavailable)."""
        return self._audit

    def __call__(self, event: Event) -> None:
        audit = self._audit
        if audit is None:
            return

        t = event.type
        step = _label(event)
        detail: dict[str, Any] | None = None
        if event.stage and event.step:
            detail = {"stage": event.stage}

        if t is EventType.STAGE_STARTED:
            audit.automation("stage started", step=step, detail=detail)
        elif t is EventType.STAGE_SUCCEEDED:
            audit.automation("stage succeeded", step=step, detail=detail)
        elif t is EventType.STAGE_FAILED:
            audit.automation("stage failed", step=step, status="error", detail=detail)
        elif t is EventType.STEP_STARTED:
            audit.automation("step started", step=step, detail=detail)
        elif t is EventType.STEP_RETRYING:
            self._warned = True
            audit.warn(f"step retrying (attempt {event.attempt}): {event.message or ''}".rstrip(),
                       step=step, detail=detail)
        elif t is EventType.STEP_SUCCEEDED:
            audit.automation("step succeeded", step=step, detail=detail)
        elif t is EventType.STEP_WARNING:
            self._warned = True
            audit.warn(f"step warning: {event.message or ''}".rstrip(), step=step, detail=detail)
        elif t is EventType.STEP_FAILED:
            audit.automation(f"step failed: {event.message or ''}".rstrip(),
                             step=step, status="error", detail=detail)
        elif t is EventType.LOG:
            # Only mirror WARNING/ERROR logs; INFO chatter stays in the run-store trail.
            level = (event.level or "INFO").upper()
            if level in ("WARNING", "WARN", "ERROR", "CRITICAL") and event.message:
                self._warned = self._warned or level in ("WARNING", "WARN")
                status = "error" if level in ("ERROR", "CRITICAL") else "warning"
                if status == "warning":
                    audit.warn(event.message, step=step, detail=detail)
                else:
                    audit.automation(event.message, step=step, status="error", detail=detail)
        elif t is EventType.RUN_SUCCEEDED:
            self._finalize("warning" if self._warned else "ok")
        elif t is EventType.RUN_FAILED:
            if event.message:
                audit.set_outcome(error=event.message)
            self._finalize("failed")

    def close(self, status: str = "ok") -> None:
        """Finalize an owned AuditRun if the terminal event never arrived.

        Safe to call unconditionally: it is a no-op unless this subscriber owns the
        AuditRun and has not already finalized it. ``runner`` calls this in a
        ``finally`` block as a backstop against an unexpected exception that bypasses
        the RUN_SUCCEEDED / RUN_FAILED events.
        """
        self._finalize(status)

    def _finalize(self, status: str) -> None:
        if self._finalized or self._audit is None or not self._own:
            return
        self._finalized = True
        self._audit.finalize(status)
