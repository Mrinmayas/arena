"""Default SSO browser-login portal for enterprise (Entra / Conditional Access) sites.

``BrowserPortal`` is the boilerplate's recommended baseline for portals behind
corporate single-sign-on. It codifies four mechanics, generalised from a
production portal automation, into a portal-agnostic base:

1. **Zero-prompt default channel.** The browser channel is a parameter
   (``default_channel``, defaults to ``"msedge"``) and is launched directly — no
   interactive picker, no ``input()``, nothing blocks an unattended run.
2. **Persistent profile for device compliance.** Launches a persistent
   ``user_data_dir`` (one sub-folder per channel), not a throwaway guest context.
   A persistent profile presents the device's real Entra/Intune compliance state
   to Conditional Access; a fresh guest profile is typically rejected as a
   non-compliant device. Sign in once per profile; later runs reuse the device
   identity.
3. **Tiered login click-flow.** ``login()`` navigates to ``login_url``, best-effort
   clicks the SSO entry control (short timeout, no retries — the operator may
   click it themselves), then waits up to ``login_timeout_ms`` for the app to
   reach ``success_url_glob``. Element clicks elsewhere use :func:`try_click`'s
   tiered schedule of named timeout constants (never fixed sleeps).
4. **Per-run session teardown.** On close, cookies + local/session storage are
   wiped (best-effort, never raising) while the persistent profile is **kept**.
   This forces a fresh login next run (avoids stale-SPA state) yet device
   compliance still passes, because device identity lives in the OS/browser
   broker and the profile on disk — not in the cleared cookies.

Everything portal-specific (URL, SSO control text/selector, success URL, channel,
profile location, timeouts) is a class attribute or constructor parameter with a
sensible default. Depends only on the standard library and ``playwright``.

Open it headed (``headless=False``) so the operator can complete SSO/MFA::

    async with await MyPortal.open(
        secrets=store, workspace=Path("runs/today"), headless=False, log=print
    ) as portal:
        await portal.navigate(portal.login_url + "/reports")
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PWTimeout

from .base import Portal

# --------------------------------------------------------------------------- #
# Named timeout constants (never fixed sleeps).
# --------------------------------------------------------------------------- #
#: Generous per-locator / navigation ceiling for slow enterprise SPAs. Locators
#: auto-wait, so a fast page proceeds immediately and a slow one waits up to this.
DEFAULT_TIMEOUT_MS = 45_000
#: How long to wait for the app to reach the post-login URL while SSO/MFA is
#: completed (often by hand) before giving up and leaving it to the operator.
LOGIN_TIMEOUT_MS = 180_000
#: Tiered click schedule: a quick attempt for the common case, then two longer
#: retries. 3 + 20 + 20 = 43s covers the vast majority of slow renders; a final
#: dynamic (networkidle) attempt catches the rare straggler.
CLICK_RETRY_TIMEOUTS_MS: tuple[int, ...] = (3_000, 20_000, 20_000)


async def settle(
    page: Page,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    log: Callable[[str], None] | None = None,
) -> None:
    """Best-effort wait for the page to stop loading before locating elements.

    Blocks only as long as the page actually needs, up to ``timeout_ms``; never a
    fixed sleep. A timeout is swallowed (the caller's next locator will re-wait).
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PWTimeout:
        if log is not None:
            log("page still busy after waiting — continuing anyway")


async def try_click(
    page: Page,
    *,
    text: str | None = None,
    selector: str | None = None,
    attempts_ms: tuple[int, ...] = CLICK_RETRY_TIMEOUTS_MS,
    dynamic_timeout_ms: int = DEFAULT_TIMEOUT_MS,
    log: Callable[[str], None] | None = None,
) -> bool:
    """Best-effort click with a tiered wait schedule. Returns True on success.

    Target the element by visible ``text`` (substring match) or a raw ``selector``.
    Each ``click(timeout=T)`` auto-waits up to ``T`` for the element to be
    clickable, so the windows chain to cover continuous time. If every tiered
    attempt misses, wait for the page to go idle and make one final attempt.
    """
    if selector is not None:
        locator = page.locator(selector).first
        label = selector
    elif text is not None:
        locator = page.get_by_text(text, exact=False).first
        label = text
    else:
        raise ValueError("try_click needs text= or selector=")

    for attempt, t in enumerate(attempts_ms, 1):
        if log is not None:
            log(f"click {label!r} — attempt {attempt}/{len(attempts_ms)} (up to {t // 1000}s)")
        try:
            await locator.click(timeout=t)
            return True
        except PWTimeout:
            continue

    # Rare very-slow case: let the page go idle, then try once more.
    await settle(page, timeout_ms=dynamic_timeout_ms, log=log)
    try:
        await locator.click(timeout=dynamic_timeout_ms)
        return True
    except PWTimeout:
        if log is not None:
            log(f"auto-click missed for {label!r}")
        return False


def _glob_needle(glob: str) -> str:
    """Reduce a URL glob to a plain substring for a quick 'are we there yet' check.

    ``"**/dashboard"`` -> ``"/dashboard"``. Playwright's ``wait_for_url`` does the
    real glob match; this is only for the cheap already-authenticated shortcut.
    """
    return glob.replace("*", "")


class BrowserPortal(Portal):
    """Persistent-profile SSO portal. Subclass and set the class attributes below.

    A concrete portal usually only needs to set ``name``, ``login_url``,
    ``success_url_glob`` and (optionally) ``login_click_text``/``login_selector``.
    """

    #: Entry URL; shows the SSO login when the session is not authenticated.
    login_url: str = ""
    #: Glob for the definitive post-login URL, e.g. ``"**/dashboard"``. Reaching it
    #: means we're authenticated.
    success_url_glob: str = ""
    #: Visible text of the SSO entry control to click (e.g. ``"Sign in"``).
    #: Optional — leave ``None`` if SSO starts automatically or the operator clicks.
    login_click_text: str | None = None
    #: Alternatively, a CSS/XPath selector for the SSO entry control.
    login_selector: str | None = None

    #: Root under which per-channel persistent profiles live. Holds live auth
    #: tokens — treat as sensitive, keep out of version control.
    profile_root: Path = Path("data/portals/profiles")
    #: Browser channel launched when the caller passes ``channel=None``. Edge is
    #: the enterprise default (broker-backed device identity for Conditional Access).
    default_channel: str | None = "msedge"

    #: Wipe cookies + web storage on close (keeping the profile) so each run logs
    #: in fresh. Set False for portals where session reuse across runs is fine.
    reset_session_on_close: bool = True

    #: Overridable timeout knobs (see the module-level constants for rationale).
    default_timeout_ms: int = DEFAULT_TIMEOUT_MS
    login_timeout_ms: int = LOGIN_TIMEOUT_MS
    click_retry_timeouts_ms: tuple[int, ...] = CLICK_RETRY_TIMEOUTS_MS

    def __init__(self, **kwargs: object) -> None:
        # Default the channel to this portal's default_channel (mechanic #1:
        # a sensible default is launched with no prompt) when none is injected.
        if kwargs.get("channel") is None:
            kwargs["channel"] = self.default_channel
        super().__init__(**kwargs)  # type: ignore[arg-type]

    # -- mechanic #2: persistent per-channel profile -------------------------- #
    def _profile_dir(self) -> Path:
        return self.profile_root / (self.channel or "default")

    async def _configure_page(self) -> None:
        # Slow environments: every locator/navigation inherits this ceiling.
        assert self.page is not None
        self.page.set_default_timeout(self.default_timeout_ms)
        self.page.set_default_navigation_timeout(self.default_timeout_ms)

    async def _on_login_page(self) -> bool:
        """We still need to log in unless we've already reached ``success_url_glob``."""
        assert self.page is not None
        if self.success_url_glob:
            return _glob_needle(self.success_url_glob) not in self.page.url
        if self.login_selector is not None:
            return await self.page.locator(self.login_selector).count() > 0
        if self.login_click_text is not None:
            return await self.page.get_by_text(self.login_click_text, exact=False).count() > 0
        return True

    # -- mechanic #3: tiered login click-flow --------------------------------- #
    async def login(self) -> None:
        page = self.page
        assert page is not None
        # Best-effort: click the SSO entry control IF present, with a short timeout
        # and no retries — the operator may click it, or finish login, themselves,
        # so we never hammer a button that's already gone.
        if self.login_selector is not None or self.login_click_text is not None:
            try:
                if self.login_selector is not None:
                    await page.locator(self.login_selector).first.click(timeout=4_000)
                else:
                    await page.get_by_text(self.login_click_text, exact=False).first.click(
                        timeout=4_000
                    )
            except PWTimeout:
                self.log(f"{self.name}: SSO control not clicked by us — you may be logging in")

        self.log(f"{self.name}: complete SSO/MFA in the browser window if prompted")
        if self.success_url_glob:
            try:
                await page.wait_for_url(self.success_url_glob, timeout=self.login_timeout_ms)
                self.log(f"{self.name}: reached post-login page — authenticated")
            except PWTimeout:
                self.log(
                    f"{self.name}: timed out waiting for the post-login URL — "
                    "confirm the home page is visible"
                )
        await settle(page, timeout_ms=self.default_timeout_ms, log=self._log)

    # -- mechanic #4: per-run session teardown (keep the profile) ------------- #
    async def reset_session(self) -> None:
        """Wipe cookies + web storage so the next run logs in fresh.

        The persistent profile on disk is KEPT (device compliance depends on it);
        only the *web session* is cleared. Best-effort — never raises.
        """
        page = self.page
        try:
            await self.context.clear_cookies()
        except Exception as exc:  # noqa: BLE001 - cleanup must never mask the outcome
            self.log(f"{self.name}: could not clear cookies: {exc!r}")
        if page is not None:
            try:
                await page.evaluate(
                    "() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} }"
                )
            except Exception as exc:  # noqa: BLE001
                self.log(f"{self.name}: could not clear web storage: {exc!r}")
        self.log(f"{self.name}: cleared web session (next run will require login)")

    async def close(self) -> None:
        # Reset the session BEFORE tearing the context down — the equivalent of
        # the source automation's finally block, reconciled with the persistent profile:
        # clear cookies/storage but leave user_data_dir intact.
        if self._handle is not None and self.reset_session_on_close and self.page is not None:
            try:
                await self.reset_session()
            except Exception as exc:  # noqa: BLE001
                self.log(f"{self.name}: session reset failed: {exc!r}")
        await super().close()
