"""Reusable enterprise-portal access (generic boilerplate).

Layers:
  - ``Portal`` (base) -- shared lifecycle: launch a context (seeded ``storage_state``
    OR persistent profile), detect auth, run ``login`` if needed, then
    navigate/download/upload. Framework-agnostic: run state is injected
    (``secrets``, ``workspace``, ``headless``, optional ``log`` callback).
  - ``BrowserPortal`` -- the recommended default for corporate SSO / Conditional
    Access sites: zero-prompt default channel, persistent per-channel profile,
    tiered login click-flow, and per-run web-session teardown.
  - ``browser`` -- the low-level Playwright launchers both patterns build on.

``example.py`` holds copy-me templates (not exported); one module per real portal
subclasses these so a portal UI change is a one-file fix.

Depends only on the standard library and ``playwright``.
"""

from __future__ import annotations

from .base import Portal, SecretProvider
from .browser import BrowserHandle, launch_context, launch_persistent_context
from .browser_portal import (
    CLICK_RETRY_TIMEOUTS_MS,
    DEFAULT_TIMEOUT_MS,
    LOGIN_TIMEOUT_MS,
    BrowserPortal,
    settle,
    try_click,
)

__all__ = [
    "Portal",
    "SecretProvider",
    "BrowserPortal",
    "BrowserHandle",
    "launch_context",
    "launch_persistent_context",
    "try_click",
    "settle",
    "DEFAULT_TIMEOUT_MS",
    "LOGIN_TIMEOUT_MS",
    "CLICK_RETRY_TIMEOUTS_MS",
]
