const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const path = require("node:path");
const test = require("node:test");

const { createBackendRunner } = require("../src/backend-runner");

function makeRunner(overrides = {}) {
  const marks = [];
  const timers = [];
  const state = { backendProcess: null, ownsBackend: false };
  const launcher = overrides.launcher || {
    command: "/bin/elevate",
    args: ["dashboard"],
    cwd: "/tmp",
    extraEnv: { EXTRA: "1" },
  };
  const runner = createBackendRunner({
    backendMatchesDesktopMode: async () => Boolean(overrides.alreadyReady),
    backendProbeSummary: async () => "port=9119 status=false",
    chooseBackendPort: async () => {
      marks.push(["choose"]);
    },
    embeddedChat: overrides.embeddedChat !== false,
    ensureGatewayInstalled: overrides.ensureGatewayInstalled || (() => {}),
    envWithPath: (extra = {}) => ({ PATH: "/bin", ...extra }),
    getBackendPort: () => 9119,
    markStartup: (name, detail = "") => {
      marks.push([name, detail]);
    },
    path,
    resolveElevateLauncher: () => overrides.launcher === null ? null : launcher,
    runtimeMetadata: overrides.runtimeMetadata || {
      appVersion: "1.2.68",
      architecture: "arm64",
      appBundleName: "Elevate Beta.app",
      releaseChannel: "beta",
      sourceReceiptId: "a".repeat(64),
    },
    setBackendProcess: (proc) => {
      state.backendProcess = proc;
    },
    setOwnsBackend: (value) => {
      state.ownsBackend = value;
    },
    setTimeout(callback, delay) {
      timers.push([callback, delay]);
      return timers.length;
    },
    spawn: overrides.spawn || ((command, args, options) => {
      state.spawnCall = { args, command, options };
      const proc = new EventEmitter();
      proc.stdout = new EventEmitter();
      proc.stderr = new EventEmitter();
      return proc;
    }),
    waitForBackend: async () => overrides.readyAfterSpawn !== false,
  });
  return { launcher, marks, runner, state, timers };
}

test("backend runner schedules gateway self-heal for already-compatible backend", async () => {
  let healed = false;
  const { runner, timers } = makeRunner({
    alreadyReady: true,
    ensureGatewayInstalled: () => {
      healed = true;
    },
    runtimeMetadata: { releaseChannel: "stable" },
  });

  assert.equal(await runner.ensureBackend(), true);
  assert.equal(timers.length, 1);
  assert.equal(timers[0][1], 8000);

  timers[0][0]();
  assert.equal(healed, true);
});

test("Beta awaits stale gateway cleanup even when the CLI launcher is missing", async () => {
  let cleanupArgs = null;
  const { runner, timers } = makeRunner({
    alreadyReady: true,
    launcher: null,
    ensureGatewayInstalled: (...args) => {
      cleanupArgs = args;
    },
    runtimeMetadata: { releaseChannel: "beta" },
  });

  assert.equal(await runner.ensureBackend(), true);
  assert.equal(timers.length, 0);
  assert.equal(cleanupArgs[0], null);
  assert.equal(cleanupArgs[1].ELEVATE_RELEASE_CHANNEL, "beta");
});

test("Stable still skips gateway self-heal when the CLI launcher is missing", async () => {
  let healed = false;
  const { runner, timers } = makeRunner({
    alreadyReady: true,
    launcher: null,
    ensureGatewayInstalled: () => {
      healed = true;
    },
    runtimeMetadata: { releaseChannel: "stable" },
  });

  assert.equal(await runner.ensureBackend(), true);
  assert.equal(timers.length, 0);
  assert.equal(healed, false);
});

test("backend runner spawns dashboard and clears owned process on exit", async () => {
  const { launcher, marks, runner, state, timers } = makeRunner();

  assert.equal(await runner.ensureBackend(), true);
  assert.equal(state.ownsBackend, true);
  assert.equal(state.spawnCall.command, "/bin/elevate");
  assert.deepEqual(state.spawnCall.options.env, {
    ELEVATE_APP_ARCHITECTURE: "arm64",
    ELEVATE_APP_BUNDLE_NAME: "Elevate Beta.app",
    ELEVATE_APP_VERSION: "1.2.68",
    ELEVATE_DASHBOARD_TUI: "1",
    ELEVATE_DASHBOARD_PORT: "9119",
    ELEVATE_DESKTOP_APP: "1",
    ELEVATE_RELEASE_CHANNEL: "beta",
    ELEVATE_SMS_VIA_APP: "1",
    ELEVATE_SOURCE_RECEIPT_ID: "a".repeat(64),
    EXTRA: "1",
    PATH: "/bin",
  });
  assert.equal(timers.length, 0);
  assert.ok(marks.some(([name, detail]) => name === "backend:port-selected" && detail === "9119"));
  assert.ok(marks.some(([name, detail]) => name === "backend:spawn" && detail === "elevate"));

  state.backendProcess.emit("exit", 0, null);
  assert.equal(state.backendProcess, null);
  assert.equal(state.ownsBackend, false);
  assert.deepEqual(launcher.args, ["dashboard"]);
});

test("Beta cleanup completes before port selection, compatibility checks, or spawn", async () => {
  let releaseCleanup;
  const cleanup = new Promise((resolve) => {
    releaseCleanup = resolve;
  });
  const { marks, runner, state } = makeRunner({
    ensureGatewayInstalled: () => cleanup,
    runtimeMetadata: { releaseChannel: "beta" },
  });

  const pending = runner.ensureBackend();
  await Promise.resolve();
  assert.deepEqual(marks, [
    ["backend:ensure-start", ""],
    ["backend:beta-gateway-cleanup-start", ""],
  ]);
  assert.equal(state.spawnCall, undefined);

  releaseCleanup();
  assert.equal(await pending, true);
  const cleanupDone = marks.findIndex(([name]) => name === "backend:beta-gateway-cleanup-complete");
  const choose = marks.findIndex(([name]) => name === "choose");
  const spawn = marks.findIndex(([name]) => name === "backend:spawn");
  assert.ok(cleanupDone >= 0 && cleanupDone < choose && choose < spawn);
  assert.equal(state.spawnCall.command, "/bin/elevate");
});

test("Beta cleanup failure aborts startup before port or backend work", async () => {
  const cleanupError = Object.assign(new Error("launchctl timed out"), {
    code: "ETIMEDOUT",
  });
  const { marks, runner, state, timers } = makeRunner({
    ensureGatewayInstalled: async () => {
      throw cleanupError;
    },
    runtimeMetadata: { releaseChannel: "beta" },
  });

  await assert.rejects(runner.ensureBackend(), cleanupError);
  assert.equal(state.spawnCall, undefined);
  assert.equal(timers.length, 0);
  assert.equal(marks.some(([name]) => name === "choose"), false);
  assert.equal(marks.some(([name]) => name === "backend:spawn"), false);
});
