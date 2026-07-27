"""OpenTelemetry EventBus subscriber — translates run events to OTel spans and logs.

Optional: this module imports the ``opentelemetry`` SDK at module load, so it is only
imported behind a guard (see ``runner._attach_otel``). When the ``otel`` extra is not
installed the engine never imports it and runs on the run-store + logging subscribers.

One instance per run.  Span lifecycle mirrors the run/stage/step hierarchy:

  RUN_STARTED   → root span
  STAGE_STARTED → child span of run
  STEP_STARTED  → child span of stage (parallel steps are siblings under the same stage)
  terminal      → set status, end span, flush on run terminal

Span parenting uses explicit ``context=set_span_in_context(parent)`` rather than
OTel's ``contextvars``-based automatic propagation.  ``asyncio.gather`` forks task
contexts, making automatic propagation unreliable for parallel steps; storing spans
in instance dicts and passing contexts explicitly sidesteps the issue entirely.

LOG events and step warnings are emitted as OTel log records correlated to the
innermost active span (step > stage > run), so they appear in trace timelines in
Jaeger / Grafana Tempo without any extra correlation work.
"""

from __future__ import annotations

import logging

from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import INVALID_SPAN, Span, StatusCode, set_span_in_context

from ..events import Event, EventType

_LEVEL_TO_SEVERITY: dict[str, SeverityNumber] = {
    "DEBUG":    SeverityNumber.DEBUG,
    "INFO":     SeverityNumber.INFO,
    "WARNING":  SeverityNumber.WARN,
    "WARN":     SeverityNumber.WARN,
    "ERROR":    SeverityNumber.ERROR,
    "CRITICAL": SeverityNumber.FATAL,
}


class OtelSubscriber:
    """EventBus subscriber that maps run/stage/step events to OTel spans and logs.

    ``__call__`` is synchronous — all OTel SDK operations are synchronous, and the
    EventBus only awaits subscribers that return coroutines.
    """

    def __init__(
        self,
        run_id: str,
        automation: str,
        *,
        tracer_provider: TracerProvider,
        logger_provider: LoggerProvider,
        triggered_by: str = "cli",
    ) -> None:
        self._run_id = run_id
        self._automation = automation
        self._triggered_by = triggered_by
        self._tracer = tracer_provider.get_tracer("aiops.engine")
        self._logger = logger_provider.get_logger("aiops.run")
        self._tracer_provider = tracer_provider
        self._logger_provider = logger_provider

        self._run_span: Span = INVALID_SPAN
        self._stage_spans: dict[str, Span] = {}
        self._step_spans: dict[tuple[str, str], Span] = {}

    # ------------------------------------------------------------------
    # EventBus subscriber entry point
    # ------------------------------------------------------------------

    def __call__(self, event: Event) -> None:
        t = event.type
        try:
            if t is EventType.RUN_STARTED:
                self._on_run_started(event)
            elif t is EventType.STAGE_STARTED:
                self._on_stage_started(event)
            elif t is EventType.STEP_STARTED:
                self._on_step_started(event)
            elif t is EventType.STEP_RETRYING:
                self._on_step_retrying(event)
            elif t is EventType.STEP_SUCCEEDED:
                self._on_step_terminal(event, StatusCode.OK)
            elif t is EventType.STEP_WARNING:
                self._on_step_warning(event)
            elif t is EventType.STEP_FAILED:
                self._on_step_terminal(event, StatusCode.ERROR)
            elif t is EventType.STAGE_SUCCEEDED:
                self._on_stage_terminal(event, StatusCode.OK)
            elif t is EventType.STAGE_FAILED:
                self._on_stage_terminal(event, StatusCode.ERROR)
            elif t is EventType.RUN_SUCCEEDED:
                self._on_run_terminal(event, StatusCode.OK)
            elif t is EventType.RUN_FAILED:
                self._on_run_terminal(event, StatusCode.ERROR)
            elif t is EventType.LOG:
                self._on_log(event)
        except Exception:  # noqa: BLE001 — never let OTel break the run
            logging.getLogger("aiops.otel").debug("OtelSubscriber error", exc_info=True)

    # ------------------------------------------------------------------
    # Span lifecycle
    # ------------------------------------------------------------------

    def _on_run_started(self, event: Event) -> None:
        span = self._tracer.start_span(
            self._automation,
            context=set_span_in_context(INVALID_SPAN),  # explicit root — no ambient context
        )
        span.set_attribute("run.id", self._run_id)
        span.set_attribute("automation.name", self._automation)
        span.set_attribute("triggered_by", self._triggered_by)
        self._run_span = span

    def _on_stage_started(self, event: Event) -> None:
        if not event.stage:
            return
        ctx = set_span_in_context(self._run_span)
        span = self._tracer.start_span(event.stage, context=ctx)
        span.set_attribute("stage.name", event.stage)
        self._stage_spans[event.stage] = span

    def _on_step_started(self, event: Event) -> None:
        if not event.step:
            return
        stage = event.stage or ""
        parent = self._stage_spans.get(stage, self._run_span)
        ctx = set_span_in_context(parent)
        span = self._tracer.start_span(event.step, context=ctx)
        span.set_attribute("step.name", event.step)
        span.set_attribute("step.stage", stage)
        if event.attempt is not None:
            span.set_attribute("step.attempt", event.attempt)
        self._step_spans[(stage, event.step)] = span

    def _on_step_retrying(self, event: Event) -> None:
        span = self._step_spans.get((event.stage or "", event.step or ""))
        if span:
            span.add_event("retrying", {
                "attempt": event.attempt or 0,
                "reason": event.message or "",
            })

    def _on_step_terminal(self, event: Event, status_code: StatusCode) -> None:
        if not event.step:
            return
        key = (event.stage or "", event.step)
        span = self._step_spans.pop(key, None)
        if span is None:
            return
        span.set_attribute("step.attempts", event.attempt if event.attempt is not None else 1)
        if status_code is StatusCode.ERROR:
            span.set_status(StatusCode.ERROR, event.message or "")
            retryable = (event.data or {}).get("retryable")
            if retryable is not None:
                span.set_attribute("step.retryable", bool(retryable))
        else:
            span.set_status(StatusCode.OK)
        span.end()

    def _on_step_warning(self, event: Event) -> None:
        if not event.step:
            return
        key = (event.stage or "", event.step)
        span = self._step_spans.pop(key, None)
        if span:
            span.add_event("warning", {"message": event.message or ""})
            span.set_attribute("step.attempts", event.attempt if event.attempt is not None else 1)
            span.set_status(StatusCode.OK)
            span.end()
        # Also emit a WARN log record correlated to the step
        self._emit_log(
            event,
            SeverityNumber.WARN,
            span_ctx=set_span_in_context(
                self._stage_spans.get(event.stage or "", self._run_span)
            ),
        )

    def _on_stage_terminal(self, event: Event, status_code: StatusCode) -> None:
        if not event.stage:
            return
        span = self._stage_spans.pop(event.stage, None)
        if span is None:
            return
        span.set_status(status_code)
        span.end()

    def _on_run_terminal(self, event: Event, status_code: StatusCode) -> None:
        if status_code is StatusCode.ERROR:
            self._run_span.set_status(StatusCode.ERROR, event.message or "")
        else:
            self._run_span.set_status(StatusCode.OK)
        self._run_span.end()
        # shutdown() flushes all pending spans/logs and terminates the batch processor
        # background threads — prevents thread accumulation across runs in the same process.
        self._tracer_provider.shutdown()
        self._logger_provider.shutdown()

    # ------------------------------------------------------------------
    # Log emission
    # ------------------------------------------------------------------

    def _on_log(self, event: Event) -> None:
        severity = _LEVEL_TO_SEVERITY.get((event.level or "INFO").upper(), SeverityNumber.INFO)
        # Attach to the innermost active span
        stage = event.stage or ""
        step = event.step or ""
        if step and (stage, step) in self._step_spans:
            ctx = set_span_in_context(self._step_spans[(stage, step)])
        elif stage and stage in self._stage_spans:
            ctx = set_span_in_context(self._stage_spans[stage])
        else:
            ctx = set_span_in_context(self._run_span)
        self._emit_log(event, severity, span_ctx=ctx)

    def _emit_log(self, event: Event, severity: SeverityNumber, *, span_ctx) -> None:
        attrs: dict[str, str] = {}
        if event.stage:
            attrs["stage"] = event.stage
        if event.step:
            attrs["step"] = event.step
        self._logger.emit(
            severity_number=severity,
            severity_text=severity.name,
            body=event.message or "",
            attributes=attrs or None,
            context=span_ctx,
        )
