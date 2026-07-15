"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { sanitizeFileName } = require("builder-util/out/filename");

const createBuilderConfig = require("../electron-builder.config");
const {
  artifactFileName,
  applyElectronProfile,
  backendRuntimeExpectation,
  downloadAliasFileName,
  downloadAliasFileNames,
  releaseArtifactNames,
  resolveReleaseProfile,
  resolveRuntimePaths,
} = require("../src/release-profile");

function builderConfig(channel, sourceReceiptId) {
  const previous = process.env.ELEVATE_RELEASE_CHANNEL;
  const previousSourceReceiptId = process.env.ELEVATE_SOURCE_RECEIPT_ID;
  try {
    process.env.ELEVATE_RELEASE_CHANNEL = channel;
    if (sourceReceiptId) process.env.ELEVATE_SOURCE_RECEIPT_ID = sourceReceiptId;
    else delete process.env.ELEVATE_SOURCE_RECEIPT_ID;
    return createBuilderConfig();
  } finally {
    if (previous === undefined) delete process.env.ELEVATE_RELEASE_CHANNEL;
    else process.env.ELEVATE_RELEASE_CHANNEL = previous;
    if (previousSourceReceiptId === undefined) delete process.env.ELEVATE_SOURCE_RECEIPT_ID;
    else process.env.ELEVATE_SOURCE_RECEIPT_ID = previousSourceReceiptId;
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
    "artifactPrefix",
    "downloadAliasPrefix",
    "downloadAliasPrefixes",
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

test("desktop requires the exact Beta runtime receipt and leaves Stable legacy-compatible", () => {
  const home = "/Users/tester";
  const stableProfile = resolveReleaseProfile("latest");
  const betaProfile = resolveReleaseProfile("beta");
  const stablePaths = resolveRuntimePaths({ profile: stableProfile, home });
  const betaPaths = resolveRuntimePaths({ profile: betaProfile, home });

  assert.equal(
    backendRuntimeExpectation({ profile: stableProfile, paths: stablePaths }),
    null,
  );
  assert.deepEqual(
    backendRuntimeExpectation({ profile: betaProfile, paths: betaPaths }),
    {
      releaseChannel: "beta",
      elevateHome: "/Users/tester/.elevate-beta",
      providerPolicyVersion: "realtor-beta-codex-v1",
      allowedModelsVersion: "2026-07-14-v1",
      entitlementAssertionSchema: 1,
      entitlementAssertionAcceptedKeyIds: [
        "ent-2026-07-a",
        "ent-2026-07-b",
      ],
      entitlementAssertionKeysetSha256:
        "1d97a77a0be01aa7506fd3619ad454c709a375f8aab8febbd9818a47c5e53a0c",
      allowedProvider: "openai-codex",
      allowedModels: [
        "gpt-5.5",
        "gpt-5.4-mini",
        "gpt-5.4",
        "gpt-5.3-codex",
        "gpt-5.3-codex-spark",
        "gpt-5.2-codex",
        "gpt-5.1-codex-max",
        "gpt-5.1-codex-mini",
      ],
    },
  );
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
  assert.equal(stable.artifactName, "Elevate-${version}-${os}-${arch}.${ext}");
  assert.equal(resolveReleaseProfile("latest").downloadAliasPrefix, "Elevate-latest");

  assert.equal(beta.productName, "Elevate Beta");
  assert.equal(beta.appId, "com.elevationrealestate.elevate.beta");
  assert.equal(beta.extraMetadata.name, "elevate-beta-desktop");
  assert.equal(beta.extraMetadata.elevateReleaseChannel, "beta");
  assert.deepEqual(beta.protocols[0].schemes, ["elevate-beta"]);
  assert.equal(beta.publish[0].channel, "beta");
  assert.equal(beta.artifactName, "Elevate-Beta-${version}-${os}-${arch}.${ext}");
  assert.equal(resolveReleaseProfile("beta").downloadAliasPrefix, "Elevate-Beta");
  assert.equal(beta.dmg.title, "Elevate Beta");
  const updaterCache = (config) =>
    `${sanitizeFileName(config.extraMetadata.name).toLowerCase()}-updater`;
  assert.equal(updaterCache(beta), "elevate-beta-desktop-updater");
  assert.notEqual(updaterCache(beta), updaterCache(stable));
});

test("Stable and Beta artifact/download names stay visibly separated", () => {
  const stable = resolveReleaseProfile("latest");
  const beta = resolveReleaseProfile("beta");
  assert.equal(artifactFileName(stable, "1.2.67", "arm64", "dmg"), "Elevate-1.2.67-mac-arm64.dmg");
  assert.equal(artifactFileName(beta, "1.2.67", "arm64", "dmg"), "Elevate-Beta-1.2.67-mac-arm64.dmg");
  assert.equal(downloadAliasFileName(stable, "arm64"), "Elevate-latest-mac-arm64.dmg");
  assert.equal(downloadAliasFileName(beta, "arm64"), "Elevate-Beta-mac-arm64.dmg");
  assert.deepEqual(downloadAliasFileNames(beta, "arm64"), [
    "Elevate-Beta-mac-arm64.dmg",
    "Elevate-beta-mac-arm64.dmg",
  ]);
  assert.equal(releaseArtifactNames(beta, "1.2.67").length, 4);
  assert.ok(releaseArtifactNames(beta, "1.2.67").every((name) => name.startsWith("Elevate-Beta-")));
});

test("electron-builder stamps the immutable source receipt into both candidates", () => {
  const sourceReceiptId = "a".repeat(64);
  assert.equal(builderConfig("latest", sourceReceiptId).extraMetadata.elevateSourceReceiptId, sourceReceiptId);
  assert.equal(builderConfig("beta", sourceReceiptId).extraMetadata.elevateSourceReceiptId, sourceReceiptId);
});
