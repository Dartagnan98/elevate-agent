function createGatewaySelfHeal({
  app,
  appendBackendLog,
  envWithPath,
  fileExists,
  fs,
  os,
  path,
  process,
  spawnSync,
}) {
  function runGatewayCommand(launcher, baseEnv, gwArgs, { timeoutMs = 90000 } = {}) {
    const idx = launcher.args.indexOf("dashboard");
    const prefix = idx >= 0 ? launcher.args.slice(0, idx) : [];
    const args = [...prefix, "gateway", ...gwArgs];
    return spawnSync(launcher.command, args, {
      cwd: launcher.cwd,
      env: envWithPath({ ...baseEnv, ...(launcher.extraEnv || {}) }),
      timeout: timeoutMs,
      encoding: "utf8",
    });
  }

  function gatewayVersionMarkerPath() {
    return path.join(os.homedir(), ".elevate", ".gateway_version");
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
      fs.mkdirSync(path.join(os.homedir(), ".elevate"), { recursive: true });
      fs.writeFileSync(gatewayVersionMarkerPath(), `${version}\n`, "utf8");
    } catch (e) {
      appendBackendLog(`[gateway] version marker write failed: ${e}\n`);
    }
  }

  function existingGatewayMissingResource() {
    try {
      const statusPath = path.join(os.homedir(), ".elevate", "gateway_state.json");
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

  function kickstartGateway(uid) {
    const res = spawnSync(
      "launchctl",
      ["kickstart", "-k", `gui/${uid}/ai.elevate.gateway`],
      { encoding: "utf8", timeout: 15000 },
    );
    const out = String(res.stdout || res.stderr || "").trim().slice(-300);
    appendBackendLog(`[gateway] kickstart rc=${res.status}\n${out}\n`);
    return res.status === 0;
  }

  function probeGateway(uid) {
    try {
      const probe = spawnSync(
        "launchctl",
        ["print", `gui/${uid}/ai.elevate.gateway`],
        { encoding: "utf8", timeout: 8000 },
      );
      const out = String(probe.stdout || "");
      const loaded = probe.status === 0;
      const running =
        loaded && (/\bpid = \d+/.test(out) || /state = running/.test(out));
      return { loaded, running };
    } catch {
      return { loaded: false, running: false };
    }
  }

  function bootstrapGatewayDirect(uid, plist) {
    const bs = spawnSync(
      "launchctl",
      ["bootstrap", `gui/${uid}`, plist],
      { encoding: "utf8", timeout: 15000 },
    );
    appendBackendLog(
      `[gateway] direct bootstrap rc=${bs.status} ${String(bs.stdout || bs.stderr || "").trim().slice(-200)}\n`,
    );
    if (!probeGateway(uid).running) kickstartGateway(uid);
    return probeGateway(uid).running;
  }

  function ensureGatewayInstalled(launcher, baseEnv) {
    if (process.platform !== "darwin") return;
    try {
      const plist = path.join(
        os.homedir(),
        "Library",
        "LaunchAgents",
        "ai.elevate.gateway.plist",
      );
      const uid = typeof process.getuid === "function" ? process.getuid() : "";
      const { loaded, running } = probeGateway(uid);
      const appVersion = app.getVersion();
      if (fileExists(plist) && loaded && !running) {
        appendBackendLog(
          "[gateway] self-heal: loaded but NOT running -> kickstart\n",
        );
        if (kickstartGateway(uid) && probeGateway(uid).running) return;
      } else if (fileExists(plist) && loaded) {
        const lastVersion = readGatewayVersionMarker();
        if (lastVersion !== appVersion) {
          appendBackendLog(
            `[gateway] version change ${lastVersion || "(none)"} -> ${appVersion}; reinstalling to load new code + refresh plist env\n`,
          );
          const reinstall = runGatewayCommand(launcher, baseEnv, ["install"]);
          const rout = String(reinstall.stdout || reinstall.stderr || "").trim().slice(-300);
          appendBackendLog(`[gateway] version-change reinstall rc=${reinstall.status}\n${rout}\n`);
          if (reinstall.status === 0) {
            if (kickstartGateway(uid)) {
              writeGatewayVersionMarker(appVersion);
            }
          } else if (kickstartGateway(uid)) {
            writeGatewayVersionMarker(appVersion);
          }
        } else {
          const missingResource = existingGatewayMissingResource();
          if (missingResource) {
            appendBackendLog(
              `[gateway] self-heal: packaged resource recovered (${missingResource}); reinstalling gateway\n`,
            );
            const reinstall = runGatewayCommand(launcher, baseEnv, ["install"]);
            const rout = String(reinstall.stdout || reinstall.stderr || "").trim().slice(-300);
            appendBackendLog(`[gateway] recovered-resource reinstall rc=${reinstall.status}\n${rout}\n`);
            if (reinstall.status === 0) {
              if (kickstartGateway(uid)) {
                writeGatewayVersionMarker(appVersion);
              }
            } else if (kickstartGateway(uid)) {
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
      const res = runGatewayCommand(launcher, baseEnv, ["install"]);
      const out = String(res.stdout || res.stderr || "").trim().slice(-400);
      appendBackendLog(`[gateway] self-heal install rc=${res.status}\n${out}\n`);
      if (res.status === 0) writeGatewayVersionMarker(appVersion);
      if (!probeGateway(uid).running && fileExists(plist)) {
        appendBackendLog(
          "[gateway] self-heal: install did not yield a running job; direct launchctl bootstrap fallback\n",
        );
        const revived = bootstrapGatewayDirect(uid, plist);
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
