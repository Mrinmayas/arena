"""Per-run working memory: persisted key/value store + named file store.

Replaces an in-memory bag with a store backed by ``runs/<run_id>/memory/`` on disk,
so state survives process exit and is available for resume and audit.

Layout::

    runs/<run_id>/memory/
        manifest.json      -- values + file metadata (atomic writes)
        files/
            <name>         -- binary artifacts registered via put_file()

Parallel safety: sibling steps in a stage write **distinct names** (enforced by
convention, not by locking). Concurrent writes to different names are safe because
each write is an atomic manifest replace; two concurrent writers for the same name
would race, but that is an authoring violation.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any


class WorkingMemory:
    """Persisted per-run store of values and files."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._files_dir = root / "files"
        self._manifest_path = root / "manifest.json"
        # manifest shape: {"values": {name: value}, "files": {name: {size, ts}}}
        self._values: dict[str, Any] = {}
        self._file_meta: dict[str, dict[str, Any]] = {}
        self._files_dir.mkdir(parents=True, exist_ok=True)
        if self._manifest_path.exists():
            self._load()

    # ------------------------------------------------------------------
    # Value API
    # ------------------------------------------------------------------

    def put_value(self, name: str, value: Any) -> None:
        """Store a serialisable value; manifest persisted atomically."""
        self._values[name] = value
        self._persist_manifest()

    def get_value(self, name: str, default: Any = None) -> Any:
        return self._values.get(name, default)

    def has(self, name: str) -> bool:
        return name in self._values or name in self._file_meta

    # ------------------------------------------------------------------
    # File API
    # ------------------------------------------------------------------

    def path_for(self, name: str) -> Path:
        """Return the canonical path for a named file (does not register it).

        Use this to get a download target; call ``put_file(name)`` afterward
        to register the file in the manifest.
        """
        return self._files_dir / name

    def put_file(self, name: str, src: Path | None = None) -> Path:
        """Register a named file, optionally copying it from *src*.

        If *src* is ``None``, the file must already exist at ``path_for(name)``
        (e.g. written directly by a browser download).
        """
        dest = self._files_dir / name
        if src is not None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        size = dest.stat().st_size if dest.exists() else 0
        self._file_meta[name] = {"size": size, "ts": time.time()}
        self._persist_manifest()
        return dest

    def get_file(self, name: str) -> Path:
        """Return path for a registered named file; raises ``KeyError`` if unknown."""
        if name not in self._file_meta:
            raise KeyError(f"No file named {name!r} in working memory")
        return self._files_dir / name

    # ------------------------------------------------------------------
    # Audit / cleanup
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a serialisable summary for run.json.

        Values are previewed (not raw) to stay JSON-safe for arbitrary objects.
        Files include size and registration timestamp.
        """
        def _preview(v: Any) -> str:
            r = repr(v)
            return r[:120] + "..." if len(r) > 120 else r

        return {
            "values": {k: _preview(v) for k, v in self._values.items()},
            "files": {
                k: {"size_bytes": m["size"], "ts": m["ts"]}
                for k, m in self._file_meta.items()
            },
        }

    def cleanup(self) -> None:
        """Delete the files directory; keep manifest for audit.

        Called by ``RunStoreSubscriber`` after a successful production run.
        """
        shutil.rmtree(self._files_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _persist_manifest(self) -> None:
        """Atomic write: write to .tmp then ``os.replace()`` (NTFS-safe).

        Raises ``TypeError`` if any stored value is not JSON-serializable.
        ``put_value()`` accepts only JSON-native types (str, int, float, bool,
        list, dict, None) to ensure round-trip correctness on resume.

        Retries ``os.replace`` up to 5 times with a short back-off because on
        Windows, antivirus or the NTFS indexer can briefly hold the .tmp file
        open after it is written, causing ``os.replace`` to fail with WinError 5.
        """
        payload = {"values": self._values, "files": self._file_meta}
        tmp = self._manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, self._manifest_path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)

    def _load(self) -> None:
        """Reconstruct in-memory state from an existing manifest (resume path)."""
        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            self._values = data.get("values", {})
            self._file_meta = data.get("files", {})
        except (json.JSONDecodeError, OSError):
            # Corrupted manifest — start fresh; files on disk are accessible via path_for()
            self._values = {}
            self._file_meta = {}
