"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const { BETA } = require("./release-profile");

const RECOVERY_RUNTIME_POLICY = Object.freeze({
  mode: "roll-forward-recovery",
  backend: false,
  gateway: false,
  tools: false,
  preservesProfile: true,
  preservesLaunchAgent: true,
  updaterChannel: "beta",
  gatewayLabel: BETA.gatewayLabel,
});

const MISSING_SERVICE_PATTERN = /could not find service|service not found|no such process/i;
const ACTOR_PATTERNS = Object.freeze([
  [
    "gateway",
    /(?:^|\s)(?:\S*python\S*\s+-m\s+)?elevate_cli\.main\s+gateway(?:\s|$)|(?:^|\s)\S*elevate\s+gateway(?:\s|$)|gateway[\\/]run\.py|gateway\.run/,
  ],
  [
    "backend",
    /(?:^|\s)(?:\S*python\S*\s+-m\s+)?elevate_cli\.main\s+dashboard(?:\s|$)|(?:^|\s)\S*elevate\s+dashboard(?:\s|$)/,
  ],
  [
    "backend-store",
    /site-packages[\\/]pgserver[\\/].*[\\/]postgres\s+-D\s+\S*[\\/]\.elevate-beta[\\/]pgdata(?:\s|$)/,
  ],
  [
    "pty",
    /(?:^|\s)\S*python\S*\s+-m\s+tui_gateway\.(?:entry|slash_worker)(?:\s|$)|(?:^|\s)\S*node\S*\s+\S*ui-tui[\\/]dist[\\/]entry\.js(?:\s|$)/,
  ],
  [
    "desktop",
    /Elevate Beta\.app[\\/]Contents[\\/](?:MacOS[\\/]Elevate Beta|Frameworks[\\/]Elevate Beta Helper)/,
  ],
]);

function runCommand(command, args, { spawn = spawnSync, timeout = 15_000 } = {}) {
  let result;
  try {
    result = spawn(command, args, {
      encoding: "utf8",
      timeout,
      maxBuffer: 8 * 1024 * 1024,
    });
  } catch (error) {
    return {
      command,
      args: [...args],
      status: null,
      signal: null,
      error: error?.message || String(error),
      output: "",
    };
  }
  return {
    command,
    args: [...args],
    status: Number.isInteger(result?.status) ? result.status : null,
    signal: result?.signal || null,
    error: result?.error?.message || "",
    output: `${result?.stdout || ""}\n${result?.stderr || ""}`.trim(),
  };
}

function runLaunchctl(args, options = {}) {
  return runCommand("/bin/launchctl", args, options);
}

function betaGatewayPlist(home = os.homedir()) {
  return path.join(home, "Library", "LaunchAgents", `${BETA.gatewayLabel}.plist`);
}

function classifyLaunchctlAbsence(result) {
  if (!result || result.error || result.status === null) {
    return {
      proven: false,
      reason: result?.error || "launchctl did not return a status",
    };
  }
  if (result.status === 0) {
    return { proven: false, reason: "service remains loaded" };
  }
  if (result.status === 113 || MISSING_SERVICE_PATTERN.test(result.output || "")) {
    return { proven: true, reason: "service is absent" };
  }
  return {
    proven: false,
    reason: `unrecognized launchctl result (rc=${result.status})`,
  };
}

function launchctlFailure(action, result) {
  const detail = result?.error || result?.output || `launchctl rc=${result?.status}`;
  return new Error(`Recovery could not ${action} the exact Beta gateway: ${detail}`);
}

async function quiesceLaunchdGateway({ service, spawn, sleep }) {
  const commands = [];
  const invoke = (args) => {
    const result = runLaunchctl(args, { spawn });
    commands.push(result);
    return result;
  };
  const inspect = () => {
    const result = invoke(["print", service]);
    const absence = classifyLaunchctlAbsence(result);
    if (result.error || result.status === null) {
      throw launchctlFailure("inspect", result);
    }
    if (!absence.proven && result.status !== 0) {
      throw launchctlFailure("prove absent", result);
    }
    return { result, absence };
  };

  // Do not use `launchctl disable`: that state survives the recovery app and
  // would strand the fixed Beta. Bootout is enough once exact absence is proven.
  invoke(["bootout", service]);
  let state = inspect();
  if (state.absence.proven) return { commands, inspect: state.result };

  for (const signal of ["SIGTERM", "SIGKILL"]) {
    invoke(["kill", signal, service]);
    await sleep(signal === "SIGTERM" ? 150 : 50);
    invoke(["bootout", service]);
    state = inspect();
    if (state.absence.proven) return { commands, inspect: state.result };
  }

  throw new Error(
    "Recovery could not prove the exact Beta gateway absent after bounded TERM/KILL retries.",
  );
}

function parsePidRecord(raw) {
  const text = String(raw || "").trim();
  if (!text) return null;
  let value;
  try {
    value = JSON.parse(text);
  } catch {
    if (!/^\d+$/.test(text)) return null;
    value = Number(text);
  }
  if (Number.isSafeInteger(value)) value = { pid: value };
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const pid = Number(value.pid);
  if (!Number.isSafeInteger(pid) || pid <= 1) return null;
  return { ...value, pid };
}

function readOptionalFile(filePath, fsImpl = fs) {
  try {
    return fsImpl.readFileSync(filePath, "utf8");
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw new Error(`Recovery could not read ${filePath}: ${error?.message || error}`);
  }
}

function readGatewayRecord(profileRoot, fsImpl = fs) {
  const pidPath = path.join(profileRoot, "gateway.pid");
  const raw = readOptionalFile(pidPath, fsImpl);
  if (raw === null || !String(raw).trim()) return { path: pidPath, record: null };
  const record = parsePidRecord(raw);
  if (!record) {
    throw new Error("Recovery found an invalid exact-Beta gateway.pid and cannot prove its owner.");
  }
  return { path: pidPath, record };
}

function readProcessRegistry(profileRoot, fsImpl = fs) {
  const registryPath = path.join(profileRoot, "processes.json");
  const raw = readOptionalFile(registryPath, fsImpl);
  if (raw === null || !String(raw).trim()) return { path: registryPath, entries: [] };
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    throw new Error("Recovery found an invalid exact-Beta processes.json registry.");
  }
  if (!Array.isArray(payload)) {
    throw new Error("Recovery found a malformed exact-Beta processes.json registry.");
  }
  const entries = payload.map((entry, index) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error(`Recovery found a malformed process registry entry at index ${index}.`);
    }
    const pid = Number(entry.pid);
    if (!Number.isSafeInteger(pid) || pid <= 1) {
      throw new Error(`Recovery found an invalid process PID at registry index ${index}.`);
    }
    return { ...entry, pid };
  });
  return { path: registryPath, entries };
}

function parseProcessRows(output) {
  const rows = [];
  for (const line of String(output || "").split(/\r?\n/)) {
    if (!line.trim()) continue;
    const match = line.match(/^\s*(\d+)\s+(\d+)\s+(.*)$/);
    if (!match) {
      throw new Error("Recovery could not parse the macOS process inventory.");
    }
    const pid = Number(match[1]);
    const ppid = Number(match[2]);
    if (!Number.isSafeInteger(pid) || pid <= 0 || !Number.isSafeInteger(ppid) || ppid < 0) {
      throw new Error("Recovery received an invalid macOS process inventory.");
    }
    rows.push({ pid, ppid, command: match[3] || "" });
  }
  return rows;
}

function listProcesses({ spawn = spawnSync } = {}) {
  const result = runCommand(
    "/bin/ps",
    ["eww", "-axo", "pid=,ppid=,command="],
    { spawn, timeout: 10_000 },
  );
  if (result.error || result.status !== 0) {
    throw new Error(
      `Recovery could not inventory exact-Beta processes: ${result.error || result.output || `ps rc=${result.status}`}`,
    );
  }
  return parseProcessRows(result.output);
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function hasExactBetaHome(command, betaHome) {
  const value = escapeRegExp(path.resolve(betaHome));
  return new RegExp(
    `(?:^|\\s)ELEVATE_HOME=(?:["']${value}["']|${value})(?=\\s|$)`,
  ).test(String(command || ""));
}

function classifyKnownActor(command) {
  const text = String(command || "");
  for (const [kind, pattern] of ACTOR_PATTERNS) {
    if (pattern.test(text)) return kind;
  }
  return null;
}

function hasExactBetaDesktopIdentity(command) {
  const text = String(command || "");
  return classifyKnownActor(text) === "desktop" && (
    /(?:^|\s)__CFBundleIdentifier=com\.elevationrealestate\.elevate\.beta(?:\s|$)/.test(text)
    || /Elevate Beta\.app[\\/]Contents[\\/]/.test(text)
  );
}

function normalizedCommand(value) {
  return String(value || "").trim().replace(/\s+/g, " ");
}

function registryCommandMatches(entry, processCommand) {
  const expected = normalizedCommand(entry?.command);
  if (!expected) return false;
  return normalizedCommand(processCommand).includes(expected);
}

function buildActorInventory({
  rows,
  betaHome,
  currentPid,
  gatewayRecord,
  registryEntries,
}) {
  const byPid = new Map(rows.map((row) => [row.pid, row]));
  const registryByPid = new Map(
    registryEntries
      .filter((entry) => String(entry.pid_scope || "host") === "host")
      .map((entry) => [entry.pid, entry]),
  );
  const actors = new Map();

  if (gatewayRecord && byPid.has(gatewayRecord.pid)) {
    const row = byPid.get(gatewayRecord.pid);
    if (!hasExactBetaHome(row.command, betaHome) || classifyKnownActor(row.command) !== "gateway") {
      throw new Error(
        `Recovery refused to signal gateway.pid ${gatewayRecord.pid}: exact Beta gateway identity was not proven.`,
      );
    }
    actors.set(row.pid, { ...row, kind: "gateway", source: "gateway.pid" });
  }

  for (const [pid, entry] of registryByPid) {
    const row = byPid.get(pid);
    if (!row) continue;
    if (!hasExactBetaHome(row.command, betaHome) || !registryCommandMatches(entry, row.command)) {
      throw new Error(
        `Recovery refused to signal registered PID ${pid}: exact Beta process identity was not proven.`,
      );
    }
    actors.set(pid, { ...row, kind: classifyKnownActor(row.command) || "managed-tool", source: "processes.json" });
  }

  for (const row of rows) {
    if (row.pid === currentPid) continue;
    const kind = classifyKnownActor(row.command);
    if (
      kind
      && (hasExactBetaHome(row.command, betaHome) || hasExactBetaDesktopIdentity(row.command))
      && !actors.has(row.pid)
    ) {
      actors.set(row.pid, { ...row, kind, source: "process-scan" });
    }
  }

  // A registered or known Beta actor can own helper descendants whose command
  // is intentionally generic (shells and tool subprocesses). Include only
  // descendants that still carry the exact Beta profile environment.
  let changed = true;
  while (changed) {
    changed = false;
    for (const row of rows) {
      if (
        row.pid !== currentPid
        && !actors.has(row.pid)
        && actors.has(row.ppid)
        && hasExactBetaHome(row.command, betaHome)
      ) {
        actors.set(row.pid, { ...row, kind: "actor-child", source: `parent:${row.ppid}` });
        changed = true;
      }
    }
  }

  const ambiguous = rows.filter((row) => (
    row.pid !== currentPid
    && hasExactBetaHome(row.command, betaHome)
    && !actors.has(row.pid)
  ));
  if (ambiguous.length) {
    throw new Error(
      `Recovery found ${ambiguous.length} exact-Beta process(es) whose runtime ownership could not be proven.`,
    );
  }

  return [...actors.values()];
}

function sameProcessIdentity(actor, row, betaHome) {
  return Boolean(
    row
    && row.pid === actor.pid
    && row.ppid === actor.ppid
    && row.command === actor.command
    && (
      hasExactBetaHome(row.command, betaHome)
      || (actor.kind === "desktop" && hasExactBetaDesktopIdentity(row.command))
    ),
  );
}

async function waitForActorExit(actor, {
  betaHome,
  scan,
  sleep,
  timeoutMs,
  pollIntervalMs,
}) {
  const attempts = Math.max(1, Math.ceil(timeoutMs / pollIntervalMs));
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const row = scan().find((candidate) => candidate.pid === actor.pid);
    if (!row) return true;
    if (!sameProcessIdentity(actor, row, betaHome)) {
      throw new Error(`Recovery lost exact identity proof while waiting for PID ${actor.pid}.`);
    }
    await sleep(pollIntervalMs);
  }
  return false;
}

async function terminateActor(actor, {
  betaHome,
  scan,
  signalProcess,
  sleep,
  termWaitMs,
  killWaitMs,
  pollIntervalMs,
}) {
  const initial = scan().find((row) => row.pid === actor.pid);
  if (!initial) return { ...actor, signal: "already-exited" };
  if (!sameProcessIdentity(actor, initial, betaHome)) {
    throw new Error(`Recovery refused to signal PID ${actor.pid}: its identity changed.`);
  }

  try {
    signalProcess(actor.pid, "SIGTERM");
  } catch (error) {
    if (error?.code === "ESRCH") return { ...actor, signal: "already-exited" };
    throw new Error(`Recovery could not TERM exact-Beta PID ${actor.pid}: ${error?.message || error}`);
  }
  if (await waitForActorExit(actor, {
    betaHome, scan, sleep, timeoutMs: termWaitMs, pollIntervalMs,
  })) {
    return { ...actor, signal: "SIGTERM" };
  }

  const beforeKill = scan().find((row) => row.pid === actor.pid);
  if (!sameProcessIdentity(actor, beforeKill, betaHome)) {
    throw new Error(`Recovery refused to KILL PID ${actor.pid}: its identity changed.`);
  }
  try {
    signalProcess(actor.pid, "SIGKILL");
  } catch (error) {
    if (error?.code === "ESRCH") return { ...actor, signal: "SIGTERM" };
    throw new Error(`Recovery could not KILL exact-Beta PID ${actor.pid}: ${error?.message || error}`);
  }
  if (!(await waitForActorExit(actor, {
    betaHome, scan, sleep, timeoutMs: killWaitMs, pollIntervalMs,
  }))) {
    throw new Error(`Recovery could not prove exact-Beta PID ${actor.pid} exited after SIGKILL.`);
  }
  return { ...actor, signal: "SIGKILL" };
}

async function quiesceBetaGateway({
  uid = typeof process.getuid === "function" ? process.getuid() : null,
  home = os.homedir(),
  spawn = spawnSync,
  fsImpl = fs,
  signalProcess = (pid, signal) => process.kill(pid, signal),
  sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
  currentPid = process.pid,
  termWaitMs = 1_500,
  killWaitMs = 1_000,
  pollIntervalMs = 50,
} = {}) {
  if (!Number.isSafeInteger(uid) || uid < 0) {
    throw new Error("Recovery could not determine the current macOS user ID.");
  }
  if (!Number.isSafeInteger(currentPid) || currentPid <= 1) {
    throw new Error("Recovery could not determine its own process identity.");
  }
  const profileRoot = path.resolve(home, BETA.elevateHomeName);
  const domain = `gui/${uid}`;
  const service = `${domain}/${BETA.gatewayLabel}`;
  const launchd = await quiesceLaunchdGateway({ service, spawn, sleep });
  const { path: gatewayPidPath, record: gatewayRecord } = readGatewayRecord(profileRoot, fsImpl);
  const { path: registryPath, entries: registryEntries } = readProcessRegistry(profileRoot, fsImpl);
  const scan = () => listProcesses({ spawn });
  const killed = [];

  // A bounded number of passes catches children that outlive a parent and an
  // actor that was in the middle of starting when the first snapshot ran.
  for (let pass = 0; pass < 4; pass += 1) {
    const actors = buildActorInventory({
      rows: scan(),
      betaHome: profileRoot,
      currentPid,
      gatewayRecord,
      registryEntries,
    });
    if (!actors.length) break;

    // Children first keeps their identity/parent relationship available while
    // each signal is verified. A later pass catches any reparented survivors.
    const depth = (actor) => {
      let value = 0;
      let cursor = actor;
      const seen = new Set();
      while (cursor && !seen.has(cursor.pid)) {
        seen.add(cursor.pid);
        cursor = actors.find((candidate) => candidate.pid === cursor.ppid);
        if (cursor) value += 1;
      }
      return value;
    };
    actors.sort((left, right) => depth(right) - depth(left));
    for (const actor of actors) {
      killed.push(await terminateActor(actor, {
        betaHome: profileRoot,
        scan,
        signalProcess,
        sleep,
        termWaitMs,
        killWaitMs,
        pollIntervalMs,
      }));
    }
  }

  const remaining = buildActorInventory({
    rows: scan(),
    betaHome: profileRoot,
    currentPid,
    gatewayRecord,
    registryEntries,
  });
  if (remaining.length) {
    throw new Error(`Recovery could not contain ${remaining.length} exact-Beta runtime process(es).`);
  }

  const finalInspect = runLaunchctl(["print", service], { spawn });
  const finalAbsence = classifyLaunchctlAbsence(finalInspect);
  if (!finalAbsence.proven) throw launchctlFailure("re-prove absent", finalInspect);

  return {
    ok: true,
    gatewayLabel: BETA.gatewayLabel,
    service,
    plist: betaGatewayPlist(home),
    plistPreserved: true,
    profileRoot,
    profilePreserved: true,
    gatewayPidPath,
    registryPath,
    killed,
    commands: [...launchd.commands, finalInspect],
  };
}

module.exports = {
  RECOVERY_RUNTIME_POLICY,
  betaGatewayPlist,
  buildActorInventory,
  classifyKnownActor,
  classifyLaunchctlAbsence,
  hasExactBetaHome,
  hasExactBetaDesktopIdentity,
  listProcesses,
  parsePidRecord,
  parseProcessRows,
  quiesceBetaGateway,
  readGatewayRecord,
  readProcessRegistry,
  registryCommandMatches,
  runLaunchctl,
  terminateActor,
};
