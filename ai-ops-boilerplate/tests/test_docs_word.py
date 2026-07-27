"""Tests for the operator Word renderer. Skipped unless the `docs` extra is installed."""
import zipfile

import pytest

pytest.importorskip("docx", reason="install the 'docs' extra: uv sync --extra docs")

from core.docs import parse_text  # noqa: E402
from core.docs.word import render_operator_guide  # noqa: E402

SAMPLE = """\
# Sample Automation — Process Steps
> Daily run before the payment cycle.

## Phase 1 — Fetch (portal)

### Step 1 — Log into the portal  `[AUTO · Playwright]`
Uses the SSO-persistent browser profile.

## Phase 2 — Review

### Step 2 — Assess each set  `[AUTO · Python]`
Classify and prioritise.
- **HITL:** yes
- **Decision:** Is it a confirmed duplicate?
  - Yes -> Step 3
  - No -> Release

### Step 3 — Stop the payment  `[MANUAL]`
Notify the payments team.
"""


def _docx_text(path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    # strip tags so we can assert on the visible text
    import re
    return re.sub(r"<[^>]+>", " ", xml)


def test_renders_docx_with_expected_content(tmp_path):
    p = parse_text(SAMPLE)
    out = render_operator_guide(p, tmp_path / "guide.docx")
    assert out.exists() and out.stat().st_size > 0

    text = _docx_text(out)
    assert "Sample Automation — Operator Guide" in text
    assert "Fetch (portal)" in text and "Review" in text          # phase headings
    assert "Step 1 — Log into the portal" in text
    assert "[Automated]" in text                                   # automated tag
    assert "[You]" in text                                         # manual tag (Step 3)
    assert "Review needed" in text                                 # HITL callout on Step 2
    assert "Is it a confirmed duplicate?" in text                  # decision question
    assert "Yes → Step 3" in text                                  # branch


def test_missing_screenshot_dir_is_ignored(tmp_path):
    p = parse_text(SAMPLE)
    # no screenshots_dir passed -> must not raise even though nothing to embed
    out = render_operator_guide(p, tmp_path / "guide.docx")
    assert out.exists()
