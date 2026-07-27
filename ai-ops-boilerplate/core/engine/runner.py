"""Composition root: turn a ready ``Automation`` into an executed, recorded run.

This is the one place that wires the otherwise-decoupled pieces together — it picks
the subscribers, mints the run id, creates the workspace + working memory, builds the
``RunContext``, and runs the automation. Keeping it out of the core engine modules is
deliberate: the engine never imports subscribers, the run store, an audit backend, or a
UI; only this module does.

There is no auto-discovery: ``run_automation`` takes a fully-wired ``Automation`` object
(explicit wiring, no registry). Every run gets, in order:

  1. ``logging_subscriber``          — always-on textual trail;
  2. ``RunStoreSubscriber``          — the rich structured ``runs/<run_id>/`` store;
  3. ``AuditSubscriber``             — the boilerplate's human-vs-automation
                                        ``audit_logs/<ts>/`` trail (via ``core.audit``);
  4. ``OtelSubscriber``              — only if the optional ``otel`` extra is installed
                                        and OTel is enabled;
  5. any caller-supplied ``extra_subscribers`` — presentation (live GUI, SSE pump…).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .automation import Automation, AutomationResult
from .args import ArgSpec, validate_arguments
from .context import RunContext
from .events import EventBus, Subscriber
from .memory import WorkingMemory
from .runstore.store import DEFAULT_RUNS_DIR, RunStore
from .subscribers import AuditSubscriber, RunStoreSubscriber, logging_subscriber

if TYPE_CHECKING:  # pragma: no cover - typing only
    from core.audit import AuditRun


def _attach_otel(bus: EventBus, run_id: str, name: str, store: RunStore, triggered_by: str) -> None:
    """Wire an ``OtelSubscriber`` onto the bus if the optional ``otel`` extra is present.

    The ``opentelemetry`` SDK is imported lazily *inside* this function so the engine
    imports and runs cleanly when the extra is not installed. ImportError here simply
    means OTel is not available — the run continues on the other subscribers.
    """
    try:
        from .subscribers.otel_config import build_otel_providers
        from .subscribers.otel_sub import OtelSubscriber
    except ImportError:
        return  # opentelemetry not installed — OTel is an opt-in extra

    providers = build_otel_providers(run_id, name, run_dir=store.run_dir(run_id))
    if providers is None:
        return  # OTel present but disabled via OTEL_ENABLED=false
    bus.subscribe(OtelSubscriber(
        run_id, name,
        tracer_provider=providers[0],
        logger_provider=providers[1],
        triggered_by=triggered_by,
    ))


def _attach_audit(
    bus: EventBus,
    name: str,
    audit: "AuditRun | None",
    *,
    audit_root: str,
    operator: str | None,
) -> AuditSubscriber:
    """Wire an ``AuditSubscriber`` so every run leaves a ``core.audit`` trail.

    If *audit* is provided, the subscriber mirrors into it and does not finalize it
    (the caller owns its lifecycle). Otherwise the subscriber creates and finalizes its
    own ``AuditRun``. If ``core.audit`` is unavailable the subscriber is a no-op.
    """
    sub = AuditSubscriber(audit, name=name, audit_root=audit_root, operator=operator)
    bus.subscribe(sub)
    return sub


def mint_run_id(automation: str) -> str:
    """A sortable, unique-per-run id: ``<automation>_<UTC timestamp>_<rand>``."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{automation}_{stamp}_{uuid.uuid4().hex[:6]}"


async def run_automation(
    automation: Automation,
    *,
    config: object = None,
    headless: bool = True,
    extra_subscribers: Sequence[Subscriber] = (),
    runs_dir: Path = DEFAULT_RUNS_DIR,
    triggered_by: str = "cli",
    secrets: Any = None,
    debug: bool = False,
    arguments: dict[str, Any] | None = None,
    input_files: dict[str, Path] | None = None,
    arg_schema: list[ArgSpec] | None = None,
    audit: "AuditRun | None" = None,
    audit_root: str = "audit_logs",
    operator: str | None = None,
) -> AutomationResult:
    """Run a fully-wired ``Automation`` and record it.

    Validates arguments against *arg_schema* (if given) before creating any run
    artifacts, seeds them into working memory, attaches the standard subscribers, then
    executes. ``secrets`` is any credential provider a step may need (the engine treats
    it opaquely); pass ``core.secretstore.get_default_store()`` from the caller when
    required. ``audit`` lets a caller supply its own ``core.audit.AuditRun``; when None,
    one is created and finalized automatically.
    """
    # Validate before creating any run artifacts.
    if arg_schema is not None:
        validate_arguments(arg_schema, arguments or {}, input_files or {})

    run_id = mint_run_id(automation.name)
    store = RunStore(runs_dir)
    store.reconcile()
    store.ensure_run_dir(run_id)
    memory = WorkingMemory(store.run_dir(run_id) / "memory")  # creates memory/files/

    # Seed arguments into working memory before stage 1.
    for name, value in (arguments or {}).items():
        memory.put_value(name, value)
    for name, path in (input_files or {}).items():
        memory.put_file(name, Path(path))

    bus = EventBus()
    bus.subscribe(logging_subscriber)
    bus.subscribe(
        RunStoreSubscriber(
            run_id,
            automation.name,
            runs_dir=runs_dir,
            triggered_by=triggered_by,
            memory=memory,
            debug=debug,
            arguments={**(arguments or {}), **{k: str(v) for k, v in (input_files or {}).items()}},
        )
    )
    audit_sub = _attach_audit(bus, automation.name, audit, audit_root=audit_root, operator=operator)
    _attach_otel(bus, run_id, automation.name, store, triggered_by)
    for sub in extra_subscribers:
        bus.subscribe(sub)

    ctx = RunContext(
        run_id=run_id,
        automation=automation.name,
        workspace=store.workspace(run_id),
        bus=bus,
        secrets=secrets,
        config=config,
        headless=headless,
        memory=memory,
        arguments=arguments or {},
        debug=debug,
    )
    try:
        return await automation.run(ctx, resume_state=None)
    except BaseException:
        # Backstop: finalize an owned audit trail if the terminal event never fired.
        audit_sub.close("failed")
        raise


async def resume_automation(
    automation: Automation,
    run_id: str,
    *,
    config: object = None,
    headless: bool = True,
    extra_subscribers: Sequence[Subscriber] = (),
    runs_dir: Path = DEFAULT_RUNS_DIR,
    triggered_by: str = "cli",
    secrets: Any = None,
    debug: bool = False,
    audit: "AuditRun | None" = None,
    audit_root: str = "audit_logs",
    operator: str | None = None,
) -> AutomationResult:
    """Resume a previously failed/incomplete run from its failed step.

    Reopens ``runs/<run_id>/``, reloads the persisted ``WorkingMemory`` (so prior state
    is reused, not re-seeded) and ``state.json`` (so already-succeeded stages/steps are
    skipped), then continues the automation onward.

    The run keeps its original ``run_id``; ``run.json`` is rewritten as the audit source
    of truth, and a fresh ledger row is appended for the resumed completion. Arguments
    are recovered from the prior ``run.json`` for the record — they already live in
    working memory, so no re-seeding occurs.
    """
    store = RunStore(runs_dir)
    if not store.run_dir(run_id).exists():
        raise FileNotFoundError(f"No run directory for {run_id!r} under {runs_dir}")

    store.reconcile()
    state = store.read_state(run_id)

    # Recover the original arguments for the record (already seeded in working memory).
    arguments: dict[str, Any] = {}
    run_json = store.run_dir(run_id) / "run.json"
    if run_json.exists():
        try:
            arguments = json.loads(run_json.read_text(encoding="utf-8")).get("arguments", {}) or {}
        except (json.JSONDecodeError, OSError):
            arguments = {}

    memory = WorkingMemory(store.run_dir(run_id) / "memory")  # reloads manifest from disk

    bus = EventBus()
    bus.subscribe(logging_subscriber)
    bus.subscribe(
        RunStoreSubscriber(
            run_id,
            automation.name,
            runs_dir=runs_dir,
            triggered_by=triggered_by,
            memory=memory,
            debug=debug,
            arguments=arguments,
            resume_state=state,
        )
    )
    audit_sub = _attach_audit(bus, automation.name, audit, audit_root=audit_root, operator=operator)
    _attach_otel(bus, run_id, automation.name, store, triggered_by)
    for sub in extra_subscribers:
        bus.subscribe(sub)

    ctx = RunContext(
        run_id=run_id,
        automation=automation.name,
        workspace=store.workspace(run_id),
        bus=bus,
        secrets=secrets,
        config=config,
        headless=headless,
        memory=memory,
        arguments=arguments,
        debug=debug,
    )
    try:
        return await automation.run(ctx, resume_state=state)
    except BaseException:
        audit_sub.close("failed")
        raise
