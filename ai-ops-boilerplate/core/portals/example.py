"""Portal templates -- copy one of these when onboarding a real portal.

Two first-class login patterns are shown; both inherit the shared lifecycle
(context launch, auth detection, navigate/download/upload) from ``Portal``:

* ``ExampleSsoPortal`` -- **SSO via a persistent browser profile**, subclassing
  ``BrowserPortal`` (the boilerplate's recommended default for corporate
  Conditional-Access portals). A one-time interactive sign-on is reused via the
  on-disk profile; cookies are wiped each run so login is always fresh while the
  device stays compliant. Usually you only set the URLs and the SSO control.

* ``ExamplePasswordPortal`` -- scripted **username/password** login against a
  seeded ``storage_state`` context. Credentials come from the injected secret
  store; the seed is refreshed after each login so later runs skip the form.

To adapt: set the class attributes, wire your project's ``SecretKey`` members
(for the password pattern), and replace the selectors/URLs with the real ones.
"""

from __future__ import annotations

from pathlib import Path

from .base import Portal
from .browser_portal import BrowserPortal

# The password template references the sibling secret registry only to show the
# real wiring. The core framework modules (base.py, browser.py, browser_portal.py)
# depend solely on stdlib + playwright; this import lives in the template you copy.
from ..secretstore import SecretKey


class ExampleSsoPortal(BrowserPortal):
    """SSO portal template -- persistent profile, zero-prompt, session reset on close."""

    name = "example-sso"
    login_url = "https://portal.example.com/"
    success_url_glob = "**/dashboard"
    login_click_text = "Sign in"  # or set login_selector = "..."
    # profile_root / default_channel / timeouts inherit BrowserPortal's defaults.

    # No _on_login_page / login overrides needed: BrowserPortal detects auth from
    # success_url_glob and drives the click-then-wait SSO flow generically. Open
    # this portal headed (headless=False) so the operator can complete SSO/MFA.


class ExamplePasswordPortal(Portal):
    """Username/password portal template -- seeded storage_state, scripted login."""

    name = "example-password"
    login_url = "https://portal.example.com/login"
    storage_state_path = Path("data/portals/example/storage_state.json")

    async def _on_login_page(self) -> bool:
        assert self.page is not None
        return await self.page.locator("input#username").count() > 0

    async def login(self) -> None:
        assert self.page is not None
        username = self.secrets.require_secret(SecretKey.EXAMPLE_PORTAL_USERNAME)
        password = self.secrets.require_secret(SecretKey.EXAMPLE_PORTAL_PASSWORD)
        await self.page.fill("input#username", username)
        await self.page.fill("input#password", password)
        await self.page.click("button[type=submit]")
        await self.page.wait_for_load_state("networkidle")
