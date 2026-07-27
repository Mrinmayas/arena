"""Concurrency-safe append to the shared CSV ledger.

Multiple automations can run at once (a scheduled job overlapping a manual run), and
on Windows a CSV opened in Excel is exclusively locked. Plain ``csv`` appends from
several processes would interleave rows or fail outright. This module serializes
appends with a cross-process advisory lock (``msvcrt.locking`` on Windows) around a
whole-row write, retrying briefly on contention.

If the file stays locked (the classic case: a user has ``runs.csv`` open in Excel),
the row is *spilled* to ``runs/_pending/<csv>.jsonl`` instead of being lost. The next
run calls :func:`reconcile` to fold pending rows back in. The per-run ``run.json`` is
written independently, so the ledger is always reconstructable even if a spill is lost.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from pathlib import Path

try:
    import msvcrt  # Windows-only; provides cross-process file region locking
except ImportError:  # pragma: no cover - non-Windows fallback (best effort, no x-proc lock)
    msvcrt = None  # type: ignore[assignment]

_RETRIES = 50
_RETRY_DELAY = 0.1


def _row_to_line(header: list[str], row: dict[str, object]) -> str:
    buf = io.StringIO()
    csv.DictWriter(buf, fieldnames=header, extrasaction="ignore").writerow(row)
    return buf.getvalue()


def _try_append(path: Path, header: list[str], row: dict[str, object]) -> bool:
    """Attempt a single locked, retried append. Returns False if it never won the lock.

    Does not spill — callers decide what to do on failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = _row_to_line(header, row)
    for _ in range(_RETRIES):
        try:
            f = open(path, "a+", newline="", encoding="utf-8")
        except OSError:
            # File is locked by another process (e.g. Excel has it open). Wait & retry.
            time.sleep(_RETRY_DELAY)
            continue
        try:
            # Lock a fixed 1-byte region (byte 0) so the lock and unlock target the
            # exact same range — Windows requires symmetric lock/unlock. Locking past
            # EOF is allowed. Writes still go to EOF because the file is in append mode.
            if msvcrt is not None:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                f.seek(0, os.SEEK_END)
                if f.tell() == 0:
                    f.write(",".join(header) + "\r\n")
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            finally:
                if msvcrt is not None:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            return True
        except OSError:
            # Could not acquire the region lock; back off and retry the whole open.
            time.sleep(_RETRY_DELAY)
        finally:
            f.close()
    return False


def append_row(path: Path, header: list[str], row: dict[str, object]) -> bool:
    """Append one row to the ledger; spill to pending if the file stays locked.

    Returns True if written directly, False if spilled for later :func:`reconcile`.
    """
    if _try_append(path, header, row):
        return True
    _spill(path, header, row)
    return False


def _pending_dir(path: Path) -> Path:
    return path.parent / "_pending"


def _spill(path: Path, header: list[str], row: dict[str, object]) -> None:
    pdir = _pending_dir(path)
    pdir.mkdir(parents=True, exist_ok=True)
    record = {"header": header, "row": row}
    with open(pdir / f"{path.stem}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def reconcile(path: Path) -> int:
    """Fold any spilled rows for ``path`` back into the ledger. Returns rows recovered.

    Called at run start. Rows that still cannot be written (file remains locked) are
    kept in the spill file for the next attempt.
    """
    spill_file = _pending_dir(path) / f"{path.stem}.jsonl"
    if not spill_file.exists():
        return 0
    try:
        lines = spill_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    recovered = 0
    remaining: list[str] = []
    for raw in lines:
        if not raw.strip():
            continue
        rec = json.loads(raw)
        if _try_append(path, rec["header"], rec["row"]):
            recovered += 1
        else:
            remaining.append(raw)
    if remaining:
        spill_file.write_text("\n".join(remaining) + "\n", encoding="utf-8")
    else:
        spill_file.unlink(missing_ok=True)
    return recovered
