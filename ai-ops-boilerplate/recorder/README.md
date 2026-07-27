# Recorder

Development-time tool. Launches a browser via Playwright, records every user action you take, traces the browser session, and gives you an in-page Capture button to save tagged snapshots of pages you care about.

The recorder is portal-agnostic. Its defaults target Microsoft Edge / Entra portals (see [Configuration](#configuration)), but every Microsoft-specific assumption is a config value you can override to point at any client's portal.

## Run

```
uv run record https://example.com
```

Or, equivalently:

```
uv run python -m recorder https://example.com
```

URL is optional — without one, the browser opens blank and you navigate manually.

## Options

| Flag | Default | Purpose |
|---|---|---|
| `--session-name NAME` | timestamp | Folder name under `--output-dir` |
| `--output-dir DIR` | `./recordings` | Where session folders are written |
| `--user-data-dir DIR` | `./.recorder-profile` | Persistent browser profile; keeps portal logins between runs |
| `--browser-channel CH` | `msedge` | Playwright browser channel (`msedge`, `chrome`, `msedge-beta`, …). Empty string = bundled Chromium |
| `--api-path-pattern RE` | Microsoft/SharePoint/Graph regex | Case-insensitive regex marking a URL as API-ish when curating `api_calls.json` |

## Configuration

All portal- and environment-specific settings live on `RecorderConfig` (in `config.py`). The CLI builds one from the flags above; you can also import and drive `run_session(config)` directly. Defaults reproduce the original Microsoft Edge behavior so nothing changes out of the box.

| Field | Default | Notes |
|---|---|---|
| `start_url` | `about:blank` | Initial URL |
| `session_name` | `None` (timestamp) | Session folder name |
| `output_dir` | `<package parent>/recordings` | Session output root |
| `profile_dir` | `<package parent>/.recorder-profile` | Persistent profile (formerly the Edge/Entra profile) |
| `browser_channel` | `msedge` | `None`/`""` → bundled Chromium |
| `api_path_pattern` | `(/_api/\|/_vti_bin/\|/api/\|graph\.microsoft\.com\|/odata\|/rest/)` | API-detection heuristic |
| `headless` | `False` | The overlay UI needs a visible window |
| `viewport_width` / `viewport_height` | `1440` / `900` | Launch viewport |

Retargeting a non-Microsoft portal is a config change, e.g.:

```python
from recorder import RecorderConfig, run_session
import asyncio

cfg = RecorderConfig(
    start_url="https://portal.someclient.com",
    browser_channel="chrome",
    api_path_pattern=r"(/api/v[0-9]+/|/graphql|/services/)",
)
asyncio.run(run_session(cfg))
```

## The overlay

A small dark panel appears bottom-left on every page.

- **Tag input + Capture** — type a tag (e.g. `invoice-list-empty-state`) and click **Capture** (or hit Enter). Saves the tagged snapshot bundle described below.
- **Harvest session** — snapshots replayable auth (cookies + storage) into `harvests/NNN/` on demand. Auth is freshest mid-session, and this is the only session-level harvest you get if you close the window instead of clicking Stop. See [API capture & auth harvest](#api-capture--auth-harvest).
- **Stop & save session** — ends the session gracefully: closes the current trace chunk into `trace.zip` at the session root, flushes `actions.json`, harvests auth to the session root, and shuts down the browser. Two-click confirm (the first click arms, the second within 3s commits).
- **Hotkeys** — `Ctrl+Shift+H` collapses/expands the panel from anywhere on the page; `Ctrl+Shift+S` triggers Stop; `Ctrl+Shift+A` triggers Harvest.
- Drag the header to move the panel; the `_` button collapses it to just the title bar.

The Actions counter at the bottom of the panel ticks up as you click/type/navigate, so you can see the action recorder is alive.

## What gets saved

```
recordings/<session>/
  actions.json              # ordered user-action log, canonical JSON array (see below)
  actions.jsonl             # same events, append-only one-per-line — cheap durability between captures
  trace.zip                 # final trace chunk (post-last-capture window). Only present on graceful Stop.
  session.har               # FULL network dump — every request/response incl. headers + bodies
  api_calls.json            # focused, searchable subset of API-looking calls (see below)
  storage_state.json        # Playwright-native auth: cookies + localStorage. Replayable. Graceful Stop only.
  auth/
    cookies.json            # all cookies + a flat requests-style name->value dict; flags has_fedauth/has_rtfa
    session_storage.json    # per-origin sessionStorage (NOT in storage_state — where SPA/MSAL tokens often live)
  harvests/
    001/                    # one folder per "Harvest session" click; same storage_state.json + auth/ as above
    ...
  captures/
    001_<your-tag>/
      viewport.png          # what you saw when you clicked Capture
      full_page.png         # whole scrollable page
      page.html             # full DOM at capture time (recorder overlay stripped) — grep for selectors
      meta.json             # tag, slug, index, URL, title, timestamp, viewport
      storage.json          # cookies + localStorage + sessionStorage
      console.json          # last 200 console messages, includes pageerror
      network.json          # last 200 request/response events (lightweight breadcrumb)
      trace.zip             # trace chunk covering the window leading up to this capture
    002_<next-tag>/
    ...
```

### `actions.json`

A flat, ordered list of events. Each entry has a `type`, a `ts` (unix seconds), and a `url` (the page URL when the event happened). Other fields depend on type:

`actions.jsonl` holds the same events one-per-line; it's appended cheaply as you go (the `.json` array is rewritten only on capture and at Stop). If a session is killed hard before Stop, `actions.jsonl` is the most complete record.

| `type` | Extra fields |
|---|---|
| `page-load` | `title` |
| `click` | `selector`, `tag`, `text`, `x`, `y`, `button` |
| `input` | `selector`, `tag`, `inputType`, `value` (debounced 400ms; logs the last value after typing pauses) |
| `change` | `selector`, `value`, `text` (for `<select>`) |
| `submit` | `selector`, `action`, `method` |
| `key` | `key`, `ctrl`, `shift`, `alt`, `meta`, `selector` (only Enter / Escape / Tab / Ctrl+letter etc. — not every keystroke) |
| `nav` | `reason` (`popstate` or `hashchange`, for SPA navigation) |
| `capture` | `index`, `tag`, `slug`, `dir` — inlined whenever you hit Capture, so the action log correlates with the saved snapshots |

Events on the recorder overlay itself are filtered out (we don't log your clicks on the Capture/Stop buttons).

Selectors are derived in priority order: `[data-testid]` → `#id` → `[aria-label]` → `[name]` → short CSS path. Capped at 200 chars. Good enough to identify the element in `page.html`; not guaranteed unique across a complex SPA.

### Trace chunks

Playwright tracing runs continuously, split into chunks. Each capture closes the current chunk into the capture's folder (`captures/NNN_<tag>/trace.zip`) and starts a fresh one. The final chunk — from the last capture to your click on **Stop** — is saved to `recordings/<session>/trace.zip`.

If you close the browser window instead of clicking Stop, the per-capture chunks survive (already on disk) but the session-level `trace.zip` won't be written.

View any chunk:

```
uv run playwright show-trace recordings/<session>/trace.zip
uv run playwright show-trace recordings/<session>/captures/001_<tag>/trace.zip
```

The Trace Viewer shows screenshots, DOM snapshots, console, and network over time. Note: for human-driven sessions Playwright doesn't see user clicks as discrete "actions" in the trace — that's what `actions.json` is for. The trace gives you the visual timeline; the action log gives you the labeled events.

## API capture & auth harvest

Every session records the full network — including request/response bodies — as a HAR
(`session.har`, Playwright `record_har`, `mode=full`, `content=embed`). This is the complete,
high-fidelity dump for reverse-engineering a portal's API calls and rebuilding them in Python
`requests`.

`session.har` captures *everything* (JS, CSS, fonts, XHR/fetch), so a focused
`api_calls.json` is post-processed from it after the browser closes. **Search `api_calls.json`
first; fall back to `session.har`** if a call isn't there. An entry is kept when it looks like
an API call: resource type `xhr`/`fetch`, a JSON/XML response, or a URL matching
`api_path_pattern`. The default pattern recognizes Microsoft/SharePoint/Graph shapes
(`/_api/`, `/_vti_bin/`, `/api/`, `graph.microsoft.com`, `/odata`, `/rest/`); set
`--api-path-pattern` for a different portal. Shape:

```jsonc
{
  "count": 12,
  "calls": [
    {
      "started": "2026-...", "duration_ms": 83, "method": "GET",
      "url": "https://contoso.sharepoint.com/_api/web/lists",
      "resource_type": "fetch",
      "request_headers": { "Authorization": "Bearer ...", "X-RequestDigest": "..." },
      "request_body": null, "request_truncated": false,
      "response_status": 200,
      "response_content_type": "application/json;odata=verbose",
      "response_headers": { "...": "..." },
      "response_body": "{ \"d\": { ... } }", "response_truncated": false
    }
  ]
}
```

Bodies are decoded from the HAR (base64 in embed mode) and capped at 64 KB; `*_truncated`
flags when the stored body was cut (the full bytes stay in `session.har`). True binary bodies
(file downloads) are left `null` with `response_binary: true` + `response_size`. Auth headers
(`Authorization`, `Cookie`, `X-RequestDigest`) are kept verbatim — they're the point.

**Auth harvest** gives you a replayable session without an app registration:

- `storage_state.json` — Playwright-native (cookies for all origins + per-origin localStorage).
  Reload it directly with `browser.new_context(storage_state="storage_state.json")`. Written on
  graceful **Stop** and on every **Harvest session** click (into `harvests/NNN/`); **not** written
  if you close the window instead of stopping — then use the latest `captures/NNN/storage.json`.
- `auth/cookies.json` — all cookies plus `requests_cookies` (a flat `{name: value}` dict ready
  to drop into `requests`), and `has_fedauth`/`has_rtfa` flags (SharePoint-specific; harmless and
  always false on other portals).
- `auth/session_storage.json` — per-origin sessionStorage, where SPA/MSAL bearer tokens often
  live (`storage_state` does not capture sessionStorage).

Replaying SharePoint REST with the harvested cookies (read, then a digest-protected write) — an
example of the general pattern:

```python
import json, requests
auth = json.load(open("recordings/<session>/auth/cookies.json"))
s = requests.Session(); s.cookies.update(auth["requests_cookies"])
base = "https://contoso.sharepoint.com"
hdr = {"Accept": "application/json;odata=verbose"}
s.get(f"{base}/_api/web/lists", headers=hdr)                      # read
digest = s.post(f"{base}/_api/contextinfo", headers=hdr).json() \
          ["d"]["GetContextWebInformation"]["FormDigestValue"]   # required for writes
s.post(f"{base}/_api/web/...", headers={**hdr, "X-RequestDigest": digest}, data=...)
```

Cookies (`FedAuth`/`rtFa`) and bearer tokens are short-lived — typically hours, bearer ~1h — so a
harvest has a limited replay window. Re-harvest when calls start returning 401/403.

## Notes

- The persistent profile means you log into a portal once and stay logged in across runs. Delete `./.recorder-profile/` to start fresh.
- `recordings/` and `.recorder-profile/` should be gitignored. **They contain live secrets** — `session.har`, `api_calls.json`, `storage_state.json`, and `auth/*` hold real cookies, `Authorization` bearer tokens, and any request-signing values; `actions.json` holds whatever you typed into form fields, including passwords. Treat a session folder like a credential. Don't commit it, paste it, or share it outside the gitignored dir.
- The overlay injects on every page, including new tabs and after navigation.
- The recorder only sees pages inside the Playwright-controlled browser process. If a portal hands off to a different browser process (e.g. Citrix Workspace opening Chrome via OS protocol handler), that window is invisible to the recorder. Workaround: get the URL from that window and start a second recorder session against it.
