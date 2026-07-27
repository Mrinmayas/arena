(() => {
  if (window.__recorderOverlayInstalled) return;
  window.__recorderOverlayInstalled = true;

  // Only the top frame renders the visible UI. Action recording still runs in
  // every frame (each cross-origin iframe is its own realm with its own bound
  // __recordAction). Accessing window.top across origins doesn't throw for the
  // identity comparison, but guard anyway and treat failure as "subframe".
  const IS_TOP = (() => {
    try { return window.top === window.self; } catch (_) { return false; }
  })();

  // Styling lives inside a Shadow DOM so the page's CSS can't reach the overlay
  // and a strict style-src CSP can't drop it. The five load-bearing host props
  // (position/z-index/visibility) are set inline via CSSOM (not subject to
  // style-src) with !important (the host lives in light DOM, so page rules can
  // match it). Everything else rides in a constructable stylesheet — also
  // programmatic, also not gated by style-src.
  const SHADOW_CSS = `
    :host, * { box-sizing: border-box; }
    :host {
      display: block;
      background: #1f1f1f; color: #fff;
      font: 13px/1.4 -apple-system, Segoe UI, system-ui, sans-serif;
      border-radius: 8px; padding: 10px 12px;
      box-shadow: 0 4px 16px rgba(0,0,0,.35);
      width: 280px;
    }
    header {
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 8px; cursor: move; user-select: none;
    }
    h6 {
      margin: 0; font-size: 11px; font-weight: 600;
      letter-spacing: .08em; text-transform: uppercase; opacity: .7;
    }
    button.toggle {
      background: transparent; color: #aaa; border: 0; cursor: pointer;
      font-size: 16px; line-height: 1; padding: 0 4px;
    }
    input[type=text] {
      width: 100%; padding: 6px 8px; border-radius: 4px;
      border: 1px solid #444; background: #2a2a2a; color: #fff;
      margin-bottom: 6px; font: inherit;
    }
    input[type=text]:focus { outline: none; border-color: #007acc; }
    button.capture {
      width: 100%; padding: 8px; border: 0; border-radius: 4px;
      background: #007acc; color: #fff; cursor: pointer;
      font-weight: 600; font: inherit;
    }
    button.capture:hover { background: #0098ff; }
    button.capture:disabled { background: #555; cursor: wait; }
    button.harvest {
      width: 100%; padding: 6px; margin-top: 6px; border: 0; border-radius: 4px;
      background: #1f6f4a; color: #d6ffe8; cursor: pointer;
      font-weight: 600; font: inherit;
    }
    button.harvest:hover { background: #248a5c; color: #fff; }
    button.harvest:disabled { background: #333; color: #777; cursor: wait; }
    button.stop {
      width: 100%; padding: 6px; margin-top: 6px; border: 0; border-radius: 4px;
      background: #5a1a1a; color: #ff9b9b; cursor: pointer;
      font-weight: 600; font: inherit;
    }
    button.stop:hover { background: #c0392b; color: #fff; }
    button.stop:disabled { background: #333; color: #777; cursor: wait; }
    .status {
      margin-top: 6px; font-size: 11px; opacity: .8; min-height: 14px;
      word-break: break-word;
    }
    .meter {
      margin-top: 4px; font-size: 10px; opacity: .55; font-variant-numeric: tabular-nums;
    }
    :host(.collapsed) .body { display: none; }
    :host(.collapsed) { width: auto; padding: 6px 10px; }
  `;

  // Closure-scoped so isInOverlay stays id-independent and subframes (no UI)
  // see it as null → every event there is recorded.
  let host = null;

  // -------- helpers --------

  const isInOverlay = (el) =>
    el && el.nodeType === 1 && host &&
    (el === host || (host.contains && host.contains(el)));

  const cssEscape = (s) =>
    (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/(["\\])/g, "\\$1");

  const safeText = (el) => {
    try {
      const t = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
      return t.slice(0, 60);
    } catch (_) { return ""; }
  };

  const selectorFor = (el) => {
    if (!el || el.nodeType !== 1) return null;
    try {
      if (el.dataset && el.dataset.testid) return `[data-testid="${cssEscape(el.dataset.testid)}"]`;
      if (el.id && /^[A-Za-z_][\w-]*$/.test(el.id)) return `#${el.id}`;
      const aria = el.getAttribute("aria-label");
      if (aria) return `${el.tagName.toLowerCase()}[aria-label="${cssEscape(aria.slice(0, 80))}"]`;
      const name = el.getAttribute("name");
      if (name) return `${el.tagName.toLowerCase()}[name="${cssEscape(name)}"]`;
      // tag + optional one short class, walking up max 4 levels
      const parts = [];
      let cur = el;
      let depth = 0;
      while (cur && cur.nodeType === 1 && depth < 4) {
        let part = cur.tagName.toLowerCase();
        if (typeof cur.className === "string" && cur.className.trim()) {
          const cls = cur.className.trim().split(/\s+/)
            .filter((c) => /^[A-Za-z_-][\w-]*$/.test(c) && c.length < 30)
            .slice(0, 1);
          if (cls.length) part += "." + cls[0];
        }
        parts.unshift(part);
        cur = cur.parentElement;
        depth++;
      }
      return parts.join(" > ").slice(0, 200);
    } catch (_) {
      return el.tagName ? el.tagName.toLowerCase() : null;
    }
  };

  // Build DOM the Trusted-Types-safe way: createElement + textContent +
  // setAttribute (no innerHTML/outerHTML anywhere).
  const make = (tag, props, children) => {
    const node = document.createElement(tag);
    if (props) {
      for (const k in props) {
        if (k === "class") node.className = props[k];
        else if (k === "text") node.textContent = props[k];
        else node.setAttribute(k, props[k]);
      }
    }
    if (children) for (const c of children) node.appendChild(c);
    return node;
  };

  // -------- action forwarding --------

  let actionSeq = 0;
  const sendAction = (action) => {
    if (typeof window.__recordAction !== "function") return;
    action.seq = ++actionSeq;
    action.ts = action.ts || Date.now() / 1000;
    action.url = action.url || (location && location.href) || null;
    try {
      // Fire-and-forget. Binding returns a promise but we don't care.
      window.__recordAction(action);
    } catch (_) { /* ignore */ }
  };

  // -------- install UI (top frame only) --------

  const installUI = (attempts = 0) => {
    // documentElement exists at document-start init time for HTML pages; a few
    // top-level responses (raw XML/JSON) never grow one — cap retries (~10s).
    if (!document.documentElement) {
      if (attempts >= 200) return;
      return setTimeout(() => installUI(attempts + 1), 50);
    }

    host = make("div", { id: "__recorder-overlay-host" });
    // CSP-proof critical layout — inline CSSOM with !important so neither
    // style-src nor a page rule matching the host can move/hide/bury it.
    // Anchored bottom-LEFT: Edge docks its sidebar / downloads / Copilot panel
    // on the right edge, so a right-anchored overlay visually merges with that
    // chrome. Bottom-left keeps it clearly in the page content. Still draggable.
    host.style.setProperty("position", "fixed", "important");
    host.style.setProperty("left", "16px", "important");
    host.style.setProperty("bottom", "16px", "important");
    host.style.setProperty("z-index", "2147483647", "important");
    host.style.setProperty("visibility", "visible", "important");

    const shadow = host.attachShadow({ mode: "open" });

    // Primary styling path: constructable stylesheet (not gated by style-src).
    // Fallback: a shadow-scoped <style> built via textContent (not innerHTML).
    // Worst case (both blocked) the inline host styles above still keep the
    // overlay positioned/topmost/visible; only :hover/theme polish is lost.
    try {
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(SHADOW_CSS);
      shadow.adoptedStyleSheets = [sheet];
    } catch (e) {
      console.warn("[recorder-overlay] constructable stylesheet unavailable, using <style>:", e);
      const styleEl = make("style", { text: SHADOW_CSS });
      shadow.appendChild(styleEl);
    }

    const toggle = make("button", { class: "toggle", title: "Hide (Ctrl+Shift+H)", text: "_" });
    const header = make("header", null, [
      make("h6", { text: "Recorder" }),
      toggle,
    ]);
    const input = make("input", {
      type: "text", placeholder: "Tag for this capture...", autocomplete: "off",
    });
    const captureBtn = make("button", { class: "capture", text: "Capture" });
    const harvestBtn = make("button", {
      class: "harvest", title: "Harvest auth session (Ctrl+Shift+A)", text: "Harvest session",
    });
    const stopBtn = make("button", {
      class: "stop", title: "Stop & save (Ctrl+Shift+S)", text: "Stop & save session",
    });
    const status = make("div", { class: "status", text: "Ready" });
    const meter = make("div", { class: "meter", text: "Actions: 0" });
    const body = make("div", { class: "body" }, [
      input, captureBtn, harvestBtn, stopBtn, status, meter,
    ]);
    shadow.appendChild(header);
    shadow.appendChild(body);

    document.documentElement.appendChild(host);

    const setStatus = (msg) => { status.textContent = msg; };
    const refreshMeter = () => { meter.textContent = `Actions: ${actionSeq}`; };

    const doCapture = async () => {
      const tag = (input.value || "").trim() || "untitled";
      captureBtn.disabled = true;
      setStatus("Capturing...");
      try {
        const result = await window.__capture(tag);
        if (result && result.ok) {
          setStatus("Saved #" + result.index + " '" + result.tag + "'");
          input.value = "";
        } else {
          setStatus("Failed: " + ((result && result.error) || "unknown"));
        }
      } catch (e) {
        setStatus("Failed: " + (e && e.message ? e.message : e));
      } finally {
        captureBtn.disabled = false;
        refreshMeter();
      }
    };

    const doHarvest = async () => {
      if (typeof window.__harvestSession !== "function") return;
      harvestBtn.disabled = true;
      setStatus("Harvesting auth session...");
      try {
        const result = await window.__harvestSession();
        if (result && result.ok) {
          setStatus("Auth harvested #" + result.index);
        } else {
          setStatus("Harvest failed: " + ((result && result.error) || "unknown"));
        }
      } catch (e) {
        setStatus("Harvest failed: " + (e && e.message ? e.message : e));
      } finally {
        harvestBtn.disabled = false;
      }
    };

    let stopArmed = false;
    let stopArmTimer = null;
    const doStop = async () => {
      // Two-click confirm: first click arms, second click within 3s actually stops.
      // Avoids relying on window.confirm() which Playwright may auto-dismiss.
      if (!stopArmed) {
        stopArmed = true;
        stopBtn.textContent = "Click again to confirm stop";
        setStatus("Click Stop once more to end the session.");
        if (stopArmTimer) clearTimeout(stopArmTimer);
        stopArmTimer = setTimeout(() => {
          stopArmed = false;
          stopBtn.textContent = "Stop & save session";
          setStatus("Ready");
        }, 3000);
        return;
      }
      if (stopArmTimer) { clearTimeout(stopArmTimer); stopArmTimer = null; }
      stopBtn.disabled = true;
      captureBtn.disabled = true;
      setStatus("Stopping session...");
      try {
        if (typeof window.__stopSession === "function") {
          await window.__stopSession();
        }
        setStatus("Session stopped — you can close this window.");
      } catch (e) {
        setStatus("Stop failed: " + (e && e.message ? e.message : e));
        stopBtn.disabled = false;
        captureBtn.disabled = false;
      }
    };

    captureBtn.addEventListener("click", doCapture);
    harvestBtn.addEventListener("click", doHarvest);
    stopBtn.addEventListener("click", doStop);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); doCapture(); }
    });

    toggle.addEventListener("click", () => host.classList.toggle("collapsed"));
    document.addEventListener("keydown", (e) => {
      if (!e.ctrlKey || !e.shiftKey) return;
      if (e.key === "H" || e.key === "h") {
        e.preventDefault();
        host.classList.toggle("collapsed");
      } else if (e.key === "S" || e.key === "s") {
        e.preventDefault();
        doStop();
      } else if (e.key === "A" || e.key === "a") {
        e.preventDefault();
        doHarvest();
      }
    }, true);

    window.__overlay_hide = () => { host.style.setProperty("visibility", "hidden", "important"); };
    window.__overlay_show = () => { host.style.setProperty("visibility", "visible", "important"); };
    window.__overlay_bumpMeter = () => refreshMeter();

    // Serialize the document with the overlay host detached, then re-attach it —
    // so captured page.html reflects the portal only, not the recorder UI
    // (visibility:hidden keeps it in the DOM, so hiding isn't enough). Shadow
    // contents are encapsulated; detaching the single host removes everything.
    window.__overlay_clean_html = () => {
      const pairs = [host]
        .filter((n) => n && n.parentNode)
        .map((n) => {
          const ph = document.createComment("__recorder_removed__");
          n.parentNode.replaceChild(ph, n);
          return [ph, n];
        });
      try {
        const dt = document.doctype;
        const prefix = dt ? "<!DOCTYPE " + (dt.name || "html") + ">\n" : "";
        return prefix + document.documentElement.outerHTML;
      } finally {
        pairs.forEach(([ph, n]) => {
          if (ph.parentNode) ph.parentNode.replaceChild(n, ph);
        });
      }
    };

    // Dragging — header lives inside the shadow tree, so e.target there is the
    // real inner element (no retargeting within the same tree).
    let drag = null;
    header.addEventListener("mousedown", (e) => {
      if (e.target.tagName === "BUTTON") return;
      const rect = host.getBoundingClientRect();
      drag = { dx: e.clientX - rect.left, dy: e.clientY - rect.top };
      e.preventDefault();
    });
    window.addEventListener("mousemove", (e) => {
      if (!drag) return;
      host.style.setProperty("left", (e.clientX - drag.dx) + "px", "important");
      host.style.setProperty("top", (e.clientY - drag.dy) + "px", "important");
      host.style.setProperty("right", "auto", "important");
      host.style.setProperty("bottom", "auto", "important");
    });
    window.addEventListener("mouseup", () => { drag = null; });
  };

  if (IS_TOP) {
    // A UI failure must never stop action recording, so isolate it and keep
    // going. Surface to the console so a developer can see what happened.
    try {
      installUI();
      console.debug("[recorder-overlay] UI installed (top frame)");
    } catch (e) {
      console.warn("[recorder-overlay] UI install failed:", e);
    }
  } else {
    console.debug("[recorder-overlay] recording-only (subframe)");
  }

  // -------- action listeners (document-level, capture phase, all frames) --------

  // Log the page load itself so the action log shows navigations between pages.
  sendAction({ type: "page-load", title: document.title || null });

  const bumpUI = () => { if (typeof window.__overlay_bumpMeter === "function") window.__overlay_bumpMeter(); };

  document.addEventListener("click", (e) => {
    const t = e.target;
    if (isInOverlay(t)) return;
    sendAction({
      type: "click",
      selector: selectorFor(t),
      tag: t && t.tagName ? t.tagName.toLowerCase() : null,
      text: safeText(t),
      x: e.clientX,
      y: e.clientY,
      button: e.button
    });
    bumpUI();
  }, true);

  // Debounced input — last value per element after 400ms idle
  const inputTimers = new WeakMap();
  document.addEventListener("input", (e) => {
    const t = e.target;
    if (isInOverlay(t)) return;
    if (!t || !("value" in t)) return;
    if (inputTimers.has(t)) clearTimeout(inputTimers.get(t));
    const timer = setTimeout(() => {
      inputTimers.delete(t);
      sendAction({
        type: "input",
        selector: selectorFor(t),
        tag: t.tagName ? t.tagName.toLowerCase() : null,
        inputType: t.type || null,
        value: t.value == null ? null : String(t.value)
      });
      bumpUI();
    }, 400);
    inputTimers.set(t, timer);
  }, true);

  document.addEventListener("change", (e) => {
    const t = e.target;
    if (isInOverlay(t)) return;
    if (!t || t.tagName !== "SELECT") return; // <input> handled by input listener
    sendAction({
      type: "change",
      selector: selectorFor(t),
      value: t.value == null ? null : String(t.value),
      text: t.options && t.selectedIndex >= 0 ? safeText(t.options[t.selectedIndex]) : null
    });
    bumpUI();
  }, true);

  document.addEventListener("submit", (e) => {
    const t = e.target;
    if (isInOverlay(t)) return;
    sendAction({
      type: "submit",
      selector: selectorFor(t),
      action: t && t.getAttribute ? t.getAttribute("action") : null,
      method: t && t.getAttribute ? t.getAttribute("method") : null
    });
    bumpUI();
  }, true);

  document.addEventListener("keydown", (e) => {
    if (isInOverlay(e.target)) return;
    const interesting = e.key === "Enter" || e.key === "Escape" || e.key === "Tab"
      || ((e.ctrlKey || e.altKey || e.metaKey) && e.key && e.key.length === 1);
    if (!interesting) return;
    sendAction({
      type: "key",
      key: e.key,
      ctrl: !!e.ctrlKey, shift: !!e.shiftKey, alt: !!e.altKey, meta: !!e.metaKey,
      selector: selectorFor(e.target)
    });
    bumpUI();
  }, true);

  window.addEventListener("popstate", () => {
    sendAction({ type: "nav", reason: "popstate" });
    bumpUI();
  });
  window.addEventListener("hashchange", () => {
    sendAction({ type: "nav", reason: "hashchange" });
    bumpUI();
  });
})();
