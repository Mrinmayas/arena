"""Tests for the draw.io workflow renderer — stdlib only (no extra needed)."""
import xml.etree.ElementTree as ET

from core.docs import parse_text
from core.docs.drawio import render_diagram

SAMPLE = """\
# Sample Automation — Process Steps
> Daily run before the payment cycle.

## Phase 1 — Fetch

### Step 1 — Log into the portal  `[AUTO · Playwright]`
Uses the SSO-persistent browser profile.

### Step 2 — Assess each set  `[AUTO · Python]`
- **HITL:** yes
- **Decision:** Is it a confirmed duplicate?
  - Yes -> Step 3
  - No -> Release

### Step 3 — Stop the payment  `[MANUAL]`
Notify the payments team.
"""


def _cells(path):
    root = ET.parse(path).getroot()
    return root.findall(".//mxCell")


def test_wellformed_and_has_start_end_and_steps(tmp_path):
    p = parse_text(SAMPLE)
    out = render_diagram(p, tmp_path / "wf.drawio")
    cells = _cells(out)                      # parses => XML is well-formed
    ids = {c.get("id") for c in cells}
    assert {"start", "end", "s1", "s2", "s3"} <= ids
    assert any(c.get("id") == "legend" for c in cells)


def test_decision_is_rhombus_and_branches_become_edges(tmp_path):
    p = parse_text(SAMPLE)
    out = render_diagram(p, tmp_path / "wf.drawio")
    cells = _cells(out)
    by_id = {c.get("id"): c for c in cells}

    assert "rhombus" in by_id["s2"].get("style")          # decision shape
    assert "dashed=1" in by_id["s2"].get("style")         # HITL marker

    edges = [c for c in cells if c.get("edge") == "1"]
    # Yes -> Step 3 (jump to a step), No -> Release (drops to a terminal)
    labels = {e.get("value") for e in edges}
    assert "Yes" in labels and "No" in labels
    # the "No -> Release" branch created an exception terminal, not a step
    targets = {e.get("target") for e in edges}
    assert any(t and t.startswith("t") for t in targets)


FANOUT = """\
# Fan-out — Process Steps
> A decision with mutually-exclusive action steps.

## Phase 1 — Decide

### Step 1 — Assess  `[AUTO · Python]`
- **Decision:** Which action?
  - Pay -> Step 2
  - Refund -> Step 3
  - Escalate -> Step 4

### Step 2 — Pay  `[MANUAL]`
### Step 3 — Refund  `[MANUAL]`
### Step 4 — Escalate  `[MANUAL]`
"""


def test_mutually_exclusive_targets_do_not_chain_and_converge_to_end(tmp_path):
    p = parse_text(FANOUT)
    out = render_diagram(p, tmp_path / "wf.drawio")
    edges = [c for c in _cells(out) if c.get("edge") == "1"]
    pairs = {(e.get("source"), e.get("target")) for e in edges}
    # steps entered by a branch are NOT chained sequentially...
    assert ("s2", "s3") not in pairs and ("s3", "s4") not in pairs
    # ...they terminate at End instead of dangling
    assert ("s2", "end") in pairs and ("s3", "end") in pairs and ("s4", "end") in pairs
    # and the decision fans out to each
    assert {("s1", "s2"), ("s1", "s3"), ("s1", "s4")} <= pairs


def _geom(cell):
    g = cell.find("mxGeometry")
    return tuple(float(g.get(k)) for k in ("x", "y", "width", "height"))


def test_decision_targets_share_a_column_and_stack_on_rows(tmp_path):
    """Mutually-exclusive targets fan out vertically (same x, different y)."""
    p = parse_text(FANOUT)
    out = render_diagram(p, tmp_path / "wf.drawio")
    by_id = {c.get("id"): c for c in _cells(out) if c.get("vertex") == "1"}
    xs = {k: _geom(by_id[k])[0] for k in ("s2", "s3", "s4")}
    ys = {k: _geom(by_id[k])[1] for k in ("s2", "s3", "s4")}
    assert len(set(xs.values())) == 1          # same column (rank)
    assert len(set(ys.values())) == 3          # three distinct rows (no stacking collision)


def test_no_boxes_overlap(tmp_path):
    """The whole diagram is laid out without any two boxes intersecting."""
    p = parse_text(SAMPLE)
    out = render_diagram(p, tmp_path / "wf.drawio")
    boxes = [
        _geom(c) for c in _cells(out)
        if c.get("vertex") == "1" and c.get("id") not in ("title", "subtitle", "legend")
    ]

    def overlap(a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah

    clashes = [(i, j) for i in range(len(boxes)) for j in range(i + 1, len(boxes))
               if overlap(boxes[i], boxes[j])]
    assert clashes == []


def test_actor_colours_distinguish_auto_from_manual(tmp_path):
    p = parse_text(SAMPLE)
    out = render_diagram(p, tmp_path / "wf.drawio")
    by_id = {c.get("id"): c for c in _cells(out)}
    assert "#dae8fc" in by_id["s1"].get("style")          # automated = blue
    assert "#ffe6cc" in by_id["s3"].get("style")          # manual = orange
