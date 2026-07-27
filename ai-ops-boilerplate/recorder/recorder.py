"""Session recorder: per-page event buffers, on-demand tagged captures,
user-action log, and per-capture Playwright trace chunks."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ijson
from playwright.async_api import BrowserContext, Page, async_playwright

from .config import RecorderConfig

CONSOLE_BUFFER = 200
NETWORK_BUFFER = 200
ACTIONS_FLUSH_EVERY = 25

# Cap each request/response body stored in api_calls.json. Full bodies always
# remain in session.har; this only bounds the curated, human/LLM-readable file.
API_BODY_MAX = 64 * 1024

# Read storage as a plain object. Some origins (data:, sandboxed iframes,
# pages with restrictive CSP) throw SecurityError on storage access — return
# a sentinel object instead of crashing the whole capture.
_READ_STORAGE_JS = """
(kind) => {
  try {
    const store = kind === 'session' ? sessionStorage : localStorage;
    const out = {};
    for (let i = 0; i < store.length; i++) {
      const k = store.key(i);
      out[k] = store.getItem(k);
    }
    return out;
  } catch (e) {
    return { __unavailable__: String(e && e.message || e) };
  }
}
"""


def har_options(session_dir: Path) -> dict[str, Any]:
    """record_har_* kwargs for launch_persistent_context. Single source of
    truth so the smoke test can't silently drift from run_session.

    Full network dump incl. bodies; embed keeps it one portable, text-
    searchable file. build_api_calls() streams it back into api_calls.json.
    """
    return {
        "record_har_path": str(session_dir / "session.har"),
        "record_har_mode": "full",
        "record_har_content": "embed",
    }


def _slug(s: str) -> str:
    s = (s or "untitled").strip().lower()
    s = re.sub(r"[^a-z0-9._-]+", "-", s).strip("-") or "untitled"
    return s[:60]


class SessionRecorder:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.captures_dir = session_dir / "captures"
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.capture_counter = 0
        self.actions: list[dict] = []
        self._actions_since_flush = 0
        self._jsonl_count = 0  # actions already appended to actions.jsonl
        # id(page) -> {"console": deque, "network": deque}
        self._page_state: dict[int, dict[str, deque]] = {}

    def attach_page(self, page: Page) -> None:
        state = {
            "console": deque(maxlen=CONSOLE_BUFFER),
            "network": deque(maxlen=NETWORK_BUFFER),
        }
        self._page_state[id(page)] = state

        def on_console(msg) -> None:
            state["console"].append({
                "ts": time.time(),
                "type": msg.type,
                "text": msg.text,
                "location": msg.location,
            })

        def on_request(req) -> None:
            state["network"].append({
                "ts": time.time(),
                "phase": "request",
                "method": req.method,
                "url": req.url,
                "resource_type": req.resource_type,
            })

        def on_response(resp) -> None:
            state["network"].append({
                "ts": time.time(),
                "phase": "response",
                "status": resp.status,
                "url": resp.url,
            })

        def on_pageerror(err) -> None:
            state["console"].append({
                "ts": time.time(),
                "type": "pageerror",
                "text": str(err),
                "location": None,
            })

        page.on("console", on_console)
        page.on("request", on_request)
        page.on("response", on_response)
        page.on("pageerror", on_pageerror)
        page.on("close", lambda _p: self._page_state.pop(id(page), None))

    def record_action(self, action: dict, page_url: str | None = None) -> None:
        action.setdefault("ts", time.time())
        if page_url and "url" not in action:
            action["url"] = page_url
        self.actions.append(action)
        self._actions_since_flush += 1
        if self._actions_since_flush >= ACTIONS_FLUSH_EVERY:
            # Cheap O(new) durability between captures — avoid re-serializing
            # the whole list every 25 actions (that was O(n²) over a session).
            self._append_jsonl()
            self._actions_since_flush = 0

    def _append_jsonl(self) -> None:
        """Append not-yet-written actions to actions.jsonl, one JSON per line."""
        new = self.actions[self._jsonl_count:]
        if not new:
            return
        try:
            with (self.session_dir / "actions.jsonl").open(
                "a", encoding="utf-8"
            ) as f:
                for a in new:
                    f.write(json.dumps(a, default=str) + "\n")
            self._jsonl_count = len(self.actions)
        except Exception as e:
            print(f"[recorder] actions.jsonl append failed: {e!r}")

    def flush_actions(self) -> None:
        """Write the canonical actions.json array (and sync actions.jsonl).

        Called on each capture and at shutdown — not on every action — so the
        full-list serialization cost stays off the hot path.
        """
        self._append_jsonl()
        self._actions_since_flush = 0
        path = self.session_dir / "actions.json"
        try:
            path.write_text(
                json.dumps(self.actions, indent=2, default=str), encoding="utf-8"
            )
        except Exception as e:
            print(f"[recorder] flush_actions failed: {e!r}")

    async def capture(self, page: Page, tag: str) -> dict[str, Any]:
        self.capture_counter += 1
        idx = f"{self.capture_counter:03d}"
        slug = _slug(tag)
        cap_dir = self.captures_dir / f"{idx}_{slug}"
        cap_dir.mkdir(parents=True, exist_ok=True)

        # Hide overlay so it isn't part of the screenshot, then restore.
        try:
            await page.evaluate("window.__overlay_hide && window.__overlay_hide()")
        except Exception:  # nosec B110 — page may be detached; overlay hide is best-effort
            pass
        try:
            await page.screenshot(path=str(cap_dir / "viewport.png"), full_page=False)
            await page.screenshot(path=str(cap_dir / "full_page.png"), full_page=True)
        finally:
            try:
                await page.evaluate("window.__overlay_show && window.__overlay_show()")
            except Exception:  # nosec B110 — page may be detached; overlay restore is best-effort
                pass

        # page.content() would include the injected overlay DOM (it's only
        # visibility:hidden during the screenshot, still in the document). Use
        # the overlay helper that serializes with its nodes temporarily removed;
        # fall back to raw content() if the overlay isn't installed.
        html = None
        try:
            html = await page.evaluate(
                "() => window.__overlay_clean_html && window.__overlay_clean_html()"
            )
        except Exception:
            html = None
        if not html:
            html = await page.content()
        (cap_dir / "page.html").write_text(html, encoding="utf-8")

        try:
            local_storage = await page.evaluate(_READ_STORAGE_JS, "local")
        except Exception as e:
            local_storage = {"__error__": repr(e)}
        try:
            session_storage = await page.evaluate(_READ_STORAGE_JS, "session")
        except Exception as e:
            session_storage = {"__error__": repr(e)}
        try:
            cookies = await page.context.cookies()
        except Exception as e:
            cookies = [{"__error__": repr(e)}]

        state = self._page_state.get(id(page), {})
        console_log = list(state.get("console", []))
        network_log = list(state.get("network", []))

        meta = {
            "tag": tag,
            "slug": slug,
            "index": idx,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url": page.url,
            "title": await page.title(),
            "viewport": page.viewport_size,
        }
        (cap_dir / "meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        (cap_dir / "storage.json").write_text(
            json.dumps(
                {
                    "cookies": cookies,
                    "localStorage": local_storage,
                    "sessionStorage": session_storage,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        (cap_dir / "console.json").write_text(
            json.dumps(console_log, indent=2), encoding="utf-8"
        )
        (cap_dir / "network.json").write_text(
            json.dumps(network_log, indent=2), encoding="utf-8"
        )

        # Inline a capture marker in the action log so the timeline correlates.
        self.record_action({
            "type": "capture",
            "index": idx,
            "tag": tag,
            "slug": slug,
            "dir": str(cap_dir),
            "url": page.url,
        })
        self.flush_actions()

        return {"ok": True, "index": idx, "tag": slug, "dir": str(cap_dir)}


async def harvest_session(
    context: BrowserContext, pages: list[Page], out_dir: Path
) -> dict[str, Any]:
    """Snapshot replayable auth into out_dir: Playwright storage_state (cookies +
    localStorage), a focused cookies file with a requests-style dict, and
    per-origin sessionStorage (which storage_state omits). Needs a live context.

    Each artifact is written independently so one failure doesn't lose the rest.

    Note: ``has_fedauth`` / ``has_rtfa`` are SharePoint-specific convenience
    flags. They're harmless on non-Microsoft portals (simply always false) and
    kept so the cookies file has a stable shape across clients.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    auth_dir = out_dir / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"ok": True, "dir": str(out_dir)}

    # storage_state writes the file itself when given a path.
    try:
        await context.storage_state(path=str(out_dir / "storage_state.json"))
    except Exception as e:
        print(f"[recorder] storage_state failed: {e!r}")
        result["storage_state_error"] = repr(e)

    try:
        cookies = await context.cookies()
        (auth_dir / "cookies.json").write_text(
            json.dumps(
                {
                    "cookies": cookies,
                    "requests_cookies": {
                        c.get("name"): c.get("value")
                        for c in cookies
                        if c.get("name")
                    },
                    "has_fedauth": any(
                        c.get("name") == "FedAuth" for c in cookies
                    ),
                    "has_rtfa": any(c.get("name") == "rtFa" for c in cookies),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[recorder] cookies harvest failed: {e!r}")
        result["cookies_error"] = repr(e)

    # sessionStorage is per-origin and not part of storage_state. Collect it
    # from each live page, keyed by origin (last page for an origin wins).
    session_storage: dict[str, Any] = {}
    for page in pages:
        try:
            origin = await page.evaluate("() => location.origin")
            session_storage[origin] = await page.evaluate(
                _READ_STORAGE_JS, "session"
            )
        except Exception as e:
            print(f"[recorder] sessionStorage read failed: {e!r}")
    try:
        (auth_dir / "session_storage.json").write_text(
            json.dumps(session_storage, indent=2, default=str), encoding="utf-8"
        )
    except Exception as e:
        print(f"[recorder] sessionStorage write failed: {e!r}")
        result["session_storage_error"] = repr(e)

    return result


def _decode_har_body(content: dict | None) -> tuple[str | None, bool, bool, int]:
    """Return (text, truncated, binary, size) for a HAR request/response body.

    `size` is always a byte count; truncation is bounded by API_BODY_MAX bytes
    (on a UTF-8 boundary). HAR `content`/`postData` carries `text` plus an
    optional `encoding` of "base64" (used by embed mode for binary); decode
    text/JSON and leave true binary as None flagged binary.
    """
    if not content:
        return None, False, False, 0
    text = content.get("text")
    if text is None:
        return None, False, False, int(content.get("size") or 0)
    if content.get("encoding") == "base64":
        try:
            raw = base64.b64decode(text)
        except Exception:
            return None, False, True, int(content.get("size") or 0)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None, False, True, len(raw)
    encoded = text.encode("utf-8")
    size = len(encoded)
    if size > API_BODY_MAX:
        # Decode back on a UTF-8 boundary so a multibyte char isn't split.
        return encoded[:API_BODY_MAX].decode("utf-8", "ignore"), True, False, size
    return text, False, False, size


def build_api_calls(session_dir: Path, api_path_re: re.Pattern[str]) -> None:
    """Post-process session.har into a focused, searchable api_calls.json.

    Keeps entries that look like API calls (XHR/fetch resource type, a JSON/XML
    response, or an API-ish URL per ``api_path_re``) and flattens headers to
    dicts. Never raises: a malformed HAR must not lose the rest of the session.

    Streams the HAR one entry at a time with ijson rather than loading the
    whole file. With record_har_content="embed" a download-heavy session can
    produce a multi-hundred-MB HAR (binaries are ~33% larger as base64);
    streaming bounds peak memory to a single entry instead of the whole file.
    session.har remains the full record.
    """
    har_path = session_dir / "session.har"
    try:
        if not har_path.exists():
            print("[recorder] no session.har; skipping api_calls.json")
            return

        def _headers(hlist) -> dict[str, str]:
            return {h.get("name", ""): h.get("value", "") for h in (hlist or [])}

        calls: list[dict] = []
        with har_path.open("rb") as f:
            for entry in ijson.items(f, "log.entries.item"):
                req = entry.get("request", {}) or {}
                resp = entry.get("response", {}) or {}
                resp_content = resp.get("content", {}) or {}
                resp_ctype = resp_content.get("mimeType", "") or ""
                url = req.get("url", "")
                resource_type = entry.get("_resourceType", "")

                is_api = (
                    resource_type in {"xhr", "fetch"}
                    or bool(re.search(r"json|xml", resp_ctype, re.I))
                    or bool(api_path_re.search(url))
                )
                if not is_api:
                    continue

                req_body, req_trunc, _req_bin, _req_size = _decode_har_body(
                    req.get("postData")
                )
                resp_body, resp_trunc, resp_bin, resp_size = _decode_har_body(
                    resp_content
                )

                call = {
                    "started": entry.get("startedDateTime"),
                    "duration_ms": entry.get("time"),
                    "method": req.get("method"),
                    "url": url,
                    "resource_type": resource_type or None,
                    "request_headers": _headers(req.get("headers")),
                    "request_body": req_body,
                    "request_truncated": req_trunc,
                    "response_status": resp.get("status"),
                    "response_content_type": resp_ctype or None,
                    "response_headers": _headers(resp.get("headers")),
                    "response_body": resp_body,
                    "response_truncated": resp_trunc,
                }
                if resp_bin:
                    call["response_binary"] = True
                    call["response_size"] = resp_size
                calls.append(call)

        calls.sort(key=lambda c: c.get("started") or "")
        (session_dir / "api_calls.json").write_text(
            json.dumps({"count": len(calls), "calls": calls}, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"[recorder] api_calls.json written ({len(calls)} call(s))")
    except Exception as e:
        print(f"[recorder] build_api_calls failed: {e!r}")


async def run_session(config: RecorderConfig) -> Path:
    output_root = config.output_dir
    user_data_dir = config.profile_dir
    output_root.mkdir(parents=True, exist_ok=True)
    user_data_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = _slug(config.session_name) if config.session_name else f"session_{ts}"
    session_dir = output_root / name
    session_dir.mkdir(parents=True, exist_ok=True)
    print(f"[recorder] session directory: {session_dir.resolve()}")
    print(f"[recorder] persistent profile: {user_data_dir.resolve()}")

    overlay_js = (Path(__file__).parent / "overlay.js").read_text(encoding="utf-8")

    # Empty channel means "use Playwright's bundled Chromium" — pass None so the
    # launcher picks the default build rather than looking for a channel named "".
    channel = config.browser_channel or None

    async with async_playwright() as p:
        context: BrowserContext = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            channel=channel,
            headless=config.headless,
            viewport=config.viewport,
            **har_options(session_dir),
        )

        recorder = SessionRecorder(session_dir)
        await context.tracing.start(
            screenshots=True, snapshots=True, sources=True
        )
        await context.tracing.start_chunk()

        stop_requested = asyncio.Event()
        closed = asyncio.Event()

        # Serialize tracing chunk operations and track in-flight background
        # chunk writes so graceful shutdown can drain them before stopping.
        tracing_lock = asyncio.Lock()
        pending_chunks: set[asyncio.Task] = set()
        # Serialize on-demand harvests (they hit the same CDP connection as the
        # trace-chunk swaps) and track them so shutdown can drain before close.
        harvest_lock = asyncio.Lock()
        pending_harvests: set[asyncio.Task] = set()

        async def _swap_chunk(cap_dir: Path) -> None:
            async with tracing_lock:
                try:
                    await context.tracing.stop_chunk(
                        path=str(cap_dir / "trace.zip")
                    )
                except Exception as e:
                    print(f"[recorder] background stop_chunk failed: {e!r}")
                try:
                    await context.tracing.start_chunk()
                except Exception as e:
                    print(f"[recorder] background start_chunk failed: {e!r}")

        async def handle_capture(source: dict, tag: str) -> dict:
            page: Page = source["page"]
            try:
                # User-visible work first so the overlay flips to "Saved" fast.
                # The trace chunk swap (which can write tens of MB for long
                # gaps between captures) runs in the background.
                result = await recorder.capture(page, tag or "untitled")
                print(
                    f"[recorder] captured #{result['index']} "
                    f"'{result['tag']}' -> {result['dir']}"
                )
                cap_dir = Path(result["dir"])
                task = asyncio.create_task(_swap_chunk(cap_dir))
                pending_chunks.add(task)
                task.add_done_callback(pending_chunks.discard)
                return result
            except Exception as e:
                print(f"[recorder] capture failed: {e!r}")
                return {"ok": False, "error": str(e)}

        async def handle_action(source: dict, action: dict) -> dict:
            try:
                page: Page | None = source.get("page")
                page_url = page.url if page else None
                if not isinstance(action, dict):
                    return {"ok": False, "error": "action must be an object"}
                recorder.record_action(action, page_url=page_url)
                return {"ok": True, "seq": len(recorder.actions)}
            except Exception as e:
                print(f"[recorder] record_action failed: {e!r}")
                return {"ok": False, "error": str(e)}

        async def handle_stop(source: dict) -> dict:
            print("[recorder] stop requested from overlay")
            stop_requested.set()
            return {"ok": True}

        harvest_counter = {"n": 0}

        async def _run_harvest(out_dir: Path) -> dict:
            # Hold harvest_lock so harvest CDP calls don't interleave with each
            # other (storage_state/cookies/evaluate on the shared connection).
            async with harvest_lock:
                return await harvest_session(context, list(context.pages), out_dir)

        async def handle_harvest(source: dict) -> dict:
            # Once Stop is requested the context is about to close; refuse new
            # harvests rather than race context.close() in the graceful path.
            if stop_requested.is_set():
                return {"ok": False, "error": "session is stopping"}
            harvest_counter["n"] += 1  # safe: no await between read and write
            idx = f"{harvest_counter['n']:03d}"
            out_dir = session_dir / "harvests" / idx
            task = asyncio.create_task(_run_harvest(out_dir))
            pending_harvests.add(task)
            task.add_done_callback(pending_harvests.discard)
            try:
                await task
                print(f"[recorder] harvested auth #{idx} -> {out_dir}")
                return {"ok": True, "index": idx, "dir": str(out_dir)}
            except Exception as e:
                print(f"[recorder] harvest failed: {e!r}")
                return {"ok": False, "error": str(e)}

        await context.expose_binding("__capture", handle_capture)
        await context.expose_binding("__recordAction", handle_action)
        await context.expose_binding("__stopSession", handle_stop)
        await context.expose_binding("__harvestSession", handle_harvest)
        await context.add_init_script(overlay_js)

        def attach(page: Page) -> None:
            recorder.attach_page(page)

        context.on("page", attach)
        for page in context.pages:
            attach(page)

        page = context.pages[0] if context.pages else await context.new_page()
        if config.start_url and config.start_url != "about:blank":
            try:
                await page.goto(config.start_url)
            except Exception as e:
                print(f"[recorder] initial navigation failed: {e!r}")

        print(
            "[recorder] browser ready. Click 'Stop & save session' in the "
            "overlay (or Ctrl+Shift+S) to end gracefully."
        )

        context.on("close", lambda _c: closed.set())

        stop_task = asyncio.create_task(stop_requested.wait())
        closed_task = asyncio.create_task(closed.wait())
        try:
            await asyncio.wait(
                {stop_task, closed_task}, return_when=asyncio.FIRST_COMPLETED
            )
        except KeyboardInterrupt:
            print("[recorder] interrupted")
            stop_requested.set()
        finally:
            for t in (stop_task, closed_task):
                if not t.done():
                    t.cancel()

        # Graceful path: context is still alive, save trace + actions, then close.
        if stop_requested.is_set() and not closed.is_set():
            # Drain in-flight per-capture chunk writes and any on-demand harvest
            # so the trace stop / context.close() below doesn't race them.
            drainable = list(pending_chunks) + list(pending_harvests)
            if drainable:
                print(
                    f"[recorder] draining {len(drainable)} "
                    "background task(s)..."
                )
                await asyncio.gather(*drainable, return_exceptions=True)
            trace_path = session_dir / "trace.zip"
            async with tracing_lock:
                try:
                    await context.tracing.stop_chunk(path=str(trace_path))
                    print(f"[recorder] final trace chunk saved to {trace_path}")
                except Exception as e:
                    print(f"[recorder] final stop_chunk failed: {e!r}")
                try:
                    await context.tracing.stop()
                except Exception as e:
                    print(f"[recorder] tracing.stop failed: {e!r}")
            recorder.flush_actions()
            # Context is still live — snapshot replayable auth at session level.
            try:
                await _run_harvest(session_dir)
                print(f"[recorder] session auth harvested to {session_dir}")
            except Exception as e:
                print(f"[recorder] final harvest failed: {e!r}")
            try:
                await context.close()
            except Exception:  # nosec B110 — context may already be closed; cleanup is best-effort
                pass
        else:
            # Fallback: window was closed before Stop was clicked. The CDP
            # connection is gone — abandon in-flight chunk tasks (they'll
            # error out cleanly), chunks already on disk are all we have.
            # storage_state needs a live context so it's unavailable here; the
            # latest captures/NNN/storage.json is the auth salvage.
            print(
                "[recorder] browser closed before Stop was clicked. "
                "Per-capture trace chunks and storage.json are kept; no "
                "session-level trace.zip or storage_state.json."
            )
            # Snapshot the set first: done-callbacks discard from it concurrently.
            leftover = list(pending_chunks) + list(pending_harvests)
            for t in leftover:
                t.cancel()
            if leftover:
                await asyncio.gather(*leftover, return_exceptions=True)
            recorder.flush_actions()
            # Coax Playwright into flushing session.har even though the window
            # is gone (HAR flush is driver-side). Safe no-op if already closed.
            try:
                await context.close()
            except Exception:  # nosec B110 — context already gone; close attempt is best-effort
                pass

    # Context is closed and session.har is flushed — curate the focused file.
    build_api_calls(session_dir, config.api_path_re())

    print(f"[recorder] session complete: {session_dir}")
    return session_dir
