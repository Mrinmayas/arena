"""OTel provider factory — reads env vars and wires up TracerProvider + LoggerProvider.

Optional: imports the ``opentelemetry`` SDK at module load, so it is only imported
behind a guard (see ``runner._attach_otel``).

Environment variables (all optional):

  OTEL_ENABLED                  "false" disables OTel entirely (default: enabled).
  OTEL_EXPORTER_OTLP_ENDPOINT   When set, exports via OTLP HTTP to that endpoint
                                 (e.g. "http://localhost:4318" for a local collector).
                                 When absent, spans and logs are written to local
                                 .jsonl files in the run directory.
  OTEL_SERVICE_NAME             Overrides the service.name resource attribute
                                 (default: automation name).

Providers are created fresh per run — never registered globally — so concurrent
runs in the same process (CLI loop, GUI) cannot leak span context into each other.
"""

from __future__ import annotations

import os
from pathlib import Path

from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .otel_exporters import FileLogExporter, FileSpanExporter


def build_otel_providers(
    run_id: str,
    automation: str,
    *,
    run_dir: Path,
) -> tuple[TracerProvider, LoggerProvider] | None:
    """Return wired (TracerProvider, LoggerProvider), or None if OTel is disabled."""
    if os.getenv("OTEL_ENABLED", "true").lower() == "false":
        return None

    service_name = os.getenv("OTEL_SERVICE_NAME", automation)
    resource = Resource.create({"service.name": service_name, "run.id": run_id})

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        span_exporter = OTLPSpanExporter()      # reads OTEL_EXPORTER_OTLP_ENDPOINT automatically
        log_exporter = OTLPLogExporter()
    else:
        span_exporter = FileSpanExporter(run_dir / "otel_traces.jsonl")
        log_exporter = FileLogExporter(run_dir / "otel_logs.jsonl")

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))

    return tracer_provider, logger_provider
