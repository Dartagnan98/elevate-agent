"use strict";

const { WebContentsView, session } = require("electron");

const MAX_TEXT = 40_000;
const CORNER_RADIUS = 8;

const READ_PAGE_JS = `(() => {
  const selector = 'a[href],button,input,select,textarea,summary,[role],[onclick],[contenteditable="true"]';
  for (const el of document.querySelectorAll('[data-elv-ref]')) {
    el.removeAttribute('data-elv-ref');
  }
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    const style = getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none';
  };
  let seq = 0;
  const elements = [];
  for (const el of document.querySelectorAll(selector)) {
    if (!visible(el)) continue;
    const ref = 'e' + (++seq);
    el.setAttribute('data-elv-ref', ref);
    const name = (
      el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') ||
      el.getAttribute('title') ||
      (el.innerText || '') ||
      el.getAttribute('alt') ||
      ''
    ).replace(/\\s+/g, ' ').trim().slice(0, 160);
    elements.push({
      ref,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      role: el.getAttribute('role') || '',
      name,
      value: typeof el.value === 'string' ? el.value.slice(0, 160) : '',
      disabled: !!el.disabled,
    });
  }
  return {
    url: location.href,
    title: document.title,
    text: (document.body ? document.body.innerText : '').slice(0, ${MAX_TEXT}),
    elements,
  };
})()`;

function normalizeRef(ref) {
  const normalized = String(ref || "").replace(/^@/, "");
  if (!/^e\d+$/.test(normalized)) throw new Error(`bad ref: ${ref}`);
  return normalized;
}

function locateJs(ref) {
  return `(() => {
    const el = document.querySelector('[data-elv-ref="${normalizeRef(ref)}"]');
    if (!el) return null;
    el.scrollIntoView({ block: 'center', inline: 'center' });
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    el.focus();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
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

class BrowserPane {
  constructor({ window, partition = "persist:elevate-browser", onEvent = () => {} }) {
    this.window = window;
    this.partition = partition;
    this.onEvent = onEvent;
    this.tabs = new Map();
    this.activeId = null;
    this.seq = 0;
    this.bounds = null;
    this.visible = false;
  }

  newTab(url = "about:blank") {
    const id = `tab_${++this.seq}`;
    const view = new WebContentsView({
      webPreferences: {
        session: session.fromPartition(this.partition),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
      },
    });
    view.setVisible(false);
    view.setBounds({ x: 0, y: 0, width: 1, height: 1 });
    const tab = { id, view, title: "", lastError: null };
    this.tabs.set(id, tab);
    this._wire(tab);
    this.window.contentView.addChildView(view);
    this.activeId = id;
    this.applyLayout();
    this.emitTabs();
    if (url && url !== "about:blank") {
      this.navigate(id, url).catch(() => {});
    }
    return id;
  }

  closeTab(id) {
    const tab = this.tabs.get(id);
    if (!tab) return false;
    this.window.contentView.removeChildView(tab.view);
    tab.view.webContents.close();
    this.tabs.delete(id);
    if (this.activeId === id) {
      this.activeId = this.tabs.keys().next().value || null;
    }
    if (!this.activeId) this.newTab();
    this.applyLayout();
    this.emitTabs();
    return true;
  }

  selectTab(id) {
    const tab = this.tabs.get(id);
    if (!tab) return false;
    this.activeId = id;
    this.window.contentView.addChildView(tab.view);
    this.applyLayout();
    this.emitTabs();
    return true;
  }

  tab(id) {
    const tab = this.tabs.get(id || this.activeId);
    if (!tab) throw new Error(`no such tab: ${id || this.activeId}`);
    return tab;
  }

  list() {
    return [...this.tabs.values()].map((tab) => ({
      id: tab.id,
      url: tab.view.webContents.getURL() || "about:blank",
      title: tab.title,
      active: tab.id === this.activeId,
      loading: tab.view.webContents.isLoading(),
      canGoBack: tab.view.webContents.navigationHistory.canGoBack(),
      canGoForward: tab.view.webContents.navigationHistory.canGoForward(),
      lastError: tab.lastError,
    }));
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
    const x = Math.ceil(this.bounds.x * zoom);
    const y = Math.ceil(this.bounds.y * zoom);
    const width = Math.max(
      0,
      Math.floor((this.bounds.x + this.bounds.width) * zoom) - x,
    );
    const height = Math.max(
      0,
      Math.floor((this.bounds.y + this.bounds.height) * zoom) - y,
    );
    for (const tab of this.tabs.values()) {
      tab.view.setBounds({ x, y, width, height });
      if (typeof tab.view.setBorderRadius === "function") {
        tab.view.setBorderRadius(Math.round(CORNER_RADIUS * zoom));
      }
      tab.view.setVisible(
        this.visible && width > 0 && height > 0 && tab.id === this.activeId,
      );
    }
  }

  async navigate(id, url) {
    const tab = this.tab(id);
    const target = normalizeNavigationUrl(url);
    tab.lastError = null;
    await tab.view.webContents.loadURL(target);
    return { ok: true, url: tab.view.webContents.getURL() };
  }

  async readPage(id) {
    return this.tab(id).view.webContents.executeJavaScript(READ_PAGE_JS, true);
  }

  async _pointForRef(tab, ref) {
    const point = await tab.view.webContents.executeJavaScript(locateJs(ref), true);
    if (!point) throw new Error(`ref not found or not visible: ${ref}`);
    const zoom = tab.view.webContents.getZoomFactor();
    return { x: Math.round(point.x * zoom), y: Math.round(point.y * zoom) };
  }

  async click(id, ref) {
    const tab = this.tab(id);
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

  async fill(id, ref, value) {
    const tab = this.tab(id);
    await this.click(id, ref);
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

  async type(id, text) {
    const tab = this.tab(id);
    for (const char of String(text)) {
      tab.view.webContents.sendInputEvent({ type: "char", keyCode: char });
    }
    return { ok: true };
  }

  async key(id, keyCode) {
    const tab = this.tab(id);
    const key = String(keyCode || "");
    tab.view.webContents.sendInputEvent({ type: "keyDown", keyCode: key });
    tab.view.webContents.sendInputEvent({ type: "keyUp", keyCode: key });
    return { ok: true };
  }

  async scroll(id, dy) {
    await this.tab(id).view.webContents.executeJavaScript(
      `window.scrollBy({ top: ${Number(dy) || 0}, behavior: "instant" })`,
      true,
    );
    return { ok: true };
  }

  back(id) {
    const contents = this.tab(id).view.webContents;
    if (contents.navigationHistory.canGoBack()) contents.navigationHistory.goBack();
    return { ok: true, url: contents.getURL() };
  }

  forward(id) {
    const contents = this.tab(id).view.webContents;
    if (contents.navigationHistory.canGoForward()) contents.navigationHistory.goForward();
    return { ok: true, url: contents.getURL() };
  }

  reload(id) {
    const contents = this.tab(id).view.webContents;
    contents.reload();
    return { ok: true, url: contents.getURL() };
  }

  async evaluate(id, expression) {
    const result = await this.tab(id).view.webContents.executeJavaScript(
      String(expression || ""),
      true,
    );
    return { ok: true, result };
  }

  async screenshot(id) {
    const image = await this.tab(id).view.webContents.capturePage();
    return { ok: true, png_base64: image.toPNG().toString("base64") };
  }

  _wire(tab) {
    const contents = tab.view.webContents;

    contents.on("will-navigate", (event, url) => {
      try {
        normalizeNavigationUrl(url);
      } catch (error) {
        event.preventDefault();
        this.emit("blocked", {
          tabId: tab.id,
          url,
          reason: error && error.message ? error.message : String(error),
        });
      }
    });

    contents.setWindowOpenHandler(({ url }) => {
      try {
        normalizeNavigationUrl(url);
        this.newTab(url);
      } catch (error) {
        this.emit("blocked", {
          tabId: tab.id,
          url,
          reason: error && error.message ? error.message : String(error),
        });
      }
      return { action: "deny" };
    });

    contents.on("page-title-updated", (_event, title) => {
      tab.title = title;
      this.emitTabs();
    });
    contents.on("did-start-loading", () => this.emitTabs());
    contents.on("did-stop-loading", () => this.emitTabs());
    contents.on("did-navigate", () => this.emitTabs());
    contents.on("did-navigate-in-page", () => this.emitTabs());
    contents.on("did-fail-load", (_event, code, description, url) => {
      if (code === -3) return;
      tab.lastError = `${code} ${description}`;
      this.emit("load-failed", {
        tabId: tab.id,
        url,
        code,
        description,
      });
      this.emitTabs();
    });
  }

  emit(type, payload) {
    this.onEvent({ type, ...payload });
  }

  emitTabs() {
    this.emit("tabs", { tabs: this.list() });
  }

  destroy() {
    this.visible = false;
    for (const tab of [...this.tabs.values()]) {
      try {
        this.window.contentView.removeChildView(tab.view);
        tab.view.webContents.close();
      } catch {
        // Window teardown can beat child-view cleanup.
      }
    }
    this.tabs.clear();
    this.activeId = null;
  }
}

function registerPaneIpc(ipcMain, getPane) {
  const withPane = (handler) => (_event, ...args) => {
    const pane = getPane();
    if (!pane) throw new Error("browser pane is unavailable");
    return handler(pane, ...args);
  };

  ipcMain.handle("browser:set-bounds", withPane((pane, rect) => pane.setBounds(rect)));
  ipcMain.handle("browser:set-visible", withPane((pane, visible) => pane.setVisible(visible)));
  ipcMain.handle("browser:list", withPane((pane) => pane.list()));
  ipcMain.handle("browser:new-tab", withPane((pane, url) => pane.newTab(url)));
  ipcMain.handle("browser:close-tab", withPane((pane, id) => pane.closeTab(id)));
  ipcMain.handle("browser:select-tab", withPane((pane, id) => pane.selectTab(id)));
  ipcMain.handle("browser:navigate", withPane((pane, id, url) => pane.navigate(id, url)));
  ipcMain.handle("browser:back", withPane((pane, id) => pane.back(id)));
  ipcMain.handle("browser:forward", withPane((pane, id) => pane.forward(id)));
  ipcMain.handle("browser:reload", withPane((pane, id) => pane.reload(id)));
}

module.exports = { BrowserPane, registerPaneIpc };
