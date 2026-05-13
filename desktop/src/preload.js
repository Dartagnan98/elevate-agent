const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("elevateDesktop", {
  retry: () => ipcRenderer.invoke("desktop:retry"),
  install: () => ipcRenderer.invoke("desktop:install"),
});
