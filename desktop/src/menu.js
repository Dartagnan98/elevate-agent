"use strict";

function createMenu({
  app,
  backendUrl,
  clearLicense,
  hqBaseUrl,
  loadAppPath,
  mainWindow,
  Menu,
  openLoginWindow,
  shell,
  startPath,
}) {
  const template = [
    {
      label: "Elevate",
      submenu: [
        { role: "about" },
        { type: "separator" },
        {
          label: "Sign In...",
          accelerator: "CmdOrCtrl+L",
          click: () => openLoginWindow(),
        },
        {
          label: "Account...",
          click: () => shell.openExternal(`${hqBaseUrl}/account`),
        },
        {
          label: "Sign Out",
          click: () => {
            clearLicense();
            if (mainWindow() && !mainWindow().isDestroyed()) {
              loadAppPath(startPath);
            }
          },
        },
        { type: "separator" },
        {
          label: "Quit Elevate",
          accelerator: "CmdOrCtrl+Q",
          click: () => app.quit(),
        },
      ],
    },
    {
      label: "Edit",
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        { role: "pasteAndMatchStyle" },
        { role: "delete" },
        { role: "selectAll" },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload", accelerator: "CmdOrCtrl+R" },
        { role: "forceReload", accelerator: "Shift+CmdOrCtrl+R" },
        { type: "separator" },
        { role: "resetZoom", accelerator: "CmdOrCtrl+0" },
        { role: "zoomIn", accelerator: "CmdOrCtrl+Plus" },
        { role: "zoomOut", accelerator: "CmdOrCtrl+-" },
      ],
    },
    {
      label: "Navigate",
      submenu: [
        { label: "Chat", accelerator: "CmdOrCtrl+1", click: () => loadAppPath("/chat") },
        { label: "Agent Hub", accelerator: "CmdOrCtrl+2", click: () => loadAppPath("/hub") },
        { label: "Setup", accelerator: "CmdOrCtrl+3", click: () => loadAppPath("/desktop-setup") },
        { label: "Tasks", accelerator: "CmdOrCtrl+4", click: () => loadAppPath("/tasks") },
        { label: "Memory", accelerator: "CmdOrCtrl+5", click: () => loadAppPath("/memory") },
      ],
    },
    {
      label: "Window",
      submenu: [
        { role: "minimize", accelerator: "CmdOrCtrl+M" },
        { role: "zoom" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    {
      label: "Help",
      submenu: [
        {
          label: "Open Dashboard In Browser",
          click: () => shell.openExternal(backendUrl()),
        },
        {
          label: "Toggle Developer Tools",
          accelerator: "Alt+CmdOrCtrl+I",
          click: () => mainWindow()?.webContents.toggleDevTools(),
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

module.exports = { createMenu };
