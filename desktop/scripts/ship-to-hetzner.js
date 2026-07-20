#!/usr/bin/env node
// Push electron-builder artifacts to the Hetzner ctrl-flow box so
// electron-updater (generic provider) can pull them from
// https://api.elevationrealestatehq.com/updates/
//
// Flow:
//   1. `npm run release:mac` builds/finalizes/static-smokes a candidate
//   2. `npm run smoke:mac:live` proves the installed candidate through real AI
//   3. `npm run ship:mac` stages the exact candidate under a global publish lock
//   4. Verify and archive public bytes before declaring the release live.
//
// Requirements:
//   - SSH key auth set up for root@5.78.46.234
//   - rsync installed locally (default on macOS)

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");
const yaml = require("js-yaml");
const { artifactFileName } = require("../src/release-profile");
const {
  assertFileRecord,
  assertGloballyNewVersion,
  assertPublicFeedsUnchanged,
  archiveSuccessfulRelease,
  buildRemotePublishTransaction,
  classifyPublicCandidateFeeds,
  fetchPublicFeeds,
  realtorBetaRetainedRecoveryFeedName,
  resolveReleaseCandidateForShip,
  ROLLBACK_FREEZE_FILE,
  sha256File,
  validateFeed,
  verifyCandidateReceipt,
  writeAtomicJson,
} = require("./candidate-receipt");

const DIST = path.resolve(__dirname, "..", "dist");
const REPO = path.resolve(DIST, "..", "..");
const CANDIDATE_RECEIPT_PATH = path.join(DIST, "candidate-receipt.json");
const PACKAGE_VERSION = require("../package.json").version;
const requestedChannel = (process.env.ELEVATE_RELEASE_CHANNEL || "latest").trim().toLowerCase();
if (!new Set(["latest", "beta"]).has(requestedChannel)) {
  throw new Error(`[ship] unsupported requested channel ${requestedChannel || "<empty>"}`);
}
let resolvedCandidate;
try {
  resolvedCandidate = resolveReleaseCandidateForShip({
    distRoot: DIST,
    channel: requestedChannel,
    version: PACKAGE_VERSION,
    verifyActiveCandidate: () => verifyCandidateReceipt({ requireApps: true, requireEvidence: true }),
  });
} catch (candidateError) {
  throw new Error(`[ship] no exact releasable candidate was accepted: ${candidateError.message}`);
}
const { candidate, archiveRecovery } = resolvedCandidate;
const RELEASE_CHANNEL = candidate.release.channel;
if (requestedChannel !== RELEASE_CHANNEL) {
  throw new Error(`[ship] requested channel ${requestedChannel} does not match candidate ${RELEASE_CHANNEL}`);
}
const FEED_NAME = `${RELEASE_CHANNEL}-mac.yml`;
const FEED = path.join(DIST, FEED_NAME);
const PKG_VERSION = candidate.release.version;
if (PKG_VERSION !== PACKAGE_VERSION) {
  throw new Error(`[ship] candidate/archive version ${PKG_VERSION} does not match package ${PACKAGE_VERSION}`);
}
const CANDIDATE_RECEIPT_SHA256 = archiveRecovery
  ? archiveRecovery.archive.files["candidate-receipt.json"].sha256
  : sha256File(CANDIDATE_RECEIPT_PATH);
const HOST = "root@5.78.46.234";
const REMOTE = "/var/www/elevate-updates/";
const PUBLIC_URL = "https://api.elevationrealestatehq.com/updates";
const GLOBAL_RELEASE_LOCK = "/var/lock/elevate-release-publish.lock";
const SSH_OPTIONS = [
  "-o", "BatchMode=yes",
  "-o", "ConnectTimeout=20",
  "-o", "ServerAliveInterval=15",
  "-o", "ServerAliveCountMax=4",
];
const REMOTE_COMMAND_TIMEOUT_MS = 20 * 60 * 1000;
const UPLOAD_TIMEOUT_MS = 2 * 60 * 60 * 1000;
const RSYNC_SSH_COMMAND = "ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4";

function sshCommand(command, options = {}) {
  return spawnSync("ssh", [...SSH_OPTIONS, HOST, command], {
    timeout: REMOTE_COMMAND_TIMEOUT_MS,
    ...options,
  });
}

function assertShipFeedState(currentFeeds, context) {
  const state = classifyPublicCandidateFeeds(candidate, currentFeeds, context);
  if (state === "old") {
    assertGloballyNewVersion(PKG_VERSION, currentFeeds);
    assertPublicFeedsUnchanged(candidate.public_feeds_at_finalize, currentFeeds, context);
  } else {
    console.log(`[ship] ${FEED_NAME} is already the exact candidate; resuming immutable publication proof`);
  }
  return state;
}

function curl(args, label) {
  const result = spawnSync(
    "curl",
    ["--fail", "--silent", "--show-error", "--location", "--retry", "5", "--retry-delay", "2", "--header", "Cache-Control: no-cache", ...args],
    { encoding: "utf8" },
  );
  if (result.status !== 0) {
    const error = (result.stderr || result.stdout || "").trim();
    throw new Error(`${label} failed${error ? `: ${error}` : ""}`);
  }
  return result.stdout || "";
}

function verifyRemoteFile(name, expected) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-public-readback-"));
  const destination = path.join(tempDir, path.basename(name));
  try {
    const result = spawnSync(
      "curl",
      ["--fail", "--silent", "--show-error", "--location", "--retry", "5", "--retry-delay", "2", "--header", "Cache-Control: no-cache", "--output", destination, `${PUBLIC_URL}/${name}`],
      { encoding: "utf8", timeout: 30 * 60 * 1000 },
    );
    if (result.status !== 0) {
      throw new Error(`[ship] public read-back failed for ${name}: ${(result.stderr || result.stdout || "").trim()}`);
    }
    assertFileRecord(destination, expected, `public ${name}`);
    return { url: `${PUBLIC_URL}/${name}`, size: expected.size, sha256: expected.sha256 };
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

function verifyPublicRelease(expectedVersion) {
  console.log("[ship] verifying public feed and artifacts");
  const remoteText = curl([`${PUBLIC_URL}/${FEED_NAME}`], `fetch public ${FEED_NAME}`);
  const remoteFeedHash = crypto.createHash("sha256").update(remoteText).digest("hex");
  if (remoteFeedHash !== candidate.artifacts[FEED_NAME]?.sha256) {
    throw new Error(`[ship] public ${FEED_NAME} SHA256 does not match the finalized candidate`);
  }
  const remoteFeed = yaml.load(remoteText);
  if (remoteFeed.version !== expectedVersion) {
    throw new Error(`[ship] public feed version ${remoteFeed.version || "missing"} != ${expectedVersion}`);
  }
  validateFeed(remoteFeed, candidate.release, candidate.artifacts);

  const artifacts = {};
  for (const file of remoteFeed.files || []) {
    if (!file.url) continue;
    const expected = candidate.artifacts[file.url];
    if (!expected) throw new Error(`[ship] candidate receipt is missing ${file.url}`);
    artifacts[file.url] = verifyRemoteFile(file.url, expected);
  }

  const aliases = {};
  for (const alias of candidate.release.download_aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    const src = artifactFileName(candidate.release.profile, expectedVersion, arch, "dmg");
    const expected = candidate.artifacts[src];
    if (!expected) throw new Error(`[ship] candidate receipt is missing alias source ${src}`);
    aliases[alias] = verifyRemoteFile(alias, expected);
  }
  const recoveryArtifacts = {};
  if (candidate.recovery) {
    for (const name of candidate.recovery.artifact_names) {
      recoveryArtifacts[name] = verifyRemoteFile(name, candidate.recovery.artifacts[name]);
    }
    console.log(`[ship] verified ${Object.keys(recoveryArtifacts).length} public recovery ${candidate.recovery.version} artifacts`);
  }
  console.log(`[ship] verified public ${expectedVersion} feed and artifacts`);
  return {
    schema_version: 1,
    kind: "elevate-public-readback",
    candidate_id: candidate.candidate_id,
    source_receipt_id: candidate.source_receipt_id,
    candidate_receipt_sha256: CANDIDATE_RECEIPT_SHA256,
    channel: RELEASE_CHANNEL,
    version: expectedVersion,
    verified_at: new Date().toISOString(),
    feed: {
      url: `${PUBLIC_URL}/${FEED_NAME}`,
      size: Buffer.byteLength(remoteText),
      sha256: remoteFeedHash,
    },
    artifacts,
    aliases,
    ...(candidate.recovery ? {
      recovery: {
        version: candidate.recovery.version,
        retained_feed_name: realtorBetaRetainedRecoveryFeedName(candidate.recovery.version, FEED_NAME),
        retained_feed_sha256: candidate.recovery.local_feed.sha256,
        artifacts: recoveryArtifacts,
      },
    } : {}),
  };
}

function hashFile(filePath) {
  return crypto.createHash("sha512").update(fs.readFileSync(filePath)).digest("base64");
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'\\''`)}'`;
}

function verifyLocalRelease(feed, expectedVersion) {
  validateFeed(feed, candidate.release, candidate.artifacts);
  if (feed.version !== expectedVersion) {
    throw new Error(`[ship] local feed version ${feed.version || "missing"} != ${expectedVersion}`);
  }
  const files = new Map((feed.files || []).map((file) => [file.url, file]));
  for (const name of candidate.release.artifact_names) {
    const file = files.get(name);
    if (!file) throw new Error(`[ship] local feed missing ${name}`);
    const filePath = path.join(DIST, name);
    if (!fs.existsSync(filePath)) throw new Error(`[ship] missing ${filePath}`);
    const size = fs.statSync(filePath).size;
    if (Number(file.size || 0) !== size) {
      throw new Error(`[ship] local feed size mismatch for ${name}`);
    }
    if (file.sha512 !== hashFile(filePath)) {
      throw new Error(`[ship] local feed sha512 mismatch for ${name}`);
    }
  }
}

function verifyLocalRecovery() {
  if (!candidate.recovery) return [];
  const staged = [];
  for (const name of candidate.recovery.artifact_names) {
    const record = candidate.recovery.artifacts[name];
    const filePath = path.join(REPO, record.path);
    assertFileRecord(filePath, record, `local recovery ${name}`);
    staged.push(filePath);
  }
  const feedRecord = candidate.recovery.local_feed;
  const feedPath = path.join(REPO, feedRecord.path);
  assertFileRecord(feedPath, feedRecord, "local recovery feed");
  // The recovery feed shares the candidate feed's basename, so stage it under
  // the transaction's expected staged name via a temp copy.
  const stagedFeedDir = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-recovery-stage-"));
  process.on("exit", () => fs.rmSync(stagedFeedDir, { recursive: true, force: true }));
  const stagedFeedPath = path.join(stagedFeedDir, `recovery-${FEED_NAME}`);
  fs.copyFileSync(feedPath, stagedFeedPath);
  staged.push(stagedFeedPath);
  return staged;
}

function cleanupUnpackedBundles() {
  for (const sub of ["mac", "mac-arm64"]) {
    const dir = path.join(DIST, sub);
    if (fs.existsSync(dir)) {
      fs.rmSync(dir, { recursive: true, force: true });
      console.log(`[ship] cleaned unpacked bundle dist/${sub}/ (no Spotlight ghost)`);
    }
  }
}

if (archiveRecovery) {
  try {
    // A deterministic local archive is necessary but not sufficient: prove the
    // public feed, every updater artifact, and every alias still match its exact
    // completion evidence before adopting cleanup from a crashed ship process.
    verifyPublicRelease(PKG_VERSION);
    const adopted = archiveSuccessfulRelease({ candidate, distRoot: DIST, repoRoot: REPO });
    if (!adopted.adopted || adopted.archive.archive_id !== archiveRecovery.archive.archive_id) {
      throw new Error("[ship] exact successful release archive adoption changed identity");
    }
    console.log(`[ship] recovered exact completed publication proof at ${adopted.archivePath}`);
    cleanupUnpackedBundles();
    console.log(`\n[ship] live at ${PUBLIC_URL}/`);
    process.exit(0);
  } catch (error) {
    console.error(`[ship] archived publication recovery failed closed: ${error?.message || String(error)}`);
    process.exit(1);
  }
}

if (!fs.existsSync(DIST)) {
  console.error(`[ship] no dist/ folder at ${DIST} — did the build run?`);
  process.exit(1);
}

if (!fs.existsSync(FEED)) {
  console.error(`[ship] no ${FEED_NAME} at ${FEED} — did the build run?`);
  process.exit(1);
}

// electron-builder emits latest-mac.yml (the feed file electron-updater polls).
// Ship exactly the files referenced by the feed, plus matching blockmaps when
// present, so stale artifacts in dist/ never leak into the update directory.
const feed = yaml.load(fs.readFileSync(FEED, "utf8"));
let recoveryStagedPaths = [];
try {
  const currentFeeds = fetchPublicFeeds();
  assertShipFeedState(currentFeeds, "ship preflight");
  verifyLocalRelease(feed, PKG_VERSION);
  recoveryStagedPaths = verifyLocalRecovery();
} catch (err) {
  console.error(err && err.message ? err.message : String(err));
  process.exit(1);
}

// Intentionally do not ship blockmaps: older clients must fall back to the
// pristine full ZIP instead of reconstructing a signed bundle differentially.
const selected = new Set(candidate.release.artifact_names);

const matches = Array.from(selected)
  .filter((name) => fs.existsSync(path.join(DIST, name)));

if (matches.length === 0) {
  console.error(`[ship] no matching artifacts in ${DIST}`);
  process.exit(1);
}

const stagingName = `.candidate-${candidate.candidate_id}-${crypto.randomUUID()}`;
const stagingPath = `${REMOTE}${stagingName}/`;
const createStage = sshCommand(
  `mkdir --mode=0700 -- ${shellQuote(stagingPath)}`,
  { stdio: "inherit" },
);
if (createStage.status !== 0) {
  console.error("[ship] could not create unique remote candidate staging directory");
  process.exit(createStage.status || 1);
}

console.log(`[ship] staging ${matches.length} artifact files, feed${recoveryStagedPaths.length ? `, and ${recoveryStagedPaths.length} recovery retention files` : ""} at ${HOST}:${stagingPath}`);
for (const name of matches) {
  const size = (fs.statSync(path.join(DIST, name)).size / (1024 * 1024)).toFixed(1);
  console.log(`  - ${name} (${size} MB)`);
}
for (const filePath of recoveryStagedPaths) {
  const size = (fs.statSync(filePath).size / (1024 * 1024)).toFixed(1);
  console.log(`  - ${path.basename(filePath)} (${size} MB, recovery retention)`);
}

// Nothing is uploaded to a public final name before the locked transaction.
const args = [
  "-avh",
  "--progress",
  "-e",
  RSYNC_SSH_COMMAND,
  ...[...matches, FEED_NAME].map((name) => path.join(DIST, name)),
  ...recoveryStagedPaths,
  `${HOST}:${stagingPath}`,
];

const result = spawnSync("rsync", args, { stdio: "inherit", timeout: UPLOAD_TIMEOUT_MS });

if (result.status !== 0) {
  sshCommand(`rm -rf -- ${shellQuote(stagingPath)}`, { stdio: "inherit" });
  console.error(`[ship] rsync failed with exit ${result.status}`);
  process.exit(result.status || 1);
}

// Recheck immediately before publication. The transaction repeats this CAS
// under one global Stable+Beta lock before touching any public release path.
try {
  const currentFeeds = fetchPublicFeeds();
  assertShipFeedState(currentFeeds, "feed publication; rebuild for a truthful rollback target");
} catch (err) {
  sshCommand(`rm -rf -- ${shellQuote(stagingPath)}`, { stdio: "inherit" });
  console.error(err && err.message ? err.message : String(err));
  process.exit(1);
}
const publishFeed = sshCommand(
  buildRemotePublishTransaction({ candidate, remote: REMOTE, stagingName }),
  { encoding: "utf8", maxBuffer: 4 * 1024 * 1024 },
);
if (publishFeed.stdout) process.stdout.write(publishFeed.stdout);
if (publishFeed.stderr) process.stderr.write(publishFeed.stderr);
const completionMarkers = (publishFeed.stdout || "").match(
  /^REMOTE_PUBLISH_OK state=(committed|recovered_committed|already_committed)$/gm,
) || [];
if (publishFeed.status !== 0 || publishFeed.error || completionMarkers.length !== 1) {
  const reason = publishFeed.error?.message
    || (publishFeed.signal ? `terminated by ${publishFeed.signal}` : `exit ${publishFeed.status}`);
  console.error(`[ship] locked publication did not return one validated completion marker (${reason}); rerun this exact candidate to resume safely`);
  process.exit(publishFeed.status || 1);
}
const publishState = completionMarkers[0].slice("REMOTE_PUBLISH_OK state=".length);
console.log(`[ship] ${publishState}: verified artifacts, ${candidate.release.download_aliases.length} alias(es), and ${FEED_NAME} under global release lock`);

const publicReadbackPath = path.join(DIST, "evidence", "public-readback.json");
try {
  const publicReadback = verifyPublicRelease(PKG_VERSION);
  writeAtomicJson(publicReadbackPath, publicReadback);
} catch (err) {
  console.error(err && err.message ? err.message : String(err));
  process.exit(1);
}

// Prune only after the new feed and its public bytes are proven. Before this
// point a feed-aware pruner still sees the old release and can delete the newly
// uploaded candidate. Beta never invokes the Stable retention policy.
let pruneStatus = null;
if (RELEASE_CHANNEL === "latest") {
  const pruneInner = [
    "set -euo pipefail",
    `if test -e ${shellQuote(`${REMOTE}${ROLLBACK_FREEZE_FILE}`)} || test -L ${shellQuote(`${REMOTE}${ROLLBACK_FREEZE_FILE}`)}; then`,
    "  echo 'prune-elevate-updates: skipped while the Realtor Beta rollback release freeze is active'",
    "  exit 0",
    "fi",
    `if test -f ${shellQuote(`${REMOTE}beta-mac.yml`)}; then`,
    "  echo 'prune-elevate-updates: skipped while the Beta feed is retained'",
    "  exit 0",
    "fi",
    "exec bash /root/prune-elevate-updates.sh",
  ].join("\n");
  const pruneCommand = `flock -x -w 300 ${shellQuote(GLOBAL_RELEASE_LOCK)} bash -c ${shellQuote(pruneInner)}`;
  const prune = sshCommand(pruneCommand, { stdio: "inherit" });
  pruneStatus = prune.status;
  if (prune.status !== 0) console.warn("[ship] artifact prune exited non-zero — disk may be growing");
} else {
  console.log("[ship] skipped stable artifact pruning for beta channel");
}

const shipRecordPath = path.join(DIST, "evidence", "ship.json");
fs.mkdirSync(path.dirname(shipRecordPath), { recursive: true });
const liveAiPath = path.join(REPO, candidate.required_evidence.live_ai);
writeAtomicJson(shipRecordPath, {
  schema_version: 1,
  kind: "elevate-ship-record",
  candidate_id: candidate.candidate_id,
  source_receipt_id: candidate.source_receipt_id,
  candidate_receipt_sha256: CANDIDATE_RECEIPT_SHA256,
  channel: RELEASE_CHANNEL,
  version: PKG_VERSION,
  shipped_at: new Date().toISOString(),
  remote_publish_state: publishState,
  rollback_target: candidate.rollback_target,
  public_feed: `${PUBLIC_URL}/${FEED_NAME}`,
  public_artifacts: Object.fromEntries(matches.map((name) => [name, candidate.artifacts[name]])),
  ...(candidate.recovery ? {
    recovery_retention: {
      version: candidate.recovery.version,
      retained_feed_name: realtorBetaRetainedRecoveryFeedName(candidate.recovery.version, FEED_NAME),
      retained_feed_sha256: candidate.recovery.local_feed.sha256,
      public_artifacts: Object.fromEntries(candidate.recovery.artifact_names.map((name) => [name, candidate.recovery.artifacts[name]])),
    },
  } : {}),
  live_ai_evidence_sha256: sha256File(liveAiPath),
  public_readback_sha256: sha256File(publicReadbackPath),
  stable_pruner_status: pruneStatus,
});

const archived = archiveSuccessfulRelease({
  candidate,
  distRoot: DIST,
  repoRoot: REPO,
  publicReadbackPath,
  shipRecordPath,
});
console.log(`[ship] archived immutable release proof at ${archived.archivePath}`);

console.log(`\n[ship] live at ${PUBLIC_URL}/`);
console.log("[ship] running apps poll every ~3min (and on window focus), so it lands within minutes.");

// Cleanup: electron-builder leaves unpacked .app bundles in dist/mac and
// dist/mac-arm64. macOS Spotlight indexes those as standalone "Elevate" apps,
// which then clutter the launcher as ghost duplicates of the real install.
// The shippable artifacts (zip/dmg/yml) are already on Hetzner, so drop the
// unpacked bundles after every successful ship. Keep the dmg/zip as a local
// release archive.
cleanupUnpackedBundles();
