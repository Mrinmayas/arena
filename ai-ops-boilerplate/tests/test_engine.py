"""End-to-end test for the opt-in orchestration engine and its core.audit bridge.

Proves that a minimal Automation runs, writes the structured ``runs/<run_id>/`` store,
AND leaves the ``audit_logs/<ts>/`` human-vs-automation trail via the AuditSubscriber.
"""
import asyncio
import json

from core.engine import Automation, Stage, Step, run_automation


def _build_demo() -> Automation:
    async def do_work(ctx):
        ctx.put("count", 3)
        await ctx.log("did the work")  # ctx.log is a coroutine — always await it

    return Automation("demo_engine", [Stage("main", [Step("do_work", do_work)])])


def test_engine_runs_and_writes_both_trails(tmp_path):
    audit_root = tmp_path / "audit_logs"
    runs_dir = tmp_path / "runs"

    result = asyncio.run(
        run_automation(
            _build_demo(),
            runs_dir=runs_dir,
            audit_root=str(audit_root),
            operator="alice",
        )
    )

    # 1. Engine reports success.
    assert "succeed" in str(result.status).lower()

    # 2. Structured runs/<run_id>/ store exists with a run.json.
    run_dirs = [p for p in runs_dir.iterdir() if p.is_dir()]
    assert run_dirs, "engine did not create runs/<run_id>/"
    assert (run_dirs[0] / "run.json").exists()

    # 3. The AuditSubscriber bridged engine events into core.audit's trail.
    audit_dirs = [p for p in audit_root.iterdir() if p.is_dir()]
    assert audit_dirs, "AuditSubscriber did not write audit_logs/"
    summary = json.loads((audit_dirs[0] / "run_summary.json").read_text())
    assert summary["counts"]["automation"] >= 1  # step/stage events bridged
    assert summary["counts"]["human"] >= 1        # operator launch recorded
