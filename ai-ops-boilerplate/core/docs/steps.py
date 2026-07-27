"""Canonical process-step model + parser — the single source of truth for docs.

`PROCESS_STEPS.md` is the agreed, code-reconciled description of an automation's
process. Both the doc-generation and workflow-diagram-generation skills render from
the model this module parses, so the README, the operator Word guide, and the drawio
diagram never drift from each other. Stdlib only.

See `core/docs/SCHEMA.md` for the authoring format. In brief::

    # <Name> — Process Steps
    > <one-line context>

    ## Phase 1 — <phase title>

    ### Step 1 — <title>  `[AUTO · Playwright]`
    <free-text description…>
    - **HITL:** yes
    - **Decision:** <question?>
      - <branch label> -> Step 3
      - <branch label> -> Reject
    - **Screenshot:** login_page
    - **Note:** <automation note>
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: Recognised actor tags. A step is automated if AUTO is present.
ACTORS = ("AUTO", "ERP", "MANUAL")


@dataclass
class Branch:
    """One outgoing path from a decision: a label and where it goes."""
    label: str
    target: str  # "Step N" | "Reject" | "Park" | "End" | free text


@dataclass
class Decision:
    """A branch point. Its presence makes the step render as a rhombus."""
    question: str
    branches: list[Branch] = field(default_factory=list)


@dataclass
class Step:
    number: int
    title: str
    phase: str
    tag: str                       # raw tag text, e.g. "AUTO · Playwright"
    actors: list[str] = field(default_factory=list)  # subset of ACTORS
    description: str = ""
    hitl: bool = False             # human-in-the-loop / review step
    decision: Decision | None = None
    screenshot: str | None = None  # recorder capture id to embed (operator doc)
    note: str | None = None

    @property
    def is_automated(self) -> bool:
        return "AUTO" in self.actors

    @property
    def is_manual(self) -> bool:
        # ERP-only or MANUAL steps are performed by a person.
        return not self.is_automated and bool(self.actors or True)


@dataclass
class Process:
    name: str
    context: str = ""
    steps: list[Step] = field(default_factory=list)

    def phases(self) -> list[str]:
        seen: list[str] = []
        for s in self.steps:
            if s.phase and s.phase not in seen:
                seen.append(s.phase)
        return seen

    def by_phase(self) -> dict[str, list[Step]]:
        out: dict[str, list[Step]] = {}
        for s in self.steps:
            out.setdefault(s.phase, []).append(s)
        return out

    def automated_steps(self) -> list[Step]:
        return [s for s in self.steps if s.is_automated]


# --- parsing ---------------------------------------------------------------
_H1 = re.compile(r"^#\s+(.*)$")
_H2 = re.compile(r"^##\s+(.*)$")
_STEP = re.compile(r"^###\s+Step\s+(\d+)\s*[—\-]\s*(.*)$")
_TAG = re.compile(r"`\[([^\]]+)\]`\s*$")
_META = re.compile(r"^\s*[-*]\s+\*\*(HITL|Decision|Screenshot|Note)\s*:?\s*\*\*\s*:?\s*(.*)$", re.I)
_BRANCH = re.compile(r"^\s+[-*]\s+(.*?)\s*(?:->|→)\s*(.+)$")
_FALSEY = {"no", "false", "n", "0"}


def parse_text(md: str) -> Process:
    """Parse PROCESS_STEPS markdown into a :class:`Process`."""
    name = ""
    context = ""
    phase = ""
    steps: list[Step] = []
    cur: Step | None = None
    desc: list[str] = []
    pending_decision: Decision | None = None

    def flush() -> None:
        nonlocal cur, desc
        if cur is not None:
            cur.description = "\n".join(desc).strip()
            steps.append(cur)
        cur, desc = None, []

    for raw in md.splitlines():
        line = raw.rstrip()

        if line.startswith("### "):
            m = _STEP.match(line)
            if m:
                flush()
                pending_decision = None
                rest = m.group(2).strip()
                tag = ""
                tm = _TAG.search(rest)
                if tm:
                    tag = tm.group(1).strip()
                    rest = rest[: tm.start()].strip()
                actors = [a for a in ACTORS if re.search(rf"\b{a}\b", tag, re.I)]
                cur = Step(number=int(m.group(1)), title=rest, phase=phase, tag=tag, actors=actors)
                continue

        if line.startswith("## "):
            flush()
            pending_decision = None
            t = _H2.match(line).group(1).strip()
            phase = re.sub(r"^Phase\s+[\w.]+\s*[—\-]\s*", "", t).strip()
            continue

        if line.startswith("# "):
            nm = _H1.match(line).group(1).strip()
            name = re.sub(r"\s*[—\-]\s*Process Steps\s*$", "", nm).strip()
            continue

        if cur is None:
            if line.startswith(">") and not context:
                context = line.lstrip(">").strip()
            continue

        meta = _META.match(line)
        if meta:
            key, val = meta.group(1).lower(), meta.group(2).strip()
            if key == "hitl":
                cur.hitl = val.lower() not in _FALSEY
            elif key == "decision":
                cur.decision = Decision(question=val)
                pending_decision = cur.decision
            elif key == "screenshot":
                cur.screenshot = val or None
            elif key == "note":
                cur.note = val or None
            continue

        br = _BRANCH.match(line)
        if br and pending_decision is not None:
            pending_decision.branches.append(Branch(label=br.group(1).strip(), target=br.group(2).strip()))
            continue

        if line.strip():
            desc.append(line.strip())

    flush()
    return Process(name=name, context=context, steps=steps)


def parse_file(path: str | Path) -> Process:
    return parse_text(Path(path).read_text(encoding="utf-8"))
