"""Always-on local observability for automations built from the AI-Ops boilerplate.

Every run writes a timestamped folder under ``audit_logs/``::

    audit_logs/2026-07-26_23-44-01/
        audit.log          human-readable, one line per event
        events.jsonl       structured, append-only; EVERY event carries `actor`
        run_summary.json   end-of-run: what the AUTOMATION did vs what a HUMAN did/approved

`actor` ("automation" | "human") is a first-class field on every event, so a reviewer
can tell which figures the tool produced and which a person entered or approved
(four-eyes / preparer-reviewer sign-off). Stdlib only — no third-party dependencies.
OpenTelemetry export is an optional add-on (extra ``otel``), never required here.
"""
from __future__ import annotations

import getpass
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# Keys whose values are masked when a run is started with redact=True.
_MONEY_HINTS = ("amount", "value", "total", "balance", "tax", "net", "gross",
                "price", "debit", "credit", "sum")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _redact_detail(detail: dict | None, enabled: bool) -> dict | None:
    if not detail or not enabled:
        return detail
    return {
        k: ("[REDACTED]" if any(h in k.lower() for h in _MONEY_HINTS) else v)
        for k, v in detail.items()
    }


class AuditRun:
    """Records a single automation run with per-event human/automation attribution."""

    def __init__(self, name: str, *, audit_root: str | Path = "audit_logs",
                 operator: str | None = None, redact: bool = False) -> None:
        self.name = name
        self.operator = operator or getpass.getuser()
        self.redact = redact
        self.started_at = _utc_now()
        self.outcome: dict[str, Any] = {}
        self._events: list[dict[str, Any]] = []

        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.dir = Path(audit_root) / stamp
        self.dir.mkdir(parents=True, exist_ok=True)
        self._events_path = self.dir / "events.jsonl"

        self._logger = logging.getLogger(f"audit.{name}.{id(self)}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        self._handler = logging.FileHandler(self.dir / "audit.log", encoding="utf-8")
        self._handler.setFormatter(
            logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
        self._logger.addHandler(self._handler)

        # Launching a run is, by definition, a human action.
        self.human(self.operator, f"launched automation '{name}'", step="run_start")

    def _emit(self, actor: str, action: str, *, step: str | None = None,
              status: str = "ok", who: str | None = None,
              detail: dict | None = None) -> dict[str, Any]:
        event: dict[str, Any] = {
            "ts": _utc_now(), "actor": actor, "step": step,
            "action": action, "status": status,
        }
        if who:
            event["who"] = who
        detail = _redact_detail(detail, self.redact)
        if detail:
            event["detail"] = detail
        self._events.append(event)
        with self._events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str) + "\n")
        who_s = f" [{who}]" if who else ""
        self._logger.info(f"{actor.upper():<10}{who_s} {step or '-'}: {action} ({status})")
        return event

    # --- public API -------------------------------------------------------
    def automation(self, action: str, *, step: str | None = None,
                   status: str = "ok", detail: dict | None = None) -> dict[str, Any]:
        """Record something the AUTOMATION did."""
        return self._emit("automation", action, step=step, status=status, detail=detail)

    def human(self, who: str, action: str, *, step: str | None = None,
              status: str = "ok", detail: dict | None = None) -> dict[str, Any]:
        """Record something a HUMAN did or approved (for the sign-off trail)."""
        return self._emit("human", action, step=step, status=status, who=who, detail=detail)

    def warn(self, action: str, *, actor: str = "automation", step: str | None = None,
             who: str | None = None, detail: dict | None = None) -> dict[str, Any]:
        return self._emit(actor, action, step=step, status="warning", who=who, detail=detail)

    def set_outcome(self, **outcome: Any) -> None:
        """Attach result facts to the run summary (e.g. tie_out_diff=0.0)."""
        self.outcome.update(outcome)

    def finalize(self, status: str = "ok") -> dict[str, Any]:
        summary = {
            "automation": self.name,
            "operator": self.operator,
            "started_at": self.started_at,
            "ended_at": _utc_now(),
            "status": status,
            "outcome": self.outcome,
            "counts": {
                "automation": sum(1 for e in self._events if e["actor"] == "automation"),
                "human": sum(1 for e in self._events if e["actor"] == "human"),
                "warnings": sum(1 for e in self._events if e["status"] == "warning"),
            },
            "actions": {
                "automation": [e for e in self._events if e["actor"] == "automation"],
                "human": [e for e in self._events if e["actor"] == "human"],
            },
        }
        (self.dir / "run_summary.json").write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8")
        self._logger.info(
            f"RUN {status.upper()} — automation={summary['counts']['automation']} actions, "
            f"human={summary['counts']['human']} actions, "
            f"warnings={summary['counts']['warnings']}")
        self._handler.close()
        self._logger.removeHandler(self._handler)
        return summary


@contextmanager
def audit_run(name: str, **kwargs: Any) -> Iterator[AuditRun]:
    """Context manager: create an AuditRun and finalize it (ok/failed) on exit."""
    run = AuditRun(name, **kwargs)
    try:
        yield run
    except Exception as exc:
        run._emit("automation", f"run failed: {exc}", step="error", status="error")
        run.set_outcome(error=str(exc))
        run.finalize("failed")
        raise
    else:
        run.finalize("ok")
