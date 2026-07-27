"""Render a workflow diagram (draw.io / mxGraph XML) from a Process.

Same source of truth as the README and the operator Word guide
(``PROCESS_STEPS.md`` → :class:`core.docs.Process`). The output is a ``.drawio`` file
that opens in draw.io / diagrams.net and in the VS Code draw.io extension, and can be
exported to PNG/SVG/PDF for sign-off.

Layout — a small **layered (rank-based) layout**, not a single row:

* Each node is ranked by its **longest path from Start**, so a step's column reflects
  how far along the flow it is — and mutually-exclusive targets of a decision (which all
  sit the same distance from Start) land in the **same column**.
* Nodes sharing a rank are **stacked on separate rows**, so a decision **fans out
  vertically** (branches go up AND down) instead of firing several arrows along one row.
  This is what stops the two failures of a naive one-row layout: **overlapping arrows**
  and **branch labels landing on top of boxes**.
* The result is still **left → right** with one clean horizontal spine; it only spreads
  vertically where a decision actually branches.
* Steps are rectangles, decisions are rhombi, start/end are ellipses; **orthogonal
  edges** with fixed exit/entry ports keep the spine straight and branches tidy.
* **Colour by actor** — blue = automated, orange = a person ("You") — with a **legend**
  box so the diagram is never colour-alone (each swatch is labelled).

Stdlib only (no external deps): the mxGraph format is plain XML we emit directly.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import quoteattr

from .steps import Process, Step

# --- palette (draw.io's standard fill/stroke pairs; labelled, never colour-alone) ---
AUTO_FILL, AUTO_STROKE = "#dae8fc", "#6c8ebf"   # blue — automated
YOU_FILL, YOU_STROKE = "#ffe6cc", "#d79b00"     # orange — person/operator
DEC_FILL, DEC_STROKE = "#fff2cc", "#d6b656"     # yellow — decision
END_FILL, END_STROKE = "#d5e8d4", "#82b366"     # green — start/end
EXIT_FILL, EXIT_STROKE = "#f8cecc", "#b85450"   # red — reject/park exit

# geometry — a column per rank, a row per stacked node.
COL_W = 300                 # horizontal stride between columns (ranks)
ROW_H = 150                 # vertical stride between rows (stacked branches)
X0 = 40                     # left margin (Start column's left edge)
SPINE_Y = 380               # y-centre of the spine row (row 0); rows above use SPINE_Y - ROW_H
STEP_W, STEP_H = 190, 70
DEC_W, DEC_H = 170, 90
ELL_W, ELL_H = 70, 50
TERM_W, TERM_H = 140, 50


def _is_step_target(target: str) -> int | None:
    t = target.strip().lower()
    if t.startswith("step"):
        digits = "".join(ch for ch in target if ch.isdigit())
        return int(digits) if digits else None
    return None


class _XML:
    """Tiny mxGraph cell accumulator."""

    def __init__(self) -> None:
        self.cells: list[str] = []

    def vertex(self, cid, value, style, x, y, w, h) -> None:
        self.cells.append(
            f'<mxCell id={quoteattr(cid)} value={quoteattr(value)} '
            f'style={quoteattr(style)} vertex="1" parent="1">'
            f'<mxGeometry x="{int(x)}" y="{int(y)}" width="{w}" height="{h}" as="geometry"/></mxCell>'
        )

    def edge(self, cid, source, target, value, style) -> None:
        self.cells.append(
            f'<mxCell id={quoteattr(cid)} value={quoteattr(value)} style={quoteattr(style)} '
            f'edge="1" parent="1" source={quoteattr(source)} target={quoteattr(target)}>'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>'
        )


def _step_style(step: Step) -> str:
    hitl = "dashed=1;" if step.hitl else ""  # HITL gets a dashed border + label marker
    if step.decision is not None:
        return f"rhombus;whiteSpace=wrap;html=1;fillColor={DEC_FILL};strokeColor={DEC_STROKE};{hitl}"
    fill, stroke = (AUTO_FILL, AUTO_STROKE) if step.is_automated else (YOU_FILL, YOU_STROKE)
    return f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};{hitl}"


def _step_label(step: Step) -> str:
    label = f"{step.number}. {step.title}"
    if step.hitl:
        label += "\n⏸ review"
    return label


def _edge_style(src_rank: int, tgt_rank: int, src_row: int, tgt_row: int) -> str:
    """Orthogonal edge with exit/entry ports chosen from the node placement.

    Keeps the spine dead straight (right→left, same row) and makes a branch leave the
    decision from its top/bottom (so the fan is visible and labels sit on the vertical
    segment, off the boxes).
    """
    base = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;fontSize=11;"
    if tgt_row == src_row and tgt_rank > src_rank:          # spine: straight across
        ports = "exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;"
    elif tgt_row > src_row:                                 # branch downward
        entry = "entryX=0;entryY=0.5;" if tgt_rank > src_rank else "entryX=0.5;entryY=0;"
        ports = f"exitX=0.5;exitY=1;exitDx=0;exitDy=0;{entry}entryDx=0;entryDy=0;"
    elif tgt_row < src_row:                                 # branch upward
        entry = "entryX=0;entryY=0.5;" if tgt_rank > src_rank else "entryX=0.5;entryY=1;"
        ports = f"exitX=0.5;exitY=0;exitDx=0;exitDy=0;{entry}entryDx=0;entryDy=0;"
    else:                                                   # same row, backward: let it route
        ports = ""
    return base + ports


def render_diagram(
    process: Process,
    out_path: str | Path,
    *,
    title: str | None = None,
    subtitle: str | None = None,
) -> Path:
    """Write a ``.drawio`` workflow diagram for ``process``; returns the output path."""
    steps = process.steps
    ids = {s.number: f"s{s.number}" for s in steps}

    # ---- 1. build the logical graph: nodes (kind/label/style/size) + directed edges ----
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    nodes["start"] = dict(value="Start", w=ELL_W, h=ELL_H,
                          style=f"ellipse;whiteSpace=wrap;html=1;fillColor={END_FILL};strokeColor={END_STROKE};")
    nodes["end"] = dict(value="End", w=ELL_W, h=ELL_H,
                        style=f"ellipse;whiteSpace=wrap;html=1;fillColor={END_FILL};strokeColor={END_STROKE};")
    for s in steps:
        is_dec = s.decision is not None
        nodes[ids[s.number]] = dict(
            value=_step_label(s), style=_step_style(s),
            w=DEC_W if is_dec else STEP_W, h=DEC_H if is_dec else STEP_H,
            step=s.number,
        )

    terminals: dict[str, str] = {}

    def terminal(label: str) -> str:
        key = label.strip().lower()
        if key in terminals:
            return terminals[key]
        tid = f"t{len(terminals)}"
        nodes[tid] = dict(value=label, w=TERM_W, h=TERM_H,
                          style=f"rounded=1;whiteSpace=wrap;html=1;fillColor={EXIT_FILL};strokeColor={EXIT_STROKE};")
        terminals[key] = tid
        return tid

    def add_edge(src: str, tgt: str, label: str = "") -> None:
        edges.append(dict(s=src, t=tgt, label=label))

    # steps entered via a decision branch are NOT reached by the spine (don't chain them).
    decision_targets: set[int] = set()
    for s in steps:
        if s.decision is not None:
            for b in s.decision.branches:
                m = _is_step_target(b.target)
                if m is not None:
                    decision_targets.add(m)

    add_edge("start", ids[steps[0].number])
    for i, s in enumerate(steps):
        src = ids[s.number]
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        if s.decision is not None:
            for b in s.decision.branches:
                m = _is_step_target(b.target)
                if m is not None and m in ids:
                    add_edge(src, ids[m], b.label)
                else:
                    add_edge(src, terminal(b.target), b.label)
        elif nxt is not None and nxt.number not in decision_targets:
            add_edge(src, ids[nxt.number])
    # convergence: any step with no outgoing edge (a branch end action, or the last step)
    # flows to End so nothing dangles. Terminals are intentional sinks — leave them.
    have_out = {e["s"] for e in edges}
    for s in steps:
        if ids[s.number] not in have_out:
            add_edge(ids[s.number], "end")

    # ---- 2. rank each node by longest path from Start (DAG longest-path relaxation) ----
    succ: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        succ[e["s"]].append(e["t"])
    rank: dict[str, int] = {"start": 0}
    for _ in range(len(nodes) + 1):
        changed = False
        for e in edges:
            if e["s"] in rank and rank.get(e["t"], -1) < rank[e["s"]] + 1:
                rank[e["t"]] = rank[e["s"]] + 1
                changed = True
        if not changed:
            break
    for nid in nodes:
        rank.setdefault(nid, 0)

    # ---- 3. assign a row within each rank; the spine keeps row 0, branches fan up/down ----
    by_rank: dict[int, list[str]] = defaultdict(list)
    for nid in nodes:
        by_rank[rank[nid]].append(nid)

    def _sortkey(nid: str) -> tuple:
        n = nodes[nid]
        return (0, n["step"]) if "step" in n else (1, nid)  # steps first, ascending number

    row: dict[str, int] = {}
    for r, members in by_rank.items():
        # spine node = one that continues to the very next column (rank r+1).
        continues = [n for n in members if any(rank.get(t) == r + 1 for t in succ.get(n, []))]
        if "start" in members:
            row0 = "start"
        elif "end" in members:
            row0 = "end"
        else:
            row0 = sorted(continues or members, key=_sortkey)[0]
        row[row0] = 0
        # everyone else fans out: +1, -1, +2, -2, … (down first, then up)
        others = [n for n in sorted(members, key=_sortkey) if n != row0]
        for i, n in enumerate(others):
            row[n] = ((i // 2) + 1) * (1 if i % 2 == 0 else -1)

    # ---- 4. coordinates (centre boxes on the column/row grid so the spine aligns) ----
    def col_cx(r: int) -> float:
        return X0 + r * COL_W + COL_W / 2

    def row_cy(rw: int) -> float:
        return SPINE_Y + rw * ROW_H

    xml = _XML()
    ttl = title or process.name
    xml.vertex("title", ttl, "text;html=1;fontSize=20;fontStyle=1;align=left;", X0, 24, 760, 30)
    sub = subtitle if subtitle is not None else process.context
    if sub:
        xml.vertex("subtitle", sub, "text;html=1;fontSize=12;fontColor=#666666;align=left;", X0, 58, 960, 24)

    for nid, n in nodes.items():
        cx, cy = col_cx(rank[nid]), row_cy(row[nid])
        xml.vertex(nid, n["value"], n["style"], cx - n["w"] / 2, cy - n["h"] / 2, n["w"], n["h"])

    for k, e in enumerate(edges):
        style = _edge_style(rank[e["s"]], rank[e["t"]], row[e["s"]], row[e["t"]])
        xml.edge(f"e{k}", e["s"], e["t"], e["label"], style)

    # legend below the lowest node (labelled swatches — identity is never colour-alone).
    max_row = max(row.values())
    legend_y = row_cy(max_row) + ROW_H
    legend = (
        f'<b>Legend</b><br/>'
        f'<font color="{AUTO_STROKE}">■</font> Automated (the tool)&nbsp;&nbsp;'
        f'<font color="{YOU_STROKE}">■</font> You (operator)<br/>'
        f'<font color="{DEC_STROKE}">◆</font> Decision&nbsp;&nbsp;'
        f'<font color="{END_STROKE}">●</font> Start / End&nbsp;&nbsp;'
        f'<font color="{EXIT_STROKE}">■</font> Exit (reject / park)<br/>'
        f'<i>dashed border = needs your review (HITL)</i>'
    )
    xml.vertex("legend", legend,
               "text;html=1;align=left;verticalAlign=top;spacingLeft=8;spacingTop=6;"
               "fillColor=#f5f5f5;strokeColor=#cccccc;rounded=1;",
               X0, legend_y, 560, 90)

    body = "".join(xml.cells)
    doc = (
        '<mxfile host="app.diagrams.net">'
        f'<diagram name={quoteattr(ttl)}>'
        '<mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" '
        'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        'pageWidth="1600" pageHeight="900" math="0" shadow="0">'
        '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        f'{body}'
        '</root></mxGraphModel></diagram></mxfile>'
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out
