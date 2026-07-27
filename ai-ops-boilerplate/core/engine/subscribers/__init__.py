"""Event subscribers: the sinks that turn run events into something useful.

Subscribers are the swappable presentation/persistence layer. Each is a callable
``(Event) -> None`` (or an awaitable) that can be attached to a run's ``EventBus``.

  - ``logging_subscriber``: structured ``logging`` output (always attached).
  - ``console_subscriber``: human-readable stdout progress (opt-in, for batch).
  - ``RunStoreSubscriber``: persists per-run JSON + appends the CSV ledger.
  - ``AuditSubscriber``: bridges events into the boilerplate's ``core.audit`` trail
    (wired by default in ``runner``; no-op if ``core.audit`` is unavailable).
  - ``OtelSubscriber``: emits OTel spans and logs (opt-in ``otel`` extra). Import it
    from ``.otel_sub`` directly — it is deliberately NOT re-exported here so importing
    this package never pulls in the ``opentelemetry`` SDK.

A live GUI or a future web dashboard is just another subscriber added here.
"""

from __future__ import annotations

from .audit_sub import AuditSubscriber, audit_available
from .console_sub import console_subscriber
from .logging_sub import logging_subscriber
from .runstore_sub import RunStoreSubscriber

__all__ = [
    "AuditSubscriber",
    "audit_available",
    "console_subscriber",
    "logging_subscriber",
    "RunStoreSubscriber",
]
