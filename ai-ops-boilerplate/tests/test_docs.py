"""Tests for the PROCESS_STEPS parser — the shared source-of-truth contract."""
from core.docs import parse_text

SAMPLE = """\
# Sample Automation — Process Steps
> Daily run before the payment cycle; ~1 working-day review window.

## Phase 1 — Fetch (portal)

### Step 1 — Log into the portal  `[AUTO · Playwright]`
Uses the SSO-persistent browser profile.
- **Screenshot:** login_page

### Step 2 — Download the exceptions report  `[AUTO · Playwright]`
Applies the region filter and downloads the report.

## Phase 2 — Review

### Step 3 — Assess each set  `[AUTO · Python]`
Classify and prioritise.
- **HITL:** yes
- **Decision:** Is it a confirmed duplicate?
  - Yes, not yet paid -> Step 4
  - No -> Release
- **Note:** ERP access would let us automate the lookup.

### Step 4 — Stop the payment  `[MANUAL]`
Notify the payments team.
"""


def test_parses_name_context_and_counts():
    p = parse_text(SAMPLE)
    assert p.name == "Sample Automation"
    assert "payment cycle" in p.context
    assert len(p.steps) == 4
    assert p.phases() == ["Fetch (portal)", "Review"]


def test_actor_tags_and_automation_flag():
    p = parse_text(SAMPLE)
    s1, s3, s4 = p.steps[0], p.steps[2], p.steps[3]
    assert s1.actors == ["AUTO"] and s1.is_automated
    assert "AUTO" in s3.actors
    assert s4.actors == ["MANUAL"] and not s4.is_automated and s4.is_manual
    assert len(p.automated_steps()) == 3


def test_metadata_hitl_screenshot_note_decision():
    p = parse_text(SAMPLE)
    s1, s3 = p.steps[0], p.steps[2]
    assert s1.screenshot == "login_page"
    assert s3.hitl is True
    assert s3.note and "ERP access" in s3.note
    assert s3.decision is not None
    assert s3.decision.question.endswith("?")
    assert [b.target for b in s3.decision.branches] == ["Step 4", "Release"]
    assert s3.decision.branches[0].label.startswith("Yes")


def test_description_captured_without_metadata_lines():
    p = parse_text(SAMPLE)
    assert p.steps[0].description == "Uses the SSO-persistent browser profile."
