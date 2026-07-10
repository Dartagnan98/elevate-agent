function createGatewaySelfHeal({
  app,
  appendBackendLog,
  envWithPath,
  fileExists,
  fs,
  os,
  path,
  process,
  spawn,
  elevateHome = path.join(os.homedir(), ".elevate"),
  gatewayLabel = "ai.elevate.gateway",
}) {
  // Async replacement for the old injected spawnSync — resolves with the
  // same result shape ({status, signal, stdout, stderr, error}) so the
  // heal chain reads identically but never blocks Electron's main thread
  // (the install step alone could freeze IPC/menus for up to 90s).
  function run(command, args, { cwd, env, timeout = 90000 } = {}) {
    return new Promise((resolve) => {
      let child;
      try {
        child = spawn(command, args, { cwd, env });
      } catch (error) {
        resolve({ status: null, signal: null, stdout: "", stderr: "", error });
        return;
      }
      let stdout = "";
      let stderr = "";
      let settled = false;
      const timer = setTimeout(() => {
        try {
          child.kill("SIGTERM");
        } catch {
          /* already gone */
        }
      }, timeout);
      const settle = (status, signal, error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve({ status, signal: signal || null, stdout, stderr, error });
      };
      if (child.stdout) child.stdout.on("data", (d) => { stdout += d; });
      if (child.stderr) child.stderr.on("data", (d) => { stderr += d; });
      child.on("error", (error) => settle(null, null, error));
      child.on("close", (status, signal) => settle(status, signal));
    });
  }

  function runGatewayCommand(launcher, baseEnv, gwArgs, { timeoutMs = 90000 } = {}) {
    const idx = launcher.args.indexOf("dashboard");
    const prefix = idx >= 0 ? launcher.args.slice(0, idx) : [];
    const args = [...prefix, "gateway", ...gwArgs];
    return run(launcher.command, args, {
      cwd: launcher.cwd,
      env: envWithPath({ ...baseEnv, ...(launcher.extraEnv || {}) }),
      timeout: timeoutMs,
    });
  }

  function gatewayVersionMarkerPath() {
    return path.join(elevateHome, ".gateway_version");
  }

  function readGatewayVersionMarker() {
    try {
      return fs.readFileSync(gatewayVersionMarkerPath(), "utf8").trim();
    } catch {
      return "";
    }
  }

  function writeGatewayVersionMarker(version) {
    try {
      fs.mkdirSync(elevateHome, { recursive: true });
      fs.writeFileSync(gatewayVersionMarkerPath(), `${version}\n`, "utf8");
    } catch (e) {
      appendBackendLog(`[gateway] version marker write failed: ${e}\n`);
    }
  }

  function existingGatewayMissingResource() {
    try {
      const statusPath = path.join(elevateHome, "gateway_state.json");
      const payload = JSON.parse(fs.readFileSync(statusPath, "utf8"));
      const platforms = payload && typeof payload === "object" ? payload.platforms : null;
      if (!platforms || typeof platforms !== "object") return "";

      for (const [name, state] of Object.entries(platforms)) {
        if (!state || typeof state !== "object") continue;
        const code = String(state.error_code || "");
        if (!code.endsWith("_missing")) continue;
        const message = String(state.error_message || "");
        const marker = " missing at ";
        const idx = message.indexOf(marker);
        if (idx < 0) continue;
        const candidate = message.slice(idx + marker.length).trim().replace(/\.$/, "");
        if (candidate && fileExists(candidate)) {
          return `${name}:${code}:${candidate}`;
        }
      }
    } catch {
      // no status yet, malformed JSON, or unreadable file: not a recovery signal
    }
    return "";
  }

  async function kickstartGateway(uid) {
    const res = await run(
      "launchctl",
      ["kickstart", "-k", `gui/${uid}/${gatewayLabel}`],
      { timeout: 15000 },
    );
    const out = String(res.stdout || res.stderr || "").trim().slice(-300);
    appendBackendLog(`[gateway] kickstart rc=${res.status}\n${out}\n`);
    return res.status === 0;
  }

  async function probeGateway(uid) {
    const probe = await run(
      "launchctl",
      ["print", `gui/${uid}/${gatewayLabel}`],
      { timeout: 8000 },
    );
    const out = String(probe.stdout || "");
    const loaded = probe.status === 0;
    const running =
      loaded && (/\bpid = \d+/.test(out) || /state = running/.test(out));
    return { loaded, running };
  }

  async function bootstrapGatewayDirect(uid, plist) {
    const bs = await run(
      "launchctl",
      ["bootstrap", `gui/${uid}`, plist],
      { timeout: 15000 },
    );
    appendBackendLog(
      `[gateway] direct bootstrap rc=${bs.status} ${String(bs.stdout || bs.stderr || "").trim().slice(-200)}\n`,
    );
    if (!(await probeGateway(uid)).running) await kickstartGateway(uid);
    return (await probeGateway(uid)).running;
  }

  async function ensureGatewayInstalled(launcher, baseEnv) {
    if (process.platform !== "darwin") return;
    try {
      const plist = path.join(
        os.homedir(),
        "Library",
        "LaunchAgents",
        `${gatewayLabel}.plist`,
      );
      const uid = typeof process.getuid === "function" ? process.getuid() : "";
      const { loaded, running } = await probeGateway(uid);
      const appVersion = app.getVersion();
      if (fileExists(plist) && loaded && !running) {
        appendBackendLog(
          "[gateway] self-heal: loaded but NOT running -> kickstart\n",
        );
        if ((await kickstartGateway(uid)) && (await probeGateway(uid)).running) return;
      } else if (fileExists(plist) && loaded) {
        const lastVersion = readGatewayVersionMarker();
        if (lastVersion !== appVersion) {
          appendBackendLog(
            `[gateway] version change ${lastVersion || "(none)"} -> ${appVersion}; reinstalling to load new code + refresh plist env\n`,
          );
          const reinstall = await runGatewayCommand(launcher, baseEnv, ["install"]);
          const rout = String(reinstall.stdout || reinstall.stderr || "").trim().slice(-300);
          appendBackendLog(`[gateway] version-change reinstall rc=${reinstall.status}\n${rout}\n`);
          if (reinstall.status === 0) {
            if (await kickstartGateway(uid)) {
              writeGatewayVersionMarker(appVersion);
            }
          } else if (await kickstartGateway(uid)) {
            writeGatewayVersionMarker(appVersion);
          }
        } else {
          const missingResource = existingGatewayMissingResource();
          if (missingResource) {
            appendBackendLog(
              `[gateway] self-heal: packaged resource recovered (${missingResource}); reinstalling gateway\n`,
            );
            const reinstall = await runGatewayCommand(launcher, baseEnv, ["install"]);
            const rout = String(reinstall.stdout || reinstall.stderr || "").trim().slice(-300);
            appendBackendLog(`[gateway] recovered-resource reinstall rc=${reinstall.status}\n${rout}\n`);
            if (reinstall.status === 0) {
              if (await kickstartGateway(uid)) {
                writeGatewayVersionMarker(appVersion);
              }
            } else if (await kickstartGateway(uid)) {
              writeGatewayVersionMarker(appVersion);
            }
          } else {
            appendBackendLog(
              "[gateway] self-heal: healthy (plist present + loaded, version current)\n",
            );
          }
        }
        return;
      }
      appendBackendLog(
        `[gateway] self-heal: plist=${fileExists(plist)} loaded=${loaded} running=${running} -> installing\n`,
      );
      const res = await runGatewayCommand(launcher, baseEnv, ["install"]);
      const out = String(res.stdout || res.stderr || "").trim().slice(-400);
      appendBackendLog(`[gateway] self-heal install rc=${res.status}\n${out}\n`);
      if (res.status === 0) writeGatewayVersionMarker(appVersion);
      if (!(await probeGateway(uid)).running && fileExists(plist)) {
        appendBackendLog(
          "[gateway] self-heal: install did not yield a running job; direct launchctl bootstrap fallback\n",
        );
        const revived = await bootstrapGatewayDirect(uid, plist);
        appendBackendLog(
          `[gateway] self-heal: direct bootstrap ${revived ? "revived the gateway" : "FAILED — gateway still down"}\n`,
        );
      }
    } catch (e) {
      appendBackendLog(`[gateway] self-heal error: ${e}\n`);
    }
  }

  return {
    bootstrapGatewayDirect,
    ensureGatewayInstalled,
    existingGatewayMissingResource,
    gatewayVersionMarkerPath,
    kickstartGateway,
    probeGateway,
    readGatewayVersionMarker,
    runGatewayCommand,
    writeGatewayVersionMarker,
  };
}

module.exports = { createGatewaySelfHeal };
