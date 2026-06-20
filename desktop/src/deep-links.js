"use strict";

function createDeepLinks({ app, mainWindow, openLoginWindow }) {
  let pendingDeepLink = null;

  function handleDeepLink(url) {
    if (!url) return;
    const win = mainWindow();
    if (!win || win.isDestroyed()) {
      pendingDeepLink = url;
      return;
    }
    app.focus({ steal: true });
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
    openLoginWindow();
  }

  function registerOpenUrl() {
    app.on("open-url", (event, url) => {
      event.preventDefault();
      handleDeepLink(url);
    });
  }

  function registerProtocolClient() {
    app.setAsDefaultProtocolClient("elevate");
  }

  function replayPending() {
    if (!pendingDeepLink) return;
    const url = pendingDeepLink;
    pendingDeepLink = null;
    handleDeepLink(url);
  }

  return {
    handleDeepLink,
    registerOpenUrl,
    registerProtocolClient,
    replayPending,
  };
}

module.exports = { createDeepLinks };
