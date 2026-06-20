function createInstallerController({
  appendBackendLog,
  dialog,
  ensureBackend,
  envWithPath,
  findCommand,
  loadAppPath,
  loadLocalPage,
  mainWindow,
  os,
  spawn,
  startPath,
}) {
  let installProcess = null;

  function currentWindow() {
    return typeof mainWindow === "function" ? mainWindow() : mainWindow;
  }

  function runInstaller() {
    if (installProcess) {
      return { ok: false, message: "Install is already running." };
    }

    const npx = findCommand("npx");
    if (!npx) {
      return { ok: false, message: "npx was not found. Install Node.js first, then retry." };
    }

    installProcess = spawn(
      npx,
      ["--yes", "github:Dartagnan98/elevate-agent", "install", "--skip-setup"],
      {
        cwd: os.homedir(),
        env: envWithPath(),
        stdio: ["ignore", "pipe", "pipe"],
      },
    );

    installProcess.stdout.on("data", appendBackendLog);
    installProcess.stderr.on("data", appendBackendLog);
    installProcess.on("exit", async (code) => {
      installProcess = null;
      if (code === 0 && currentWindow()) {
        const ready = await ensureBackend();
        if (ready) {
          loadAppPath(startPath);
          return;
        }
        loadLocalPage("install.html");
        dialog.showErrorBox("Elevate install failed", "The installer finished, but Elevate was still not ready. Check the terminal logs and try again.");
      } else if (currentWindow()) {
        dialog.showErrorBox("Elevate install failed", "The installer exited before Elevate was ready. Check the terminal logs and try again.");
      }
    });

    return { ok: true, message: "Install started." };
  }

  async function retry() {
    loadLocalPage("loading.html");
    const ready = await ensureBackend();
    if (ready) {
      loadAppPath(startPath);
      return { ok: true };
    }
    loadLocalPage("install.html");
    return { ok: false };
  }

  return { retry, runInstaller };
}

module.exports = { createInstallerController };
