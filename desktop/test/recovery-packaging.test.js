"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const asar = require("@electron/asar");

const createRecoveryBuilderConfig = require("../electron-builder.recovery.config");
const {
  CANDIDATE_VERSION,
  RECOVERY_SOURCE_FILES,
  RECOVERY_VERSION,
} = createRecoveryBuilderConfig;
const {
  assertRecoveryAsarEntries,
  default: afterPackRecoveryMac,
  recoveryArchitecture,
  verifyRecoveryBundle,
  verifyRecoverySourceProvenance,
  writeImmutableEvidence,
} = require("../scripts/after-pack-recovery-mac");

const SOURCE_RECEIPT_ID = "a".repeat(64);

function config(overrides = {}) {
  return createRecoveryBuilderConfig({
    env: { ELEVATE_RECOVERY_SOURCE_RECEIPT_ID: SOURCE_RECEIPT_ID },
    manifest: { version: CANDIDATE_VERSION },
    ...overrides,
  });
}

async function recoveryBundleFixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-recovery-package-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const appPath = path.join(root, "Elevate Beta.app");
  const resourcesPath = path.join(appPath, "Contents", "Resources");
  const sourcePath = path.join(root, "asar-source");
  fs.mkdirSync(path.join(sourcePath, "src"), { recursive: true });
  fs.mkdirSync(resourcesPath, { recursive: true });
  for (const source of RECOVERY_SOURCE_FILES) {
    const output = path.join(sourcePath, source);
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, source.endsWith(".html") ? "<!doctype html>" : '"use strict";\n');
  }
  fs.writeFileSync(path.join(sourcePath, "package.json"), `${JSON.stringify({
    name: "elevate-beta-desktop",
    version: RECOVERY_VERSION,
    main: "src/recovery-main.js",
    elevateReleaseChannel: "beta",
    elevateRecoveryMode: true,
    elevateRecoveryCandidateVersion: CANDIDATE_VERSION,
    elevateRecoverySourceReceiptId: SOURCE_RECEIPT_ID,
    dependencies: {
      "electron-log": "^5.4.4",
      "electron-updater": "^6.8.3",
    },
  })}\n`);
  await asar.createPackage(sourcePath, path.join(resourcesPath, "app.asar"));
  fs.writeFileSync(path.join(resourcesPath, "app-update.yml"), [
    "provider: generic",
    "url: https://api.elevationrealestatehq.com/updates",
    "channel: beta",
    "updaterCacheDirName: elevate-beta-desktop-updater",
    "",
  ].join("\n"));
  fs.writeFileSync(path.join(appPath, "Contents", "Info.plist"), "fixture");

  const plist = {
    CFBundleIdentifier: "com.elevationrealestate.elevate.beta",
    CFBundleName: "Elevate Beta",
    CFBundleDisplayName: "Elevate Beta",
    CFBundleShortVersionString: RECOVERY_VERSION,
    CFBundleVersion: RECOVERY_VERSION,
    "CFBundleURLTypes.0.CFBundleURLSchemes.0": "elevate-beta",
  };
  return {
    appPath,
    resourcesPath,
    readPlist: (_plistPath, key) => plist[key],
  };
}

test("recovery builder is an exact 1.2.84 Beta roll-forward package", () => {
  const build = config();
  assert.equal(RECOVERY_VERSION, "1.2.84");
  assert.equal(CANDIDATE_VERSION, "1.2.83");
  assert.equal(build.appId, "com.elevationrealestate.elevate.beta");
  assert.equal(build.productName, "Elevate Beta");
  assert.equal(build.extraMetadata.name, "elevate-beta-desktop");
  assert.equal(build.extraMetadata.version, "1.2.84");
  assert.equal(build.extraMetadata.main, "src/recovery-main.js");
  assert.equal(build.extraMetadata.elevateReleaseChannel, "beta");
  assert.equal(build.extraMetadata.elevateRecoveryMode, true);
  assert.equal(build.extraMetadata.elevateRecoveryCandidateVersion, "1.2.83");
  assert.equal(build.extraMetadata.elevateRecoverySourceReceiptId, SOURCE_RECEIPT_ID);
  assert.deepEqual(build.protocols[0].schemes, ["elevate-beta"]);
  assert.equal(build.publish[0].channel, "beta");
  assert.equal(build.publish[0].url, "https://api.elevationrealestatehq.com/updates");
});

test("recovery artifacts and feed output cannot collide with the candidate", () => {
  const build = config();
  assert.equal(build.directories.output, "dist/recovery");
  assert.equal(
    build.artifactName,
    "Elevate-Beta-Recovery-${version}-mac-${arch}.${ext}",
  );
  assert.equal(build.afterPack, "scripts/after-pack-recovery-mac.js");
  assert.deepEqual(build.mac.target, [
    { target: "dmg", arch: ["arm64", "x64"] },
    { target: "zip", arch: ["arm64", "x64"] },
  ]);
  assert.equal(build.mac.hardenedRuntime, true);
  assert.equal(build.mac.notarize, true);
});

test("recovery builder contains no CLI, runtime, backend, gateway, or tools resources", () => {
  const build = config();
  assert.deepEqual(build.extraResources, []);
  assert.deepEqual(build.asarUnpack, []);
  assert.deepEqual(build.files, ["package.json", ...RECOVERY_SOURCE_FILES]);
  assert.ok(build.files.every((entry) => !/(^|\/)(cli|runtime|backend|gateway|tools)(\/|$)/.test(entry)));
  assert.ok(!build.files.includes("src/main.js"));
  assert.ok(!build.files.includes("src/backend-runner.js"));
  assert.ok(!build.files.includes("src/gateway-self-heal.js"));
});

test("recovery config fails closed without exact provenance or candidate version", () => {
  assert.throws(
    () => createRecoveryBuilderConfig({ env: {}, manifest: { version: CANDIDATE_VERSION } }),
    /ELEVATE_RECOVERY_SOURCE_RECEIPT_ID/,
  );
  assert.throws(
    () => createRecoveryBuilderConfig({
      env: { ELEVATE_RECOVERY_SOURCE_RECEIPT_ID: "not-a-receipt" },
      manifest: { version: CANDIDATE_VERSION },
    }),
    /64-character candidate source receipt ID/,
  );
  assert.throws(
    () => config({ manifest: { version: "1.2.84" } }),
    /bound to candidate 1\.2\.83/,
  );
});

test("recovery afterPack maps both supported builder architectures", () => {
  assert.equal(recoveryArchitecture(1), "x64");
  assert.equal(recoveryArchitecture(3), "arm64");
  assert.equal(recoveryArchitecture("x64"), "x64");
  assert.equal(recoveryArchitecture("arm64"), "arm64");
});

test("recovery afterPack verifies exact bundle identity, updater lane, and runtime absence", async (t) => {
  const fixture = await recoveryBundleFixture(t);
  const evidence = verifyRecoveryBundle({
    appPath: fixture.appPath,
    architecture: "arm64",
    sourceReceiptId: SOURCE_RECEIPT_ID,
    readPlist: fixture.readPlist,
  });
  assert.equal(evidence.kind, "elevate-beta-roll-forward-recovery-pre-sign");
  assert.equal(evidence.recovery_version, "1.2.84");
  assert.equal(evidence.candidate_version, "1.2.83");
  assert.equal(evidence.source_receipt_id, SOURCE_RECEIPT_ID);
  assert.deepEqual(evidence.runtime_policy, {
    backend: false,
    cli: false,
    gateway: false,
    runtime: false,
    tools: false,
    profile_preserved: true,
  });
  assert.match(evidence.app_asar_sha256, /^[a-f0-9]{64}$/);
  assert.match(evidence.updater_config_sha256, /^[a-f0-9]{64}$/);
  assert.match(evidence.evidence_id, /^[a-f0-9]{64}$/);
});

test("recovery verifier rejects extra desktop runtime and forbidden agent modules", () => {
  assert.throws(
    () => assertRecoveryAsarEntries([
      "/package.json",
      ...RECOVERY_SOURCE_FILES.map((name) => `/${name}`),
      "/src/backend-runner.js",
    ]),
    /forbidden desktop runtime module/,
  );
  assert.throws(
    () => assertRecoveryAsarEntries([
      "/package.json",
      ...RECOVERY_SOURCE_FILES.map((name) => `/${name}`),
      "/node_modules/node-pty/index.js",
    ]),
    /forbidden agent\/tool module/,
  );
});

test("recovery verifier rejects forbidden top-level packaged resources", async (t) => {
  const fixture = await recoveryBundleFixture(t);
  fs.mkdirSync(path.join(fixture.resourcesPath, "cli"));
  assert.throws(
    () => verifyRecoveryBundle({
      appPath: fixture.appPath,
      architecture: "x64",
      sourceReceiptId: SOURCE_RECEIPT_ID,
      readPlist: fixture.readPlist,
    }),
    /forbidden packaged recovery resource: cli/,
  );
});

test("recovery provenance must match the exact Beta 1.2.83 source receipt", () => {
  let inputs = null;
  const receipt = verifyRecoverySourceProvenance({
    sourceReceiptId: SOURCE_RECEIPT_ID,
    receiptPath: "/fixture/candidate-source.json",
    verify: (value) => {
      inputs = value;
      return { source_receipt_id: SOURCE_RECEIPT_ID };
    },
  });
  assert.equal(receipt.source_receipt_id, SOURCE_RECEIPT_ID);
  assert.equal(inputs.channel, "beta");
  assert.equal(inputs.version, "1.2.83");
  assert.equal(inputs.receiptPath, "/fixture/candidate-source.json");
  assert.throws(
    () => verifyRecoverySourceProvenance({
      sourceReceiptId: SOURCE_RECEIPT_ID,
      verify: () => ({ source_receipt_id: "b".repeat(64) }),
    }),
    /does not match recovery build provenance/,
  );
});

test("recovery pre-sign evidence is immutable", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-recovery-evidence-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const output = path.join(root, "pre-sign-recovery-arm64.json");
  const evidence = { kind: "recovery", evidence_id: "a".repeat(64) };
  writeImmutableEvidence(output, evidence);
  writeImmutableEvidence(output, evidence);
  assert.throws(
    () => writeImmutableEvidence(output, { ...evidence, evidence_id: "b".repeat(64) }),
    /refusing to replace mismatched/,
  );
});

test("recovery afterPack aborts before packaging work when provenance is absent", async () => {
  const previous = process.env.ELEVATE_RECOVERY_SOURCE_RECEIPT_ID;
  delete process.env.ELEVATE_RECOVERY_SOURCE_RECEIPT_ID;
  try {
    await assert.rejects(
      afterPackRecoveryMac({ electronPlatformName: "darwin", arch: "arm64", appOutDir: "/tmp" }),
      /ELEVATE_RECOVERY_SOURCE_RECEIPT_ID/,
    );
  } finally {
    if (previous === undefined) delete process.env.ELEVATE_RECOVERY_SOURCE_RECEIPT_ID;
    else process.env.ELEVATE_RECOVERY_SOURCE_RECEIPT_ID = previous;
  }
});
