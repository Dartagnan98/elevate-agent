const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const path = require("node:path");
const test = require("node:test");

const { createBackendRunner } = require("../src/backend-runner");

function makeRunner(overrides = {}) {
  const marks = [];
  const timers = [];
  const state = {
    backendProcess: null,
    ownsBackend: false,
    backendReady: null,
    shuttingDown: false,
    gaveUp: 0,
    logWrites: [],
    renames: [],
  };
  const launcher = overrides.launcher || {
    command: "/bin/elevate",
    args: ["dashboard"],
    cwd: "/tmp",
    extraEnv: { EXTRA: "1" },
  };
  // In-memory fake for the backend.log WriteStream so capture/rotation can be
  // asserted without touching disk (mirrors the EventEmitter fakes above).
  const fakeFs = overrides.fs || {
    mkdirSync: () => {},
    statSync: () => {
      throw Object.assign(new Error("ENOENT"), { code: "ENOENT" });
    },
    renameSync: (from, to) => {
      state.renames.push([from, to]);
    },
    createWriteStream: () => ({
      write: (chunk) => {
        state.logWrites.push(chunk.toString());
      },
      end: () => {},
    }),
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
    fs: fakeFs,
    getBackendLogPath:
      overrides.getBackendLogPath || (() => "/tmp/elevate-test/backend.log"),
    getBackendPort: () => 9119,
    isShuttingDown: overrides.isShuttingDown || (() => Boolean(state.shuttingDown)),
    markStartup: (name, detail = "") => {
      marks.push([name, detail]);
    },
    now: overrides.now || (() => (state.now !== undefined ? state.now : Date.now())),
    onBackendGaveUp: overrides.onBackendGaveUp || (() => {
      state.gaveUp += 1;
    }),
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
    setBackendReady: (value) => {
      state.backendReady = value;
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

// Records every spawned child so a test can drive multiple respawns.
function recordingSpawn(procs) {
  return () => {
    const proc = new EventEmitter();
    proc.stdout = new EventEmitter();
    proc.stderr = new EventEmitter();
    procs.push(proc);
    return proc;
  };
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

test("supervisor respawns the backend with exponential backoff after an unexpected exit", async () => {
  const procs = [];
  const { runner, state, timers } = makeRunner({ spawn: recordingSpawn(procs) });

  assert.equal(await runner.ensureBackend(), true);
  assert.equal(procs.length, 1);
  // A healthy start arms no timer — restarts are driven by exits, not polling.
  assert.equal(timers.length, 0);

  // First unexpected exit → readiness flips false + respawn scheduled at 1s.
  procs[0].emit("exit", 1, null);
  assert.equal(state.backendReady, false);
  assert.equal(state.backendProcess, null);
  assert.equal(state.ownsBackend, false);
  assert.equal(timers.length, 1);
  assert.equal(timers[0][1], 1000);

  // Fire the scheduled respawn → a fresh child is spawned and owned again.
  timers[0][0]();
  assert.equal(procs.length, 2);
  assert.equal(state.ownsBackend, true);

  // Second consecutive fast exit → backoff doubles to 2s.
  procs[1].emit("exit", 1, null);
  assert.equal(timers.length, 2);
  assert.equal(timers[1][1], 2000);

  timers[1][0]();
  assert.equal(procs.length, 3);

  // Third consecutive fast exit → 4s.
  procs[2].emit("exit", 1, null);
  assert.equal(timers[2][1], 4000);
});

test("supervisor treats a run past the stability window as healthy and resets the backoff", async () => {
  const procs = [];
  const clock = { t: 0 };
  const { runner, timers } = makeRunner({
    spawn: recordingSpawn(procs),
    now: () => clock.t,
  });

  assert.equal(await runner.ensureBackend(), true);

  // Backend stayed up well past the 30s stability window before dying.
  clock.t = 40000;
  procs[0].emit("exit", 1, null);
  // Counter reset (uptime >= window) then incremented to 1 → 1s backoff, not escalated.
  assert.equal(timers.length, 1);
  assert.equal(timers[0][1], 1000);
});

test("supervisor does not respawn when the app is shutting down", async () => {
  const procs = [];
  const { runner, state, timers } = makeRunner({ spawn: recordingSpawn(procs) });

  assert.equal(await runner.ensureBackend(), true);
  assert.equal(procs.length, 1);

  // The before-quit handler sets this flag before killing the backend.
  state.shuttingDown = true;
  procs[0].emit("exit", 0, "SIGTERM");

  assert.equal(state.backendReady, false);
  assert.equal(state.backendProcess, null);
  assert.equal(state.ownsBackend, false);
  assert.equal(timers.length, 0); // no respawn scheduled
  assert.equal(procs.length, 1); // no new process spawned
});

test("supervisor captures raw backend stdout/stderr to backend.log", async () => {
  const { runner, state } = makeRunner();

  assert.equal(await runner.ensureBackend(), true);

  // Raw chunks (Buffer and string) are written verbatim to the log stream.
  state.backendProcess.stdout.emit("data", Buffer.from("listening on 9119\n"));
  state.backendProcess.stderr.emit("data", "Traceback: boom\n");

  assert.ok(state.logWrites.includes("listening on 9119\n"));
  assert.ok(state.logWrites.includes("Traceback: boom\n"));
});

test("supervisor stops respawning after the fast-failure cap and surfaces the outage", async () => {
  const procs = [];
  const { runner, state, timers } = makeRunner({ spawn: recordingSpawn(procs) });

  assert.equal(await runner.ensureBackend(), true);

  // Drive consecutive fast failures: exit → fire the scheduled respawn → repeat.
  // Attempts 1..4 each schedule a respawn; the 5th consecutive failure trips the cap.
  procs[0].emit("exit", 1, null); // restartCount 1 → respawn @1s
  timers[0][0]();
  procs[1].emit("exit", 1, null); // 2 → @2s
  timers[1][0]();
  procs[2].emit("exit", 1, null); // 3 → @4s
  timers[2][0]();
  procs[3].emit("exit", 1, null); // 4 → @8s
  timers[3][0]();
  procs[4].emit("exit", 1, null); // 5 → cap: give up, no respawn

  assert.equal(state.gaveUp, 1);
  assert.equal(procs.length, 5); // capped: no 6th spawn
  assert.equal(timers.length, 4); // only 4 respawns were ever scheduled
  assert.equal(state.backendReady, false);
  assert.deepEqual(
    timers.map(([, delay]) => delay),
    [1000, 2000, 4000, 8000],
  );
});
