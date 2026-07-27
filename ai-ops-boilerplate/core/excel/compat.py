"""openpyxl / ERP compatibility helpers.

Two safety utilities that were repeatedly hand-rolled (and drifted) across
standalone report tools, consolidated here as first-class, generic helpers:

* :func:`find_header` — locate a header row in a source workbook that is
  resilient to the variable ERP *preamble* rows (title banners, filter echoes,
  blank spacers) that sit above the real column headers. Parameterised on the
  anchor labels to look for and how deep to scan.
* :func:`repair_dropped_rels` — repair the dangling relationship-id references
  openpyxl can leave behind on save (most visibly external links), which make
  Excel report the rendered file as corrupt. Works purely at the zip / Open
  Packaging Conventions level, so it needs no openpyxl (the very library that
  drops the references) and no extra dependency.

Both depend only on the standard library (:func:`find_header` additionally uses
the package's own :mod:`.coerce` for value normalisation). Neither couples to
any orchestration/engine module.
"""

from __future__ import annotations

import os
import posixpath
import re
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import coerce
from .errors import HeaderNotFoundError

# ---------------------------------------------------------------------------
# find_header — anchor-scan header detection (resilient to ERP preamble rows)
# ---------------------------------------------------------------------------
#: Default depth (number of leading rows) scanned for the header row. ERP
#: exports rarely push the header deeper than this; raise it per call if needed.
DEFAULT_SCAN_ROWS = 25


def _default_norm(value: Any) -> str:
    """Normalise a cell/label for comparison: text, stripped, case-folded."""
    return coerce.to_text(value).strip().casefold()


@dataclass(frozen=True)
class HeaderMatch:
    """The outcome of a :func:`find_header` scan.

    ``columns`` maps each **normalised** header label to its 0-based column
    index (the *first* occurrence wins, so duplicated labels downstream resolve
    to the leftmost). ``values`` is the header row's raw cell values.
    """

    row: int  # 1-based row index of the located header
    columns: dict[str, int]  # normalised label -> 0-based column index
    values: tuple[Any, ...]  # raw header-row cell values

    def col(self, label: str) -> int | None:
        """0-based column index for ``label`` (normalised), or ``None``."""
        return self.columns.get(_default_norm(label))

    def require(self, label: str) -> int:
        """0-based column index for ``label``, raising ``KeyError`` if absent."""
        idx = self.col(label)
        if idx is None:
            raise KeyError(f"header column {label!r} not found in row {self.row}")
        return idx


def _iter_rows(source: Any, max_scan_rows: int) -> list[tuple[Any, ...]]:
    """Materialise up to ``max_scan_rows`` leading rows from ``source``.

    Accepts an openpyxl worksheet (anything exposing ``iter_rows``) or a plain
    iterable of row sequences — the latter keeps the scan unit-testable without
    a live workbook.
    """
    if hasattr(source, "iter_rows"):
        rows = source.iter_rows(min_row=1, max_row=max_scan_rows, values_only=True)
        return [tuple(r) for r in rows]
    out: list[tuple[Any, ...]] = []
    for i, row in enumerate(source):
        if i >= max_scan_rows:
            break
        out.append(tuple(row))
    return out


def find_header(
    source: Any,
    anchors: Sequence[str],
    *,
    max_scan_rows: int = DEFAULT_SCAN_ROWS,
    require_all: bool = True,
    normalize: Callable[[Any], str] | None = None,
) -> HeaderMatch:
    """Locate the header row of a source sheet by scanning for anchor labels.

    Scans the first ``max_scan_rows`` rows and picks the row that matches the
    most of ``anchors`` (all of them, ideally), so the variable ERP preamble
    above the real headers is skipped. ``anchors`` need only be a distinctive
    *subset* of the columns — enough to identify the header row unambiguously.

    Comparison is done through ``normalize`` (default: text, stripped,
    case-folded), so header casing/whitespace differences don't matter.

    :param source: an openpyxl worksheet, or an iterable of row sequences.
    :param anchors: labels expected on the header row.
    :param max_scan_rows: how many leading rows to scan.
    :param require_all: when ``True`` (default), raise
        :class:`~.errors.HeaderNotFoundError` unless *every* anchor is matched;
        when ``False``, return the best-matching row even if partial.
    :param normalize: optional label/cell normaliser override.
    :returns: a :class:`HeaderMatch`.
    :raises HeaderNotFoundError: if ``require_all`` and not all anchors matched,
        or if no rows were scanned at all.
    """
    norm = normalize or _default_norm
    wanted = [norm(a) for a in anchors]
    rows = _iter_rows(source, max_scan_rows)

    best_idx: int | None = None
    best_hits = -1
    for idx, row in enumerate(rows):
        cells = {norm(c) for c in row}
        hits = sum(1 for a in wanted if a in cells)
        if hits > best_hits:
            best_hits, best_idx = hits, idx
        if hits == len(wanted) and wanted:
            break

    if best_idx is None:
        raise HeaderNotFoundError(
            "no rows to scan for a header row", anchors=tuple(anchors), matched=0
        )
    if require_all and best_hits < len(wanted):
        raise HeaderNotFoundError(
            f"could not locate header row (matched {best_hits}/{len(wanted)} "
            f"anchors: {list(anchors)}); check the report layout or raise "
            f"max_scan_rows (scanned {len(rows)})",
            anchors=tuple(anchors),
            matched=max(best_hits, 0),
        )

    values = rows[best_idx]
    columns: dict[str, int] = {}
    for i, cell in enumerate(values):
        key = norm(cell)
        if key and key not in columns:  # first occurrence wins
            columns[key] = i
    return HeaderMatch(row=best_idx + 1, columns=columns, values=values)


# ---------------------------------------------------------------------------
# repair_dropped_rels — fix dangling relationship ids openpyxl leaves on save
# ---------------------------------------------------------------------------
_RELS_HEADER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/'
    'package/2006/relationships">'
)


def snapshot_rels(path: str | Path) -> dict[str, bytes]:
    """Capture every ``.rels`` part of a workbook *before* openpyxl rewrites it.

    Call this on the pristine input immediately before the render/save; pass the
    returned mapping to :func:`repair_dropped_rels` afterwards. Returns an empty
    mapping if the file cannot be read as a zip (so a missing/odd input degrades
    to a no-op repair rather than raising).
    """
    try:
        with zipfile.ZipFile(path) as z:
            return {n: z.read(n) for n in z.namelist() if n.endswith(".rels")}
    except (OSError, zipfile.BadZipFile):
        return {}


def _rel_entries(rels_bytes: bytes | None) -> dict[str, str]:
    """Parse a ``.rels`` blob into ``{Id: full <Relationship .../> tag}``."""
    out: dict[str, str] = {}
    if not rels_bytes:
        return out
    txt = rels_bytes.decode("utf-8", "replace")
    for tag in re.findall(r"<Relationship\b[^>]*?/?>", txt):
        m = re.search(r'\bId="([^"]+)"', tag)
        if m:
            out[m.group(1)] = tag
    return out


def _target_ok(tag: str, rels_name: str, saved_names: set[str]) -> bool:
    """True if a relationship's target is external or still present in the package."""
    if 'TargetMode="External"' in tag:
        return True
    m = re.search(r'Target="([^"]+)"', tag)
    if not m:
        return True
    t = m.group(1)
    base = posixpath.dirname(posixpath.dirname(rels_name))
    resolved = t[1:] if t.startswith("/") else posixpath.normpath(
        posixpath.join(base, t)
    )
    return resolved in saved_names


def repair_dropped_rels(
    save_path: str | Path,
    orig_rels: dict[str, bytes],
    *,
    log: Callable[[str], None] | None = None,
) -> int:
    """Re-inject relationship entries openpyxl dropped, leaving dangling ``r:id``s.

    On save, openpyxl can leave dangling relationship-id references that make
    Excel report the file as corrupt. The main offender is **external links**:
    ``externalLinkN.xml`` references ``<externalBook r:id="rId1">`` but openpyxl
    rewrites that part's ``.rels`` keeping only ``rId2`` (the original carried
    both), so ``rId1`` no longer resolves.

    For every saved XML part, this finds ``r:id`` / ``r:embed`` / ``r:link``
    references its current ``.rels`` does not satisfy, then **merges** the
    matching ``<Relationship>`` entries back in from ``orig_rels`` (captured with
    :func:`snapshot_rels` before the save) — but only when each entry's target is
    external-mode or still exists in the saved package. Merging (rather than
    replacing) preserves relationships openpyxl legitimately added (e.g.
    hyperlinks) and skips references to parts openpyxl correctly removed
    (drawings, printer settings, …).

    A fallback handles openpyxl's external-link *renumbering* (a fresh ``rId`` in
    the ``.rels`` while the XML still references the old one, with no snapshot to
    consult because the input was itself a prior openpyxl output): an
    unreferenced external-mode entry is renamed to the missing id, making the
    repair idempotent across repeated in-place runs.

    The file is rewritten in place. Returns the number of ``.rels`` parts patched
    (``0`` if nothing needed repair or ``orig_rels`` is empty).
    """
    _log = log or (lambda _msg: None)
    save_path = os.fspath(save_path)
    if not orig_rels:
        return 0
    try:
        with zipfile.ZipFile(save_path) as z:
            saved = {n: z.read(n) for n in z.namelist()}
    except (OSError, zipfile.BadZipFile) as e:
        _log(f"[XLSX] Could not read saved file for rels repair: {e}")
        return 0
    saved_names = set(saved)

    patched: dict[str, bytes] = {}  # rels_name -> new bytes
    for part, data in saved.items():
        if not part.endswith(".xml") or part.endswith(".rels"):
            continue
        txt = data.decode("utf-8", "replace")
        refs = set(re.findall(r'r:(?:id|embed|link)="([^"]+)"', txt))
        if not refs:
            continue

        rels_name = (
            f"{posixpath.dirname(part)}/_rels/{posixpath.basename(part)}.rels"
        )
        present = _rel_entries(saved.get(rels_name))
        missing = refs - set(present)
        if not missing:
            continue

        orig = _rel_entries(orig_rels.get(rels_name))
        add = [
            orig[rid]
            for rid in missing
            if rid in orig and _target_ok(orig[rid], rels_name, saved_names)
        ]

        merged = dict(present)
        for tag in add:
            rid = re.search(r'\bId="([^"]+)"', tag).group(1)
            merged[rid] = tag

        # Fallback for openpyxl's external-link renumbering (see docstring):
        # rename a spare unreferenced external-mode entry to the missing id.
        still_missing = missing - set(merged)
        if still_missing:
            referenced = refs & set(merged)
            spare = [
                rid
                for rid, tag in merged.items()
                if rid not in referenced and 'TargetMode="External"' in tag
            ]
            for want in sorted(still_missing):
                if not spare:
                    break
                old_rid = spare.pop(0)
                tag = merged.pop(old_rid)
                merged[want] = re.sub(
                    r'\bId="[^"]+"', f'Id="{want}"', tag, count=1
                )

        if merged == present:
            continue
        patched[rels_name] = (
            _RELS_HEADER + "".join(merged.values()) + "</Relationships>"
        ).encode("utf-8")

    if not patched:
        return 0

    _log(
        f"[XLSX] Repaired {len(patched)} relationship file(s) to fix dangling "
        f"references left by openpyxl (external links) — keeps the file openable."
    )
    tmp = f"{save_path}.__relfix__.tmp"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for n, d in saved.items():
                zout.writestr(n, patched.get(n, d))
        os.replace(tmp, save_path)
    except (OSError, zipfile.BadZipFile) as e:
        _log(f"[XLSX] Could not write rels repair: {e}")
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return 0
    return len(patched)


__all__ = [
    "DEFAULT_SCAN_ROWS",
    "HeaderMatch",
    "find_header",
    "snapshot_rels",
    "repair_dropped_rels",
]
