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

// Apple's timestamp, notary, and ticket services blip often enough that a single
// failure used to cost a full ~40 minute rebuild ("The timestamp service is not
// available." during codesign is the classic). Only failures that look like the
// service being unreachable are retried; anything that looks like a real
// rejection (invalid artifact, bad credentials, missing file) fails fast and
// loudly on the first attempt.
// Backoff ladder indexed by the attempt that just failed; the cap on attempts
// decides how much of it is used (3 attempts => waits of 5s then 15s).
const APPLE_RETRY_ATTEMPTS = 3;
const APPLE_RETRY_DELAYS_MS = [5_000, 15_000, 45_000];

// Checked first: if a failure matches here it is NEVER retried, even when the
// same text also carries network-shaped words.
const APPLE_HARD_FAILURE_PATTERNS = [
  /\bstatus:\s*"?(?:invalid|rejected)"?/i,
  /\binvalid\b/i,
  /\brejected\b/i,
  /\bunauthorized\b/i,
  /\bauthenticat(?:e|ion|ing)\b/i,
  /\bforbidden\b/i,
  /no such file or directory/i,
  /no identity found/i,
  /identity not found/i,
  /unable to (?:build|find) (?:the )?(?:certificate )?chain/i,
  /no Developer ID Application identity/i,
  /keychain profile[^\n]*(?:not found|does not exist)/i,
  /code object is not signed at all/i,
  /resource fork, Finder information, or similar detritus not allowed/i,
  /is not a (?:valid|disk image)/i,
  /unable to read/i,
  /malformed/i,
];

const APPLE_TRANSIENT_FAILURE_PATTERNS = [
  /timestamp service is not available/i,
  /timestamp[^\n]*(?:unavailable|unreachable)/i,
  /errSecTimestampServiceNotAvailable/i,
  /the network connection was lost/i,
  /network (?:error|failure|is down|is unreachable)/i,
  /could not connect to the server/i,
  /connection (?:reset|refused|was lost|timed out)/i,
  /a server with the specified hostname could not be found/i,
  /(?:request|operation)[^\n]*timed out/i,
  /temporarily unavailable/i,
  /(?:service|server) (?:is )?unavailable/i,
  /\bbad gateway\b/i,
  /\bgateway timeout\b/i,
  /internal server error/i,
  /too many requests/i,
  /http status code:\s*(?:408|429|5\d\d)\b/i,
  /try again later/i,
  /unable to (?:reach|contact)[^\n]*(?:apple|notary|server|service)/i,
];

function isTransientAppleFailure(message) {
  const text = String(message || "");
  if (!text) return false;
  if (APPLE_HARD_FAILURE_PATTERNS.some((pattern) => pattern.test(text))) return false;
  return APPLE_TRANSIENT_FAILURE_PATTERNS.some((pattern) => pattern.test(text));
}

function sleepSync(ms) {
  if (!(ms > 0)) return;
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function retryDelayMs(attempt, delays = APPLE_RETRY_DELAYS_MS) {
  if (!delays.length) return 0;
  return delays[Math.min(attempt, delays.length) - 1];
}

// Returns whatever the SUCCESSFUL attempt returned, so the recorded evidence
// always describes the attempt that actually produced the artifact.
function withAppleRetry(label, task, options = {}) {
  const {
    attempts = APPLE_RETRY_ATTEMPTS,
    delays = APPLE_RETRY_DELAYS_MS,
    sleep = sleepSync,
    logger = console,
  } = options;
  for (let attempt = 1; ; attempt += 1) {
    try {
      const result = task(attempt);
      if (attempt > 1) {
        logger.log(`[finalize] ${label} succeeded on attempt ${attempt}/${attempts}`);
      }
      return result;
    } catch (error) {
      const message = error?.message || String(error);
      if (!isTransientAppleFailure(message)) {
        logger.error(`[finalize] ${label} failed on attempt ${attempt}/${attempts} and is not retryable: ${message}`);
        throw error;
      }
      if (attempt >= attempts) {
        logger.error(`[finalize] ${label} still failing after ${attempts} attempt(s) against Apple services: ${message}`);
        throw error;
      }
      const delay = retryDelayMs(attempt, delays);
      logger.warn(
        `[finalize] ${label} attempt ${attempt}/${attempts} hit a transient Apple-service failure; retrying in ${Math.round(delay / 1000)}s: ${message}`,
      );
      sleep(delay);
    }
  }
}

function runAppleEvidence(label, command, args, options = {}, retryOptions = {}) {
  return withAppleRetry(label, () => runEvidence(command, args, options), retryOptions);
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

function finalize() {
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
    const sign = runAppleEvidence(`codesign ${dmg}`, "codesign", ["--force", "--sign", identity, "--timestamp", filePath]);
    const codesign = runEvidence("codesign", ["--verify", "--verbose=2", filePath]);
    const codesignDetails = runEvidence("codesign", ["-d", "--verbose=4", filePath]);
    const designatedRequirement = runEvidence("codesign", ["-d", "-r-", filePath]);
    assertTrustedSignerEvidence(codesignDetails.output, designatedRequirement.output, dmg);
    const notary = runAppleEvidence(`notarytool submit ${dmg}`, "xcrun", [
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
    const staple = runAppleEvidence(`stapler staple ${dmg}`, "xcrun", ["stapler", "staple", filePath]);
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
}

if (require.main === module) finalize();

module.exports = {
  APPLE_RETRY_ATTEMPTS,
  APPLE_RETRY_DELAYS_MS,
  default: finalize,
  isTransientAppleFailure,
  retryDelayMs,
  runAppleEvidence,
  runEvidence,
  withAppleRetry,
};
