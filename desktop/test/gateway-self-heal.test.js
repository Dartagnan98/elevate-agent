const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const runnerPath = path.resolve(__dirname, "../src/backend-runner.js");
const gatewayPath = path.resolve(__dirname, "../src/gateway-self-heal.js");

function functionBlock(source, name) {
  const start = source.indexOf(`function ${name}`);
  assert.notEqual(start, -1, `${name} function not found`);
  const next = source.indexOf("\nfunction ", start + 1);
  return source.slice(start, next === -1 ? undefined : next);
}

test("gateway probe detects loaded and running launchd states", () => {
  const gateway = fs.readFileSync(gatewayPath, "utf8");
  const block = functionBlock(gateway, "probeGateway");

  assert.match(block, /"launchctl",\s*\[\s*"print",\s*`gui\/\$\{uid\}\/\$\{gatewayLabel\}`\s*\]/s);
  assert.match(block, /const loaded = probe\.status === 0/);
  assert.match(block, /\\bpid = \\d\+/);
  assert.match(block, /state = running/);
  assert.match(block, /return \{ loaded, running \}/);
});

test("gateway self-heal kickstarts a loaded but dead service", () => {
  const gateway = fs.readFileSync(gatewayPath, "utf8");
  const block = functionBlock(gateway, "ensureGatewayInstalled");

  assert.match(block, /if \(fileExists\(plist\) && loaded && !running\)/);
  assert.match(block, /loaded but NOT running -> kickstart/);
  assert.match(
    block,
    /if \(\(await kickstartGateway\(uid\)\) && \(await probeGateway\(uid\)\)\.running\) return/,
  );
});

test("gateway self-heal installs missing service and direct-bootstraps as fallback", () => {
  const gateway = fs.readFileSync(gatewayPath, "utf8");
  const block = functionBlock(gateway, "ensureGatewayInstalled");

  assert.match(block, /-> installing/);
  assert.match(block, /runGatewayCommand\(launcher, baseEnv, \["install"\]\)/);
  assert.match(block, /install did not yield a running job; direct launchctl bootstrap fallback/);
  assert.match(block, /bootstrapGatewayDirect\(uid, plist\)/);
  assert.match(block, /revived the gateway/);
  assert.match(block, /gateway still down/);
});

test("desktop schedules gateway self-heal for adopted and spawned dashboards", () => {
  const runner = fs.readFileSync(runnerPath, "utf8");
  const block = functionBlock(runner, "ensureBackend");
  const calls = block.match(/scheduleGatewaySelfHeal\(launcher, baseEnv\)/g) || [];

  assert.equal(calls.length, 2);
  assert.ok(
    block.indexOf("backend:already-compatible") <
      block.indexOf("scheduleGatewaySelfHeal(launcher, baseEnv)"),
  );
  assert.ok(
    block.lastIndexOf("scheduleGatewaySelfHeal(launcher, baseEnv)") >
      block.indexOf("backend:compatible"),
  );
});

// C5 behavioral coverage: the heal chain must run through async spawn (never
// blocking the main thread) while preserving the spawnSync result shape.
const { EventEmitter } = require("node:events");
const { createGatewaySelfHeal } = require("../src/gateway-self-heal");

function fakeSpawn(behavior) {
  const calls = [];
  const spawn = (command, args) => {
    calls.push({ command, args });
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.kill = () => child.emit("close", null, "SIGTERM");
    process.nextTick(() => {
      const b = behavior(command, args) || {};
      if (b.stdout) child.stdout.emit("data", b.stdout);
      child.emit("close", b.status ?? 0, null);
    });
    return child;
  };
  return { spawn, calls };
}

function buildSelfHeal(spawn, logs, overrides = {}) {
  return createGatewaySelfHeal({
    app: { getVersion: () => "0.0.0-test" },
    appendBackendLog: (line) => logs.push(line),
    envWithPath: (env) => env,
    fileExists: () => false,
    fs: require("node:fs"),
    os: require("node:os"),
    path: require("node:path"),
    process: { platform: "darwin", getuid: () => 501 },
    spawn,
    elevateHome: overrides.elevateHome,
    gatewayLabel: overrides.gatewayLabel,
  });
}

test("probeGateway parses launchctl print output asynchronously", async () => {
  const { spawn } = fakeSpawn(() => ({ status: 0, stdout: "pid = 4242\n" }));
  const heal = buildSelfHeal(spawn, []);
  const pending = heal.probeGateway(501);
  assert.equal(typeof pending.then, "function", "probeGateway must not block");
  assert.deepEqual(await pending, { loaded: true, running: true });
});

test("Beta gateway uses its own state root and launchd label", async () => {
  const { spawn, calls } = fakeSpawn(() => ({ status: 0, stdout: "pid = 4242\n" }));
  const heal = buildSelfHeal(spawn, [], {
    elevateHome: "/Users/tester/.elevate-beta",
    gatewayLabel: "ai.elevate.gateway-1234abcd",
  });

  assert.equal(
    heal.gatewayVersionMarkerPath(),
    "/Users/tester/.elevate-beta/.gateway_version",
  );
  await heal.probeGateway(501);
  assert.deepEqual(calls[0].args, ["print", "gui/501/ai.elevate.gateway-1234abcd"]);
});

test("ensureGatewayInstalled runs install without throwing when nothing is loaded", async () => {
  const logs = [];
  const { spawn, calls } = fakeSpawn((command) =>
    command === "launchctl" ? { status: 113 } : { status: 0, stdout: "installed" },
  );
  const heal = buildSelfHeal(spawn, logs);
  await heal.ensureGatewayInstalled(
    { command: "elevate", args: ["dashboard"], cwd: "/tmp" },
    {},
  );
  assert.ok(
    calls.some((c) => c.command === "elevate" && c.args.includes("install")),
    "install command must run",
  );
  assert.ok(logs.some((l) => l.includes("-> installing")));
});
