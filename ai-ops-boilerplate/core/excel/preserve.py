"""Restore OOXML parts that openpyxl drops on save.

openpyxl is a *partial-fidelity* writer: when it loads and re-saves a workbook it
silently drops or rewrites every package part it does not model — cell comments
(and their legacy VML), printer settings, named sheet views, the custom-XML data
store, sensitivity labels, drawings, images. For a workbook authored in Excel and
regenerated through :func:`.render.render`, the result is missing operator
content and — most visibly — Excel's *"we found a problem with some content …
recovered records"* repair dialog on open (triggered by openpyxl's rewritten
comments).

:func:`restore_parts` repairs the rendered output **after** the final render by
copying the dropped parts back from the pristine, Excel-authored source. It works
purely at the zip / Open Packaging Conventions level (openpyxl is the very thing
that loses these parts, so it cannot be used here) and is driven entirely by the
**source's relationship graph** — no part filenames, sheet numbers, or counts are
hardcoded. The only fixed constants are ECMA-376 relationship-type URIs and the
standard ``CT_Worksheet`` child-element order.

A relationship is restored when its target part is **absent from the rendered
output by path** (so parts openpyxl kept untouched — pivot tables, external links,
theme — are left alone, and parts it *renamed* such as comments are correctly
re-introduced and their openpyxl counterpart purged). Relationship types in
``exclude_rel_types`` (images and the picture-drawings that embed them, by
default) are never restored.
"""
from __future__ import annotations

import os
import posixpath
import re
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# --- ECMA-376 / MS relationship-type URIs (spec constants, not workbook-specific)
_OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
TYPE_IMAGE = _OFFICE + "image"
TYPE_DRAWING = _OFFICE + "drawing"
TYPE_PRINTER_SETTINGS = _OFFICE + "printerSettings"
TYPE_VML_DRAWING = _OFFICE + "vmlDrawing"
TYPE_COMMENTS = _OFFICE + "comments"

#: Structural / writer-owned relationship types. These parts make up the document
#: itself and are (re)written by the renderer — restoring the source copy would be
#: stale or duplicate it. Notably ``worksheet``: if the writer renumbers a sheet
#: part, the source's worksheet rel points at a now-absent path and must NOT be
#: re-injected (the live sheet is matched by name instead). ``calcChain`` is here
#: because a stale chain itself triggers a repair; ``sharedStrings`` because the
#: writer may inline strings instead. Always excluded, regardless of the caller's
#: *exclude_rel_types*.
_WRITER_MANAGED: frozenset[str] = frozenset(
    _OFFICE + t for t in (
        "worksheet", "chartsheet", "dialogsheet", "styles", "theme",
        "officeDocument", "sharedStrings", "calcChain",
    )
)

#: Relationship types excluded from restore by default — images and the
#: picture-drawings that embed them (a drawing restored without its images would
#: dangle). Pass a different frozenset to change the policy.
IMAGE_REL_TYPES: frozenset[str] = frozenset({TYPE_IMAGE, TYPE_DRAWING})

# Worksheet child-element order (ECMA-376 CT_Worksheet), tail portion — used to
# insert restored reference elements in a schema-valid position. Out-of-order
# insertion is itself a repair trigger.
_WORKSHEET_CHILD_ORDER: tuple[str, ...] = (
    "sheetPr", "dimension", "sheetViews", "sheetFormatPr", "cols", "sheetData",
    "sheetCalcPr", "sheetProtection", "protectedRanges", "scenarios", "autoFilter",
    "sortState", "dataConsolidate", "customSheetViews", "mergeCells", "phoneticPr",
    "conditionalFormatting", "dataValidations", "hyperlinks", "printOptions",
    "pageMargins", "pageSetup", "headerFooter", "rowBreaks", "colBreaks",
    "customProperties", "cellWatches", "ignoredErrors", "smartTags", "drawing",
    "legacyDrawing", "legacyDrawingHF", "drawingHF", "picture", "oleObjects",
    "controls", "webPublishItems", "tableParts", "extLst",
)


@dataclass
class RestoreReport:
    """Outcome of a :func:`restore_parts` call."""

    restored: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"restored {len(self.restored)} part(s)"
            + (f", skipped {len(self.skipped)}" if self.skipped else "")
        )


# ---------------------------------------------------------------------------
# Low-level OPC helpers (string/zip level — no openpyxl, no XML reserialisation)
# ---------------------------------------------------------------------------
def _read_parts(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def _rels_path(part: str) -> str:
    """The .rels part that holds *part*'s relationships."""
    d, f = posixpath.split(part)
    return f"{d}/_rels/{f}.rels" if d else f"_rels/{f}.rels"


def _resolve_target(owner_part: str, target: str) -> str:
    """Resolve a relationship Target (relative or '/'-absolute) to a part path."""
    if target.startswith("/"):
        return target.lstrip("/")
    base = posixpath.dirname(owner_part)
    return posixpath.normpath(posixpath.join(base, target))


@dataclass
class _Rel:
    id: str
    type: str
    target: str
    mode: str | None  # "External" or None


def _parse_rels(xml: bytes) -> list[_Rel]:
    rels: list[_Rel] = []
    for m in re.finditer(rb"<Relationship\b[^>]*/>", xml):
        tag = m.group(0).decode("utf-8")
        rid = _attr(tag, "Id")
        typ = _attr(tag, "Type")
        tgt = _attr(tag, "Target")
        mode = _attr(tag, "TargetMode")
        if rid and typ and tgt is not None:
            rels.append(_Rel(rid, typ, tgt, mode))
    return rels


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'{name}="([^"]*)"', tag)
    return m.group(1) if m else None


_EMPTY_RELS = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
    b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    b"</Relationships>"
)


def _add_rel(parts: dict[str, bytes], rels_part: str, rel: _Rel) -> None:
    xml = parts.get(rels_part, _EMPTY_RELS)
    entry = (
        f'<Relationship Id="{rel.id}" Type="{rel.type}" Target="{rel.target}"'
        + (f' TargetMode="{rel.mode}"' if rel.mode else "")
        + "/>"
    ).encode("utf-8")
    parts[rels_part] = xml.replace(b"</Relationships>", entry + b"</Relationships>")


def _remove_rels(parts: dict[str, bytes], rels_part: str, predicate) -> list[_Rel]:
    """Drop relationships matching *predicate*; return the removed ones."""
    if rels_part not in parts:
        return []
    removed: list[_Rel] = []
    keep = parts[rels_part]
    for rel in _parse_rels(parts[rels_part]):
        if predicate(rel):
            removed.append(rel)
            keep = re.sub(
                rf'<Relationship\b[^>]*Id="{re.escape(rel.id)}"[^>]*/>'.encode(),
                b"", keep,
            )
    parts[rels_part] = keep
    return removed


def _next_rid(rels_part: str, parts: dict[str, bytes]) -> str:
    existing = {r.id for r in _parse_rels(parts.get(rels_part, _EMPTY_RELS))}
    n = 1
    while f"rId{n}" in existing:
        n += 1
    return f"rId{n}"


# --- [Content_Types].xml ---------------------------------------------------
def _ct_has_override(ct: bytes, part: str) -> bool:
    return f'PartName="/{part}"'.encode() in ct


def _ct_has_default(ct: bytes, ext: str) -> bool:
    return re.search(rf'<Default Extension="{re.escape(ext)}"'.encode(), ct) is not None


def _ct_add(parts: dict[str, bytes], source_ct: bytes, part: str) -> None:
    """Ensure the target content-types declares *part* — copying the source's
    Override, or ensuring a Default for the extension (also copied from source)."""
    ct = parts["[Content_Types].xml"]
    m = re.search(rf'<Override PartName="/{re.escape(part)}"[^>]*/>'.encode(), source_ct)
    if m:
        if not _ct_has_override(ct, part):
            parts["[Content_Types].xml"] = ct.replace(b"</Types>", m.group(0) + b"</Types>")
        return
    ext = part.rsplit(".", 1)[-1]
    if not _ct_has_default(ct, ext):
        dm = re.search(rf'<Default Extension="{re.escape(ext)}"[^>]*/>'.encode(), source_ct)
        if dm:
            # Insert the Default immediately after the <Types …> opening tag.
            parts["[Content_Types].xml"] = re.sub(
                rb"(<Types\b[^>]*>)", rb"\1" + dm.group(0), ct, count=1
            )


def _ct_remove_override(parts: dict[str, bytes], part: str) -> None:
    ct = parts["[Content_Types].xml"]
    parts["[Content_Types].xml"] = re.sub(
        rf'<Override PartName="/{re.escape(part)}"[^>]*/>'.encode(), b"", ct
    )


#: The relationships namespace URI for the conventional ``r`` prefix. openpyxl
#: omits this declaration on the <worksheet> root when the sheet has no
#: relationship-bearing elements, so any ``r:id`` we inject (pageSetup printer
#: settings, legacyDrawing/VML) would be an *unbound prefix* — a fatal XML error
#: that corrupts the whole file. It must be declared before the attribute is used.
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _ensure_r_namespace(xml: bytes) -> bytes:
    """Declare ``xmlns:r`` on the <worksheet> root if it isn't already, so an
    injected ``r:id`` resolves. No-op when the prefix is already bound."""
    m = re.match(rb"<worksheet\b[^>]*>", xml)
    if not m:
        return xml
    root = m.group(0)
    if b"xmlns:r=" in root:
        return xml
    new_root = root[:-1] + f' xmlns:r="{_R_NS}"'.encode() + b">"
    return new_root + xml[m.end():]


# --- worksheet-XML element insertion (schema-ordered) ----------------------
def _insert_worksheet_child(xml: bytes, element: bytes, tag: str) -> bytes:
    """Insert *element* (for child *tag*) into a <worksheet> at a schema-valid spot:
    before the first existing child that must follow it; else before </worksheet>."""
    order = _WORKSHEET_CHILD_ORDER
    idx = order.index(tag)
    for later in order[idx + 1:]:
        m = re.search(rf"<{later}[ />]".encode(), xml)
        if m:
            return xml[: m.start()] + element + xml[m.start():]
    return re.sub(rb"</worksheet>", element + b"</worksheet>", xml, count=1)


def _set_pagesetup_rid(xml: bytes, rid: str) -> bytes:
    xml = _ensure_r_namespace(xml)
    m = re.search(rb"<pageSetup\b[^>]*?/?>", xml)
    if m:
        tag = m.group(0)
        if b"r:id=" in tag:
            new = re.sub(rb'r:id="[^"]*"', f'r:id="{rid}"'.encode(), tag)
        else:
            new = tag[:-2] + f' r:id="{rid}"/>'.encode() if tag.endswith(b"/>") \
                else tag[:-1] + f' r:id="{rid}"/>'.encode()
        return xml[: m.start()] + new + xml[m.end():]
    return _insert_worksheet_child(xml, f'<pageSetup r:id="{rid}"/>'.encode(), "pageSetup")


def _set_legacy_drawing(xml: bytes, rid: str) -> bytes:
    xml = _ensure_r_namespace(xml)
    xml = re.sub(rb"<legacyDrawing\b[^>]*/>", b"", xml)  # drop openpyxl's placeholder
    return _insert_worksheet_child(xml, f'<legacyDrawing r:id="{rid}"/>'.encode(), "legacyDrawing")


# --- workbook → sheet-name mapping -----------------------------------------
def _sheet_name_to_part(parts: dict[str, bytes]) -> dict[str, str]:
    """Map worksheet *name* → part path, via workbook.xml + its rels."""
    wb = parts.get("xl/workbook.xml")
    rels = parts.get("xl/_rels/workbook.xml.rels")
    if not wb or not rels:
        return {}
    rid_to_part = {r.id: _resolve_target("xl/workbook.xml", r.target) for r in _parse_rels(rels)}
    out: dict[str, str] = {}
    for m in re.finditer(rb'<sheet\b[^>]*/>', wb):
        tag = m.group(0).decode("utf-8")
        name, rid = _attr(tag, "name"), _attr(tag, "r:id")
        if name and rid and rid in rid_to_part:
            out[name] = rid_to_part[rid]
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def restore_parts(
    source: str | Path,
    target: str | Path,
    *,
    exclude_rel_types: frozenset[str] = IMAGE_REL_TYPES,
    log: Callable[[str], None] | None = None,
) -> RestoreReport:
    """Restore into *target* the OPC parts that openpyxl dropped, from *source*.

    *source* is the pristine, Excel-authored workbook; *target* is the rendered
    output. Both are ``.xlsx`` paths. Relationships whose type is in
    *exclude_rel_types* (images/drawings by default) are skipped. The target is
    rewritten in place (atomic temp-file + ``os.replace`` with a Windows retry).
    """
    source, target = Path(source), Path(target)
    excluded = exclude_rel_types | _WRITER_MANAGED
    src = _read_parts(source)
    tgt = _read_parts(target)
    report = RestoreReport()

    src_name_to_part = _sheet_name_to_part(src)
    tgt_name_to_part = _sheet_name_to_part(tgt)
    src_part_to_name = {p: n for n, p in src_name_to_part.items()}
    source_ct = src.get("[Content_Types].xml", b"")

    # Gather restorable source relationships, grouped by (target-owner, type).
    # A relationship is restorable iff its target part is absent from the output
    # (covers both dropped and openpyxl-renamed parts).
    groups: dict[tuple[str, str], list[tuple[str, _Rel]]] = {}
    for rels_part, xml in list(src.items()):
        if not rels_part.endswith(".rels"):
            continue
        owner = _owner_of_rels(rels_part)
        for rel in _parse_rels(xml):
            if rel.mode == "External" or rel.type in excluded:
                continue
            src_target = _resolve_target(owner, rel.target)
            if src_target in tgt:
                continue  # openpyxl kept it untouched
            tgt_owner = _map_owner(owner, src_part_to_name, tgt_name_to_part)
            if tgt_owner is None:
                report.skipped.append(f"{src_target} (owner sheet not in output)")
                continue
            groups.setdefault((tgt_owner, rel.type), []).append((src_target, rel))

    for (tgt_owner, rel_type), members in groups.items():
        _purge_existing(tgt, tgt_owner, rel_type)
        for src_target, rel in members:
            _restore_one(src, tgt, source_ct, tgt_owner, rel, src_target,
                         excluded, report)

    _atomic_write(tgt, target)
    if log:
        log(f"restore_parts: {report.summary()}")
    return report


def _owner_of_rels(rels_part: str) -> str:
    """The part that owns a given .rels file ('' = package root)."""
    # xl/worksheets/_rels/sheet6.xml.rels -> xl/worksheets/sheet6.xml
    # _rels/.rels                          -> '' (package root)
    d = posixpath.dirname(posixpath.dirname(rels_part))
    f = posixpath.basename(rels_part)[: -len(".rels")]
    return posixpath.join(d, f) if f else d


def _map_owner(src_owner: str, src_part_to_name: dict[str, str],
               tgt_name_to_part: dict[str, str]) -> str | None:
    """Map a source owner part to the target owner part (by sheet *name* for
    worksheets; identity for the package root and workbook-level owners)."""
    if src_owner.startswith("xl/worksheets/") and src_owner.endswith(".xml"):
        name = src_part_to_name.get(src_owner)
        if name is None:
            return None
        return tgt_name_to_part.get(name)  # None if renamed/deleted in output
    return src_owner  # root ('') or xl/workbook.xml etc.


def _purge_existing(tgt: dict[str, bytes], owner: str, rel_type: str) -> None:
    """Remove the output's own relationship(s) of *rel_type* on *owner* — the
    openpyxl-generated counterpart (e.g. its rewritten comments/VML) — including
    the target part, content-type and any referencing worksheet element."""
    rels_part = _rels_path(owner)
    removed = _remove_rels(tgt, rels_part, lambda r: r.type == rel_type)
    for rel in removed:
        part = _resolve_target(owner, rel.target)
        tgt.pop(part, None)
        tgt.pop(_rels_path(part), None)
        _ct_remove_override(tgt, part)
        if rel_type == TYPE_VML_DRAWING and owner in tgt:
            tgt[owner] = re.sub(rb"<legacyDrawing\b[^>]*/>", b"", tgt[owner])


def _restore_one(src: dict[str, bytes], tgt: dict[str, bytes], source_ct: bytes,
                 owner: str, rel: _Rel, src_target: str,
                 exclude_rel_types: frozenset[str], report: RestoreReport) -> None:
    # 1. copy the part bytes + recurse into its own sub-parts (e.g. customXml item
    #    -> itemProps), honouring the same exclusions.
    _copy_part_tree(src, tgt, source_ct, src_target, exclude_rel_types)
    # 2. wire the relationship into the owner's .rels with a fresh, unique id.
    rels_part = _rels_path(owner)
    rid = _next_rid(rels_part, tgt)
    _add_rel(tgt, rels_part, _Rel(rid, rel.type, rel.target, rel.mode))
    # 3. insert the worksheet reference element where the type requires one.
    if rel.type == TYPE_PRINTER_SETTINGS and owner in tgt:
        tgt[owner] = _set_pagesetup_rid(tgt[owner], rid)
    elif rel.type == TYPE_VML_DRAWING and owner in tgt:
        tgt[owner] = _set_legacy_drawing(tgt[owner], rid)
    report.restored.append(src_target)


def _copy_part_tree(src: dict[str, bytes], tgt: dict[str, bytes], source_ct: bytes,
                    part: str, exclude_rel_types: frozenset[str]) -> None:
    if part not in src:
        return
    tgt[part] = src[part]
    _ct_add(tgt, source_ct, part)
    rels_part = _rels_path(part)
    if rels_part in src:
        tgt[rels_part] = src[rels_part]
        for sub in _parse_rels(src[rels_part]):
            if sub.mode == "External" or sub.type in exclude_rel_types:
                continue
            _copy_part_tree(src, tgt, source_ct, _resolve_target(part, sub.target),
                            exclude_rel_types)


def _atomic_write(parts: dict[str, bytes], path: Path,
                  replace_attempts: int = 5, replace_delay: float = 0.1) -> None:
    """Write *parts* to a new zip and atomically replace *path* (Windows-safe)."""
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            # [Content_Types].xml conventionally leads the archive.
            for name in sorted(parts, key=lambda n: (n != "[Content_Types].xml", n)):
                z.writestr(name, parts[name])
        for attempt in range(replace_attempts):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == replace_attempts - 1:
                    raise
                time.sleep(replace_delay)
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
