---
name: portal-login
description: >-
  Use whenever you log an automation into an enterprise portal — corporate SSO
  (Entra / Conditional Access / MFA) or a username+password form — driven by
  Playwright. Triggers: login, sign in, SSO, portal, Playwright, Entra, MFA,
  Conditional Access, username password, browser, credentials, storage_state,
  persistent profile, msedge. Grounds the agent in core.portals (Portal /
  BrowserPortal) and core.secretstore so a portal is a small subclass that never
  hardcodes credentials and reuses device compliance. Without it, agents hand-roll
  Playwright launches, paste passwords into source or .env, use throwaway guest
  profiles that Conditional Access rejects, and sprinkle fixed sleeps.
---

# Portal login — SSO or username/password, credentials from the keychain

Every portal login goes through **`core.portals`**. A concrete portal is a small
subclass that sets a few class attributes; the base classes own the browser
lifecycle (launch, auth detection, login, navigate/download/upload, teardown).
Credentials **always** come from **`core.secretstore`** (the OS keychain) — never
from source, a committed `.env`, or a hardcoded string.

Two first-class patterns, both in `core/portals/example.py` — copy one:

- **SSO (recommended default)** — subclass `BrowserPortal`. A persistent per-channel
  browser profile presents the device's real Entra/Intune compliance state, so
  Conditional Access accepts it; the operator completes SSO/MFA once, by hand, in a
  headed window. This is `ExampleSsoPortal`.
- **Username/password** — subclass `Portal` directly. A seeded `storage_state.json`
  keeps you logged in; when it expires, a scripted `login()` fills the form using
  secrets pulled via `self.secrets.require_secret(...)`. This is `ExamplePasswordPortal`.

## The one rule: subclass a portal base; secrets come from the keychain

Set class attributes on a `Portal`/`BrowserPortal` subclass and fetch every
credential with `self.secrets.require_secret(SecretKey.…)`. Never launch Playwright
by hand for a login, and never write a password anywhere but the OS keychain.

## Decision tree

- **Corporate SSO / Entra / Conditional Access / MFA?** → subclass **`BrowserPortal`**.
  Set `login_url`, `success_url_glob`, and one of `login_click_text` / `login_selector`.
  No `login()` override needed — the base drives click-then-wait generically.
- **Plain username + password form?** → subclass **`Portal`**. Set `login_url` and
  `storage_state_path`; implement `_on_login_page()` and `login()` (fill + submit).
- **Where do credentials come from?** → the injected store, via
  `self.secrets.require_secret(SecretKey.YOUR_PORTAL_PASSWORD)`. Add the keys to
  `core/secretstore/keys.py` (`SecretKey`); store the values once with the CLI/keychain.
  Never in code, `.env`, or git.
- **Headed or headless?** → **headed (`headless=False`) for SSO** so a human can
  complete MFA. Headless is only safe once a valid `storage_state`/profile already
  exists and no interactive step is needed.
- **Which store backend?** → `get_default_store()` picks per platform (Windows →
  `WindowsSecretStore`/WinCred, macOS → `MacOSSecretStore`/Keychain). Don't hardcode one.
- **Edge not installed / CI?** → `default_channel="msedge"` needs Edge
  (`playwright install msedge`); pass `channel=None` to use bundled Chromium instead.

## Minimal shape — SSO portal (the common case)

```python
# automation/portals/my_portal.py
from core.portals import BrowserPortal


class MyPortal(BrowserPortal):
    name = "my-portal"
    login_url = "https://portal.example.com/"
    success_url_glob = "**/dashboard"        # reaching this URL == authenticated
    login_click_text = "Sign in"             # or: login_selector = "button.sso"
    # profile_root, default_channel ("msedge"), and the timeout knobs inherit
    # BrowserPortal's defaults — override only if you must.
```

Run it (async context manager, opened **headed** so the operator can do SSO/MFA):

```python
from pathlib import Path
from core.secretstore import get_default_store
from automation.portals.my_portal import MyPortal

store = get_default_store()  # Windows -> WinCred, macOS -> Keychain

async with await MyPortal.open(
    secrets=store, workspace=Path("runs/today"), headless=False, log=print
) as portal:
    await portal.navigate(portal.login_url + "reports")
    await portal.download(Path("runs/today/report.xlsx"), click="#export")
```

## Minimal shape — username/password portal

```python
from pathlib import Path
from core.portals import Portal
from core.secretstore import SecretKey   # add MY_PORTAL_* members to keys.py


class MyPasswordPortal(Portal):
    name = "my-password-portal"
    login_url = "https://portal.example.com/login"
    storage_state_path = Path("data/portals/my-portal/storage_state.json")  # gitignored

    async def _on_login_page(self) -> bool:
        assert self.page is not None
        return await self.page.locator("input#username").count() > 0

    async def login(self) -> None:
        assert self.page is not None
        user = self.secrets.require_secret(SecretKey.MY_PORTAL_USERNAME)
        pw = self.secrets.require_secret(SecretKey.MY_PORTAL_PASSWORD)
        await self.page.fill("input#username", user)
        await self.page.fill("input#password", pw)
        await self.page.click("button[type=submit]")
        await self.page.wait_for_load_state("networkidle")
```

`Portal.open(...)` runs `login()` only when `_is_authenticated()` is false, then calls
`save_storage_state()` to refresh the seed so the next run skips the form.

## Non-negotiables

1. **Never hardcode credentials.** Pull every secret with
   `self.secrets.require_secret(SecretKey.…)`; register the key in `SecretKey`
   (`core/secretstore/keys.py`) and store its value in the OS keychain. No passwords
   in source, `.env`, logs, or git.
2. **SSO runs headed.** Open with `headless=False` so a human completes SSO/MFA.
   Never expect an unattended headless run to pass Conditional Access on first login.
3. **Use the persistent profile for SSO.** `BrowserPortal` launches a persistent
   per-channel `user_data_dir` so device compliance is preserved. Do not swap in a
   throwaway/guest context — Conditional Access rejects it. `profile_root` holds live
   auth tokens: keep it out of git (it is treated as sensitive).
4. **Go through `core.portals`.** Subclass `Portal` / `BrowserPortal`; don't call
   `playwright` launch APIs directly for a login. Reuse `navigate` / `download` /
   `upload` and the base lifecycle.
5. **No fixed sleeps.** Rely on locator auto-wait and the named timeout constants
   (`DEFAULT_TIMEOUT_MS`, `LOGIN_TIMEOUT_MS`, `CLICK_RETRY_TIMEOUTS_MS`) / helpers
   (`settle`, `try_click`). Never `asyncio.sleep(n)` to "wait for the page".
6. **Pick the store via the factory.** Use `get_default_store()` (or `get_store(name)`);
   don't hardcode a backend. On unsupported platforms/CI set `AI_OPS_SECRET_STORE`.
7. **`msedge` needs Edge installed.** `playwright install msedge`, or pass
   `channel=None` for bundled Chromium.

For the four SSO mechanics and full attribute/timeout reference, see
`reference/api.md`.
