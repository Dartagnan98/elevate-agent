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

test("backend runner schedules gateway self-heal for already-ready backend", async () => {
  let healed = false;
  const { runner, timers } = makeRunner({
    alreadyReady: true,
    ensureGatewayInstalled: () => {
      healed = true;
    },
  });

  assert.equal(await runner.ensureBackend(), true);
  assert.equal(timers.length, 1);
  assert.equal(timers[0][1], 8000);

  timers[0][0]();
  assert.equal(healed, true);
});

test("backend runner spawns dashboard and clears owned process on exit", async () => {
  const { launcher, marks, runner, state, timers } = makeRunner();

  assert.equal(await runner.ensureBackend(), true);
  assert.equal(state.ownsBackend, true);
  assert.equal(state.spawnCall.command, "/bin/elevate");
  assert.deepEqual(state.spawnCall.options.env, {
    ELEVATE_DASHBOARD_TUI: "1",
    ELEVATE_DESKTOP_APP: "1",
    ELEVATE_SMS_VIA_APP: "1",
    EXTRA: "1",
    PATH: "/bin",
  });
  assert.equal(timers.length, 1);
  assert.ok(marks.some(([name, detail]) => name === "backend:port-selected" && detail === "9119"));
  assert.ok(marks.some(([name, detail]) => name === "backend:spawn" && detail === "elevate"));

  state.backendProcess.emit("exit", 0, null);
  assert.equal(state.backendProcess, null);
  assert.equal(state.ownsBackend, false);
  assert.deepEqual(launcher.args, ["dashboard"]);
});
