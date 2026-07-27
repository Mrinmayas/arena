"""Local-file OTel exporters — spans and log records written as JSON lines.

Optional: imports the ``opentelemetry`` SDK at module load, so it is only imported
behind a guard (via ``otel_config``).

Used by default when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is not set.  Each finished span
or log record is appended as a single JSON object to a ``.jsonl`` file in the run
directory, making the data immediately inspectable without any backend.

Both classes implement the standard ``SpanExporter`` / ``LogExporter`` interfaces,
so they are drop-in replaceable with ``OTLPSpanExporter`` / ``OTLPLogExporter`` simply
by swapping the exporter in ``otel_config.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from opentelemetry.sdk._logs.export import LogExporter, LogRecordExportResult
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

if TYPE_CHECKING:
    from opentelemetry.sdk._logs import ReadableLogRecord
    from opentelemetry.sdk.trace import ReadableSpan


def _write_jsonl(path: Path, items: Sequence[Any]) -> bool:
    """Append each item's ``to_json()`` as a line. Returns True on success."""
    try:
        with open(path, "a", encoding="utf-8") as f:
            for item in items:
                f.write(item.to_json(indent=None) + "\n")
        return True
    except OSError:
        return False


class FileSpanExporter(SpanExporter):
    """Appends finished spans as JSON lines to ``path``."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return SpanExportResult.SUCCESS if _write_jsonl(self._path, spans) else SpanExportResult.FAILURE

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


class FileLogExporter(LogExporter):
    """Appends finished log records as JSON lines to ``path``."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def export(self, batch: Sequence[ReadableLogRecord]) -> LogRecordExportResult:
        return LogRecordExportResult.SUCCESS if _write_jsonl(self._path, batch) else LogRecordExportResult.FAILURE

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
