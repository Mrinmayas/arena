"""Documentation generation from a single, code-reconciled source of truth.

`PROCESS_STEPS.md` is the agreed description of an automation's process (reconciled
against the actual code). This package parses it into a model that the doc-generation
and workflow-diagram-generation skills render into the README, an operator Word guide,
and a drawio workflow diagram — so all three stay in sync with one source.

Parsing is stdlib-only. Rendering to `.docx` needs the `docs` extra (python-docx);
drawio rendering is stdlib (it writes mxGraph XML).
"""
from .steps import Branch, Decision, Process, Step, parse_file, parse_text

__all__ = ["Process", "Step", "Decision", "Branch", "parse_text", "parse_file"]
