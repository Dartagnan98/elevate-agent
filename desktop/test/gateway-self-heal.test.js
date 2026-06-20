const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const mainPath = path.resolve(__dirname, "../src/main.js");
const gatewayPath = path.resolve(__dirname, "../src/gateway-self-heal.js");

function readMain() {
  return fs.readFileSync(mainPath, "utf8");
}

function functionBlock(source, name) {
  const start = source.indexOf(`function ${name}`);
  assert.notEqual(start, -1, `${name} function not found`);
  const next = source.indexOf("\nfunction ", start + 1);
  return source.slice(start, next === -1 ? undefined : next);
}

test("gateway probe detects loaded and running launchd states", () => {
  const gateway = fs.readFileSync(gatewayPath, "utf8");
  const block = functionBlock(gateway, "probeGateway");

  assert.match(block, /"launchctl",\s*\[\s*"print",\s*`gui\/\$\{uid\}\/ai\.elevate\.gateway`\s*\]/s);
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
  assert.match(block, /if \(kickstartGateway\(uid\) && probeGateway\(uid\)\.running\) return/);
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
  const main = readMain();
  const block = functionBlock(main, "ensureBackend");
  const calls = block.match(/scheduleGatewaySelfHeal\(launcher, baseEnv\)/g) || [];

  assert.equal(calls.length, 2);
  assert.ok(
    block.indexOf("backend:already-ready") <
      block.indexOf("scheduleGatewaySelfHeal(launcher, baseEnv)"),
  );
  assert.ok(
    block.lastIndexOf("scheduleGatewaySelfHeal(launcher, baseEnv)") >
      block.indexOf("backend:ready"),
  );
});
