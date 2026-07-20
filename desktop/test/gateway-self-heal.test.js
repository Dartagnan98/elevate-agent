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

test("desktop keeps delayed gateway maintenance only on adopted and spawned Stable paths", () => {
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
      if (b.stderr) child.stderr.emit("data", b.stderr);
      child.emit("close", b.status ?? 0, null);
    });
    return child;
  };
  return { spawn, calls };
}

function buildSelfHeal(spawn, logs, overrides = {}) {
  const fsImpl = overrides.fs || require("node:fs");
  const osImpl = overrides.os || require("node:os");
  return createGatewaySelfHeal({
    app: { getVersion: () => "0.0.0-test" },
    appendBackendLog: (line) => logs.push(line),
    envWithPath: (env) => env,
    fileExists: overrides.fileExists || (() => false),
    fs: fsImpl,
    os: osImpl,
    path: require("node:path"),
    process: overrides.process || { platform: "darwin", getuid: () => 501 },
    spawn,
    elevateHome: overrides.elevateHome,
    gatewayLabel: overrides.gatewayLabel,
  });
}

test("exact Beta self-heal boots out and removes stale gateway without reviving it", async (t) => {
  const realFs = require("node:fs");
  const realOs = require("node:os");
  const realPath = require("node:path");
  const home = realFs.mkdtempSync(realPath.join(realOs.tmpdir(), "elevate-beta-gateway-"));
  t.after(() => realFs.rmSync(home, { recursive: true, force: true }));
  const plist = realPath.join(
    home,
    "Library",
    "LaunchAgents",
    "ai.elevate.gateway.plist",
  );
  realFs.mkdirSync(realPath.dirname(plist), { recursive: true });
  realFs.writeFileSync(plist, "stale beta plist", "utf8");

  const logs = [];
  const { spawn, calls } = fakeSpawn((_command, args) => {
    if (args[0] === "print") {
      return { status: 113, stderr: "Could not find service" };
    }
    return { status: 0 };
  });
  const heal = buildSelfHeal(spawn, logs, {
    fs: realFs,
    os: { homedir: () => home },
    fileExists: (candidate) => realFs.existsSync(candidate),
    elevateHome: realPath.join(home, ".elevate-beta"),
  });

  await heal.ensureGatewayInstalled(null, { ELEVATE_RELEASE_CHANNEL: "beta" });

  assert.deepEqual(calls, [
    {
      command: "launchctl",
      args: ["bootout", "gui/501/ai.elevate.gateway"],
    },
    {
      command: "launchctl",
      args: ["print", "gui/501/ai.elevate.gateway"],
    },
  ]);
  assert.equal(realFs.existsSync(plist), false);
  assert.ok(logs.some((line) => line.includes("self-heal skipped")));
  assert.equal(calls.some((call) => call.args.includes("kickstart")), false);
  assert.equal(calls.some((call) => call.args.includes("bootstrap")), false);
  assert.equal(calls.some((call) => call.command === "elevate"), false);
});

test("exact Beta cleanup kills and retries when first bootout leaves a running job", async (t) => {
  const realFs = require("node:fs");
  const realOs = require("node:os");
  const realPath = require("node:path");
  const home = realFs.mkdtempSync(realPath.join(realOs.tmpdir(), "elevate-beta-retry-"));
  t.after(() => realFs.rmSync(home, { recursive: true, force: true }));
  const plist = realPath.join(home, "Library", "LaunchAgents", "ai.elevate.gateway.plist");
  realFs.mkdirSync(realPath.dirname(plist), { recursive: true });
  realFs.writeFileSync(plist, "stale", "utf8");
  let prints = 0;
  let bootouts = 0;
  const { spawn, calls } = fakeSpawn((_command, args) => {
    if (args[0] === "bootout") {
      bootouts += 1;
      return { status: bootouts === 1 ? 5 : 0, stderr: "busy" };
    }
    if (args[0] === "print") {
      prints += 1;
      return prints === 1
        ? { status: 0, stdout: "state = running\npid = 123\n" }
        : { status: 113, stderr: "Could not find service" };
    }
    if (args[0] === "kill") return { status: 0 };
    throw new Error(`unexpected launchctl command: ${args.join(" ")}`);
  });
  const heal = buildSelfHeal(spawn, [], {
    fs: realFs,
    os: { homedir: () => home },
    fileExists: (candidate) => realFs.existsSync(candidate),
  });

  await heal.ensureGatewayInstalled(null, { ELEVATE_RELEASE_CHANNEL: "beta" });

  assert.deepEqual(calls.map((call) => call.args[0]), [
    "bootout",
    "print",
    "kill",
    "bootout",
    "print",
  ]);
  assert.equal(realFs.existsSync(plist), false);
});

test("exact Beta cleanup fails closed and preserves plist when absence is unproven", async (t) => {
  const realFs = require("node:fs");
  const realOs = require("node:os");
  const realPath = require("node:path");
  const home = realFs.mkdtempSync(realPath.join(realOs.tmpdir(), "elevate-beta-fail-"));
  t.after(() => realFs.rmSync(home, { recursive: true, force: true }));
  const plist = realPath.join(home, "Library", "LaunchAgents", "ai.elevate.gateway.plist");
  realFs.mkdirSync(realPath.dirname(plist), { recursive: true });
  realFs.writeFileSync(plist, "must survive", "utf8");
  const { spawn } = fakeSpawn((_command, args) => (
    args[0] === "print"
      ? { status: 0, stdout: "state = running\npid = 123\n" }
      : { status: 5, stderr: "operation failed" }
  ));
  const heal = buildSelfHeal(spawn, [], {
    fs: realFs,
    os: { homedir: () => home },
    fileExists: (candidate) => realFs.existsSync(candidate),
  });

  await assert.rejects(
    heal.ensureGatewayInstalled(null, { ELEVATE_RELEASE_CHANNEL: "beta" }),
    /remained loaded/,
  );
  assert.equal(realFs.readFileSync(plist, "utf8"), "must survive");
});

test("exact Beta cleanup removes a broken plist symlink after absence proof", async (t) => {
  const realFs = require("node:fs");
  const realOs = require("node:os");
  const realPath = require("node:path");
  const home = realFs.mkdtempSync(realPath.join(realOs.tmpdir(), "elevate-beta-link-"));
  t.after(() => realFs.rmSync(home, { recursive: true, force: true }));
  const plist = realPath.join(home, "Library", "LaunchAgents", "ai.elevate.gateway.plist");
  realFs.mkdirSync(realPath.dirname(plist), { recursive: true });
  realFs.symlinkSync(realPath.join(home, "missing-target"), plist);
  const { spawn } = fakeSpawn((_command, args) => (
    args[0] === "print"
      ? { status: 113, stderr: "Could not find service" }
      : { status: 0 }
  ));
  const heal = buildSelfHeal(spawn, [], {
    fs: realFs,
    os: { homedir: () => home },
    // access/exists semantics deliberately cannot see this broken symlink.
    fileExists: (candidate) => realFs.existsSync(candidate),
  });

  await heal.ensureGatewayInstalled(null, { ELEVATE_RELEASE_CHANNEL: "beta" });
  assert.throws(() => realFs.lstatSync(plist), { code: "ENOENT" });
});

test("gateway command timeout force-kills and resolves without waiting for close", async () => {
  const kills = [];
  const spawn = () => {
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.kill = (signal) => {
      kills.push(signal);
      return true;
    };
    return child;
  };
  const heal = buildSelfHeal(spawn, []);
  const started = Date.now();
  const result = await heal.run("launchctl", ["print", "missing"], { timeout: 10 });

  assert.equal(result.status, null);
  assert.equal(result.error.code, "ETIMEDOUT");
  assert.deepEqual(kills, ["SIGTERM", "SIGKILL"]);
  assert.ok(Date.now() - started < 1000);
});

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
