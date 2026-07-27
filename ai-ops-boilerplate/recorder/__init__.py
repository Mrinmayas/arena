"""Development-time Playwright recorder.

Launches a browser, records a full Playwright trace of the session, and exposes
an in-page Capture button that saves a tagged bundle (screenshots + HTML +
storage + console/network log) for each manual snapshot.

Portal- and environment-specific settings (browser channel, persistent profile
path, API-path heuristic, start URL, output dir) live on ``RecorderConfig`` in
``config.py``; its defaults reproduce the original Microsoft Edge / Entra
behavior, so retargeting a non-Microsoft portal is a config change, not a code
edit.
"""

from .config import RecorderConfig
from .recorder import run_session

__all__ = ["RecorderConfig", "run_session"]
