"""Tests for the always-on audit / observability core (the human-vs-automation trail)."""
import json

from core.audit import audit_run


def _events(run_dir):
    return [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]


def test_every_event_carries_an_actor(tmp_path):
    with audit_run("demo", audit_root=str(tmp_path), operator="alice") as a:
        a.automation("matched 10 rows", step="match")
        a.human("bob", "approved 2 exceptions", step="review")
    run_dir = next(tmp_path.iterdir())
    events = _events(run_dir)
    assert all("actor" in e for e in events)
    assert {e["actor"] for e in events} == {"automation", "human"}
    # Launching the run is attributed to the human operator.
    assert events[0]["actor"] == "human"
    assert events[0]["who"] == "alice"


def test_run_summary_splits_human_vs_automation(tmp_path):
    with audit_run("demo", audit_root=str(tmp_path), operator="alice") as a:
        a.automation("did X")
        a.human("bob", "approved X")
    summary = json.loads((next(tmp_path.iterdir()) / "run_summary.json").read_text())
    assert summary["status"] == "ok"
    assert summary["counts"]["automation"] >= 1
    assert summary["counts"]["human"] >= 2          # run_start (alice) + approval (bob)
    assert {"automation", "human"} <= summary["actions"].keys()


def test_redaction_masks_money_but_keeps_other_fields(tmp_path):
    with audit_run("demo", audit_root=str(tmp_path), redact=True) as a:
        a.automation("computed", detail={"amount": 12345.67, "vendor": "ACME"})
    computed = [e for e in _events(next(tmp_path.iterdir())) if e["action"] == "computed"][0]
    assert computed["detail"]["amount"] == "[REDACTED]"
    assert computed["detail"]["vendor"] == "ACME"


def test_failure_is_finalized_as_failed(tmp_path):
    try:
        with audit_run("demo", audit_root=str(tmp_path)) as a:
            a.automation("starting")
            raise ValueError("boom")
    except ValueError:
        pass
    summary = json.loads((next(tmp_path.iterdir()) / "run_summary.json").read_text())
    assert summary["status"] == "failed"
    assert "boom" in json.dumps(summary["outcome"])
