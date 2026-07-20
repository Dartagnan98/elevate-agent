"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  buildActorInventory,
  classifyKnownActor,
  classifyLaunchctlAbsence,
  hasExactBetaDesktopIdentity,
  hasExactBetaHome,
  parsePidRecord,
  parseProcessRows,
  quiesceBetaGateway,
  readProcessRegistry,
  terminateActor,
} = require("../src/recovery-containment");

const betaHome = "/Users/tester/.elevate-beta";
const betaEnv = `ELEVATE_HOME=${betaHome}`;

function missingFileFs() {
  return {
    readFileSync(filePath) {
      const error = new Error(`missing ${filePath}`);
      error.code = "ENOENT";
      throw error;
    },
  };
}

function launchctlAndPs({ launchctl, ps }) {
  const calls = [];
  const spawn = (command, args) => {
    calls.push({ command, args: [...args] });
    const value = command === "/bin/launchctl" ? launchctl(args) : ps(args);
    return {
      status: value.status,
      stdout: value.stdout || "",
      stderr: value.stderr || "",
      error: value.error,
      signal: value.signal || null,
    };
  };
  return { calls, spawn };
}

test("launchctl absence accepts only exact missing-service evidence", () => {
  assert.equal(classifyLaunchctlAbsence({ status: 113, output: "" }).proven, true);
  assert.equal(classifyLaunchctlAbsence({ status: 3, output: "Could not find service" }).proven, true);
  assert.equal(classifyLaunchctlAbsence({ status: 0, output: "state = waiting" }).proven, false);
  assert.equal(classifyLaunchctlAbsence({ status: 5, output: "input/output error" }).proven, false);
  assert.equal(classifyLaunchctlAbsence({ status: null, error: "timeout" }).proven, false);
  assert.equal(
    classifyLaunchctlAbsence({ status: 113, error: "spawn failed", output: "Could not find service" }).proven,
    false,
  );
});

test("PID and process inventory parsing are strict", () => {
  assert.deepEqual(parsePidRecord("42"), { pid: 42 });
  assert.deepEqual(parsePidRecord("{\"pid\":43,\"kind\":\"elevate-gateway\"}"), {
    pid: 43,
    kind: "elevate-gateway",
  });
  assert.equal(parsePidRecord("not-a-pid"), null);
  assert.equal(parsePidRecord("1"), null);
  assert.deepEqual(parseProcessRows(" 42  1 python -m elevate_cli.main gateway\n"), [
    { pid: 42, ppid: 1, command: "python -m elevate_cli.main gateway" },
  ]);
  assert.throws(() => parseProcessRows("unparseable"), /could not parse/);
});

test("exact Beta actor classification is profile-bound and covers runtime surfaces", () => {
  const rows = [
    { pid: 10, ppid: 1, command: `python -m elevate_cli.main gateway run --replace ${betaEnv}` },
    { pid: 11, ppid: 1, command: `python -m elevate_cli.main dashboard --tui ${betaEnv}` },
    { pid: 12, ppid: 11, command: `python -m tui_gateway.entry ${betaEnv}` },
    { pid: 13, ppid: 11, command: `node /app/cli/ui-tui/dist/entry.js ${betaEnv}` },
    {
      pid: 14,
      ppid: 1,
      command: "/Applications/Elevate Beta.app/Contents/MacOS/Elevate Beta __CFBundleIdentifier=com.elevationrealestate.elevate.beta",
    },
    {
      pid: 15,
      ppid: 1,
      command: `python/site-packages/pgserver/pginstall/bin/postgres -D ${betaHome}/pgdata ${betaEnv}`,
    },
    { pid: 16, ppid: 11, command: `/bin/zsh -lc pytest ${betaEnv}` },
    { pid: 17, ppid: 1, command: "python -m elevate_cli.main gateway ELEVATE_HOME=/Users/tester/.elevate" },
  ];
  const actors = buildActorInventory({
    rows,
    betaHome,
    currentPid: 999,
    gatewayRecord: { pid: 10 },
    registryEntries: [],
  });

  assert.deepEqual(new Map(actors.map((actor) => [actor.pid, actor.kind])), new Map([
    [10, "gateway"],
    [11, "backend"],
    [12, "pty"],
    [13, "pty"],
    [14, "desktop"],
    [15, "backend-store"],
    [16, "actor-child"],
  ]));
  assert.equal(hasExactBetaHome(`${betaEnv}-other`, betaHome), false);
  assert.equal(hasExactBetaDesktopIdentity(rows[4].command), true);
  assert.equal(classifyKnownActor(rows[7].command), "gateway");
});

test("registered tools require exact profile and command identity", () => {
  const row = { pid: 70, ppid: 1, command: `/bin/zsh -lc "npm test" ${betaEnv}` };
  const actors = buildActorInventory({
    rows: [row],
    betaHome,
    currentPid: 999,
    gatewayRecord: null,
    registryEntries: [{ pid: 70, pid_scope: "host", command: "npm test" }],
  });
  assert.equal(actors[0].kind, "managed-tool");
  assert.equal(actors[0].source, "processes.json");

  assert.throws(() => buildActorInventory({
    rows: [{ ...row, command: `/bin/zsh -lc "sleep 10" ${betaEnv}` }],
    betaHome,
    currentPid: 999,
    gatewayRecord: null,
    registryEntries: [{ pid: 70, pid_scope: "host", command: "npm test" }],
  }), /identity was not proven/);
});

test("unowned exact-Beta processes fail closed instead of being guessed", () => {
  assert.throws(() => buildActorInventory({
    rows: [{ pid: 88, ppid: 1, command: `/usr/bin/sleep 100 ${betaEnv}` }],
    betaHome,
    currentPid: 999,
    gatewayRecord: null,
    registryEntries: [],
  }), /ownership could not be proven/);
});

test("malformed process registry fails closed", () => {
  assert.throws(() => readProcessRegistry(betaHome, {
    readFileSync: () => "{bad-json",
  }), /invalid exact-Beta processes\.json/);
  assert.throws(() => readProcessRegistry(betaHome, {
    readFileSync: () => JSON.stringify([{ pid: 0 }]),
  }), /invalid process PID/);
});

test("actor termination uses bounded TERM then KILL and re-proves identity", async () => {
  const actor = {
    pid: 101,
    ppid: 1,
    command: `python -m tui_gateway.entry ${betaEnv}`,
    kind: "pty",
  };
  let alive = true;
  const signals = [];
  const scan = () => alive ? [{ pid: actor.pid, ppid: actor.ppid, command: actor.command }] : [];
  const result = await terminateActor(actor, {
    betaHome,
    scan,
    signalProcess: (_pid, signal) => {
      signals.push(signal);
      if (signal === "SIGKILL") alive = false;
    },
    sleep: async () => {},
    termWaitMs: 2,
    killWaitMs: 2,
    pollIntervalMs: 1,
  });

  assert.deepEqual(signals, ["SIGTERM", "SIGKILL"]);
  assert.equal(result.signal, "SIGKILL");
});

test("actor termination refuses a changed PID identity before SIGKILL", async () => {
  const actor = {
    pid: 102,
    ppid: 1,
    command: `python -m tui_gateway.entry ${betaEnv}`,
    kind: "pty",
  };
  let scans = 0;
  const scan = () => {
    scans += 1;
    return [{
      pid: actor.pid,
      ppid: actor.ppid,
      command: scans < 3 ? actor.command : `/usr/bin/sleep 1 ${betaEnv}`,
    }];
  };
  await assert.rejects(terminateActor(actor, {
    betaHome,
    scan,
    signalProcess: () => {},
    sleep: async () => {},
    termWaitMs: 2,
    killWaitMs: 2,
    pollIntervalMs: 1,
  }), /lost exact identity proof|identity changed/);
});

test("recovery quiesces a gateway.pid orphan and preserves every profile byte", async (t) => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-recovery-"));
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  const profileRoot = path.join(home, ".elevate-beta");
  const plist = path.join(home, "Library", "LaunchAgents", "ai.elevate.gateway-beta.plist");
  fs.mkdirSync(profileRoot, { recursive: true });
  fs.mkdirSync(path.dirname(plist), { recursive: true });
  const gatewayBytes = JSON.stringify({
    pid: 444,
    kind: "elevate-gateway",
    argv: ["python", "-m", "elevate_cli.main", "gateway", "run"],
  });
  fs.writeFileSync(path.join(profileRoot, "gateway.pid"), gatewayBytes);
  fs.writeFileSync(path.join(profileRoot, "processes.json"), "[]");
  fs.writeFileSync(path.join(profileRoot, "realtor-data.json"), "do-not-change");
  fs.writeFileSync(plist, "keep-launch-agent-definition");

  let alive = true;
  const signals = [];
  const command = `python -m elevate_cli.main gateway run --replace ELEVATE_HOME=${profileRoot}`;
  const { calls, spawn } = launchctlAndPs({
    launchctl: (args) => args[0] === "print"
      ? { status: 113, stderr: "Could not find service" }
      : { status: 0 },
    ps: () => ({ status: 0, stdout: alive ? `444 1 ${command}\n` : "" }),
  });

  const result = await quiesceBetaGateway({
    uid: 501,
    home,
    spawn,
    fsImpl: fs,
    currentPid: 999,
    signalProcess: (pid, signal) => {
      signals.push([pid, signal]);
      alive = false;
    },
    sleep: async () => {},
    termWaitMs: 1,
    killWaitMs: 1,
    pollIntervalMs: 1,
  });

  assert.equal(result.ok, true);
  assert.equal(result.profilePreserved, true);
  assert.equal(result.plistPreserved, true);
  assert.deepEqual(signals, [[444, "SIGTERM"]]);
  assert.equal(result.killed[0].source, "gateway.pid");
  assert.equal(fs.readFileSync(path.join(profileRoot, "gateway.pid"), "utf8"), gatewayBytes);
  assert.equal(fs.readFileSync(path.join(profileRoot, "processes.json"), "utf8"), "[]");
  assert.equal(fs.readFileSync(path.join(profileRoot, "realtor-data.json"), "utf8"), "do-not-change");
  assert.equal(fs.readFileSync(plist, "utf8"), "keep-launch-agent-definition");
  assert.equal(calls.some(({ args }) => args.includes("disable")), false);
  assert.equal(calls.some(({ args }) => args.includes("bootstrap")), false);
  assert.equal(calls.some(({ args }) => args.includes("kickstart")), false);
});

test("loaded launchd service gets bounded TERM/KILL retries without persistent disable", async () => {
  let prints = 0;
  const { calls, spawn } = launchctlAndPs({
    launchctl: (args) => {
      if (args[0] !== "print") return { status: 0 };
      prints += 1;
      return prints < 3
        ? { status: 0, stdout: "state = running\npid = 777" }
        : { status: 113, stderr: "Could not find service" };
    },
    ps: () => ({ status: 0, stdout: "" }),
  });

  await quiesceBetaGateway({
    uid: 501,
    home: "/Users/tester",
    spawn,
    fsImpl: missingFileFs(),
    currentPid: 999,
    sleep: async () => {},
  });

  assert.deepEqual(calls.filter(({ command }) => command === "/bin/launchctl").map(({ args }) => args[0]), [
    "bootout", "print", "kill", "bootout", "print", "kill", "bootout", "print", "print",
  ]);
  assert.deepEqual(calls.filter(({ args }) => args[0] === "kill").map(({ args }) => args[1]), [
    "SIGTERM", "SIGKILL",
  ]);
  assert.equal(calls.some(({ args }) => args[0] === "disable"), false);
});

test("unknown launchctl failures veto recovery and no updater-like action follows", async () => {
  const { calls, spawn } = launchctlAndPs({
    launchctl: (args) => args[0] === "print"
      ? { status: 5, stderr: "operation failed" }
      : { status: 0 },
    ps: () => ({ status: 0, stdout: "" }),
  });
  await assert.rejects(quiesceBetaGateway({
    uid: 501,
    home: "/Users/tester",
    spawn,
    fsImpl: missingFileFs(),
    currentPid: 999,
    sleep: async () => {},
  }), /prove absent|bounded TERM\/KILL/);
  assert.equal(calls.some(({ command }) => command === "/bin/ps"), false);
  assert.equal(calls.some(({ args }) => args[0] === "kill"), false);
});

test("recovery main and UI gate updater behavior on immutable containment state", () => {
  const root = path.resolve(__dirname, "..");
  const main = fs.readFileSync(path.join(root, "src", "recovery-main.js"), "utf8");
  const preload = fs.readFileSync(path.join(root, "src", "recovery-preload.js"), "utf8");
  const html = fs.readFileSync(path.join(root, "src", "recovery.html"), "utf8");
  const initialMarkup = html.slice(0, html.indexOf("<script>"));

  assert.match(main, /await quiesceBetaGateway\(\{ home \}\)/);
  assert.match(main, /if \(containmentState\.ok\) updater\.kickoffUpdates\(\)/);
  assert.match(main, /if \(containmentState\.ok\) \{\s*updater\.registerAutoUpdaterEvents\(\);\s*updater\.registerIpcHandlers\(\);/s);
  assert.match(main, /setWindowOpenHandler\(\(\) => \(\{ action: "deny" \}\)\)/);
  assert.match(main, /webContents\.on\("will-navigate"/);
  assert.match(main, /webContents\.on\("will-redirect"/);
  assert.doesNotMatch(main, /backend-runner|gateway-self-heal|terminal_tool|ensureBackend/);
  assert.match(preload, /ipcRenderer\.invoke\("recovery:containment"\)/);
  assert.doesNotMatch(initialMarkup, /safely contained/i);
  assert.match(initialMarkup, /updater will remain off until Elevate proves/i);
  assert.match(html, /if \(!containmentOk\) return/);
  assert.match(html, /Containment could not be proven/);
  assert.match(html, /updater was not started/);
  assert.match(html, /state\.ok !== true/);
});
