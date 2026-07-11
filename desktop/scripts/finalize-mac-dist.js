#!/usr/bin/env node
// Finalize macOS distribution artifacts after electron-builder:
//   - sign DMG containers
//   - notarize and staple DMG tickets
//   - refresh latest-mac.yml hashes/sizes after stapling changes DMG bytes

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const yaml = require("js-yaml");
const { releaseArtifactNames, resolveReleaseProfile } = require("../src/release-profile");
const {
  CANDIDATE_RECEIPT,
  assertTrustedSignerEvidence,
  createFinalReceipt,
  fetchPublicFeeds,
  verifySourceReceipt,
} = require("./candidate-receipt");

const ROOT = path.resolve(__dirname, "..");
const DIST = path.join(ROOT, "dist");
const RELEASE_CHANNEL = (process.env.ELEVATE_RELEASE_CHANNEL || "latest").trim().toLowerCase();
if (!["latest", "beta"].includes(RELEASE_CHANNEL)) {
  throw new Error(`[finalize] unsupported release channel: ${RELEASE_CHANNEL}`);
}
const FEED_NAME = `${RELEASE_CHANNEL}-mac.yml`;
const FEED = path.join(DIST, FEED_NAME);
const packageJson = require(path.join(ROOT, "package.json"));
const APP_BUNDLE_NAME = resolveReleaseProfile(RELEASE_CHANNEL).appBundleName;

function runEvidence(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    encoding: "utf8",
    timeout: 900_000,
    ...options,
  });
  const stdout = (result.stdout || "").trim().replaceAll(ROOT, "<desktop>");
  const stderr = (result.stderr || "").trim().replaceAll(ROOT, "<desktop>");
  const combined = `${stdout}\n${stderr}`.trim();
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed with exit ${result.status}${combined ? `: ${combined}` : ""}`);
  }
  return {
    ok: true,
    status: result.status,
    stdout,
    stderr,
    output: combined,
    output_sha256: crypto.createHash("sha256").update(combined).digest("hex"),
  };
}

function output(command, args) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    encoding: "utf8",
  });
  if (result.status !== 0) return "";
  return result.stdout || "";
}

function resolveIdentity() {
  if (process.env.CODESIGN_IDENTITY) return process.env.CODESIGN_IDENTITY;
  const cscName = (process.env.CSC_NAME || "").trim();
  if (cscName) {
    if (cscName.startsWith("Developer ID Application:")) return cscName;
    return `Developer ID Application: ${cscName}`;
  }

  const identities = output("security", ["find-identity", "-v", "-p", "codesigning"]);
  const match = identities.match(/"([^"]*Developer ID Application:[^"]+)"/);
  if (match) return match[1];
  throw new Error("No Developer ID Application identity found. Set CODESIGN_IDENTITY or CSC_NAME.");
}

function artifactPath(fileName) {
  return path.join(DIST, fileName);
}

function refreshFeedHashes() {
  const feed = yaml.load(fs.readFileSync(FEED, "utf8"));
  for (const file of feed.files || []) {
    const filePath = artifactPath(file.url);
    const bytes = fs.readFileSync(filePath);
    file.sha512 = crypto.createHash("sha512").update(bytes).digest("base64");
    file.size = bytes.length;
    if (feed.path === file.url) {
      feed.sha512 = file.sha512;
    }
  }
  fs.writeFileSync(FEED, yaml.dump(feed, { lineWidth: -1, noRefs: true }));
  console.log(`[finalize] refreshed hashes in ${path.relative(ROOT, FEED)}`);
}

if (!fs.existsSync(FEED)) {
  throw new Error(`[finalize] missing ${FEED}; run electron-builder first`);
}
if (fs.existsSync(CANDIDATE_RECEIPT)) {
  throw new Error("[finalize] immutable candidate-receipt.json already exists; use a new version/candidate");
}

const identity = resolveIdentity();
const profile = process.env.APPLE_KEYCHAIN_PROFILE || "elevate-notarization";
const version = packageJson.version;
verifySourceReceipt({ channel: RELEASE_CHANNEL, version });
const feed = yaml.load(fs.readFileSync(FEED, "utf8"));
const feedUrls = new Set((feed.files || []).map((file) => file.url).filter(Boolean));
const required = releaseArtifactNames(resolveReleaseProfile(RELEASE_CHANNEL), version);
for (const name of required) {
  if (!feedUrls.has(name)) {
    throw new Error(`[finalize] latest-mac.yml missing ${name}`);
  }
  if (!fs.existsSync(artifactPath(name))) {
    throw new Error(`[finalize] missing ${artifactPath(name)}`);
  }
}

// D5: a packaged app MUST carry app-update.yml in Resources, or every client
// shows a permanent "update metadata is not bundled" state. Catch it here at
// build time instead of on the customer's machine.
for (const appDir of ["mac", "mac-arm64"]) {
  const appPath = path.join(DIST, appDir, APP_BUNDLE_NAME);
  const updateYml = path.join(appPath, "Contents", "Resources", "app-update.yml");
  if (fs.existsSync(appPath) && !fs.existsSync(updateYml)) {
    throw new Error(
      `[finalize] ${appDir}/${APP_BUNDLE_NAME} missing Contents/Resources/app-update.yml — the auto-updater would break for every client`,
    );
  }
}

const dmgs = required.filter((name) => name.endsWith(".dmg"));
const dmgEvidence = {};
console.log(`[finalize] signing/notarizing ${dmgs.length} DMG artifact(s) as ${identity}`);
for (const dmg of dmgs) {
  const filePath = artifactPath(dmg);
  if (!fs.existsSync(filePath)) {
    throw new Error(`[finalize] missing ${filePath}`);
  }
  const arch = dmg.includes("-arm64.") ? "arm64" : "x64";
  const sign = runEvidence("codesign", ["--force", "--sign", identity, "--timestamp", filePath]);
  const codesign = runEvidence("codesign", ["--verify", "--verbose=2", filePath]);
  const codesignDetails = runEvidence("codesign", ["-d", "--verbose=4", filePath]);
  const designatedRequirement = runEvidence("codesign", ["-d", "-r-", filePath]);
  assertTrustedSignerEvidence(codesignDetails.output, designatedRequirement.output, dmg);
  const notary = runEvidence("xcrun", [
    "notarytool", "submit", filePath, "--keychain-profile", profile, "--wait", "--output-format", "json",
  ]);
  let notaryResult = {};
  try {
    notaryResult = JSON.parse(notary.stdout);
  } catch {
    notaryResult = { parse_error: true };
  }
  if (!notaryResult.id || String(notaryResult.status || "").toLowerCase() !== "accepted") {
    throw new Error(`[finalize] notarization did not return an accepted submission for ${dmg}`);
  }
  const staple = runEvidence("xcrun", ["stapler", "staple", filePath]);
  const stapleValidation = runEvidence("xcrun", ["stapler", "validate", filePath]);
  const gatekeeper = runEvidence("spctl", ["-a", "-vv", "--type", "open", "--context", "context:primary-signature", filePath]);
  dmgEvidence[arch] = {
    artifact: dmg,
    sign,
    codesign,
    codesign_details: codesignDetails,
    designated_requirement: designatedRequirement,
    notary: {
      ...notary,
      submission_id: notaryResult.id || null,
      submission_status: notaryResult.status || null,
    },
    staple,
    staple_validation: stapleValidation,
    gatekeeper,
  };
}

refreshFeedHashes();
verifySourceReceipt({ channel: RELEASE_CHANNEL, version });
const candidate = createFinalReceipt({
  publicFeeds: fetchPublicFeeds(),
  dmgEvidence,
});
console.log(`[finalize] immutable candidate receipt ${candidate.candidate_id}`);
console.log("[finalize] macOS artifacts are signed, notarized, stapled, and feed-synced");
