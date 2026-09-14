const assert = require("node:assert/strict");
const test = require("node:test");

const { createBackendPortController } = require("../src/backend-port");

function makeController(overrides = {}) {
  let selectedPort = overrides.initialPort || 9119;
  const calls = [];
  const logs = [];
  const ready = overrides.ready || {};
  const bundle = overrides.bundle || {};
  const chat = overrides.chat || {};
  const controller = createBackendPortController({
    backendBundleMatches: async (port) => Boolean(bundle[port]),
    backendIsReady: async (port) => Boolean(ready[port]),
    dashboardChatEnabled: async (port) => Boolean(chat[port]),
    embeddedChat: overrides.embeddedChat !== false,
    execFileSync: overrides.execFileSync || ((command, args) => {
      calls.push([command, args]);
      if (command === "/usr/sbin/lsof") return overrides.lsof || "";
      return "";
    }),
    getBackendPort: () => selectedPort,
    log: {
      info(message) {
        logs.push(["info", message]);
      },
      warn(message) {
        logs.push(["warn", message]);
      },
    },
    preferredPort: 9119,
    setBackendPort(port) {
      selectedPort = port;
    },
    setTimeout: (callback) => {
      callback();
      return 0;
    },
  });
  return { calls, controller, logs, selectedPort: () => selectedPort };
}

test("backend port controller adopts a ready preferred desktop backend", async () => {
  const { controller, selectedPort } = makeController({
    ready: { 9119: true },
    bundle: { 9119: true },
    chat: { 9119: true },
  });

  await controller.chooseBackendPort();

  assert.equal(selectedPort(), 9119);
});

test("backend port controller evicts stale preferred dashboard bundle", async () => {
  let killed = false;
  const calls = [];
  const { controller, logs, selectedPort } = makeController({
    ready: new Proxy({}, { get: (_target, port) => port === "9119" && !killed }),
    bundle: { 9119: false },
    execFileSync(command, args) {
      calls.push([command, args]);
      if (command === "/usr/sbin/lsof") return "123\n";
      if (command === "/bin/kill") killed = true;
      return "";
    },
  });

  await controller.chooseBackendPort();

  assert.equal(selectedPort(), 9119);
  assert.deepEqual(calls.find(([command]) => command === "/bin/kill"), [
    "/bin/kill",
    ["-TERM", "123"],
  ]);
  assert.match(logs.map((entry) => entry[1]).join("\n"), /stale-bundle/);
});

test("backend port controller picks the first empty fallback port", async () => {
  const { controller, selectedPort } = makeController({
    ready: { 9119: true, 9120: true },
    bundle: { 9119: true, 9120: true },
    chat: { 9119: false, 9120: false },
  });

  await controller.chooseBackendPort();

  assert.equal(selectedPort(), 9121);
});
