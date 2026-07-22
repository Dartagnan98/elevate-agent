"use strict";

const packageJson = require("./package.json");
const { BETA } = require("./src/release-profile");

const CANDIDATE_VERSION = "1.2.81";
const RECOVERY_VERSION = "1.2.82";
const RECOVERY_ARTIFACT_PREFIX = "Elevate-Beta-Recovery";
const RECOVERY_OUTPUT_DIRECTORY = "dist/recovery";
const UPDATE_BASE_URL = "https://api.elevationrealestatehq.com/updates";

const RECOVERY_SOURCE_FILES = Object.freeze([
  "src/recovery-main.js",
  "src/recovery-preload.js",
  "src/recovery.html",
  "src/recovery-containment.js",
  "src/release-profile.js",
  "src/updater.js",
]);

function parseVersion(value, label) {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(String(value || ""));
  if (!match) throw new Error(`[recovery-build] ${label} must be an exact three-part version`);
  return match.slice(1).map(Number);
}

function compareVersions(left, right) {
  const a = parseVersion(left, "recovery version");
  const b = parseVersion(right, "candidate version");
  for (let index = 0; index < a.length; index += 1) {
    if (a[index] !== b[index]) return a[index] > b[index] ? 1 : -1;
  }
  return 0;
}

function requireSourceReceiptId(env) {
  const value = String(env.ELEVATE_RECOVERY_SOURCE_RECEIPT_ID || "").trim();
  if (!/^[a-f0-9]{64}$/.test(value)) {
    throw new Error(
      "[recovery-build] ELEVATE_RECOVERY_SOURCE_RECEIPT_ID must be the exact 64-character candidate source receipt ID",
    );
  }
  return value;
}

function createRecoveryBuilderConfig({ env = process.env, manifest = packageJson } = {}) {
  if (manifest.version !== CANDIDATE_VERSION) {
    throw new Error(
      `[recovery-build] recovery ${RECOVERY_VERSION} is bound to candidate ${CANDIDATE_VERSION}; `
      + `package version is ${manifest.version || "<missing>"}`,
    );
  }
  if (compareVersions(RECOVERY_VERSION, manifest.version) <= 0) {
    throw new Error("[recovery-build] recovery version must be newer than the bound candidate");
  }
  const sourceReceiptId = requireSourceReceiptId(env);

  return {
    appId: BETA.appId,
    productName: BETA.productName,
    asar: true,
    asarUnpack: [],
    afterPack: "scripts/after-pack-recovery-mac.js",
    artifactName: `${RECOVERY_ARTIFACT_PREFIX}-\${version}-mac-\${arch}.\${ext}`,
    directories: {
      output: RECOVERY_OUTPUT_DIRECTORY,
      buildResources: "assets",
    },
    files: [
      "package.json",
      ...RECOVERY_SOURCE_FILES,
    ],
    extraResources: [],
    extraMetadata: {
      name: BETA.packageName,
      version: RECOVERY_VERSION,
      main: "src/recovery-main.js",
      elevateReleaseChannel: "beta",
      elevateRecoveryMode: true,
      elevateRecoveryCandidateVersion: CANDIDATE_VERSION,
      elevateRecoverySourceReceiptId: sourceReceiptId,
    },
    protocols: [{ name: BETA.productName, schemes: [BETA.protocolScheme] }],
    publish: [{
      provider: "generic",
      url: UPDATE_BASE_URL,
      channel: "beta",
    }],
    mac: {
      category: "public.app-category.productivity",
      icon: "assets/icon.icns",
      hardenedRuntime: true,
      gatekeeperAssess: false,
      entitlements: "entitlements.mac.plist",
      entitlementsInherit: "entitlements.mac.plist",
      notarize: true,
      extendInfo: {
        LSMinimumSystemVersion: "12.0",
        NSHumanReadableCopyright: "(c) 2026 Elevation Real Estate. All rights reserved.",
      },
      target: [
        { target: "dmg", arch: ["arm64", "x64"] },
        { target: "zip", arch: ["arm64", "x64"] },
      ],
    },
    dmg: { title: `${BETA.productName} Recovery` },
  };
}

module.exports = createRecoveryBuilderConfig;
module.exports.CANDIDATE_VERSION = CANDIDATE_VERSION;
module.exports.RECOVERY_ARTIFACT_PREFIX = RECOVERY_ARTIFACT_PREFIX;
module.exports.RECOVERY_OUTPUT_DIRECTORY = RECOVERY_OUTPUT_DIRECTORY;
module.exports.RECOVERY_SOURCE_FILES = RECOVERY_SOURCE_FILES;
module.exports.RECOVERY_VERSION = RECOVERY_VERSION;
module.exports.UPDATE_BASE_URL = UPDATE_BASE_URL;
module.exports.compareVersions = compareVersions;
module.exports.requireSourceReceiptId = requireSourceReceiptId;
