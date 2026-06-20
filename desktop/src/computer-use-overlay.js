function createComputerUseOverlay({
  BrowserWindow,
  screen,
  fs,
  path,
  dirname,
  flagPath,
  freshMs,
}) {
  let overlayWindow = null;
  let overlayWatcher = null;

  function createOverlay() {
    // Reusing the existing overlay avoids leaking a window each time the
    // desktop is (re)started.
    if (overlayWindow && !overlayWindow.isDestroyed()) return;
    // A frameless, transparent, click-through window that draws a pulsing glow
    // around the screen while the computer-use tool is active. It floats above
    // everything (including full-screen apps) and never steals focus or clicks.
    const display = screen.getPrimaryDisplay();
    const { x, y, width, height } = display.bounds;
    overlayWindow = new BrowserWindow({
      x,
      y,
      width,
      height,
      show: false,
      frame: false,
      transparent: true,
      hasShadow: false,
      resizable: false,
      movable: false,
      minimizable: false,
      maximizable: false,
      fullscreenable: false,
      focusable: false,
      skipTaskbar: true,
      acceptFirstMouse: false,
      enableLargerThanScreen: true,
      backgroundColor: "#00000000",
      webPreferences: { contextIsolation: true, nodeIntegration: false },
    });
    overlayWindow.setIgnoreMouseEvents(true, { forward: true });
    overlayWindow.setAlwaysOnTop(true, "screen-saver");
    if (process.platform === "darwin") {
      overlayWindow.setVisibleOnAllWorkspaces(true, {
        visibleOnFullScreen: true,
      });
    }
    overlayWindow.loadFile(path.join(dirname, "overlay.html"));
    overlayWindow.on("closed", () => {
      overlayWindow = null;
    });
  }

  function setOverlayVisible(visible) {
    if (visible) {
      createOverlay();
    }
    if (!overlayWindow || overlayWindow.isDestroyed()) return;
    if (visible && !overlayWindow.isVisible()) {
      const { x, y, width, height } = screen.getPrimaryDisplay().bounds;
      overlayWindow.setBounds({ x, y, width, height });
      overlayWindow.showInactive();
    } else if (!visible) {
      overlayWindow.destroy();
      overlayWindow = null;
    }
  }

  function startOverlayWatcher() {
    if (overlayWatcher) return;
    overlayWatcher = setInterval(() => {
      let fresh = false;
      try {
        const stat = fs.statSync(flagPath);
        fresh = Date.now() - stat.mtimeMs < freshMs;
      } catch {
        fresh = false;
      }
      setOverlayVisible(fresh);
    }, 1000);
  }

  function dispose() {
    if (overlayWatcher) {
      clearInterval(overlayWatcher);
      overlayWatcher = null;
    }
    if (overlayWindow && !overlayWindow.isDestroyed()) {
      overlayWindow.destroy();
    }
  }

  return { createOverlay, dispose, setOverlayVisible, startOverlayWatcher };
}

module.exports = { createComputerUseOverlay };
