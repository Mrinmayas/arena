# portal-login — API reference

Grounded in `core/portals/` and `core/secretstore/`. Every symbol below exists in
those modules; do not invent others.

## The four SSO mechanics `BrowserPortal` codifies

`BrowserPortal` (`core/portals/browser_portal.py`) generalises a production SSO flow
into a portal-agnostic base. Its module docstring names four mechanics:

1. **Zero-prompt default channel.** The browser channel is a parameter
   (`default_channel`, default `"msedge"`) launched directly — no interactive picker,
   nothing blocks an unattended run. `__init__` defaults `channel` to `default_channel`
   when none is injected.
2. **Persistent profile for device compliance.** Launches a persistent
   `user_data_dir` (one sub-folder per channel via `_profile_dir()` → `profile_root /
   channel`), not a throwaway guest context. A persistent profile presents the device's
   real Entra/Intune compliance state to Conditional Access; a fresh guest profile is
   typically rejected. Sign in once per profile; later runs reuse the device identity.
3. **Tiered login click-flow (no fixed sleeps).** `login()` best-effort clicks the SSO
   entry control (short 4s timeout, no retries — the operator may click it), then waits
   up to `login_timeout_ms` for the app to reach `success_url_glob`. Other clicks use
   `try_click()`'s tiered schedule of named timeout constants.
4. **Per-run session teardown that keeps the profile.** On `close()`, if
   `reset_session_on_close` is true, `reset_session()` wipes cookies + local/session
   storage (best-effort, never raising) while the persistent profile on disk is **kept**.
   Fresh login next run, but device compliance still passes because device identity
   lives in the OS/browser broker and the on-disk profile, not the cleared cookies.

## `BrowserPortal` class attributes

| Attribute | Default | Purpose |
| --- | --- | --- |
| `login_url` | `""` | Entry URL; shows SSO login when unauthenticated. |
| `success_url_glob` | `""` | Glob for the post-login URL (e.g. `"**/dashboard"`); reaching it == authenticated. |
| `login_click_text` | `None` | Visible text of the SSO entry control to click (e.g. `"Sign in"`). |
| `login_selector` | `None` | Alternatively, a CSS/XPath selector for the SSO control. |
| `profile_root` | `Path("data/portals/profiles")` | Root for per-channel persistent profiles. Holds live tokens — keep out of git. |
| `default_channel` | `"msedge"` | Channel launched when caller passes `channel=None`. |
| `reset_session_on_close` | `True` | Wipe cookies + web storage on close (keep the profile). |
| `default_timeout_ms` | `DEFAULT_TIMEOUT_MS` (45_000) | Per-locator/navigation ceiling. |
| `login_timeout_ms` | `LOGIN_TIMEOUT_MS` (180_000) | How long to wait for SSO/MFA to reach the post-login URL. |
| `click_retry_timeouts_ms` | `CLICK_RETRY_TIMEOUTS_MS` `(3_000, 20_000, 20_000)` | Tiered click schedule. |

Set only `name`, `login_url`, `success_url_glob`, and one of
`login_click_text`/`login_selector` for the common case; the rest inherit.

## `Portal` base (`core/portals/base.py`)

Class attributes: `name` (default `"portal"`), `login_url`, `storage_state_path`
(seeded/username-password pattern; `None` = no seed), `user_data_dir` (persistent
profile pattern; `None` = seeded context).

Constructor / `open` keyword args (all injected explicitly):
`secrets: SecretProvider`, `workspace: Path`, `headless: bool = False`,
`log: Callable[[str], None] | None = None`, `channel: str | None = None`.

Lifecycle:
- `await Cls.open(secrets=…, workspace=…, headless=…, log=…, channel=…)` — classmethod;
  launches, configures the page, and if `_is_authenticated()` is false runs `login()`
  then `save_storage_state()`. Returns the portal.
- `async with portal: …` — `__aenter__` / `__aexit__` guarantee `close()`.
- Abstract methods a subclass must implement: `_on_login_page() -> bool`, `login()`.
- Instance state/helpers: `self.secrets`, `self.workspace`, `self.headless`,
  `self.channel`, `self.page` (`Page | None`), `self.context` (`BrowserContext`
  property), `self.log(message)`.

Primitives: `navigate(url)`, `download(dest, *, click=None, goto=None) -> Path`,
`upload(file_input, path)`, `save_storage_state()`, `close()`.

`SecretProvider` is a runtime-checkable `Protocol` requiring only
`require_secret(key) -> str`, so `core.portals` stays decoupled from any concrete
secret backend.

## Module-level helpers (`browser_portal.py`)

- `DEFAULT_TIMEOUT_MS = 45_000`, `LOGIN_TIMEOUT_MS = 180_000`,
  `CLICK_RETRY_TIMEOUTS_MS = (3_000, 20_000, 20_000)`.
- `await settle(page, *, timeout_ms=DEFAULT_TIMEOUT_MS, log=None)` — best-effort wait
  for `networkidle`; swallows timeout. Never a fixed sleep.
- `await try_click(page, *, text=None, selector=None, attempts_ms=CLICK_RETRY_TIMEOUTS_MS,
  dynamic_timeout_ms=DEFAULT_TIMEOUT_MS, log=None) -> bool` — tiered best-effort click
  by visible `text` or `selector`.

## Low-level launchers (`browser.py`) — used by the base; rarely called directly

- `launch_context(*, downloads_dir, storage_state=None, headless=False, channel=None,
  viewport=None) -> BrowserHandle` — fresh browser + context, optionally seeded from a
  `storage_state.json`. Backs the username/password pattern.
- `launch_persistent_context(*, user_data_dir, downloads_dir, headless=False,
  channel=None, viewport=None) -> BrowserHandle` — persistent profile. Backs the SSO
  pattern.
- `BrowserHandle` dataclass (`playwright`, `context`, `browser=None`) with `close()`.
- `DEFAULT_VIEWPORT = {"width": 1440, "height": 900}`.

Prefer subclassing `Portal`/`BrowserPortal`; these launchers are the plumbing the base
already wires for you.

## `core.secretstore`

- `SecretKey` (`keys.py`) — a `StrEnum` registry; every store operation takes a member.
  Boilerplate ships `EXAMPLE_PORTAL_USERNAME` / `EXAMPLE_PORTAL_PASSWORD`. Add one
  member per real secret (rename per portal). `SERVICE_NAME` namespaces all entries in
  the OS credential store (rename per project/client).
- `SecretStore` (`store.py`) — ABC with `set_secret(key, value)`, `get_secret(key) ->
  str | None`, `delete_secret(key)`, `has_secret(key) -> bool`, and
  `require_secret(key) -> str` (raises `SecretNotFoundError` if absent). Portals use
  `require_secret`.
- Backends: `WindowsSecretStore` (`"wincred"`), `MacOSSecretStore` (`"keychain"`),
  `InMemorySecretStore` (`"memory"`, dev/tests only).
- Factory: `get_default_store()` picks per platform (Windows → wincred, macOS →
  keychain); `get_store(name="default")` selects by name. `AI_OPS_SECRET_STORE`
  (`ENV_STORE_VAR`) overrides platform detection (e.g. on Linux/CI).
- Errors: `SecretStoreError`, `SecretNotFoundError`.

Store values once (via the keychain / a small management step) — never in source or a
committed `.env`.

## Templates to copy (`core/portals/example.py`)

- `ExampleSsoPortal(BrowserPortal)` — sets `name`, `login_url`, `success_url_glob`,
  `login_click_text`. No `login()`/`_on_login_page()` override needed.
- `ExamplePasswordPortal(Portal)` — sets `name`, `login_url`, `storage_state_path`;
  implements `_on_login_page()` and `login()` (fills the form with
  `self.secrets.require_secret(SecretKey.EXAMPLE_PORTAL_USERNAME/PASSWORD)`).
