"""Configuration for the Playwright recorder.

Everything that is portal- or environment-specific lives here, so pointing the
recorder at a new client's portal is a config change rather than a code edit.

The defaults reproduce the recorder's original behavior (Microsoft Edge, an
Entra/SharePoint-flavored API-path heuristic, a profile kept beside the
package), so nothing regresses out of the box. Override any field on
``RecorderConfig`` — or pass the matching CLI flag — to retarget a
non-Microsoft portal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Recordings and the persistent browser profile are anchored beside the package
# so they always land in the same place regardless of the working directory.
# config.py -> recorder/ -> <package parent>
_PACKAGE_PARENT = Path(__file__).parent.parent
DEFAULT_OUTPUT_DIR: Path = _PACKAGE_PARENT / "recordings"
DEFAULT_PROFILE_DIR: Path = _PACKAGE_PARENT / ".recorder-profile"

# Persistent browser channel. "msedge" matches the original Edge + Entra setup.
# Use "chrome", "msedge-beta", "chrome-beta", etc. for other environments, or
# an empty string / None to fall back to Playwright's bundled Chromium.
DEFAULT_BROWSER_CHANNEL: str | None = "msedge"

# General (not portal-specific) heuristic for "this looks like an API call",
# used as ONE signal when curating api_calls.json from the full HAR. The
# default recognizes Microsoft/SharePoint/Graph shapes (/_api/, /_vti_bin/,
# graph.microsoft.com, /odata) alongside generic /api/ and /rest/. Override it
# with a pattern that matches the target portal's API surface.
DEFAULT_API_PATH_PATTERN: str = (
    r"(/_api/|/_vti_bin/|/api/|graph\.microsoft\.com|/odata|/rest/)"
)

# Launch viewport. Kept configurable so a portal that only lays out correctly at
# a particular width isn't stuck with the default.
DEFAULT_VIEWPORT_WIDTH = 1440
DEFAULT_VIEWPORT_HEIGHT = 900


@dataclass
class RecorderConfig:
    """All knobs for a recording session.

    Fields:
        start_url: Initial URL to open. "about:blank" opens an empty tab.
        session_name: Folder name under ``output_dir``. ``None`` uses a
            timestamp (``session_<YYYYmmdd_HHMMSS>``).
        output_dir: Where session folders are written.
        profile_dir: Persistent browser profile directory, kept between runs so
            portal logins are remembered.
        browser_channel: Playwright browser channel (e.g. "msedge", "chrome").
            Empty string / ``None`` uses the bundled Chromium.
        api_path_pattern: Regex (case-insensitive) marking a URL as API-ish when
            curating ``api_calls.json``.
        headless: Launch without a visible window. The overlay UI needs a
            visible window, so this defaults to ``False``.
        viewport_width / viewport_height: Launch viewport size in pixels.
    """

    start_url: str = "about:blank"
    session_name: str | None = None
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)
    profile_dir: Path = field(default_factory=lambda: DEFAULT_PROFILE_DIR)
    browser_channel: str | None = DEFAULT_BROWSER_CHANNEL
    api_path_pattern: str = DEFAULT_API_PATH_PATTERN
    headless: bool = False
    viewport_width: int = DEFAULT_VIEWPORT_WIDTH
    viewport_height: int = DEFAULT_VIEWPORT_HEIGHT

    def api_path_re(self) -> re.Pattern[str]:
        """Compile ``api_path_pattern`` into a case-insensitive regex."""
        return re.compile(self.api_path_pattern, re.I)

    @property
    def viewport(self) -> dict[str, int]:
        """Playwright ``viewport`` kwarg for context launch."""
        return {"width": self.viewport_width, "height": self.viewport_height}
