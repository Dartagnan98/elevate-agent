"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { sanitizeFileName } = require("builder-util/out/filename");

const createBuilderConfig = require("../electron-builder.config");
const {
  applyElectronProfile,
  resolveReleaseProfile,
  resolveRuntimePaths,
} = require("../src/release-profile");

function builderConfig(channel) {
  const previous = process.env.ELEVATE_RELEASE_CHANNEL;
  try {
    process.env.ELEVATE_RELEASE_CHANNEL = channel;
    return createBuilderConfig();
  } finally {
    if (previous === undefined) delete process.env.ELEVATE_RELEASE_CHANNEL;
    else process.env.ELEVATE_RELEASE_CHANNEL = previous;
  }
}

test("Stable keeps its shipping identity and Beta has a collision-free identity", () => {
  const stable = resolveReleaseProfile("latest");
  const beta = resolveReleaseProfile("beta");

  assert.deepEqual(
    {
      productName: stable.productName,
      appId: stable.appId,
      protocolScheme: stable.protocolScheme,
      elevateHomeName: stable.elevateHomeName,
      workspaceName: stable.workspaceName,
      preferredPort: stable.preferredPort,
    },
    {
      productName: "Elevate",
      appId: "com.elevationrealestate.elevate",
      protocolScheme: "elevate",
      elevateHomeName: ".elevate",
      workspaceName: "Elevation",
      preferredPort: 9119,
    },
  );
  for (const key of [
    "productName",
    "appBundleName",
    "appId",
    "packageName",
    "protocolScheme",
    "elevateHomeName",
    "workspaceName",
    "preferredPort",
    "gatewayLabel",
  ]) {
    assert.notEqual(beta[key], stable[key], `${key} must differ`);
  }
  assert.ok(beta.preferredPort > stable.preferredPort + 10);
});

test("Beta runtime roots cannot inherit Stable state", () => {
  const home = "/Users/tester";
  const stable = resolveRuntimePaths({
    profile: resolveReleaseProfile("latest"),
    home,
    env: { ELEVATE_HOME: "/tmp/custom-stable" },
  });
  const beta = resolveRuntimePaths({
    profile: resolveReleaseProfile("beta"),
    home,
    env: { ELEVATE_HOME: "/Users/tester/.elevate" },
  });

  assert.equal(stable.elevateHome, "/tmp/custom-stable");
  assert.equal(beta.elevateHome, "/Users/tester/.elevate-beta");
  assert.equal(beta.licensePath, "/Users/tester/.elevate-beta/license.json");
  assert.equal(beta.dashboardTokenPath, "/Users/tester/.elevate-beta/dashboard-session-token");
  assert.equal(beta.workspace, "/Users/tester/Elevation Beta");
  assert.equal(
    beta.pythonCache,
    "/Users/tester/Library/Caches/Elevate Beta/python-pycache",
  );
  assert.equal(
    beta.electronUserData,
    "/Users/tester/Library/Application Support/Elevate Beta",
  );
  assert.equal(beta.gatewayLabel, "ai.elevate.gateway-beta");
  assert.equal(stable.gatewayLabel, "ai.elevate.gateway");
});

test("Electron path overrides apply only to Beta", () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-beta-profile-"));
  const calls = [];
  const app = {
    setName: (value) => calls.push(["name", value]),
    setPath: (name, value) => calls.push([name, value]),
    setAppLogsPath: (value) => calls.push(["logs", value]),
  };
  try {
    const stableProfile = resolveReleaseProfile("latest");
    const stablePaths = resolveRuntimePaths({ profile: stableProfile, home });
    applyElectronProfile({ app, fs, profile: stableProfile, paths: stablePaths });
    assert.deepEqual(calls, [["name", "Elevate"]]);

    calls.length = 0;
    const betaProfile = resolveReleaseProfile("beta");
    const betaPaths = resolveRuntimePaths({ profile: betaProfile, home });
    applyElectronProfile({ app, fs, profile: betaProfile, paths: betaPaths });
    assert.deepEqual(calls, [
      ["name", "Elevate Beta"],
      ["userData", betaPaths.electronUserData],
      ["sessionData", betaPaths.electronSessionData],
      ["crashDumps", betaPaths.electronCrashDumps],
      ["logs", betaPaths.electronLogs],
    ]);
    for (const dir of [
      betaPaths.electronUserData,
      betaPaths.electronSessionData,
      betaPaths.electronCrashDumps,
      betaPaths.electronLogs,
    ]) {
      assert.equal(fs.statSync(dir).isDirectory(), true);
    }
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("electron-builder receives the selected app, protocol, feed, and updater identity", () => {
  const stable = builderConfig("latest");
  const beta = builderConfig("beta");

  assert.equal(stable.productName, "Elevate");
  assert.equal(stable.appId, "com.elevationrealestate.elevate");
  assert.equal(stable.extraMetadata.name, "@elevationrealestate/elevate-desktop");
  assert.equal(stable.extraMetadata.elevateReleaseChannel, "latest");
  assert.deepEqual(stable.protocols[0].schemes, ["elevate"]);
  assert.equal(stable.publish[0].channel, "latest");

  assert.equal(beta.productName, "Elevate Beta");
  assert.equal(beta.appId, "com.elevationrealestate.elevate.beta");
  assert.equal(beta.extraMetadata.name, "elevate-beta-desktop");
  assert.equal(beta.extraMetadata.elevateReleaseChannel, "beta");
  assert.deepEqual(beta.protocols[0].schemes, ["elevate-beta"]);
  assert.equal(beta.publish[0].channel, "beta");
  assert.equal(beta.dmg.title, "Elevate Beta");
  const updaterCache = (config) =>
    `${sanitizeFileName(config.extraMetadata.name).toLowerCase()}-updater`;
  assert.equal(updaterCache(beta), "elevate-beta-desktop-updater");
  assert.notEqual(updaterCache(beta), updaterCache(stable));
});
