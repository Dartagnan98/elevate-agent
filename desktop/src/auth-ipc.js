"use strict";

function registerAuthIpc({
  hqBaseUrl,
  ipcMain,
  loadAppPath,
  mainWindow,
  performLogin,
  setTimeout,
  shell,
  startPath,
}) {
  ipcMain.handle("auth:login", async (_event, payload) => {
    const result = await performLogin(payload || {});
    if (result.ok) {
      setTimeout(() => {
        const win = mainWindow();
        if (win && !win.isDestroyed()) loadAppPath(startPath);
      }, 250);
    }
    return result;
  });

  ipcMain.handle("auth:open-external", async (_event, target) => {
    const paths = {
      forgot: "/forgot?app=1",
      signup: "/signup",
      link: "/link",
      account: "/account",
    };
    const safePath = paths[target];
    if (!safePath) return { ok: false };
    await shell.openExternal(`${hqBaseUrl}${safePath}`);
    return { ok: true };
  });
}

module.exports = { registerAuthIpc };
