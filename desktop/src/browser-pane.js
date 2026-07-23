"use strict";

const { WebContentsView, session } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

const MAX_TEXT = 40_000;
const CORNER_RADIUS = 8;
const DEFAULT_WORKSPACE = "default";
const MAX_CONSOLE_ENTRIES = 200;
const MAX_IMPORT_COOKIES = 10_000;

const READ_PAGE_JS = `(() => {
  const selector = 'a[href],button,input,select,textarea,summary,[role],[onclick],[contenteditable="true"],[draggable="true"],[ondragstart],[ondrop],.ui-draggable,.ui-droppable';
  const documents = [];
  const visitDocument = (doc, framePath = [], offsetX = 0, offsetY = 0) => {
    if (!doc || documents.some((entry) => entry.doc === doc)) return;
    documents.push({ doc, framePath, offsetX, offsetY });
    for (const frame of doc.querySelectorAll('iframe,frame')) {
      try {
        const rect = frame.getBoundingClientRect();
        visitDocument(
          frame.contentDocument,
          [...framePath, documents.length],
          offsetX + rect.left,
          offsetY + rect.top,
        );
      } catch {
        // Cross-origin frames remain visible in page text but cannot be inspected.
      }
    }
  };
  visitDocument(document);

  const rootsFor = (doc) => {
    const roots = [doc];
    const queue = [...doc.querySelectorAll('*')];
    while (queue.length) {
      const el = queue.shift();
      if (el && el.shadowRoot) {
        roots.push(el.shadowRoot);
        queue.push(...el.shadowRoot.querySelectorAll('*'));
      }
    }
    return roots;
  };
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    const style = el.ownerDocument.defaultView.getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none' &&
      Number(style.opacity || 1) > 0;
  };

  let seq = 0;
  const elements = [];
  const text = [];
  for (const entry of documents) {
    for (const root of rootsFor(entry.doc)) {
      for (const old of root.querySelectorAll('[data-elv-ref]')) {
        old.removeAttribute('data-elv-ref');
      }
      for (const el of root.querySelectorAll(selector)) {
        if (!visible(el)) continue;
        const ref = 'ref_' + (++seq);
        el.setAttribute('data-elv-ref', ref);
        const name = (
          el.getAttribute('aria-label') ||
          el.getAttribute('placeholder') ||
          el.getAttribute('title') ||
          (el.innerText || '') ||
          el.getAttribute('alt') ||
          ''
        ).replace(/\\s+/g, ' ').trim().slice(0, 160);
        const rect = el.getBoundingClientRect();
        elements.push({
          ref,
          tag: el.tagName.toLowerCase(),
          type: el.getAttribute('type') || '',
          role: el.getAttribute('role') || '',
          name,
          value:
            el.getAttribute('type') === 'password'
              ? ''
              : typeof el.value === 'string'
                ? el.value.slice(0, 160)
                : '',
          disabled: !!el.disabled,
          checked: typeof el.checked === 'boolean' ? el.checked : undefined,
          frame: entry.framePath,
          rect: {
            x: Math.round(entry.offsetX + rect.left),
            y: Math.round(entry.offsetY + rect.top),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          },
        });
      }
    }
    const bodyText = entry.doc.body ? entry.doc.body.innerText : '';
    if (bodyText) text.push(bodyText);
  }
  return {
    url: location.href,
    title: document.title,
    text: text.join('\\n').slice(0, ${MAX_TEXT}),
    elements,
  };
})()`;

function normalizeRef(ref) {
  const normalized = String(ref || "").replace(/^@/, "");
  if (!/^(?:e\d+|ref_\d+)$/.test(normalized)) {
    throw new Error(`bad ref: ${ref}`);
  }
  return normalized;
}

function locateJs(ref) {
  return `(() => {
    const wanted = "${normalizeRef(ref)}";
    const search = (root, offsetX = 0, offsetY = 0) => {
      const direct = root.querySelector('[data-elv-ref="' + wanted + '"]');
      if (direct) {
        direct.scrollIntoView({ block: 'center', inline: 'center' });
        const rect = direct.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return null;
        direct.focus();
        return {
          x: offsetX + rect.left + rect.width / 2,
          y: offsetY + rect.top + rect.height / 2,
        };
      }
      for (const el of root.querySelectorAll('*')) {
        if (el.shadowRoot) {
          const found = search(el.shadowRoot, offsetX, offsetY);
          if (found) return found;
        }
      }
      for (const frame of root.querySelectorAll('iframe,frame')) {
        try {
          const rect = frame.getBoundingClientRect();
          const found = search(
            frame.contentDocument,
            offsetX + rect.left,
            offsetY + rect.top,
          );
          if (found) return found;
        } catch {
          // Ignore cross-origin frames.
        }
      }
      return null;
    };
    return search(document);
  })()`;
}

function normalizeNavigationUrl(value) {
  const raw = String(value || "").trim();
  if (!raw || raw === "about:blank") return "about:blank";
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("malformed URL");
  }
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error(`unsupported URL scheme: ${parsed.protocol}`);
  }
  return parsed.toString();
}

function normalizeWorkspaceId(value) {
  const normalized = String(value || DEFAULT_WORKSPACE).trim();
  return normalized.slice(0, 256) || DEFAULT_WORKSPACE;
}

function standardBrowserUserAgent(platform = process.platform, chromeVersion = process.versions.chrome) {
  const version = String(chromeVersion || "120.0.0.0");
  if (platform === "darwin") {
    return `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${version} Safari/537.36`;
  }
  if (platform === "win32") {
    return `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${version} Safari/537.36`;
  }
  return `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${version} Safari/537.36`;
}

function clampPaneBounds(rect, contentBounds, zoom = 1) {
  const contentWidth = Math.max(0, Math.floor(Number(contentBounds?.width) || 0));
  const contentHeight = Math.max(0, Math.floor(Number(contentBounds?.height) || 0));
  const rawX = Math.ceil((Number(rect?.x) || 0) * zoom);
  const rawY = Math.ceil((Number(rect?.y) || 0) * zoom);
  const x = Math.min(contentWidth, Math.max(0, rawX));
  const y = Math.min(contentHeight, Math.max(0, rawY));
  const requestedRight = Math.floor(
    ((Number(rect?.x) || 0) + Math.max(0, Number(rect?.width) || 0)) * zoom,
  );
  const requestedBottom = Math.floor(
    ((Number(rect?.y) || 0) + Math.max(0, Number(rect?.height) || 0)) * zoom,
  );
  return {
    x,
    y,
    width: Math.max(0, Math.min(contentWidth, requestedRight) - x),
    height: Math.max(0, Math.min(contentHeight, requestedBottom) - y),
  };
}

function cookieUrl(cookie) {
  const domain = String(cookie?.domain || "").replace(/^\./, "").trim();
  if (!domain || /[\s/]/.test(domain)) return null;
  const secure = Boolean(cookie?.secure) ||
    /^__(?:Secure|Host)-/.test(String(cookie?.name || ""));
  const cookiePath = String(cookie?.path || "/");
  const normalizedPath = cookiePath.startsWith("/") ? cookiePath : `/${cookiePath}`;
  return `${secure ? "https" : "http"}://${domain}${normalizedPath}`;
}

function toElectronCookieDetails(cookie, nowSeconds = Date.now() / 1000) {
  // Electron 39 cannot preserve CHIPS partition keys. Importing one without
  // that key would widen its scope, so reject it even if a caller bypasses the
  // Chrome exporter.
  if (cookie?.partitionKey) return null;
  const url = cookieUrl(cookie);
  const name = String(cookie?.name || "");
  const value = typeof cookie?.value === "string" ? cookie.value : "";
  if (!url || !name) return null;

  const expires = Number(cookie?.expires);
  if (Number.isFinite(expires) && expires > 0 && expires <= nowSeconds) return null;

  const details = {
    url,
    name,
    value,
    path: String(cookie?.path || "/"),
    secure: Boolean(cookie?.secure) || /^__(?:Secure|Host)-/.test(name),
    httpOnly: Boolean(cookie?.httpOnly),
  };
  const domain = String(cookie?.domain || "");
  if (domain.startsWith(".") && !name.startsWith("__Host-")) details.domain = domain;
  if (Number.isFinite(expires) && expires > 0 && !cookie?.session) {
    details.expirationDate = expires;
  }

  const sameSite = String(cookie?.sameSite || "").toLowerCase();
  if (sameSite === "strict") details.sameSite = "strict";
  else if (sameSite === "lax") details.sameSite = "lax";
  else if (sameSite === "none" || sameSite === "no_restriction") {
    details.sameSite = "no_restriction";
    details.secure = true;
  }
  return details;
}

class BrowserPane {
  constructor({
    window,
    partition = "persist:elevate-browser",
    elevateHome = null,
    onEvent = () => {},
  }) {
    this.window = window;
    this.partition = partition;
    this.profileReceiptPath = elevateHome
      ? path.join(elevateHome, "browser-profile-import.json")
      : null;
    this.onEvent = onEvent;
    this.workspaces = new Map();
    this.currentWorkspaceId = DEFAULT_WORKSPACE;
    this.seq = 0;
    this.bounds = null;
    this.visible = false;
    this.browserSession = session.fromPartition(this.partition);
    this.userAgent = standardBrowserUserAgent();
    this.browserSession.setUserAgent(this.userAgent, "en-US,en;q=0.9");
  }

  _lastProfileImport() {
    if (!this.profileReceiptPath) return null;
    try {
      return JSON.parse(fs.readFileSync(this.profileReceiptPath, "utf8"));
    } catch {
      return null;
    }
  }

  async profileStatus() {
    const cookies = await this.browserSession.cookies.get({});
    return {
      persistent: this.partition.startsWith("persist:"),
      partition: this.partition,
      cookieCount: cookies.length,
      domainCount: new Set(
        cookies.map((cookie) => String(cookie.domain || "").replace(/^\./, "")),
      ).size,
      lastImport: this._lastProfileImport(),
    };
  }

  async importCookies(cookies, metadata = {}) {
    if (!Array.isArray(cookies)) throw new Error("cookies must be an array");
    if (cookies.length > MAX_IMPORT_COOKIES) {
      throw new Error(`cookie import exceeds ${MAX_IMPORT_COOKIES} entries`);
    }

    let imported = 0;
    let persistentImported = 0;
    let sessionImported = 0;
    let skipped = 0;
    let failed = 0;
    const queue = [];
    for (const cookie of cookies) {
      const details = toElectronCookieDetails(cookie);
      if (!details) {
        skipped += 1;
        continue;
      }
      queue.push(details);
    }

    for (let index = 0; index < queue.length; index += 50) {
      const batch = queue.slice(index, index + 50);
      const results = await Promise.allSettled(
        batch.map((details) =>
          this.browserSession.cookies.set(details)),
      );
      for (const [offset, result] of results.entries()) {
        if (result.status === "fulfilled") {
          imported += 1;
          if (batch[offset].expirationDate) persistentImported += 1;
          else sessionImported += 1;
        } else {
          failed += 1;
        }
      }
    }

    const receipt = {
      schemaVersion: 1,
      source: "chrome",
      sourceProfile: String(metadata.sourceProfile || "Chrome"),
      importedAt: new Date().toISOString(),
      persistent: this.partition.startsWith("persist:"),
      partition: this.partition,
      total: cookies.length,
      imported,
      persistentImported,
      sessionImported,
      skipped,
      failed,
    };
    if (this.profileReceiptPath) {
      fs.mkdirSync(path.dirname(this.profileReceiptPath), { recursive: true });
      fs.writeFileSync(this.profileReceiptPath, JSON.stringify(receipt), {
        mode: 0o600,
      });
      fs.chmodSync(this.profileReceiptPath, 0o600);
    }
    return receipt;
  }

  workspace(workspaceId, create = true) {
    const id = normalizeWorkspaceId(workspaceId);
    let workspace = this.workspaces.get(id);
    if (!workspace && create) {
      workspace = { id, tabs: new Map(), activeId: null };
      this.workspaces.set(id, workspace);
    }
    return workspace || null;
  }

  setWorkspace(workspaceId) {
    this.currentWorkspaceId = normalizeWorkspaceId(workspaceId);
    const workspace = this.workspace(this.currentWorkspaceId);
    if (!workspace.activeId) this.newTab("about:blank", workspace.id);
    this.applyLayout();
    this.emitTabs(workspace.id);
    return this.status(workspace.id);
  }

  newTab(url = "about:blank", workspaceId = this.currentWorkspaceId) {
    const workspace = this.workspace(workspaceId);
    const id = `tab_${++this.seq}`;
    const view = new WebContentsView({
      webPreferences: {
        session: this.browserSession,
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
      },
    });
    view.webContents.setUserAgent(this.userAgent);
    view.setVisible(false);
    view.setBounds({ x: 0, y: 0, width: 1, height: 1 });
    const tab = {
      id,
      workspaceId: workspace.id,
      view,
      title: "",
      favicon: null,
      lastError: null,
      console: [],
      errors: [],
    };
    workspace.tabs.set(id, tab);
    workspace.activeId = id;
    this._wire(tab);
    this.window.contentView.addChildView(view);
    this.applyLayout();
    this.emitTabs(workspace.id);
    if (url && url !== "about:blank") {
      this.navigate(id, url, workspace.id).catch(() => {});
    }
    return id;
  }

  closeTab(id, workspaceId = this.currentWorkspaceId) {
    const workspace = this.workspace(workspaceId, false);
    const tab = workspace?.tabs.get(id);
    if (!workspace || !tab) return false;
    this.window.contentView.removeChildView(tab.view);
    tab.view.webContents.close();
    workspace.tabs.delete(id);
    if (workspace.activeId === id) {
      workspace.activeId = workspace.tabs.keys().next().value || null;
    }
    if (!workspace.activeId) this.newTab("about:blank", workspace.id);
    this.applyLayout();
    this.emitTabs(workspace.id);
    return true;
  }

  selectTab(id, workspaceId = this.currentWorkspaceId) {
    const workspace = this.workspace(workspaceId, false);
    const tab = workspace?.tabs.get(id);
    if (!workspace || !tab) return false;
    workspace.activeId = id;
    this.window.contentView.addChildView(tab.view);
    this.applyLayout();
    this.emitTabs(workspace.id);
    return true;
  }

  tab(id, workspaceId = this.currentWorkspaceId) {
    const workspace = this.workspace(workspaceId, false);
    const tab = workspace?.tabs.get(id || workspace.activeId);
    if (!tab) throw new Error(`no such tab: ${id || workspace?.activeId || ""}`);
    return tab;
  }

  list(workspaceId = this.currentWorkspaceId) {
    const workspace = this.workspace(workspaceId);
    return [...workspace.tabs.values()].map((tab) => ({
      id: tab.id,
      url: tab.view.webContents.getURL() || "about:blank",
      title: tab.title,
      favicon: tab.favicon,
      active: tab.id === workspace.activeId,
      loading: tab.view.webContents.isLoading(),
      canGoBack: tab.view.webContents.navigationHistory.canGoBack(),
      canGoForward: tab.view.webContents.navigationHistory.canGoForward(),
      lastError: tab.lastError,
    }));
  }

  status(workspaceId = this.currentWorkspaceId) {
    const workspace = this.workspace(workspaceId);
    const active = workspace.activeId ? workspace.tabs.get(workspace.activeId) : null;
    return {
      open: this.visible && workspace.id === this.currentWorkspaceId,
      workspaceId: workspace.id,
      tabCount: workspace.tabs.size,
      activeTabId: workspace.activeId,
      url: active?.view.webContents.getURL() || "about:blank",
      title: active?.title || "",
      tabs: this.list(workspace.id),
    };
  }

  setBounds(rect) {
    if (!rect || typeof rect !== "object") return;
    const x = Number(rect.x);
    const y = Number(rect.y);
    const width = Number(rect.width);
    const height = Number(rect.height);
    if (![x, y, width, height].every(Number.isFinite)) return;
    this.bounds = { x, y, width, height };
    this.applyLayout();
  }

  setVisible(visible) {
    this.visible = Boolean(visible);
    this.applyLayout();
  }

  applyLayout() {
    if (!this.bounds || !this.window || this.window.isDestroyed()) return;
    const zoom = this.window.webContents.getZoomFactor();
    const [contentWidth, contentHeight] = this.window.getContentSize();
    const bounds = clampPaneBounds(
      this.bounds,
      { width: contentWidth, height: contentHeight },
      zoom,
    );
    for (const workspace of this.workspaces.values()) {
      for (const tab of workspace.tabs.values()) {
        tab.view.setBounds(bounds);
        if (typeof tab.view.setBorderRadius === "function") {
          tab.view.setBorderRadius(Math.round(CORNER_RADIUS * zoom));
        }
        tab.view.setVisible(
          this.visible &&
            bounds.width > 0 &&
            bounds.height > 0 &&
            workspace.id === this.currentWorkspaceId &&
            tab.id === workspace.activeId,
        );
      }
    }
  }

  async navigate(id, url, workspaceId = this.currentWorkspaceId) {
    const tab = this.tab(id, workspaceId);
    const target = normalizeNavigationUrl(url);
    tab.lastError = null;
    await tab.view.webContents.loadURL(target);
    return { ok: true, url: tab.view.webContents.getURL() };
  }

  async readPage(id, workspaceId = this.currentWorkspaceId) {
    return this.tab(id, workspaceId).view.webContents.executeJavaScript(
      READ_PAGE_JS,
      true,
    );
  }

  async _pointForRef(tab, ref) {
    const point = await tab.view.webContents.executeJavaScript(locateJs(ref), true);
    if (!point) throw new Error(`ref not found or not visible: ${ref}`);
    const zoom = tab.view.webContents.getZoomFactor();
    return { x: Math.round(point.x * zoom), y: Math.round(point.y * zoom) };
  }

  async click(id, ref, workspaceId = this.currentWorkspaceId) {
    const tab = this.tab(id, workspaceId);
    const point = await this._pointForRef(tab, ref);
    for (const type of ["mouseDown", "mouseUp"]) {
      tab.view.webContents.sendInputEvent({
        type,
        ...point,
        button: "left",
        clickCount: 1,
      });
    }
    return { ok: true, at: point };
  }

  async drag(id, sourceRef, targetRef, workspaceId = this.currentWorkspaceId) {
    const tab = this.tab(id, workspaceId);
    const source = await this._pointForRef(tab, sourceRef);
    const target = await this._pointForRef(tab, targetRef);
    tab.view.webContents.sendInputEvent({ type: "mouseMove", ...source });
    tab.view.webContents.sendInputEvent({
      type: "mouseDown",
      ...source,
      button: "left",
      clickCount: 1,
    });
    for (let step = 1; step <= 8; step += 1) {
      tab.view.webContents.sendInputEvent({
        type: "mouseMove",
        x: Math.round(source.x + ((target.x - source.x) * step) / 8),
        y: Math.round(source.y + ((target.y - source.y) * step) / 8),
        button: "left",
      });
    }
    tab.view.webContents.sendInputEvent({
      type: "mouseUp",
      ...target,
      button: "left",
      clickCount: 1,
    });
    return { ok: true, from: source, to: target };
  }

  async fill(id, ref, value, workspaceId = this.currentWorkspaceId) {
    const tab = this.tab(id, workspaceId);
    await this.click(id, ref, workspaceId);
    const modifier = process.platform === "darwin" ? "meta" : "control";
    tab.view.webContents.sendInputEvent({
      type: "keyDown",
      keyCode: "A",
      modifiers: [modifier],
    });
    tab.view.webContents.sendInputEvent({
      type: "keyUp",
      keyCode: "A",
      modifiers: [modifier],
    });
    tab.view.webContents.sendInputEvent({ type: "keyDown", keyCode: "Backspace" });
    tab.view.webContents.sendInputEvent({ type: "keyUp", keyCode: "Backspace" });
    for (const char of String(value)) {
      tab.view.webContents.sendInputEvent({ type: "char", keyCode: char });
    }
    return { ok: true };
  }

  async type(id, text, workspaceId = this.currentWorkspaceId) {
    const tab = this.tab(id, workspaceId);
    for (const char of String(text)) {
      tab.view.webContents.sendInputEvent({ type: "char", keyCode: char });
    }
    return { ok: true };
  }

  async key(id, keyCode, workspaceId = this.currentWorkspaceId) {
    const tab = this.tab(id, workspaceId);
    const key = String(keyCode || "");
    tab.view.webContents.sendInputEvent({ type: "keyDown", keyCode: key });
    tab.view.webContents.sendInputEvent({ type: "keyUp", keyCode: key });
    return { ok: true };
  }

  async scroll(id, dy, workspaceId = this.currentWorkspaceId) {
    await this.tab(id, workspaceId).view.webContents.executeJavaScript(
      `window.scrollBy({ top: ${Number(dy) || 0}, behavior: "instant" })`,
      true,
    );
    return { ok: true };
  }

  back(id, workspaceId = this.currentWorkspaceId) {
    const contents = this.tab(id, workspaceId).view.webContents;
    if (contents.navigationHistory.canGoBack()) contents.navigationHistory.goBack();
    return { ok: true, url: contents.getURL() };
  }

  forward(id, workspaceId = this.currentWorkspaceId) {
    const contents = this.tab(id, workspaceId).view.webContents;
    if (contents.navigationHistory.canGoForward()) contents.navigationHistory.goForward();
    return { ok: true, url: contents.getURL() };
  }

  reload(id, workspaceId = this.currentWorkspaceId) {
    const contents = this.tab(id, workspaceId).view.webContents;
    contents.reload();
    return { ok: true, url: contents.getURL() };
  }

  async evaluate(id, expression, workspaceId = this.currentWorkspaceId) {
    const result = await this.tab(id, workspaceId).view.webContents.executeJavaScript(
      String(expression || ""),
      true,
    );
    return { ok: true, result };
  }

  async screenshot(id, workspaceId = this.currentWorkspaceId) {
    const image = await this.tab(id, workspaceId).view.webContents.capturePage();
    return { ok: true, png_base64: image.toPNG().toString("base64") };
  }

  console(id, workspaceId = this.currentWorkspaceId) {
    const tab = this.tab(id, workspaceId);
    return { messages: tab.console, errors: tab.errors };
  }

  noteAgentAction(workspaceId, method) {
    const workspace = normalizeWorkspaceId(workspaceId);
    this.emit("agent-action", { workspaceId: workspace, method });
  }

  _wire(tab) {
    const contents = tab.view.webContents;

    contents.on("will-navigate", (event, url) => {
      try {
        normalizeNavigationUrl(url);
      } catch (error) {
        event.preventDefault();
        this.emit("blocked", {
          workspaceId: tab.workspaceId,
          tabId: tab.id,
          url,
          reason: error && error.message ? error.message : String(error),
        });
      }
    });

    contents.setWindowOpenHandler(({ url }) => {
      try {
        normalizeNavigationUrl(url);
        this.newTab(url, tab.workspaceId);
      } catch (error) {
        this.emit("blocked", {
          workspaceId: tab.workspaceId,
          tabId: tab.id,
          url,
          reason: error && error.message ? error.message : String(error),
        });
      }
      return { action: "deny" };
    });

    contents.on("page-title-updated", (_event, title) => {
      tab.title = title;
      this.emitTabs(tab.workspaceId);
    });
    contents.on("page-favicon-updated", (_event, favicons) => {
      tab.favicon = Array.isArray(favicons) ? favicons[0] || null : null;
      this.emitTabs(tab.workspaceId);
    });
    contents.on("console-message", (_event, level, message, line, sourceId) => {
      const entry = { level, message, line, sourceId, at: Date.now() };
      tab.console.push(entry);
      tab.console = tab.console.slice(-MAX_CONSOLE_ENTRIES);
      if (level >= 2) {
        tab.errors.push(entry);
        tab.errors = tab.errors.slice(-MAX_CONSOLE_ENTRIES);
      }
    });
    contents.on("render-process-gone", (_event, details) => {
      tab.errors.push({
        level: 3,
        message: `Renderer exited: ${details.reason}`,
        at: Date.now(),
      });
      tab.errors = tab.errors.slice(-MAX_CONSOLE_ENTRIES);
    });
    contents.on("did-start-loading", () => this.emitTabs(tab.workspaceId));
    contents.on("did-stop-loading", () => this.emitTabs(tab.workspaceId));
    contents.on("did-navigate", () => this.emitTabs(tab.workspaceId));
    contents.on("did-navigate-in-page", () => this.emitTabs(tab.workspaceId));
    contents.on("did-fail-load", (_event, code, description, url) => {
      if (code === -3) return;
      tab.lastError = `${code} ${description}`;
      tab.errors.push({ level: 3, message: tab.lastError, url, at: Date.now() });
      tab.errors = tab.errors.slice(-MAX_CONSOLE_ENTRIES);
      this.emit("load-failed", {
        workspaceId: tab.workspaceId,
        tabId: tab.id,
        url,
        code,
        description,
      });
      this.emitTabs(tab.workspaceId);
    });
  }

  emit(type, payload) {
    this.onEvent({ type, ...payload });
  }

  emitTabs(workspaceId = this.currentWorkspaceId) {
    const normalized = normalizeWorkspaceId(workspaceId);
    this.emit("tabs", { workspaceId: normalized, tabs: this.list(normalized) });
  }

  destroy() {
    this.visible = false;
    for (const workspace of this.workspaces.values()) {
      for (const tab of workspace.tabs.values()) {
        try {
          this.window.contentView.removeChildView(tab.view);
          tab.view.webContents.close();
        } catch {
          // Window teardown can beat child-view cleanup.
        }
      }
      workspace.tabs.clear();
      workspace.activeId = null;
    }
    this.workspaces.clear();
  }
}

function registerPaneIpc(ipcMain, getPane) {
  const withPane = (handler) => (_event, ...args) => {
    const pane = getPane();
    if (!pane) throw new Error("browser pane is unavailable");
    return handler(pane, ...args);
  };

  ipcMain.handle("browser:set-workspace", withPane(
    (pane, workspaceId) => pane.setWorkspace(workspaceId),
  ));
  ipcMain.handle("browser:set-bounds", withPane((pane, rect) => pane.setBounds(rect)));
  ipcMain.handle("browser:set-visible", withPane((pane, visible) => pane.setVisible(visible)));
  ipcMain.handle("browser:list", withPane(
    (pane, workspaceId) => pane.list(workspaceId),
  ));
  ipcMain.handle("browser:new-tab", withPane(
    (pane, workspaceId, url) => pane.newTab(url, workspaceId),
  ));
  ipcMain.handle("browser:close-tab", withPane(
    (pane, workspaceId, id) => pane.closeTab(id, workspaceId),
  ));
  ipcMain.handle("browser:select-tab", withPane(
    (pane, workspaceId, id) => pane.selectTab(id, workspaceId),
  ));
  ipcMain.handle("browser:navigate", withPane(
    (pane, workspaceId, id, url) => pane.navigate(id, url, workspaceId),
  ));
  ipcMain.handle("browser:back", withPane(
    (pane, workspaceId, id) => pane.back(id, workspaceId),
  ));
  ipcMain.handle("browser:forward", withPane(
    (pane, workspaceId, id) => pane.forward(id, workspaceId),
  ));
  ipcMain.handle("browser:reload", withPane(
    (pane, workspaceId, id) => pane.reload(id, workspaceId),
  ));
}

module.exports = {
  BrowserPane,
  clampPaneBounds,
  cookieUrl,
  normalizeWorkspaceId,
  registerPaneIpc,
  standardBrowserUserAgent,
  toElectronCookieDetails,
};
