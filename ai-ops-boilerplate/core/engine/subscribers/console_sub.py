"""Event subscriber that prints human-readable progress to stdout.

Intended for headless/batch invocation from a terminal or scheduler log, where a
plain step-by-step trace is more useful than the structured ``logging`` output.
Attach it explicitly (it is not on by default) when you want console progress.
"""

from __future__ import annotations

from ..events import Event, EventType

_GLYPH = {
    EventType.RUN_STARTED: "▶",
    EventType.RUN_SUCCEEDED: "✓",
    EventType.RUN_FAILED: "✗",
    EventType.STEP_STARTED: "·",
    EventType.STEP_RETRYING: "↻",
    EventType.STEP_SUCCEEDED: "✓",
    EventType.STEP_FAILED: "✗",
    EventType.LOG: " ",
}


def console_subscriber(event: Event) -> None:
    glyph = _GLYPH.get(event.type, " ")
    label = event.step or event.type.value
    suffix = f" — {event.message}" if event.message else ""
    print(f"  {glyph} {label}{suffix}")
