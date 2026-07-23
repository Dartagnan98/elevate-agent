const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("elevateDesktop", {
  retry: () => ipcRenderer.invoke("desktop:retry"),
  install: () => ipcRenderer.invoke("desktop:install"),

  // Auth gate. login.html drives this.
  auth: {
    login: (creds) => ipcRenderer.invoke("auth:login", creds),
    openExternal: (target) => ipcRenderer.invoke("auth:open-external", target),
  },

  // Auto-update API. The renderer should:
  //   1. Call getStatus() on mount to get the current state (in case events
  //      fired before the listener attached).
  //   2. Call onEvent(cb) to subscribe to live updates.
  //   3. Call checkNow() if the user clicks a "Check for updates" button.
  //   4. Call install() when status === "ready" and the user clicks Restart.
  updater: {
    getStatus: () => ipcRenderer.invoke("updater:status"),
    checkNow: () => ipcRenderer.invoke("updater:check"),
    install: () => ipcRenderer.invoke("updater:install"),
    onEvent: (callback) => {
      const handler = (_event, payload) => callback(payload);
      ipcRenderer.on("updater:event", handler);
      // Return an unsubscribe function so the renderer can clean up on
      // window unload without leaking listeners.
      return () => ipcRenderer.removeListener("updater:event", handler);
    },
  },

  browserPane: {
    setBounds: (rect) => ipcRenderer.invoke("browser:set-bounds", rect),
    setVisible: (visible) => ipcRenderer.invoke("browser:set-visible", visible),
    list: () => ipcRenderer.invoke("browser:list"),
    newTab: (url) => ipcRenderer.invoke("browser:new-tab", url),
    closeTab: (id) => ipcRenderer.invoke("browser:close-tab", id),
    selectTab: (id) => ipcRenderer.invoke("browser:select-tab", id),
    navigate: (id, url) => ipcRenderer.invoke("browser:navigate", id, url),
    back: (id) => ipcRenderer.invoke("browser:back", id),
    forward: (id) => ipcRenderer.invoke("browser:forward", id),
    reload: (id) => ipcRenderer.invoke("browser:reload", id),
    onEvent: (callback) => {
      const handler = (_event, payload) => callback(payload);
      ipcRenderer.on("browser:event", handler);
      return () => ipcRenderer.removeListener("browser:event", handler);
    },
  },
});
