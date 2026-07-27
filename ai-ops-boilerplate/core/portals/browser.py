"""Playwright browser/context factory for portal automations.

Two launch strategies, both generic and reusable across portals:

* :func:`launch_context` -- a fresh browser plus a context that is optionally
  *seeded* from a ``storage_state.json`` file (cookies / localStorage harvested
  from a previous authenticated session). This backs the **username/password**
  login pattern: a scripted login refreshes the seed whenever it expires.
* :func:`launch_persistent_context` -- a context backed by an on-disk *user data
  dir* (a persistent browser profile). Cookies, SSO tokens and cache survive
  across runs, so a one-time interactive single-sign-on keeps later runs logged
  in. This backs the **SSO-persistent-profile** login pattern.

Both return a :class:`BrowserHandle` that owns every Playwright resource so the
caller can close them cleanly in one call.

Depends only on the standard library and ``playwright``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

#: Sensible default window size; override per portal via the ``viewport`` argument.
DEFAULT_VIEWPORT = {"width": 1440, "height": 900}


@dataclass
class BrowserHandle:
    """Owns the Playwright driver, (optional) browser and context.

    ``browser`` is ``None`` for a persistent context, where
    :meth:`BrowserContext.close` also disposes of the underlying browser.
    """

    playwright: Playwright
    context: BrowserContext
    browser: Browser | None = None

    async def close(self) -> None:
        try:
            await self.context.close()
            if self.browser is not None:
                await self.browser.close()
        finally:
            await self.playwright.stop()


async def launch_context(
    *,
    downloads_dir: Path,
    storage_state: Path | None = None,
    headless: bool = False,
    channel: str | None = None,
    viewport: dict[str, int] | None = None,
) -> BrowserHandle:
    """Launch a fresh browser and a context, optionally seeded from ``storage_state``.

    Args:
        downloads_dir: directory downloads are saved into (created if missing).
        storage_state: path to a harvested ``storage_state.json`` auth seed. If it
            exists the context starts already authenticated; otherwise a clean
            context is created and the caller's scripted login should run.
        headless: run without a visible window.
        channel: browser channel, e.g. ``"msedge"`` or ``"chrome"``. ``None`` uses
            Playwright's bundled Chromium. Enterprises standardised on Edge pass
            ``channel="msedge"``.
        viewport: window size; defaults to :data:`DEFAULT_VIEWPORT`.
    """
    downloads_dir.mkdir(parents=True, exist_ok=True)
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(channel=channel, headless=headless)
    seed = str(storage_state) if storage_state and storage_state.exists() else None
    context = await browser.new_context(
        storage_state=seed,
        accept_downloads=True,
        viewport=viewport or DEFAULT_VIEWPORT,
    )
    return BrowserHandle(playwright=pw, browser=browser, context=context)


async def launch_persistent_context(
    *,
    user_data_dir: Path,
    downloads_dir: Path,
    headless: bool = False,
    channel: str | None = None,
    viewport: dict[str, int] | None = None,
) -> BrowserHandle:
    """Launch a context backed by a persistent on-disk profile (``user_data_dir``).

    Cookies and SSO tokens live in ``user_data_dir`` and survive across runs, so an
    interactive sign-on done once (often SSO/MFA, i.e. human-in-the-loop) keeps
    later runs authenticated. Prefer ``headless=False`` for the first run so the
    operator can complete the sign-on.

    Args mirror :func:`launch_context` except the profile replaces the auth seed.
    """
    user_data_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)
    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        str(user_data_dir),
        headless=headless,
        channel=channel,
        accept_downloads=True,
        viewport=viewport or DEFAULT_VIEWPORT,
    )
    return BrowserHandle(playwright=pw, context=context, browser=None)
