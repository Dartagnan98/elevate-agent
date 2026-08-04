#!/usr/bin/env node
"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const yaml = require("js-yaml");
const {
  REALTOR_BETA_RECOVERY_PROCEDURE_ID,
  REALTOR_BETA_ROLLBACK_PROCEDURE_ID,
  ROLLBACK_FREEZE_FILE,
  compareSemver,
  realtorBetaRetainedRecoveryFeedName,
  realtorBetaRollbackClearedFile,
  realtorBetaRollbackFreezeBytes,
  realtorBetaRollbackFreezeRecord,
} = require("./candidate-receipt");

const MODES = new Set(["preflight", "dry-run", "execute"]);
const LANES = new Set(["rollback", "recover"]);
const DEFAULT_HOST = "root@5.78.46.234";
const DEFAULT_REMOTE_ROOT = "/var/www/elevate-updates/";
const DEFAULT_PUBLIC_URL = "https://api.elevationrealestatehq.com/updates";
const GLOBAL_LOCK = "/var/lock/elevate-release-publish.lock";
const EXPECTED_ROLLBACK_VERSION = "1.2.65";
const EXPECTED_RECOVERY_VERSION = "1.2.104";
const BETA_FEED = "beta-mac.yml";
const STABLE_FEED = "latest-mac.yml";
const EXPECTED_ALIASES = [
  "Elevate-Beta-mac-x64.dmg",
  "Elevate-beta-mac-x64.dmg",
  "Elevate-Beta-mac-arm64.dmg",
  "Elevate-beta-mac-arm64.dmg",
];
const SHA256_RE = /^[a-f0-9]{64}$/;

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function hashFile(filePath, algorithm = "sha256", encoding = "hex") {
  const hash = crypto.createHash(algorithm);
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  const fd = fs.openSync(filePath, "r");
  try {
    let bytes = 0;
    while ((bytes = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) {
      hash.update(buffer.subarray(0, bytes));
    }
  } finally {
    fs.closeSync(fd);
  }
  return hash.digest(encoding);
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]));
  }
  return value;
}

function canonicalJson(value) {
  return JSON.stringify(canonicalize(value));
}

function receiptId(value, key) {
  const body = { ...value };
  delete body[key];
  return sha256(canonicalJson(body));
}

function assertSha256(value, label) {
  if (!SHA256_RE.test(String(value || ""))) throw new Error(`[rollback] invalid ${label}`);
  return value;
}

function assertSafeBasename(value, label) {
  if (typeof value !== "string" || !value || path.posix.basename(value) !== value
      || value.includes("\\") || value.includes("?") || value.includes("#")
      || value === "." || value === "..") {
    throw new Error(`[rollback] unsafe ${label}: ${String(value)}`);
  }
  return value;
}

function sha512Hex(base64, label) {
  if (typeof base64 !== "string" || !base64) throw new Error(`[rollback] missing ${label} SHA512`);
  const bytes = Buffer.from(base64, "base64");
  if (bytes.length !== 64 || bytes.toString("base64") !== base64) {
    throw new Error(`[rollback] invalid ${label} SHA512`);
  }
  return bytes.toString("hex");
}

function normalizedFiles(value, label) {
  if (!Array.isArray(value) || value.length === 0) throw new Error(`[rollback] ${label} has no files`);
  const files = value.map((item, index) => {
    if (!item || typeof item !== "object") throw new Error(`[rollback] ${label} file ${index} is invalid`);
    const url = assertSafeBasename(item.url, `${label} file URL`);
    const size = Number(item.size);
    if (!Number.isSafeInteger(size) || size <= 0) throw new Error(`[rollback] invalid ${label} size for ${url}`);
    sha512Hex(item.sha512, `${label} ${url}`);
    return { url, size, sha512: item.sha512 };
  }).sort((left, right) => left.url.localeCompare(right.url, "en"));
  if (new Set(files.map((item) => item.url)).size !== files.length) {
    throw new Error(`[rollback] ${label} contains duplicate file URLs`);
  }
  return files;
}

function parseFeed(bytes, label) {
  let feed;
  try {
    feed = yaml.load(bytes.toString("utf8"));
  } catch (error) {
    throw new Error(`[rollback] ${label} is not valid YAML: ${error.message}`);
  }
  if (!feed || typeof feed !== "object" || Array.isArray(feed)) {
    throw new Error(`[rollback] ${label} is not a YAML mapping`);
  }
  return feed;
}

function assertFeedMatchesSnapshot(bytes, snapshot, label) {
  assertSha256(snapshot?.sha256, `${label} snapshot SHA256`);
  const actualHash = sha256(bytes);
  if (actualHash !== snapshot.sha256) throw new Error(`[rollback] ${label} SHA256 mismatch`);
  const feed = parseFeed(bytes, label);
  if (String(feed.version || "") !== String(snapshot.version || "")) {
    throw new Error(`[rollback] ${label} version mismatch`);
  }
  const actualFiles = normalizedFiles(feed.files, label);
  const expectedFiles = normalizedFiles(snapshot.files, `${label} receipt snapshot`);
  if (canonicalJson(actualFiles) !== canonicalJson(expectedFiles)) {
    throw new Error(`[rollback] ${label} metadata does not match the candidate receipt`);
  }
  const primary = expectedFiles.find((item) => item.url.endsWith("-mac-x64.zip"));
  if (!primary || feed.path !== primary.url || feed.sha512 !== primary.sha512) {
    throw new Error(`[rollback] ${label} primary updater path/sha512 mismatch`);
  }
  return { feed, sha256: actualHash, files: actualFiles };
}

function assertCandidateArtifactRecord(record, name) {
  if (!record || typeof record !== "object") throw new Error(`[rollback] missing failed artifact record: ${name}`);
  const size = Number(record.size);
  if (!Number.isSafeInteger(size) || size <= 0) throw new Error(`[rollback] invalid failed artifact size: ${name}`);
  assertSha256(record.sha256, `${name} SHA256`);
  sha512Hex(record.sha512, name);
  return { name, size, sha256: record.sha256, sha512: record.sha512 };
}

function assertFailedCandidateFeed(bytes, contract, label = "failed candidate Beta feed") {
  const actualHash = sha256(bytes);
  if (actualHash !== contract.expectedFailedFeedSha256) {
    throw new Error(`[rollback] ${label} SHA256 mismatch`);
  }
  const feed = parseFeed(bytes, label);
  if (String(feed.version || "") !== contract.failedVersion) {
    throw new Error(`[rollback] ${label} version mismatch`);
  }
  const actualFiles = normalizedFiles(feed.files, label);
  const expectedFiles = contract.failedFeedFiles;
  if (canonicalJson(actualFiles) !== canonicalJson(expectedFiles)) {
    throw new Error(`[rollback] ${label} metadata does not match the failed candidate receipt`);
  }
  const primary = expectedFiles.find((item) => item.url.endsWith("-mac-x64.zip"));
  if (!primary || feed.path !== primary.url || feed.sha512 !== primary.sha512) {
    throw new Error(`[rollback] ${label} primary updater path/sha512 mismatch`);
  }
  return { feed, sha256: actualHash, files: actualFiles };
}

function loadRollbackContract({
  candidateReceiptPath,
  expectedCandidateReceiptSha256,
  retainedFeedPath,
  expectedFailedFeedSha256,
}) {
  for (const [label, filePath] of [["candidate receipt", candidateReceiptPath], ["retained feed", retainedFeedPath]]) {
    if (!filePath) throw new Error(`[rollback] explicit ${label} path is required`);
    if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
      throw new Error(`[rollback] ${label} is missing: ${filePath}`);
    }
  }
  assertSha256(expectedCandidateReceiptSha256, "expected candidate receipt SHA256");
  assertSha256(expectedFailedFeedSha256, "expected failed-candidate feed SHA256");

  const receiptBytes = fs.readFileSync(candidateReceiptPath);
  const actualReceiptSha256 = sha256(receiptBytes);
  if (actualReceiptSha256 !== expectedCandidateReceiptSha256) {
    throw new Error("[rollback] candidate receipt SHA256 mismatch");
  }
  let receipt;
  try {
    receipt = JSON.parse(receiptBytes.toString("utf8"));
  } catch (error) {
    throw new Error(`[rollback] candidate receipt is not valid JSON: ${error.message}`);
  }
  if (receipt?.schema_version !== 2 || receipt?.kind !== "elevate-final-candidate"
      || receiptId(receipt, "candidate_id") !== receipt.candidate_id) {
    throw new Error("[rollback] invalid or forged final candidate receipt");
  }
  const release = receipt.release || {};
  if (release.channel !== "beta" || release.feed_name !== BETA_FEED
      || !/^\d+\.\d+\.\d+$/.test(String(release.version || ""))
      || release.version === EXPECTED_ROLLBACK_VERSION
      || release.profile?.channel !== "beta") {
    throw new Error("[rollback] receipt is not an exact Beta candidate");
  }
  assertSha256(receipt.source_receipt_id, "source receipt ID");
  const aliases = Array.isArray(release.download_aliases) ? [...release.download_aliases].sort() : [];
  if (canonicalJson(aliases) !== canonicalJson([...EXPECTED_ALIASES].sort())) {
    throw new Error("[rollback] candidate Beta alias contract mismatch");
  }
  const rollback = receipt.rollback_target;
  const snapshots = receipt.public_feeds_at_finalize;
  if (!rollback || !snapshots?.beta || !snapshots?.latest
      || canonicalJson(rollback) !== canonicalJson(snapshots.beta)) {
    throw new Error("[rollback] rollback target is not the candidate's retained Beta snapshot");
  }
  if (String(rollback.version || "") !== EXPECTED_ROLLBACK_VERSION || rollback.status !== 200
      || rollback.channel !== "beta") {
    throw new Error(`[rollback] rollback target must be exact Beta ${EXPECTED_ROLLBACK_VERSION}`);
  }
  if (snapshots.latest.status !== 200 || snapshots.latest.channel !== "latest"
      || !String(snapshots.latest.version || "")) {
    throw new Error("[rollback] candidate has no valid Stable snapshot");
  }
  assertSha256(rollback.sha256, "rollback target feed SHA256");
  assertSha256(snapshots.latest.sha256, "Stable snapshot SHA256");
  const feedRecord = receipt.artifacts?.[BETA_FEED];
  if (!feedRecord || feedRecord.sha256 !== expectedFailedFeedSha256) {
    throw new Error("[rollback] expected failed-candidate feed hash is not bound to the receipt");
  }

  const retainedFeedBytes = fs.readFileSync(retainedFeedPath);
  const rollbackFeed = assertFeedMatchesSnapshot(retainedFeedBytes, rollback, "retained rollback Beta feed");
  const rollbackFiles = rollbackFeed.files;
  if (rollbackFiles.length !== 4) throw new Error("[rollback] rollback target must contain exactly four updater artifacts");
  const expectedRollbackNames = ["x64", "arm64"].flatMap((arch) => ["zip", "dmg"].map(
    (extension) => `Elevate-${EXPECTED_ROLLBACK_VERSION}-mac-${arch}.${extension}`,
  )).sort();
  if (canonicalJson(rollbackFiles.map((item) => item.url).sort()) !== canonicalJson(expectedRollbackNames)) {
    throw new Error("[rollback] rollback target artifact names are not the exact retained Beta set");
  }

  const rollbackArtifacts = rollbackFiles.map((item) => ({
    name: item.url,
    size: item.size,
    sha512: item.sha512,
  }));
  const rollbackDmgs = {};
  for (const arch of ["x64", "arm64"]) {
    const rollbackDmg = rollbackArtifacts.find((item) => item.name.endsWith(`-${EXPECTED_ROLLBACK_VERSION}-mac-${arch}.dmg`));
    if (!rollbackDmg) throw new Error(`[rollback] rollback target is missing the ${arch} versioned DMG`);
    rollbackDmgs[arch] = { ...rollbackDmg, url: rollbackDmg.name };
  }

  const failedArtifacts = (release.artifact_names || []).map((name) => {
    assertSafeBasename(name, "failed feed artifact name");
    return assertCandidateArtifactRecord(receipt.artifacts?.[name], name);
  }).sort((left, right) => left.name.localeCompare(right.name, "en"));
  const failedFeedFiles = failedArtifacts.map((item) => ({
    url: item.name,
    size: item.size,
    sha512: item.sha512,
  }));
  if (failedFeedFiles.length !== 4) throw new Error("[rollback] failed candidate must contain exactly four updater artifacts");
  const expectedFailedNames = ["x64", "arm64"].flatMap((arch) => ["zip", "dmg"].map(
    (extension) => `Elevate-Beta-${release.version}-mac-${arch}.${extension}`,
  )).sort();
  if (canonicalJson(failedFeedFiles.map((item) => item.url).sort()) !== canonicalJson(expectedFailedNames)) {
    throw new Error("[rollback] failed candidate artifact names are not the exact Beta set");
  }
  const failedDmgs = {};
  for (const arch of ["x64", "arm64"]) {
    const failedDmg = failedArtifacts.find((item) => item.name.endsWith(`-mac-${arch}.dmg`));
    if (!failedDmg) throw new Error(`[rollback] failed candidate is missing the ${arch} versioned DMG`);
    failedDmgs[arch] = failedDmg;
  }

  return {
    receipt,
    receiptBytes,
    retainedFeedBytes,
    candidateId: receipt.candidate_id,
    sourceReceiptId: receipt.source_receipt_id,
    candidateReceiptSha256: actualReceiptSha256,
    expectedFailedFeedSha256,
    failedVersion: release.version,
    rollbackVersion: EXPECTED_ROLLBACK_VERSION,
    rollbackFeedSha256: rollback.sha256,
    stableFeedSha256: snapshots.latest.sha256,
    rollbackSnapshot: rollback,
    stableSnapshot: snapshots.latest,
    rollbackArtifacts,
    rollbackDmgs,
    failedArtifacts,
    failedDmgs,
    failedFeedFiles,
    aliases: EXPECTED_ALIASES,
  };
}

function rollbackFreezeRecord(contract) {
  return realtorBetaRollbackFreezeRecord(rollbackFreezeCandidate(contract));
}

function rollbackFreezeCandidate(contract) {
  return {
    candidate_id: contract.candidateId,
    source_receipt_id: contract.sourceReceiptId,
    release: { channel: "beta", feed_name: BETA_FEED },
    artifacts: { [BETA_FEED]: { sha256: contract.expectedFailedFeedSha256 } },
    rollback_target: { sha256: contract.rollbackFeedSha256 },
    public_feeds_at_finalize: { latest: { sha256: contract.stableFeedSha256 } },
  };
}

function rollbackFreezeBytes(contract) {
  return realtorBetaRollbackFreezeBytes(rollbackFreezeCandidate(contract));
}

function rollbackFreezeClearedFile(contract) {
  return realtorBetaRollbackClearedFile(rollbackFreezeCandidate(contract));
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'\\''`)}'`;
}

function assertRemoteInputs(remoteRoot, stagingName, mode) {
  if (!/^\/[A-Za-z0-9._/-]+\/$/.test(remoteRoot) || remoteRoot.split("/").includes("..")) {
    throw new Error("[rollback] unsafe remote update root");
  }
  const validStage = mode === "execute"
    ? new RegExp(`^\\.rollback-[a-f0-9]{64}-execute$`).test(stagingName || "")
    : new RegExp(`^\\.rollback-[a-f0-9]{64}-[a-f0-9-]{36}$`).test(stagingName || "");
  if (mode !== "preflight" && !validStage) {
    throw new Error("[rollback] unsafe rollback staging name");
  }
}

function buildRemoteExecuteScript({ contract, remoteRoot, stagingName }) {
  assertRemoteInputs(remoteRoot, stagingName, "execute");
  const q = shellQuote;
  const root = remoteRoot;
  const stage = `${root}${stagingName}/`;
  const betaPath = `${root}${BETA_FEED}`;
  const stablePath = `${root}${STABLE_FEED}`;
  const freezePath = `${root}${ROLLBACK_FREEZE_FILE}`;
  const clearedFreezePath = `${root}${rollbackFreezeClearedFile(contract)}`;
  const freezeBytes = rollbackFreezeBytes(contract);
  const freezeSha256 = sha256(freezeBytes);
  const journal = {
    schema_version: 1,
    kind: "elevate-realtor-beta-rollback-transaction",
    candidate_id: contract.candidateId,
    failed_feed_sha256: contract.expectedFailedFeedSha256,
    rollback_feed_sha256: contract.rollbackFeedSha256,
    stable_feed_sha256: contract.stableFeedSha256,
    aliases: contract.aliases,
    procedure_id: REALTOR_BETA_ROLLBACK_PROCEDURE_ID,
  };
  journal.transaction_id = receiptId(journal, "transaction_id");
  const journalBytes = Buffer.from(`${JSON.stringify(canonicalize(journal), null, 2)}\n`);
  const journalSha256 = sha256(journalBytes);
  const artifactToken = (item) => {
    const arch = item.name.includes("-arm64.") ? "ARM64" : "X64";
    const kind = item.name.endsWith(".zip") ? "ZIP" : "DMG";
    return `${arch}_${kind}`;
  };
  const failedStateChecks = [
    `hash_is ${q(betaPath)} ${q(contract.expectedFailedFeedSha256)}`,
    ...contract.aliases.map((alias) => {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      return `hash_is ${q(`${root}${alias}`)} ${q(contract.failedDmgs[arch].sha256)}`;
    }),
  ];
  const rollbackStateChecks = [
    `hash_is ${q(betaPath)} ${q(contract.rollbackFeedSha256)}`,
    ...contract.aliases.map((alias) => {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      return `same_bytes ${q(`${root}${contract.rollbackDmgs[arch].url}`)} ${q(`${root}${alias}`)}`;
    }),
  ];
  const knownPointerChecks = [
    `( hash_is ${q(betaPath)} ${q(contract.expectedFailedFeedSha256)} || hash_is ${q(betaPath)} ${q(contract.rollbackFeedSha256)} )`,
    ...contract.aliases.map((alias) => {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      return `( hash_is ${q(`${root}${alias}`)} ${q(contract.failedDmgs[arch].sha256)} || same_bytes ${q(`${root}${contract.rollbackDmgs[arch].url}`)} ${q(`${root}${alias}`)} )`;
    }),
  ];
  const staticChecks = [
    `assert_sha256 ${q(stablePath)} ${q(contract.stableFeedSha256)} STABLE_CAS_FAILED`,
  ];
  for (const rollback of contract.rollbackArtifacts) {
    staticChecks.push(
      `assert_size_sha512 ${q(`${root}${rollback.name}`)} ${q(rollback.size)} ${q(sha512Hex(rollback.sha512, rollback.name))} ${q(`ROLLBACK_${artifactToken(rollback)}_MISMATCH`)}`,
    );
  }
  for (const failed of contract.failedArtifacts) {
    staticChecks.push(
      `assert_size_sha512 ${q(`${root}${failed.name}`)} ${q(failed.size)} ${q(sha512Hex(failed.sha512, failed.name))} ${q(`FAILED_${artifactToken(failed)}_MISMATCH`)}`,
      `assert_sha256 ${q(`${root}${failed.name}`)} ${q(failed.sha256)} ${q(`FAILED_${artifactToken(failed)}_SHA256_MISMATCH`)}`,
    );
  }
  const backupChecks = [
    `assert_sha256 ${q(`${stage}backups/${BETA_FEED}`)} ${q(contract.expectedFailedFeedSha256)} BACKUP_FEED_MISMATCH`,
    ...contract.aliases.map((alias) => {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      return `assert_sha256 ${q(`${stage}backups/${alias}`)} ${q(contract.failedDmgs[arch].sha256)} ${q(`BACKUP_ALIAS_MISMATCH_${alias}`)}`;
    }),
  ];
  const restoreCalls = [
    ...contract.aliases.map((alias) => (
      `  restore_one ${q(`${stage}backups/${alias}`)} ${q(`${root}${alias}`)} ${q(`${stage}restore-${alias}`)} || return 1`
    )),
    `  restore_one ${q(`${stage}backups/${BETA_FEED}`)} ${q(betaPath)} ${q(`${stage}restore-${BETA_FEED}`)} || return 1`,
  ];

  const lines = [
    "set -euo pipefail",
    "umask 077",
    "fail() { echo \"ROLLBACK_FAIL $1\" >&2; exit \"${2:-50}\"; }",
    "sha256_of() { sha256sum -- \"$1\" | awk '{print $1}'; }",
    "sha512_of() { sha512sum -- \"$1\" | awk '{print $1}'; }",
    "file_size() { stat -c %s -- \"$1\" 2>/dev/null || stat -f %z \"$1\"; }",
    "file_device() { stat -c %d -- \"$1\" 2>/dev/null || stat -f %d \"$1\"; }",
    "file_mode() { stat -c %a -- \"$1\" 2>/dev/null || stat -f %Lp \"$1\"; }",
    "file_uid() { stat -c %u -- \"$1\" 2>/dev/null || stat -f %u \"$1\"; }",
    "file_gid() { stat -c %g -- \"$1\" 2>/dev/null || stat -f %g \"$1\"; }",
    "assert_directory() { test -d \"$1\" && test ! -L \"$1\" || fail \"$2\" 51; }",
    "assert_regular() { test -f \"$1\" && test ! -L \"$1\" || fail \"$2\" 52; }",
    "hash_is() { test -f \"$1\" && test ! -L \"$1\" && test \"$(sha256_of \"$1\")\" = \"$2\"; }",
    "same_bytes() { test -f \"$1\" && test ! -L \"$1\" && test -f \"$2\" && test ! -L \"$2\" && cmp -s -- \"$1\" \"$2\"; }",
    "assert_sha256() { assert_regular \"$1\" \"$3\"; test \"$(sha256_of \"$1\")\" = \"$2\" || fail \"$3\" 53; }",
    "assert_size_sha512() { assert_regular \"$1\" \"$4\"; test \"$(file_size \"$1\")\" = \"$2\" || fail \"$4\" 54; test \"$(sha512_of \"$1\")\" = \"$3\" || fail \"$4\" 55; }",
    "copy_metadata() { chmod \"$(file_mode \"$1\")\" \"$2\" && chown \"$(file_uid \"$1\"):$(file_gid \"$1\")\" \"$2\"; }",
    "durable_sync() { sync -f \"$1\" 2>/dev/null || sync; }",
    "atomic_replace() { mv -f -- \"$1\" \"$2\"; }",
    "failed_state_ok() {",
    ...failedStateChecks.map((line) => `  ${line} || return 1`),
    "}",
    "rollback_state_ok() {",
    ...rollbackStateChecks.map((line) => `  ${line} || return 1`),
    "}",
    "beta_feed_recognized() {",
    `  hash_is ${q(betaPath)} ${q(contract.expectedFailedFeedSha256)} || hash_is ${q(betaPath)} ${q(contract.rollbackFeedSha256)}`,
    "}",
    "known_pointer_state_ok() {",
    ...knownPointerChecks.map((line) => `  ${line} || return 1`),
    "}",
    "stage_payload_ok() {",
    `  hash_is ${q(`${stage}retained-${BETA_FEED}`)} ${q(contract.rollbackFeedSha256)} || return 1`,
    ...contract.aliases.map((alias) => {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      return `  hash_is ${q(`${stage}backups/${alias}`)} ${q(contract.failedDmgs[arch].sha256)} || return 1`;
    }),
    `  hash_is ${q(`${stage}backups/${BETA_FEED}`)} ${q(contract.expectedFailedFeedSha256)} || return 1`,
    "}",
    "restore_one() {",
    "  src=$1; dest=$2; temp=$3",
    "  rm -f -- \"$temp\" || return 1",
    "  cp -- \"$src\" \"$temp\" || return 1",
    "  copy_metadata \"$src\" \"$temp\" || return 1",
    "  durable_sync \"$temp\" || return 1",
    "  mv -f -- \"$temp\" \"$dest\" || return 1",
    `  durable_sync ${q(root)} || return 1`,
    "}",
    "restore_failed_state() {",
    ...restoreCalls,
    "  failed_state_ok",
    "}",
    "retire_stage() {",
    `  tombstone=${q(stage.slice(0, -1))}.retired.$$.$RANDOM`,
    "  test ! -e \"$tombstone\" || return 1",
    `  mv -- ${q(stage)} \"$tombstone\" || return 1`,
    `  durable_sync ${q(root)} || return 1`,
    "  rm -rf -- \"$tombstone\" || true",
    "}",
    `assert_directory ${q(root)} REMOTE_ROOT_INVALID`,
    `assert_sha256 ${q(stablePath)} ${q(contract.stableFeedSha256)} STABLE_CAS_FAILED`,
    "mutation_started=0",
    "committed=0",
    "freeze_present=0",
    "stage_new=0",
    "stage_trusted=0",
    "input_consumed=0",
    "cleanup() {",
    "  rc=$?",
    "  trap - EXIT HUP INT TERM",
    "  set +e",
    "  if test \"$mutation_started\" = 1 && test \"$committed\" = 0; then",
    "    if restore_failed_state && failed_state_ok; then",
    "      if retire_stage; then echo ROLLBACK_COMPENSATION_OK >&2; else rc=97; echo ROLLBACK_STAGE_RETIRE_FAILED >&2; fi",
    "    else",
    "      rc=96",
    "      echo ROLLBACK_COMPENSATION_FAILED_STAGE_PRESERVED >&2",
    "    fi",
    "  elif test \"$committed\" = 1; then",
    `    if test -e ${q(stage)}; then retire_stage || rc=97; fi`,
    "  elif test \"$stage_new\" = 1 && test \"$stage_trusted\" = 0; then",
    "    retire_stage || rc=97",
    "  fi",
    "  exit \"$rc\"",
    "}",
    "trap cleanup EXIT HUP INT TERM",
    `if test -e ${q(clearedFreezePath)} || test -L ${q(clearedFreezePath)}; then`,
    `  assert_sha256 ${q(clearedFreezePath)} ${q(freezeSha256)} RELEASE_FREEZE_CLEARED_CONFLICT`,
    `  if test -e ${q(freezePath)} || test -L ${q(freezePath)}; then fail RELEASE_FREEZE_STATE_CONFLICT 66; fi`,
    `  durable_sync ${q(clearedFreezePath)}`,
    `  durable_sync ${q(root)}`,
    "  committed=2",
    '  echo "REMOTE_ROLLBACK_EXECUTE_OK state=freeze_already_cleared"',
    "  exit 0",
    "fi",
    `if test -e ${q(freezePath)} || test -L ${q(freezePath)}; then`,
    `  assert_sha256 ${q(freezePath)} ${q(freezeSha256)} RELEASE_FREEZE_CONFLICT`,
    `  durable_sync ${q(freezePath)}`,
    `  durable_sync ${q(root)}`,
    "  freeze_present=1",
    "fi",
    `if test -e ${q(stage)}; then`,
    `  assert_directory ${q(stage)} STAGE_INVALID`,
    `  test \"$(file_device ${q(root)})\" = \"$(file_device ${q(stage)})\" || fail STAGE_CROSS_FILESYSTEM 57`,
    `  test \"$(file_mode ${q(stage)})\" = 700 || fail STAGE_MODE_INVALID 58`,
    `  if ! hash_is ${q(`${stage}transaction.json`)} ${q(journalSha256)}; then`,
    "    if failed_state_ok || rollback_state_ok; then",
    "      retire_stage || fail STAGE_RETIRE_FAILED 65",
    "    else",
    "      fail UNTRUSTED_STAGE_WITH_PARTIAL_PUBLIC_STATE 62",
    "    fi",
    "  else",
    "    stage_trusted=1",
    "    if failed_state_ok && ! stage_payload_ok; then",
    "      retire_stage || fail STAGE_RETIRE_FAILED 65",
    "      stage_trusted=0",
    "    fi",
    "  fi",
    "fi",
    `if test \"$stage_trusted\" = 0 && ! test -e ${q(stage)}; then`,
    "  if rollback_state_ok; then",
    "    test \"$freeze_present\" = 1 || fail COMMITTED_STATE_WITHOUT_RELEASE_FREEZE 68",
    ...staticChecks.map((line) => `    ${line}`),
    "    committed=2",
    '    echo "REMOTE_ROLLBACK_EXECUTE_OK state=already_committed"',
    "    exit 0",
    "  fi",
    // A public pointer this lane does not already recognize as the failed
    // candidate (checked here) or the rollback target (checked above) splits
    // into two operator-distinct cases: a feed hash we still recognize means a
    // genuinely partial/mixed pointer state, while an unrecognized feed means a
    // newer or cross-lane release won the Beta pointer and nothing is orphaned.
    "  if ! failed_state_ok; then",
    "    if beta_feed_recognized; then fail PARTIAL_PUBLIC_POINTER_STATE 63; else fail UNRECOGNIZED_BETA_FEED_STATE 63; fi",
    "  fi",
    ...staticChecks.map((line) => `  ${line}`),
    `  mkdir -m 0700 -- ${q(stage)}`,
    "  stage_new=1",
    `  test \"$(file_device ${q(root)})\" = \"$(file_device ${q(stage)})\" || fail STAGE_CROSS_FILESYSTEM 57`,
    `  test \"$(file_mode ${q(stage)})\" = 700 || fail STAGE_MODE_INVALID 58`,
    `  cat > ${q(`${stage}retained-${BETA_FEED}`)}`,
    `  assert_sha256 ${q(`${stage}retained-${BETA_FEED}`)} ${q(contract.rollbackFeedSha256)} RETAINED_FEED_MISMATCH`,
    "  input_consumed=1",
    `  mkdir -m 0700 -- ${q(`${stage}backups`)}`,
    `  cp -- ${q(betaPath)} ${q(`${stage}backups/${BETA_FEED}`)}`,
    `  copy_metadata ${q(betaPath)} ${q(`${stage}backups/${BETA_FEED}`)}`,
  ];
  for (const alias of contract.aliases) {
    lines.push(
      `  cp -- ${q(`${root}${alias}`)} ${q(`${stage}backups/${alias}`)}`,
      `  copy_metadata ${q(`${root}${alias}`)} ${q(`${stage}backups/${alias}`)}`,
    );
  }
  lines.push(
    ...backupChecks.map((line) => `  ${line}`),
    `  durable_sync ${q(stage)}`,
    `  printf %s ${q(journalBytes.toString("utf8"))} > ${q(`${stage}transaction.json.tmp`)}`,
    `  assert_sha256 ${q(`${stage}transaction.json.tmp`)} ${q(journalSha256)} JOURNAL_HASH_MISMATCH`,
    `  mv -f -- ${q(`${stage}transaction.json.tmp`)} ${q(`${stage}transaction.json`)}`,
    `  durable_sync ${q(stage)}`,
    "  stage_trusted=1",
    "fi",
    `if test \"$stage_trusted\" = 1; then`,
    ...staticChecks.map((line) => `  ${line}`),
    "  if rollback_state_ok; then",
    "    test \"$freeze_present\" = 1 || fail COMMITTED_STATE_WITHOUT_RELEASE_FREEZE 68",
    "    committed=1",
    '    echo "REMOTE_ROLLBACK_EXECUTE_OK state=recovered_committed"',
    "    exit 0",
    "  fi",
    "  if test \"$input_consumed\" = 0; then",
    `    cat > ${q(`${stage}incoming-retained-${BETA_FEED}`)}`,
    `    assert_sha256 ${q(`${stage}incoming-retained-${BETA_FEED}`)} ${q(contract.rollbackFeedSha256)} RETAINED_FEED_MISMATCH`,
    `    rm -f -- ${q(`${stage}incoming-retained-${BETA_FEED}`)}`,
    "  fi",
    `  assert_sha256 ${q(`${stage}transaction.json`)} ${q(journalSha256)} JOURNAL_HASH_MISMATCH`,
    `  assert_sha256 ${q(`${stage}retained-${BETA_FEED}`)} ${q(contract.rollbackFeedSha256)} RETAINED_FEED_MISMATCH`,
    ...backupChecks.map((line) => `  ${line}`),
    `  durable_sync ${q(stage)}`,
    `  durable_sync ${q(root)}`,
    "  known_pointer_state_ok || fail UNKNOWN_PARTIAL_PUBLIC_STATE 64",
    `  rm -rf -- ${q(`${stage}next`)}`,
    `  mkdir -m 0700 -- ${q(`${stage}next`)}`,
    `  cp -- ${q(`${stage}retained-${BETA_FEED}`)} ${q(`${stage}next/${BETA_FEED}`)}`,
    `  copy_metadata ${q(`${stage}backups/${BETA_FEED}`)} ${q(`${stage}next/${BETA_FEED}`)}`,
  );
  for (const alias of contract.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    lines.push(
      `  cp -- ${q(`${root}${contract.rollbackDmgs[arch].url}`)} ${q(`${stage}next/${alias}`)}`,
      `  copy_metadata ${q(`${stage}backups/${alias}`)} ${q(`${stage}next/${alias}`)}`,
      `  same_bytes ${q(`${root}${contract.rollbackDmgs[arch].url}`)} ${q(`${stage}next/${alias}`)} || fail ${q(`STAGED_ALIAS_MISMATCH_${alias}`)} 59`,
    );
  }
  lines.push(
    `  assert_sha256 ${q(`${stage}next/${BETA_FEED}`)} ${q(contract.rollbackFeedSha256)} STAGED_FEED_MISMATCH`,
    `  durable_sync ${q(`${stage}next`)}`,
    "  if test \"$freeze_present\" = 0; then",
    "    failed_state_ok || fail PARTIAL_STATE_WITHOUT_RELEASE_FREEZE 69",
    `    rm -f -- ${q(`${freezePath}.tmp`)}`,
    `    printf %s ${q(freezeBytes.toString("utf8"))} > ${q(`${freezePath}.tmp`)}`,
    `    assert_sha256 ${q(`${freezePath}.tmp`)} ${q(freezeSha256)} RELEASE_FREEZE_HASH_MISMATCH`,
    `    mv -f -- ${q(`${freezePath}.tmp`)} ${q(freezePath)}`,
    `    durable_sync ${q(freezePath)}`,
    `    durable_sync ${q(root)}`,
    "    freeze_present=1",
    "  fi",
    "  mutation_started=1",
  );
  for (const alias of contract.aliases) {
    lines.push(`  atomic_replace ${q(`${stage}next/${alias}`)} ${q(`${root}${alias}`)}`);
  }
  lines.push(
    `  atomic_replace ${q(`${stage}next/${BETA_FEED}`)} ${q(betaPath)}`,
    `  durable_sync ${q(root)}`,
    `  assert_sha256 ${q(betaPath)} ${q(contract.rollbackFeedSha256)} COMMITTED_FEED_MISMATCH`,
  );
  for (const alias of contract.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    lines.push(
      `  same_bytes ${q(`${root}${contract.rollbackDmgs[arch].url}`)} ${q(`${root}${alias}`)} || fail ${q(`COMMITTED_ALIAS_MISMATCH_${alias}`)} 61`,
    );
  }
  lines.push(
    ...staticChecks.map((line) => `  ${line}`),
    "  committed=1",
    "  mutation_started=0",
    '  echo "REMOTE_ROLLBACK_EXECUTE_OK state=committed"',
    "fi",
  );
  return lines.join("\n");
}

function buildRemoteRollbackFreezeClearInnerScript({ contract, remoteRoot = DEFAULT_REMOTE_ROOT }) {
  assertRemoteInputs(remoteRoot, null, "preflight");
  const q = shellQuote;
  const root = remoteRoot;
  const betaPath = `${root}${BETA_FEED}`;
  const stablePath = `${root}${STABLE_FEED}`;
  const freezePath = `${root}${ROLLBACK_FREEZE_FILE}`;
  const clearedFreezePath = `${root}${rollbackFreezeClearedFile(contract)}`;
  const freezeBytes = rollbackFreezeBytes(contract);
  const freezeSha256 = sha256(freezeBytes);
  const artifactToken = (item) => {
    const arch = item.name.includes("-arm64.") ? "ARM64" : "X64";
    const kind = item.name.endsWith(".zip") ? "ZIP" : "DMG";
    return `${arch}_${kind}`;
  };
  const stateChecks = [
    `assert_sha256 ${q(stablePath)} ${q(contract.stableFeedSha256)} STABLE_CAS_FAILED`,
    `assert_sha256 ${q(betaPath)} ${q(contract.rollbackFeedSha256)} ROLLBACK_BETA_CAS_FAILED`,
  ];
  for (const rollback of contract.rollbackArtifacts) {
    stateChecks.push(
      `assert_size_sha512 ${q(`${root}${rollback.name}`)} ${q(rollback.size)} ${q(sha512Hex(rollback.sha512, rollback.name))} ${q(`ROLLBACK_${artifactToken(rollback)}_MISMATCH`)}`,
    );
  }
  for (const failed of contract.failedArtifacts) {
    stateChecks.push(
      `assert_size_sha512 ${q(`${root}${failed.name}`)} ${q(failed.size)} ${q(sha512Hex(failed.sha512, failed.name))} ${q(`FAILED_${artifactToken(failed)}_MISMATCH`)}`,
      `assert_sha256 ${q(`${root}${failed.name}`)} ${q(failed.sha256)} ${q(`FAILED_${artifactToken(failed)}_SHA256_MISMATCH`)}`,
    );
  }
  for (const alias of contract.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    stateChecks.push(
      `same_bytes ${q(`${root}${contract.rollbackDmgs[arch].url}`)} ${q(`${root}${alias}`)} || fail ${q(`ROLLBACK_ALIAS_MISMATCH_${alias}`)} 61`,
    );
  }

  return [
    "set -euo pipefail",
    "umask 077",
    "fail() { echo \"ROLLBACK_FAIL $1\" >&2; exit \"${2:-50}\"; }",
    "sha256_of() { sha256sum -- \"$1\" | awk '{print $1}'; }",
    "sha512_of() { sha512sum -- \"$1\" | awk '{print $1}'; }",
    "file_size() { stat -c %s -- \"$1\" 2>/dev/null || stat -f %z \"$1\"; }",
    "assert_directory() { test -d \"$1\" && test ! -L \"$1\" || fail \"$2\" 51; }",
    "assert_regular() { test -f \"$1\" && test ! -L \"$1\" || fail \"$2\" 52; }",
    "assert_sha256() { assert_regular \"$1\" \"$3\"; test \"$(sha256_of \"$1\")\" = \"$2\" || fail \"$3\" 53; }",
    "assert_size_sha512() { assert_regular \"$1\" \"$4\"; test \"$(file_size \"$1\")\" = \"$2\" || fail \"$4\" 54; test \"$(sha512_of \"$1\")\" = \"$3\" || fail \"$4\" 55; }",
    "same_bytes() { test -f \"$1\" && test ! -L \"$1\" && test -f \"$2\" && test ! -L \"$2\" && cmp -s -- \"$1\" \"$2\"; }",
    "durable_sync() { sync -f \"$1\" 2>/dev/null || sync; }",
    `assert_directory ${q(root)} REMOTE_ROOT_INVALID`,
    `if test -e ${q(clearedFreezePath)} || test -L ${q(clearedFreezePath)}; then`,
    `  assert_sha256 ${q(clearedFreezePath)} ${q(freezeSha256)} RELEASE_FREEZE_CLEARED_CONFLICT`,
    `  durable_sync ${q(clearedFreezePath)}`,
    `  durable_sync ${q(root)}`,
    `  if test -e ${q(freezePath)} || test -L ${q(freezePath)}; then`,
    `    assert_sha256 ${q(freezePath)} ${q(freezeSha256)} RELEASE_FREEZE_CONFLICT`,
    `    rm -f -- ${q(freezePath)}`,
    `    durable_sync ${q(root)}`,
    '    echo "REMOTE_ROLLBACK_FREEZE_CLEAR_OK state=completed_clear"',
    "    exit 0",
    "  fi",
    '  echo "REMOTE_ROLLBACK_FREEZE_CLEAR_OK state=already_cleared"',
    "  exit 0",
    "fi",
    `if ! test -e ${q(freezePath)} && ! test -L ${q(freezePath)}; then fail RELEASE_FREEZE_MISSING 70; fi`,
    `assert_sha256 ${q(freezePath)} ${q(freezeSha256)} RELEASE_FREEZE_CONFLICT`,
    ...stateChecks,
    `rm -f -- ${q(`${clearedFreezePath}.tmp`)}`,
    `cp -- ${q(freezePath)} ${q(`${clearedFreezePath}.tmp`)}`,
    `assert_sha256 ${q(`${clearedFreezePath}.tmp`)} ${q(freezeSha256)} RELEASE_FREEZE_CLEARED_HASH_MISMATCH`,
    `chmod 0400 ${q(`${clearedFreezePath}.tmp`)}`,
    `durable_sync ${q(`${clearedFreezePath}.tmp`)}`,
    `mv -- ${q(`${clearedFreezePath}.tmp`)} ${q(clearedFreezePath)}`,
    `durable_sync ${q(clearedFreezePath)}`,
    `durable_sync ${q(root)}`,
    `rm -f -- ${q(freezePath)}`,
    `durable_sync ${q(root)}`,
    'echo "REMOTE_ROLLBACK_FREEZE_CLEAR_OK state=cleared"',
  ].join("\n");
}

function buildRemoteRollbackInnerScript({ contract, mode, remoteRoot = DEFAULT_REMOTE_ROOT, stagingName = null }) {
  if (!MODES.has(mode)) throw new Error(`[rollback] unsupported mode: ${mode}`);
  assertRemoteInputs(remoteRoot, stagingName, mode);
  if (mode === "execute") {
    return buildRemoteExecuteScript({ contract, remoteRoot, stagingName });
  }
  const q = shellQuote;
  const root = remoteRoot;
  const stage = stagingName ? `${root}${stagingName}/` : null;
  const betaPath = `${root}${BETA_FEED}`;
  const stablePath = `${root}${STABLE_FEED}`;
  const artifactToken = (item) => {
    const arch = item.name.includes("-arm64.") ? "ARM64" : "X64";
    const kind = item.name.endsWith(".zip") ? "ZIP" : "DMG";
    return `${arch}_${kind}`;
  };

  const commonChecks = [
    `assert_directory ${q(root)} REMOTE_ROOT_INVALID`,
    `assert_sha256 ${q(stablePath)} ${q(contract.stableFeedSha256)} STABLE_CAS_FAILED`,
    `assert_sha256 ${q(betaPath)} ${q(contract.expectedFailedFeedSha256)} FAILED_BETA_CAS_FAILED`,
  ];
  for (const rollback of contract.rollbackArtifacts) {
    commonChecks.push(
      `assert_size_sha512 ${q(`${root}${rollback.name}`)} ${q(rollback.size)} ${q(sha512Hex(rollback.sha512, rollback.name))} ${q(`ROLLBACK_${artifactToken(rollback)}_MISMATCH`)}`,
    );
  }
  for (const failed of contract.failedArtifacts) {
    commonChecks.push(
      `assert_size_sha512 ${q(`${root}${failed.name}`)} ${q(failed.size)} ${q(sha512Hex(failed.sha512, failed.name))} ${q(`FAILED_${artifactToken(failed)}_MISMATCH`)}`,
      `assert_sha256 ${q(`${root}${failed.name}`)} ${q(failed.sha256)} ${q(`FAILED_${artifactToken(failed)}_SHA256_MISMATCH`)}`,
    );
  }
  for (const alias of contract.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    commonChecks.push(
      `assert_sha256 ${q(`${root}${alias}`)} ${q(contract.failedDmgs[arch].sha256)} ${q(`FAILED_ALIAS_CAS_${alias}`)}`,
    );
  }

  const lines = [
    "set -euo pipefail",
    "umask 077",
    "fail() { echo \"ROLLBACK_FAIL $1\" >&2; exit \"${2:-50}\"; }",
    "sha256_of() { sha256sum -- \"$1\" | awk '{print $1}'; }",
    "sha512_of() { sha512sum -- \"$1\" | awk '{print $1}'; }",
    "file_size() { stat -c %s -- \"$1\" 2>/dev/null || stat -f %z \"$1\"; }",
    "file_device() { stat -c %d -- \"$1\" 2>/dev/null || stat -f %d \"$1\"; }",
    "file_mode() { stat -c %a -- \"$1\" 2>/dev/null || stat -f %Lp \"$1\"; }",
    "file_uid() { stat -c %u -- \"$1\" 2>/dev/null || stat -f %u \"$1\"; }",
    "file_gid() { stat -c %g -- \"$1\" 2>/dev/null || stat -f %g \"$1\"; }",
    "assert_directory() { test -d \"$1\" && test ! -L \"$1\" || fail \"$2\" 51; }",
    "assert_regular() { test -f \"$1\" && test ! -L \"$1\" || fail \"$2\" 52; }",
    "assert_sha256() { assert_regular \"$1\" \"$3\"; test \"$(sha256_of \"$1\")\" = \"$2\" || fail \"$3\" 53; }",
    "assert_size_sha512() { assert_regular \"$1\" \"$4\"; test \"$(file_size \"$1\")\" = \"$2\" || fail \"$4\" 54; test \"$(sha512_of \"$1\")\" = \"$3\" || fail \"$4\" 55; }",
    "copy_metadata() { chmod \"$(file_mode \"$1\")\" \"$2\"; chown \"$(file_uid \"$1\"):$(file_gid \"$1\")\" \"$2\"; }",
    "atomic_replace() { mv -f -- \"$1\" \"$2\"; }",
    ...commonChecks,
  ];

  if (mode === "preflight") {
    lines.push('echo "REMOTE_ROLLBACK_PREFLIGHT_OK"');
    return lines.join("\n");
  }

  lines.push(
    `test ! -e ${q(stage)} || fail STAGE_COLLISION 56`,
    `mkdir -m 0700 -- ${q(stage)}`,
    "mutation_started=0",
    "committed=0",
    "cleanup() {",
    "  rc=$?",
    "  trap - EXIT HUP INT TERM",
    `  if test \"${mode}\" = execute && test \"$mutation_started\" = 1 && test \"$committed\" = 0; then`,
    "    set +e",
    "    restore_failed=0",
    `    atomic_replace ${q(`${stage}backups/${BETA_FEED}`)} ${q(betaPath)} || restore_failed=1`,
    ...contract.aliases.map((alias) => (
      `    atomic_replace ${q(`${stage}backups/${alias}`)} ${q(`${root}${alias}`)} || restore_failed=1`
    )),
    `    test \"$(sha256_of ${q(betaPath)})\" = ${q(contract.expectedFailedFeedSha256)} || restore_failed=1`,
    ...contract.aliases.map((alias) => {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      return `    test \"$(sha256_of ${q(`${root}${alias}`)})\" = ${q(contract.failedDmgs[arch].sha256)} || restore_failed=1`;
    }),
    "    set -e",
    "    if test \"$restore_failed\" != 0; then rc=96; echo ROLLBACK_COMPENSATION_FAILED >&2; else echo ROLLBACK_COMPENSATION_OK >&2; fi",
    "  fi",
    `  rm -rf -- ${q(stage)}`,
    "  exit \"$rc\"",
    "}",
    "trap cleanup EXIT HUP INT TERM",
    `test \"$(file_device ${q(root)})\" = \"$(file_device ${q(stage)})\" || fail STAGE_CROSS_FILESYSTEM 57`,
    `test \"$(file_mode ${q(stage)})\" = 700 || fail STAGE_MODE_INVALID 58`,
    `cat > ${q(`${stage}retained-${BETA_FEED}`)}`,
    `assert_sha256 ${q(`${stage}retained-${BETA_FEED}`)} ${q(contract.rollbackFeedSha256)} RETAINED_FEED_MISMATCH`,
    `cp -- ${q(`${stage}retained-${BETA_FEED}`)} ${q(`${stage}${BETA_FEED}`)}`,
    `copy_metadata ${q(betaPath)} ${q(`${stage}${BETA_FEED}`)}`,
  );
  for (const alias of contract.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    lines.push(
      `cp -- ${q(`${root}${contract.rollbackDmgs[arch].url}`)} ${q(`${stage}${alias}`)}`,
      `copy_metadata ${q(`${root}${alias}`)} ${q(`${stage}${alias}`)}`,
      `cmp -s -- ${q(`${root}${contract.rollbackDmgs[arch].url}`)} ${q(`${stage}${alias}`)} || fail ${q(`STAGED_ALIAS_MISMATCH_${alias}`)} 59`,
    );
  }
  lines.push(
    `assert_sha256 ${q(`${stage}${BETA_FEED}`)} ${q(contract.rollbackFeedSha256)} STAGED_FEED_MISMATCH`,
    ...commonChecks,
  );

  if (mode === "dry-run") {
    lines.push(
      `mkdir -m 0700 -- ${q(`${stage}drill-current`)} ${q(`${stage}drill-next`)}`,
      `cp -- ${q(betaPath)} ${q(`${stage}drill-current/${BETA_FEED}`)}`,
      `cp -- ${q(`${stage}${BETA_FEED}`)} ${q(`${stage}drill-next/${BETA_FEED}`)}`,
    );
    for (const alias of contract.aliases) {
      lines.push(
        `cp -- ${q(`${root}${alias}`)} ${q(`${stage}drill-current/${alias}`)}`,
        `cp -- ${q(`${stage}${alias}`)} ${q(`${stage}drill-next/${alias}`)}`,
        `atomic_replace ${q(`${stage}drill-next/${alias}`)} ${q(`${stage}drill-current/${alias}`)}`,
      );
    }
    lines.push(
      `atomic_replace ${q(`${stage}drill-next/${BETA_FEED}`)} ${q(`${stage}drill-current/${BETA_FEED}`)}`,
      `assert_sha256 ${q(`${stage}drill-current/${BETA_FEED}`)} ${q(contract.rollbackFeedSha256)} DRILL_FEED_MISMATCH`,
    );
    for (const alias of contract.aliases) {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      lines.push(
        `cmp -s -- ${q(`${root}${contract.rollbackDmgs[arch].url}`)} ${q(`${stage}drill-current/${alias}`)} || fail ${q(`DRILL_ALIAS_MISMATCH_${alias}`)} 60`,
      );
    }
    lines.push(
      ...commonChecks,
      'echo "REMOTE_ROLLBACK_DRY_RUN_OK"',
    );
    return lines.join("\n");
  }

  lines.push(
    `mkdir -m 0700 -- ${q(`${stage}backups`)}`,
    `cp -- ${q(betaPath)} ${q(`${stage}backups/${BETA_FEED}`)}`,
    `copy_metadata ${q(betaPath)} ${q(`${stage}backups/${BETA_FEED}`)}`,
    `assert_sha256 ${q(`${stage}backups/${BETA_FEED}`)} ${q(contract.expectedFailedFeedSha256)} BACKUP_FEED_MISMATCH`,
  );
  for (const alias of contract.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    lines.push(
      `cp -- ${q(`${root}${alias}`)} ${q(`${stage}backups/${alias}`)}`,
      `copy_metadata ${q(`${root}${alias}`)} ${q(`${stage}backups/${alias}`)}`,
      `assert_sha256 ${q(`${stage}backups/${alias}`)} ${q(contract.failedDmgs[arch].sha256)} ${q(`BACKUP_ALIAS_MISMATCH_${alias}`)}`,
    );
  }
  lines.push("mutation_started=1");
  for (const alias of contract.aliases) {
    lines.push(`atomic_replace ${q(`${stage}${alias}`)} ${q(`${root}${alias}`)}`);
  }
  lines.push(
    `atomic_replace ${q(`${stage}${BETA_FEED}`)} ${q(betaPath)}`,
    `assert_sha256 ${q(betaPath)} ${q(contract.rollbackFeedSha256)} COMMITTED_FEED_MISMATCH`,
  );
  for (const alias of contract.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    lines.push(
      `cmp -s -- ${q(`${root}${contract.rollbackDmgs[arch].url}`)} ${q(`${root}${alias}`)} || fail ${q(`COMMITTED_ALIAS_MISMATCH_${alias}`)} 61`,
    );
  }
  lines.push(
    `assert_sha256 ${q(stablePath)} ${q(contract.stableFeedSha256)} STABLE_CHANGED_DURING_COMMIT`,
  );
  for (const rollback of contract.rollbackArtifacts) {
    lines.push(
      `assert_size_sha512 ${q(`${root}${rollback.name}`)} ${q(rollback.size)} ${q(sha512Hex(rollback.sha512, rollback.name))} ${q(`ROLLBACK_${artifactToken(rollback)}_NOT_RETAINED`)}`,
    );
  }
  for (const failed of contract.failedArtifacts) {
    lines.push(
      `assert_size_sha512 ${q(`${root}${failed.name}`)} ${q(failed.size)} ${q(sha512Hex(failed.sha512, failed.name))} ${q(`FAILED_${artifactToken(failed)}_NOT_RETAINED`)}`,
      `assert_sha256 ${q(`${root}${failed.name}`)} ${q(failed.sha256)} ${q(`FAILED_${artifactToken(failed)}_SHA256_NOT_RETAINED`)}`,
    );
  }
  lines.push(
    "committed=1",
    "mutation_started=0",
    'echo "REMOTE_ROLLBACK_EXECUTE_OK"',
  );
  return lines.join("\n");
}

function assertGlobalLockPath(globalLock) {
  if (!/^\/[A-Za-z0-9._/-]+$/.test(globalLock || "") || String(globalLock).split("/").includes("..")) {
    throw new Error("[rollback] unsafe global release lock path");
  }
  return globalLock;
}

function buildRemoteRollbackTransaction({ globalLock = GLOBAL_LOCK, ...options }) {
  const inner = buildRemoteRollbackInnerScript(options);
  return `flock -x -w 300 ${shellQuote(assertGlobalLockPath(globalLock))} bash -c ${shellQuote(inner)}`;
}

function buildRemoteRollbackFreezeClearTransaction({
  contract,
  remoteRoot = DEFAULT_REMOTE_ROOT,
  globalLock = GLOBAL_LOCK,
}) {
  const inner = buildRemoteRollbackFreezeClearInnerScript({ contract, remoteRoot });
  return `flock -x -w 300 ${shellQuote(assertGlobalLockPath(globalLock))} bash -c ${shellQuote(inner)}`;
}

function runRemoteRollback({ contract, mode, host = DEFAULT_HOST, remoteRoot = DEFAULT_REMOTE_ROOT }) {
  if (!/^[A-Za-z0-9._-]+@[A-Za-z0-9._:-]+$/.test(host)) throw new Error("[rollback] unsafe release host");
  const stagingName = mode === "preflight"
    ? null
    : (mode === "execute"
      ? `.rollback-${contract.candidateId}-execute`
      : `.rollback-${contract.candidateId}-${crypto.randomUUID()}`);
  const command = buildRemoteRollbackTransaction({ contract, mode, remoteRoot, stagingName });
  const result = spawnSync(
    "ssh",
    [
      "-o", "BatchMode=yes",
      "-o", "ConnectTimeout=15",
      "-o", "ServerAliveInterval=15",
      "-o", "ServerAliveCountMax=4",
      host,
      command,
    ],
    {
      input: mode === "preflight" ? undefined : contract.retainedFeedBytes,
      encoding: "utf8",
      timeout: 30 * 60 * 1000,
      maxBuffer: 16 * 1024 * 1024,
    },
  );
  if (result.status !== 0) {
    const detail = `${result.stdout || ""}\n${result.stderr || ""}\n${result.error?.message || ""}`.trim();
    throw new Error(`[rollback] locked remote ${mode} failed${detail ? `: ${detail}` : ""}`);
  }
  const marker = `REMOTE_ROLLBACK_${mode === "dry-run" ? "DRY_RUN" : mode.toUpperCase()}_OK`;
  if (!(result.stdout || "").includes(marker)) throw new Error(`[rollback] remote ${mode} completion marker missing`);
  return { marker, stdout: (result.stdout || "").trim() };
}

function runRemoteRollbackFreezeClear({
  contract,
  host = DEFAULT_HOST,
  remoteRoot = DEFAULT_REMOTE_ROOT,
}) {
  if (!/^[A-Za-z0-9._-]+@[A-Za-z0-9._:-]+$/.test(host)) throw new Error("[rollback] unsafe release host");
  const command = buildRemoteRollbackFreezeClearTransaction({ contract, remoteRoot });
  const result = spawnSync(
    "ssh",
    [
      "-o", "BatchMode=yes",
      "-o", "ConnectTimeout=15",
      "-o", "ServerAliveInterval=15",
      "-o", "ServerAliveCountMax=4",
      host,
      command,
    ],
    {
      encoding: "utf8",
      timeout: 30 * 60 * 1000,
      maxBuffer: 16 * 1024 * 1024,
    },
  );
  if (result.status !== 0) {
    const detail = `${result.stdout || ""}\n${result.stderr || ""}\n${result.error?.message || ""}`.trim();
    throw new Error(`[rollback] locked remote release-freeze clear failed${detail ? `: ${detail}` : ""}`);
  }
  const marker = "REMOTE_ROLLBACK_FREEZE_CLEAR_OK";
  if (!(result.stdout || "").includes(marker)) {
    throw new Error("[rollback] remote release-freeze clear completion marker missing");
  }
  return { marker, stdout: (result.stdout || "").trim() };
}

function curlToFile(url, destination, label) {
  const separator = url.includes("?") ? "&" : "?";
  const cacheBypassUrl = `${url}${separator}rollback_probe=${Date.now()}-${crypto.randomUUID()}`;
  const result = spawnSync(
    "curl",
    [
      "--fail", "--silent", "--show-error", "--location",
      "--retry", "5", "--retry-delay", "2",
      "--header", "Cache-Control: no-cache, no-store, max-age=0",
      "--header", "Pragma: no-cache",
      "--output", destination,
      cacheBypassUrl,
    ],
    { encoding: "utf8", timeout: 30 * 60 * 1000 },
  );
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || result.error?.message || "").trim();
    throw new Error(`[rollback] ${label} public readback failed${detail ? `: ${detail}` : ""}`);
  }
}

function fetchPublicFeeds({ contract, expectedBeta, publicUrl = DEFAULT_PUBLIC_URL }) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-rollback-readback-"));
  try {
    const betaPath = path.join(temp, BETA_FEED);
    const stablePath = path.join(temp, STABLE_FEED);
    curlToFile(`${publicUrl}/${BETA_FEED}`, betaPath, BETA_FEED);
    curlToFile(`${publicUrl}/${STABLE_FEED}`, stablePath, STABLE_FEED);
    const betaBytes = fs.readFileSync(betaPath);
    const stableBytes = fs.readFileSync(stablePath);
    if (expectedBeta === "failed") assertFailedCandidateFeed(betaBytes, contract);
    else assertFeedMatchesSnapshot(betaBytes, contract.rollbackSnapshot, "public rollback Beta feed");
    assertFeedMatchesSnapshot(stableBytes, contract.stableSnapshot, "public Stable feed");
    return {
      betaBytes,
      stableBytes,
      beta: { size: betaBytes.length, sha256: sha256(betaBytes) },
      stable: { size: stableBytes.length, sha256: sha256(stableBytes) },
    };
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

function assertDownloadedArtifact(filePath, expected, label) {
  const size = fs.statSync(filePath).size;
  const actualSha512 = hashFile(filePath, "sha512", "base64");
  if (size !== expected.size || actualSha512 !== expected.sha512) {
    throw new Error(`[rollback] public ${label} does not match the candidate receipt`);
  }
  return {
    size,
    sha256: hashFile(filePath),
    sha512: actualSha512,
  };
}

function verifyPublicRollbackAliases({ contract, publicUrl = DEFAULT_PUBLIC_URL }) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-rollback-alias-readback-"));
  try {
    const results = {};
    for (const alias of contract.aliases) {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      const expected = contract.rollbackDmgs[arch];
      const destination = path.join(temp, sha256(alias));
      curlToFile(`${publicUrl}/${alias}`, destination, alias);
      results[alias] = {
        url: `${publicUrl}/${alias}`,
        ...assertDownloadedArtifact(destination, expected, `alias ${alias}`),
        source: expected.url,
      };
    }
    return results;
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

function verifyPublicRollbackVersionedArtifacts({ contract, publicUrl = DEFAULT_PUBLIC_URL }) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-rollback-versioned-readback-"));
  try {
    const results = {};
    for (const expected of contract.rollbackArtifacts) {
      const destination = path.join(temp, sha256(expected.name));
      curlToFile(`${publicUrl}/${expected.name}`, destination, expected.name);
      results[expected.name] = {
        url: `${publicUrl}/${expected.name}`,
        ...assertDownloadedArtifact(destination, expected, `versioned artifact ${expected.name}`),
      };
    }
    return results;
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

function fileRecord(filePath) {
  return { size: fs.statSync(filePath).size, sha256: hashFile(filePath) };
}

function syncFile(filePath) {
  const fd = fs.openSync(filePath, "r");
  try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
}

function assertMode(filePath, expected, label) {
  const actual = fs.statSync(filePath).mode & 0o777;
  if (actual !== expected) {
    throw new Error(`[rollback] ${label} mode ${actual.toString(8)} != ${expected.toString(8)}`);
  }
  return actual;
}

function writeExclusive(filePath, bytes) {
  fs.writeFileSync(filePath, bytes, { flag: "wx", mode: 0o600 });
  syncFile(filePath);
}

function evidenceParent(evidenceRoot, contract) {
  return path.resolve(
    evidenceRoot,
    "beta",
    `${contract.failedVersion}-${contract.candidateId}`,
  );
}

function assertFileRecord(filePath, expected, label) {
  if (!expected || !Number.isSafeInteger(expected.size) || expected.size < 0
      || !SHA256_RE.test(String(expected.sha256 || ""))) {
    throw new Error(`[rollback] invalid ${label} record`);
  }
  const actual = fileRecord(filePath);
  if (actual.size !== expected.size || actual.sha256 !== expected.sha256) {
    throw new Error(`[rollback] ${label} record mismatch`);
  }
  return actual;
}

function executeIntentPath(evidenceRoot, contract) {
  return path.join(evidenceParent(evidenceRoot, contract), "execute-pending");
}

function executeCompletePath(evidenceRoot, contract) {
  return path.join(evidenceParent(evidenceRoot, contract), "execute-complete");
}

function loadExecuteIntent({ contract, evidenceRoot }) {
  const target = executeIntentPath(evidenceRoot, contract);
  const stat = fs.lstatSync(target, { throwIfNoEntry: false });
  if (!stat) return null;
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("[rollback] execute intent path is not a real directory");
  }
  assertMode(target, 0o700, "execute intent directory");
  let intent;
  try {
    intent = JSON.parse(fs.readFileSync(path.join(target, "intent.json"), "utf8"));
  } catch (error) {
    throw new Error(`[rollback] execute intent is unreadable: ${error.message}`);
  }
  if (intent?.schema_version !== 1 || intent?.kind !== "elevate-realtor-beta-rollback-intent"
      || receiptId(intent, "intent_id") !== intent.intent_id
      || intent.candidate_id !== contract.candidateId
      || intent.source_receipt_id !== contract.sourceReceiptId
      || intent.candidate_receipt_sha256 !== contract.candidateReceiptSha256
      || intent.failed_feed_sha256 !== contract.expectedFailedFeedSha256
      || intent.rollback_feed_sha256 !== contract.rollbackFeedSha256
      || intent.stable_feed_sha256 !== contract.stableFeedSha256
      || typeof intent.started_at !== "string" || !Number.isFinite(Date.parse(intent.started_at))) {
    throw new Error("[rollback] execute intent is not bound to this exact candidate");
  }
  const expectedNames = [
    "candidate-receipt.json",
    "public-before-beta-mac.yml",
    "public-before-latest-mac.yml",
    "retained-beta-mac.yml",
  ];
  if (canonicalJson(Object.keys(intent.files || {}).sort()) !== canonicalJson(expectedNames)) {
    throw new Error("[rollback] execute intent file manifest is incomplete");
  }
  for (const name of expectedNames) {
    assertFileRecord(path.join(target, name), intent.files[name], `execute intent ${name}`);
    assertMode(path.join(target, name), 0o600, `execute intent ${name}`);
  }
  assertMode(path.join(target, "intent.json"), 0o600, "execute intent manifest");
  const receiptBytes = fs.readFileSync(path.join(target, "candidate-receipt.json"));
  const retainedFeedBytes = fs.readFileSync(path.join(target, "retained-beta-mac.yml"));
  if (!receiptBytes.equals(contract.receiptBytes) || !retainedFeedBytes.equals(contract.retainedFeedBytes)) {
    throw new Error("[rollback] execute intent candidate evidence mismatch");
  }
  const betaBytes = fs.readFileSync(path.join(target, "public-before-beta-mac.yml"));
  const stableBytes = fs.readFileSync(path.join(target, "public-before-latest-mac.yml"));
  assertFailedCandidateFeed(betaBytes, contract, "execute intent failed candidate Beta feed");
  assertFeedMatchesSnapshot(stableBytes, contract.stableSnapshot, "execute intent Stable feed");
  syncFile(target);
  syncFile(path.dirname(target));
  return {
    path: target,
    intent,
    startedAt: intent.started_at,
    before: {
      betaBytes,
      stableBytes,
      beta: { size: betaBytes.length, sha256: sha256(betaBytes) },
      stable: { size: stableBytes.length, sha256: sha256(stableBytes) },
    },
  };
}

function writeExecuteIntent({ contract, evidenceRoot, startedAt, before }) {
  const existing = loadExecuteIntent({ contract, evidenceRoot });
  if (existing) return existing;
  assertFailedCandidateFeed(before.betaBytes, contract, "execute intent failed candidate Beta feed");
  assertFeedMatchesSnapshot(before.stableBytes, contract.stableSnapshot, "execute intent Stable feed");
  const parent = evidenceParent(evidenceRoot, contract);
  fs.mkdirSync(parent, { recursive: true, mode: 0o700 });
  const target = executeIntentPath(evidenceRoot, contract);
  const temp = `${target}.tmp-${process.pid}-${crypto.randomUUID()}`;
  fs.mkdirSync(temp, { mode: 0o700 });
  try {
    const files = {
      "candidate-receipt.json": contract.receiptBytes,
      "public-before-beta-mac.yml": before.betaBytes,
      "public-before-latest-mac.yml": before.stableBytes,
      "retained-beta-mac.yml": contract.retainedFeedBytes,
    };
    for (const [name, bytes] of Object.entries(files)) writeExclusive(path.join(temp, name), bytes);
    const intent = {
      schema_version: 1,
      kind: "elevate-realtor-beta-rollback-intent",
      candidate_id: contract.candidateId,
      source_receipt_id: contract.sourceReceiptId,
      candidate_receipt_sha256: contract.candidateReceiptSha256,
      failed_feed_sha256: contract.expectedFailedFeedSha256,
      rollback_feed_sha256: contract.rollbackFeedSha256,
      stable_feed_sha256: contract.stableFeedSha256,
      started_at: startedAt,
      files: Object.fromEntries(
        Object.keys(files).sort().map((name) => [name, fileRecord(path.join(temp, name))]),
      ),
    };
    intent.intent_id = receiptId(intent, "intent_id");
    writeExclusive(path.join(temp, "intent.json"), Buffer.from(`${JSON.stringify(canonicalize(intent), null, 2)}\n`));
    syncFile(temp);
    try {
      fs.renameSync(temp, target);
    } catch (error) {
      if (!fs.existsSync(target)) throw error;
      fs.rmSync(temp, { recursive: true, force: true });
    }
    syncFile(parent);
    return loadExecuteIntent({ contract, evidenceRoot });
  } catch (error) {
    fs.rmSync(temp, { recursive: true, force: true });
    throw error;
  }
}

function removeExecuteIntent({ contract, evidenceRoot }) {
  const completed = loadEvidenceArchive({
    contract,
    mode: "execute",
    target: executeCompletePath(evidenceRoot, contract),
  });
  if (!completed) throw new Error("[rollback] refusing to retire execute intent before durable completion evidence");
  const target = executeIntentPath(evidenceRoot, contract);
  const stat = fs.lstatSync(target, { throwIfNoEntry: false });
  if (!stat) return false;
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("[rollback] execute intent path is not a real directory");
  }
  const parent = evidenceParent(evidenceRoot, contract);
  const tombstone = `${target}.retired-${process.pid}-${crypto.randomUUID()}`;
  fs.renameSync(target, tombstone);
  syncFile(parent);
  fs.rmSync(tombstone, { recursive: true, force: true });
  return true;
}

function loadEvidenceArchive({ contract, mode, target }) {
  const stat = fs.lstatSync(target, { throwIfNoEntry: false });
  if (!stat) return null;
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("[rollback] evidence archive path is not a real directory");
  }
  const archiveDirectoryMode = fs.statSync(target).mode & 0o777;
  if (archiveDirectoryMode !== 0o500 && archiveDirectoryMode !== 0o700) {
    throw new Error(`[rollback] evidence archive directory mode ${archiveDirectoryMode.toString(8)} is unsafe`);
  }
  let evidence;
  let archive;
  try {
    evidence = JSON.parse(fs.readFileSync(path.join(target, "rollback.json"), "utf8"));
    archive = JSON.parse(fs.readFileSync(path.join(target, "archive.json"), "utf8"));
  } catch (error) {
    throw new Error(`[rollback] evidence archive is unreadable: ${error.message}`);
  }
  if (evidence?.kind !== "elevate-realtor-beta-production-rollback"
      || evidence.mode !== mode || receiptId(evidence, "rollback_id") !== evidence.rollback_id
      || evidence.candidate_id !== contract.candidateId
      || evidence.source_receipt_id !== contract.sourceReceiptId
      || evidence.candidate_receipt_sha256 !== contract.candidateReceiptSha256
      || evidence.expected_failed_candidate_feed_sha256 !== contract.expectedFailedFeedSha256
      || evidence.rollback_target_feed_sha256 !== contract.rollbackFeedSha256
      || evidence.stable_expected_sha256 !== contract.stableFeedSha256
      || evidence.beta_before_sha256 !== contract.expectedFailedFeedSha256
      || evidence.beta_after_sha256 !== (mode === "execute"
        ? contract.rollbackFeedSha256
        : contract.expectedFailedFeedSha256)
      || evidence.stable_before_sha256 !== contract.stableFeedSha256
      || evidence.stable_after_sha256 !== contract.stableFeedSha256
      || evidence.stable_untouched !== true) {
    throw new Error("[rollback] evidence archive is not bound to this exact rollback");
  }
  if (archive?.kind !== "elevate-realtor-beta-rollback-archive"
      || archive.mode !== mode || archive.candidate_id !== contract.candidateId
      || archive.rollback_id !== evidence.rollback_id
      || receiptId(archive, "archive_id") !== archive.archive_id) {
    throw new Error("[rollback] evidence archive manifest is invalid");
  }
  const expectedArchiveFiles = [
    "candidate-receipt.json",
    "public-after-beta-mac.yml",
    "public-after-latest-mac.yml",
    "public-before-beta-mac.yml",
    "public-before-latest-mac.yml",
    "retained-beta-mac.yml",
    "rollback.json",
  ];
  if (canonicalJson(Object.keys(archive.files || {}).sort()) !== canonicalJson(expectedArchiveFiles)) {
    throw new Error("[rollback] evidence archive file manifest is incomplete");
  }
  for (const [name, record] of Object.entries(archive.files || {})) {
    assertSafeBasename(name, "evidence archive file name");
    assertFileRecord(path.join(target, name), record, `evidence archive ${name}`);
    assertMode(path.join(target, name), 0o400, `evidence archive ${name}`);
  }
  assertMode(path.join(target, "archive.json"), 0o400, "evidence archive manifest");
  const receiptBytes = fs.readFileSync(path.join(target, "candidate-receipt.json"));
  const retainedFeedBytes = fs.readFileSync(path.join(target, "retained-beta-mac.yml"));
  if (!receiptBytes.equals(contract.receiptBytes) || !retainedFeedBytes.equals(contract.retainedFeedBytes)) {
    throw new Error("[rollback] evidence archive candidate bytes mismatch");
  }
  if (mode === "execute") {
    const expectedFreeze = {
      active_file: ROLLBACK_FREEZE_FILE,
      cleared_file: rollbackFreezeClearedFile(contract),
      freeze_id: rollbackFreezeRecord(contract).freeze_id,
      sha256: sha256(rollbackFreezeBytes(contract)),
      clear_after_execute_complete_archive: true,
    };
    if (canonicalJson(evidence.release_freeze) !== canonicalJson(expectedFreeze)) {
      throw new Error("[rollback] execute evidence release-freeze contract mismatch");
    }
    if (canonicalJson(Object.keys(evidence.public_aliases || {}).sort())
        !== canonicalJson([...contract.aliases].sort())
        || canonicalJson(Object.keys(evidence.public_versioned_artifacts || {}).sort())
        !== canonicalJson(contract.rollbackArtifacts.map((item) => item.name).sort())) {
      throw new Error("[rollback] execute evidence public artifact manifest is incomplete");
    }
    for (const alias of contract.aliases) {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      const expected = contract.rollbackDmgs[arch];
      const actual = evidence.public_aliases[alias];
      if (actual?.size !== expected.size || actual?.sha512 !== expected.sha512
          || actual?.source !== expected.url || !SHA256_RE.test(String(actual?.sha256 || ""))) {
        throw new Error(`[rollback] execute evidence alias mismatch: ${alias}`);
      }
    }
    for (const expected of contract.rollbackArtifacts) {
      const actual = evidence.public_versioned_artifacts[expected.name];
      if (actual?.size !== expected.size || actual?.sha512 !== expected.sha512
          || !SHA256_RE.test(String(actual?.sha256 || ""))) {
        throw new Error(`[rollback] execute evidence versioned artifact mismatch: ${expected.name}`);
      }
    }
  }
  if (archiveDirectoryMode === 0o700) fs.chmodSync(target, 0o500);
  assertMode(target, 0o500, "evidence archive directory");
  syncFile(target);
  syncFile(path.dirname(target));
  return { archivePath: target, evidence, archive };
}

function writeEvidenceArchive({
  contract,
  mode,
  evidenceRoot,
  startedAt,
  completedAt,
  before,
  after,
  aliases,
  versionedArtifacts,
  remote,
  host,
  remoteRoot,
}) {
  const evidenceBody = {
    schema_version: 1,
    kind: "elevate-realtor-beta-production-rollback",
    mode,
    ok: true,
    started_at: startedAt,
    completed_at: completedAt,
    candidate_id: contract.candidateId,
    source_receipt_id: contract.sourceReceiptId,
    candidate_receipt_sha256: contract.candidateReceiptSha256,
    failed_version: contract.failedVersion,
    expected_failed_candidate_feed_sha256: contract.expectedFailedFeedSha256,
    rollback_target_version: contract.rollbackVersion,
    rollback_target_feed_sha256: contract.rollbackFeedSha256,
    stable_expected_sha256: contract.stableFeedSha256,
    beta_before_sha256: before.beta.sha256,
    beta_after_sha256: after.beta.sha256,
    stable_before_sha256: before.stable.sha256,
    stable_after_sha256: after.stable.sha256,
    stable_untouched: before.stable.sha256 === after.stable.sha256
      && after.stable.sha256 === contract.stableFeedSha256,
    production_mutated: mode === "execute",
    profile_data_mutations: 0,
    rpo_seconds: 0,
    global_lock: GLOBAL_LOCK,
    remote_host: host,
    remote_root: remoteRoot,
    staging: { same_filesystem: true, mode: "0700", retained_feed_streamed_under_lock: true },
    committed_paths: mode === "execute" ? [...contract.aliases, BETA_FEED] : [],
    feed_committed_last: mode === "execute",
    stable_paths_written: [],
    backend_paths_written: [],
    profile_paths_written: [],
    failed_versioned_artifacts_retained: true,
    public_aliases: aliases,
    public_versioned_artifacts: versionedArtifacts,
    remote_completion_marker: remote.marker,
    release_freeze: mode === "execute" ? {
      active_file: ROLLBACK_FREEZE_FILE,
      cleared_file: rollbackFreezeClearedFile(contract),
      freeze_id: rollbackFreezeRecord(contract).freeze_id,
      sha256: sha256(rollbackFreezeBytes(contract)),
      clear_after_execute_complete_archive: true,
    } : null,
    procedure_id: REALTOR_BETA_ROLLBACK_PROCEDURE_ID,
  };
  evidenceBody.rollback_id = receiptId(evidenceBody, "rollback_id");

  const parent = evidenceParent(evidenceRoot, contract);
  fs.mkdirSync(parent, { recursive: true, mode: 0o700 });
  const stamp = completedAt.replaceAll(/[^0-9]/g, "").slice(0, 17);
  const target = mode === "execute"
    ? executeCompletePath(evidenceRoot, contract)
    : path.join(parent, `${stamp}-${mode}-${evidenceBody.rollback_id}`);
  if (fs.existsSync(target)) {
    if (mode === "execute") return loadEvidenceArchive({ contract, mode, target });
    throw new Error(`[rollback] immutable evidence archive already exists: ${target}`);
  }
  const temp = `${target}.tmp-${process.pid}-${crypto.randomUUID()}`;
  fs.mkdirSync(temp, { mode: 0o700 });
  let renamed = false;
  try {
    const files = {
      "candidate-receipt.json": contract.receiptBytes,
      ["retained-beta-mac.yml"]: contract.retainedFeedBytes,
      "public-before-beta-mac.yml": before.betaBytes,
      "public-before-latest-mac.yml": before.stableBytes,
      "public-after-beta-mac.yml": after.betaBytes,
      "public-after-latest-mac.yml": after.stableBytes,
    };
    for (const [name, bytes] of Object.entries(files)) writeExclusive(path.join(temp, name), bytes);
    writeExclusive(path.join(temp, "rollback.json"), Buffer.from(`${JSON.stringify(canonicalize(evidenceBody), null, 2)}\n`));
    const records = Object.fromEntries(
      fs.readdirSync(temp).sort().map((name) => [name, fileRecord(path.join(temp, name))]),
    );
    const archive = {
      schema_version: 1,
      kind: "elevate-realtor-beta-rollback-archive",
      rollback_id: evidenceBody.rollback_id,
      candidate_id: contract.candidateId,
      mode,
      files: records,
    };
    archive.archive_id = receiptId(archive, "archive_id");
    writeExclusive(path.join(temp, "archive.json"), Buffer.from(`${JSON.stringify(canonicalize(archive), null, 2)}\n`));
    for (const name of fs.readdirSync(temp)) {
      fs.chmodSync(path.join(temp, name), 0o400);
      syncFile(path.join(temp, name));
    }
    syncFile(temp);
    fs.renameSync(temp, target);
    renamed = true;
    fs.chmodSync(target, 0o500);
    syncFile(parent);
    return loadEvidenceArchive({ contract, mode, target });
  } catch (error) {
    if (!renamed) {
      fs.chmodSync(temp, 0o700);
      for (const name of fs.readdirSync(temp)) fs.chmodSync(path.join(temp, name), 0o600);
      fs.rmSync(temp, { recursive: true, force: true });
    }
    throw error;
  }
}

// ---------------------------------------------------------------------------
// Roll-forward recovery activation (procedure realtor-beta-recovery-roll-forward-v1)
//
// The second Beta recovery lane: advance the public Beta feed and all four
// Beta download aliases onto the retained 1.2.104 recovery package. Every
// expectation is bound to receipt.recovery; the payload bytes are exactly what
// the upload-first publish retention already committed on the update host
// (four versioned recovery artifacts plus the retained dot-feed), so
// activation needs no build-machine bytes and no operator-supplied hashes.
//
// Freeze interlock decision: the activation freeze reuses the shared active
// freeze path (.realtor-beta-rollback-freeze), so every publisher and the
// rollback lane fail closed while activation is in force, and a foreign freeze
// (rollback vs activation) is an exact-hash RELEASE_FREEZE_CONFLICT. After the
// freeze is retired, a stale ship of the superseded candidate still fails
// closed on its own compare-and-swap: the activated recovery feed matches
// neither that candidate's finalize snapshot nor its committed state
// (PUBLISH_STATE_NOT_OLD / PUBLISH_STATE_UNKNOWN). The rollback lane needs a
// permanent per-candidate publish tombstone because rollback restores the
// exact finalize snapshot a stale publisher would accept as "old"; activation
// moves the feed to bytes no publisher transaction trusts, so the freeze plus
// CAS is sufficient and is proven by test.
// ---------------------------------------------------------------------------

function recoveryActivationFreezeRecord(contract) {
  const values = {
    candidate_id: contract.candidateId,
    source_receipt_id: contract.sourceReceiptId,
    candidate_feed_sha256: contract.candidateFeedSha256,
    recovery_feed_sha256: contract.recoveryFeedSha256,
    stable_feed_sha256: contract.stableFeedSha256,
  };
  for (const [name, value] of Object.entries(values)) {
    assertSha256(value, `recovery activation freeze ${name}`);
  }
  const record = {
    schema_version: 1,
    kind: "elevate-realtor-beta-recovery-activation-release-freeze",
    ...values,
    procedure_id: REALTOR_BETA_RECOVERY_PROCEDURE_ID,
  };
  record.freeze_id = receiptId(record, "freeze_id");
  return record;
}

function recoveryActivationFreezeBytes(contract) {
  return Buffer.from(`${JSON.stringify(canonicalize(recoveryActivationFreezeRecord(contract)), null, 2)}\n`);
}

function recoveryActivationFreezeClearedFile(contract) {
  return `${ROLLBACK_FREEZE_FILE}.cleared-${recoveryActivationFreezeRecord(contract).freeze_id}`;
}

function recoveryRetainedFeedName(contract) {
  if (!/^\d+\.\d+\.\d+$/.test(String(contract.recoveryVersion || ""))) {
    throw new Error("[recover] invalid recovery version");
  }
  return realtorBetaRetainedRecoveryFeedName(contract.recoveryVersion, BETA_FEED);
}

function loadRecoveryActivationContract({ candidateReceiptPath, expectedCandidateReceiptSha256 }) {
  if (!candidateReceiptPath) throw new Error("[recover] explicit candidate receipt path is required");
  if (!fs.existsSync(candidateReceiptPath) || !fs.statSync(candidateReceiptPath).isFile()) {
    throw new Error(`[recover] candidate receipt is missing: ${candidateReceiptPath}`);
  }
  assertSha256(expectedCandidateReceiptSha256, "expected candidate receipt SHA256");
  const receiptBytes = fs.readFileSync(candidateReceiptPath);
  const actualReceiptSha256 = sha256(receiptBytes);
  if (actualReceiptSha256 !== expectedCandidateReceiptSha256) {
    throw new Error("[recover] candidate receipt SHA256 mismatch");
  }
  let receipt;
  try {
    receipt = JSON.parse(receiptBytes.toString("utf8"));
  } catch (error) {
    throw new Error(`[recover] candidate receipt is not valid JSON: ${error.message}`);
  }
  if (receipt?.schema_version !== 2 || receipt?.kind !== "elevate-final-candidate"
      || receiptId(receipt, "candidate_id") !== receipt.candidate_id) {
    throw new Error("[recover] invalid or forged final candidate receipt");
  }
  const release = receipt.release || {};
  if (release.channel !== "beta" || release.feed_name !== BETA_FEED
      || !/^\d+\.\d+\.\d+$/.test(String(release.version || ""))
      || release.profile?.channel !== "beta") {
    throw new Error("[recover] receipt is not an exact Beta candidate");
  }
  assertSha256(receipt.source_receipt_id, "source receipt ID");
  const aliases = Array.isArray(release.download_aliases) ? [...release.download_aliases].sort() : [];
  if (canonicalJson(aliases) !== canonicalJson([...EXPECTED_ALIASES].sort())) {
    throw new Error("[recover] candidate Beta alias contract mismatch");
  }
  const recovery = receipt.recovery;
  if (!recovery || typeof recovery !== "object") {
    throw new Error("[recover] receipt has no bound roll-forward recovery package");
  }
  if (recovery.kind !== "elevate-beta-recovery-package" || recovery.schema_version !== 1
      || recovery.channel !== "beta" || recovery.public_feed_name !== BETA_FEED
      || recovery.candidate_version !== release.version
      || recovery.source_receipt_id !== receipt.source_receipt_id) {
    throw new Error("[recover] recovery package is not bound to this exact candidate");
  }
  if (recovery.version !== EXPECTED_RECOVERY_VERSION
      || recovery.reserved_version !== EXPECTED_RECOVERY_VERSION
      || compareSemver(recovery.version, release.version) <= 0) {
    throw new Error(`[recover] recovery target must be exact Beta ${EXPECTED_RECOVERY_VERSION}, strictly newer than the candidate`);
  }
  const runtimePolicy = recovery.static_provenance?.runtime_policy || {};
  if (["backend", "cli", "gateway", "runtime", "tools"].some((key) => runtimePolicy[key] !== false)
      || runtimePolicy.profile_preserved !== true) {
    throw new Error("[recover] recovery runtime policy is not the minimal profile-preserving contract");
  }
  const feedRecord = receipt.artifacts?.[BETA_FEED];
  assertSha256(feedRecord?.sha256, "candidate Beta feed SHA256");
  assertSha256(recovery.local_feed?.sha256, "recovery feed SHA256");
  if (recovery.local_feed.sha256 === feedRecord.sha256) {
    throw new Error("[recover] recovery feed reuses the candidate feed bytes");
  }
  const snapshots = receipt.public_feeds_at_finalize;
  if (snapshots?.latest?.status !== 200 || snapshots.latest.channel !== "latest"
      || !String(snapshots.latest.version || "")) {
    throw new Error("[recover] candidate has no valid Stable snapshot");
  }
  assertSha256(snapshots.latest.sha256, "Stable snapshot SHA256");

  const candidateArtifacts = (release.artifact_names || []).map((name) => {
    assertSafeBasename(name, "candidate artifact name");
    return assertCandidateArtifactRecord(receipt.artifacts?.[name], name);
  }).sort((left, right) => left.name.localeCompare(right.name, "en"));
  if (candidateArtifacts.length !== 4) throw new Error("[recover] candidate must contain exactly four updater artifacts");
  const expectedCandidateNames = ["x64", "arm64"].flatMap((arch) => ["zip", "dmg"].map(
    (extension) => `Elevate-Beta-${release.version}-mac-${arch}.${extension}`,
  )).sort();
  if (canonicalJson(candidateArtifacts.map((item) => item.name)) !== canonicalJson(expectedCandidateNames)) {
    throw new Error("[recover] candidate artifact names are not the exact Beta set");
  }
  const candidateDmgs = {};
  for (const arch of ["x64", "arm64"]) {
    const dmg = candidateArtifacts.find((item) => item.name.endsWith(`-mac-${arch}.dmg`));
    if (!dmg) throw new Error(`[recover] candidate is missing the ${arch} versioned DMG`);
    candidateDmgs[arch] = dmg;
  }

  const expectedRecoveryNames = ["x64", "arm64"].flatMap((arch) => ["zip", "dmg"].map(
    (extension) => `Elevate-Beta-Recovery-${recovery.version}-mac-${arch}.${extension}`,
  )).sort();
  const recoveryNames = Array.isArray(recovery.artifact_names) ? [...recovery.artifact_names].sort() : [];
  if (canonicalJson(recoveryNames) !== canonicalJson(expectedRecoveryNames)) {
    throw new Error("[recover] recovery artifact names are not the exact retained recovery set");
  }
  const knownHashes = new Set([feedRecord.sha256, recovery.local_feed.sha256, ...candidateArtifacts.map((item) => item.sha256)]);
  const recoveryArtifacts = recoveryNames.map((name) => {
    assertSafeBasename(name, "recovery artifact name");
    const record = assertCandidateArtifactRecord(recovery.artifacts?.[name], name);
    if (knownHashes.has(record.sha256)) {
      throw new Error(`[recover] recovery artifact reuses candidate bytes: ${name}`);
    }
    knownHashes.add(record.sha256);
    return record;
  });
  const recoveryDmgs = {};
  for (const arch of ["x64", "arm64"]) {
    const dmg = recoveryArtifacts.find((item) => item.name.endsWith(`-mac-${arch}.dmg`));
    if (!dmg) throw new Error(`[recover] recovery package is missing the ${arch} versioned DMG`);
    recoveryDmgs[arch] = { ...dmg, url: dmg.name };
  }

  const recoveryFeedFiles = recoveryArtifacts.map((item) => ({ url: item.name, size: item.size, sha512: item.sha512 }));
  const manifest = recovery.local_feed.manifest;
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)
      || String(manifest.version || "") !== recovery.version) {
    throw new Error("[recover] recovery feed manifest version mismatch");
  }
  const manifestFiles = normalizedFiles(manifest.files, "recovery feed manifest");
  if (canonicalJson(manifestFiles) !== canonicalJson(recoveryFeedFiles)) {
    throw new Error("[recover] recovery feed manifest does not match the receipt-bound recovery artifacts");
  }
  const primary = recoveryFeedFiles.find((item) => item.url.endsWith("-mac-x64.zip"));
  if (!primary || manifest.path !== primary.url || manifest.sha512 !== primary.sha512) {
    throw new Error("[recover] recovery feed primary updater path/sha512 mismatch");
  }

  const candidateFeedFiles = candidateArtifacts.map((item) => ({ url: item.name, size: item.size, sha512: item.sha512 }));
  const contract = {
    receipt,
    receiptBytes,
    candidateId: receipt.candidate_id,
    sourceReceiptId: receipt.source_receipt_id,
    candidateReceiptSha256: actualReceiptSha256,
    candidateVersion: release.version,
    recoveryVersion: recovery.version,
    candidateFeedSha256: feedRecord.sha256,
    recoveryFeedSha256: recovery.local_feed.sha256,
    stableFeedSha256: snapshots.latest.sha256,
    candidateSnapshot: { version: release.version, sha256: feedRecord.sha256, files: candidateFeedFiles },
    recoverySnapshot: { version: recovery.version, sha256: recovery.local_feed.sha256, files: recoveryFeedFiles },
    stableSnapshot: snapshots.latest,
    candidateArtifacts,
    candidateDmgs,
    recoveryArtifacts,
    recoveryDmgs,
    aliases: EXPECTED_ALIASES,
  };
  contract.retainedFeedName = recoveryRetainedFeedName(contract);
  return contract;
}

function assertRecoveryRemoteInputs(remoteRoot, stagingName, mode) {
  if (!/^\/[A-Za-z0-9._/-]+\/$/.test(remoteRoot) || remoteRoot.split("/").includes("..")) {
    throw new Error("[recover] unsafe remote update root");
  }
  const validStage = mode === "execute"
    ? new RegExp(`^\\.recovery-[a-f0-9]{64}-execute$`).test(stagingName || "")
    : new RegExp(`^\\.recovery-[a-f0-9]{64}-[a-f0-9-]{36}$`).test(stagingName || "");
  if (mode !== "preflight" && !validStage) {
    throw new Error("[recover] unsafe recovery staging name");
  }
}

function recoveryArtifactToken(item) {
  const arch = item.name.includes("-arm64.") ? "ARM64" : "X64";
  const kind = item.name.endsWith(".zip") ? "ZIP" : "DMG";
  return `${arch}_${kind}`;
}

function recoveryStaticChecks({ contract, root, q }) {
  const retainedPath = `${root}${recoveryRetainedFeedName(contract)}`;
  const checks = [
    `assert_sha256 ${q(`${root}${STABLE_FEED}`)} ${q(contract.stableFeedSha256)} STABLE_CAS_FAILED`,
    `assert_sha256 ${q(retainedPath)} ${q(contract.recoveryFeedSha256)} RETAINED_RECOVERY_FEED_MISMATCH`,
  ];
  for (const item of contract.recoveryArtifacts) {
    checks.push(
      `assert_size_sha512 ${q(`${root}${item.name}`)} ${q(item.size)} ${q(sha512Hex(item.sha512, item.name))} ${q(`RECOVERY_${recoveryArtifactToken(item)}_MISMATCH`)}`,
      `assert_sha256 ${q(`${root}${item.name}`)} ${q(item.sha256)} ${q(`RECOVERY_${recoveryArtifactToken(item)}_SHA256_MISMATCH`)}`,
    );
  }
  for (const item of contract.candidateArtifacts) {
    checks.push(
      `assert_size_sha512 ${q(`${root}${item.name}`)} ${q(item.size)} ${q(sha512Hex(item.sha512, item.name))} ${q(`CANDIDATE_${recoveryArtifactToken(item)}_MISMATCH`)}`,
      `assert_sha256 ${q(`${root}${item.name}`)} ${q(item.sha256)} ${q(`CANDIDATE_${recoveryArtifactToken(item)}_SHA256_MISMATCH`)}`,
    );
  }
  return checks;
}

function buildRemoteRecoveryExecuteScript({ contract, remoteRoot, stagingName }) {
  assertRecoveryRemoteInputs(remoteRoot, stagingName, "execute");
  const q = shellQuote;
  const root = remoteRoot;
  const stage = `${root}${stagingName}/`;
  const betaPath = `${root}${BETA_FEED}`;
  const retainedPath = `${root}${recoveryRetainedFeedName(contract)}`;
  const freezePath = `${root}${ROLLBACK_FREEZE_FILE}`;
  const clearedFreezePath = `${root}${recoveryActivationFreezeClearedFile(contract)}`;
  const freezeBytes = recoveryActivationFreezeBytes(contract);
  const freezeSha256 = sha256(freezeBytes);
  const journal = {
    schema_version: 1,
    kind: "elevate-realtor-beta-recovery-activation-transaction",
    candidate_id: contract.candidateId,
    candidate_feed_sha256: contract.candidateFeedSha256,
    recovery_feed_sha256: contract.recoveryFeedSha256,
    stable_feed_sha256: contract.stableFeedSha256,
    retained_recovery_feed_name: recoveryRetainedFeedName(contract),
    aliases: contract.aliases,
    procedure_id: REALTOR_BETA_RECOVERY_PROCEDURE_ID,
  };
  journal.transaction_id = receiptId(journal, "transaction_id");
  const journalBytes = Buffer.from(`${JSON.stringify(canonicalize(journal), null, 2)}\n`);
  const journalSha256 = sha256(journalBytes);
  const currentStateChecks = [
    `hash_is ${q(betaPath)} ${q(contract.candidateFeedSha256)}`,
    ...contract.aliases.map((alias) => {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      return `hash_is ${q(`${root}${alias}`)} ${q(contract.candidateDmgs[arch].sha256)}`;
    }),
  ];
  const recoveryStateChecks = [
    `hash_is ${q(betaPath)} ${q(contract.recoveryFeedSha256)}`,
    ...contract.aliases.map((alias) => {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      return `same_bytes ${q(`${root}${contract.recoveryDmgs[arch].url}`)} ${q(`${root}${alias}`)}`;
    }),
  ];
  const knownPointerChecks = [
    `( hash_is ${q(betaPath)} ${q(contract.candidateFeedSha256)} || hash_is ${q(betaPath)} ${q(contract.recoveryFeedSha256)} )`,
    ...contract.aliases.map((alias) => {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      return `( hash_is ${q(`${root}${alias}`)} ${q(contract.candidateDmgs[arch].sha256)} || same_bytes ${q(`${root}${contract.recoveryDmgs[arch].url}`)} ${q(`${root}${alias}`)} )`;
    }),
  ];
  const staticChecks = recoveryStaticChecks({ contract, root, q });
  const backupChecks = [
    `assert_sha256 ${q(`${stage}backups/${BETA_FEED}`)} ${q(contract.candidateFeedSha256)} BACKUP_FEED_MISMATCH`,
    ...contract.aliases.map((alias) => {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      return `assert_sha256 ${q(`${stage}backups/${alias}`)} ${q(contract.candidateDmgs[arch].sha256)} ${q(`BACKUP_ALIAS_MISMATCH_${alias}`)}`;
    }),
  ];
  const restoreCalls = [
    ...contract.aliases.map((alias) => (
      `  restore_one ${q(`${stage}backups/${alias}`)} ${q(`${root}${alias}`)} ${q(`${stage}restore-${alias}`)} || return 1`
    )),
    `  restore_one ${q(`${stage}backups/${BETA_FEED}`)} ${q(betaPath)} ${q(`${stage}restore-${BETA_FEED}`)} || return 1`,
  ];

  const lines = [
    "set -euo pipefail",
    "umask 077",
    "fail() { echo \"RECOVERY_FAIL $1\" >&2; exit \"${2:-50}\"; }",
    "sha256_of() { sha256sum -- \"$1\" | awk '{print $1}'; }",
    "sha512_of() { sha512sum -- \"$1\" | awk '{print $1}'; }",
    "file_size() { stat -c %s -- \"$1\" 2>/dev/null || stat -f %z \"$1\"; }",
    "file_device() { stat -c %d -- \"$1\" 2>/dev/null || stat -f %d \"$1\"; }",
    "file_mode() { stat -c %a -- \"$1\" 2>/dev/null || stat -f %Lp \"$1\"; }",
    "file_uid() { stat -c %u -- \"$1\" 2>/dev/null || stat -f %u \"$1\"; }",
    "file_gid() { stat -c %g -- \"$1\" 2>/dev/null || stat -f %g \"$1\"; }",
    "assert_directory() { test -d \"$1\" && test ! -L \"$1\" || fail \"$2\" 51; }",
    "assert_regular() { test -f \"$1\" && test ! -L \"$1\" || fail \"$2\" 52; }",
    "hash_is() { test -f \"$1\" && test ! -L \"$1\" && test \"$(sha256_of \"$1\")\" = \"$2\"; }",
    "same_bytes() { test -f \"$1\" && test ! -L \"$1\" && test -f \"$2\" && test ! -L \"$2\" && cmp -s -- \"$1\" \"$2\"; }",
    "assert_sha256() { assert_regular \"$1\" \"$3\"; test \"$(sha256_of \"$1\")\" = \"$2\" || fail \"$3\" 53; }",
    "assert_size_sha512() { assert_regular \"$1\" \"$4\"; test \"$(file_size \"$1\")\" = \"$2\" || fail \"$4\" 54; test \"$(sha512_of \"$1\")\" = \"$3\" || fail \"$4\" 55; }",
    "copy_metadata() { chmod \"$(file_mode \"$1\")\" \"$2\" && chown \"$(file_uid \"$1\"):$(file_gid \"$1\")\" \"$2\"; }",
    "durable_sync() { sync -f \"$1\" 2>/dev/null || sync; }",
    "atomic_replace() { mv -f -- \"$1\" \"$2\"; }",
    "current_state_ok() {",
    ...currentStateChecks.map((line) => `  ${line} || return 1`),
    "}",
    "recovery_state_ok() {",
    ...recoveryStateChecks.map((line) => `  ${line} || return 1`),
    "}",
    "beta_feed_recognized() {",
    `  hash_is ${q(betaPath)} ${q(contract.candidateFeedSha256)} || hash_is ${q(betaPath)} ${q(contract.recoveryFeedSha256)}`,
    "}",
    "known_pointer_state_ok() {",
    ...knownPointerChecks.map((line) => `  ${line} || return 1`),
    "}",
    "stage_payload_ok() {",
    `  hash_is ${q(`${stage}recovery-${BETA_FEED}`)} ${q(contract.recoveryFeedSha256)} || return 1`,
    ...contract.aliases.map((alias) => {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      return `  hash_is ${q(`${stage}backups/${alias}`)} ${q(contract.candidateDmgs[arch].sha256)} || return 1`;
    }),
    `  hash_is ${q(`${stage}backups/${BETA_FEED}`)} ${q(contract.candidateFeedSha256)} || return 1`,
    "}",
    "restore_one() {",
    "  src=$1; dest=$2; temp=$3",
    "  rm -f -- \"$temp\" || return 1",
    "  cp -- \"$src\" \"$temp\" || return 1",
    "  copy_metadata \"$src\" \"$temp\" || return 1",
    "  durable_sync \"$temp\" || return 1",
    "  mv -f -- \"$temp\" \"$dest\" || return 1",
    `  durable_sync ${q(root)} || return 1`,
    "}",
    "restore_current_state() {",
    ...restoreCalls,
    "  current_state_ok",
    "}",
    "retire_stage() {",
    `  tombstone=${q(stage.slice(0, -1))}.retired.$$.$RANDOM`,
    "  test ! -e \"$tombstone\" || return 1",
    `  mv -- ${q(stage)} \"$tombstone\" || return 1`,
    `  durable_sync ${q(root)} || return 1`,
    "  rm -rf -- \"$tombstone\" || true",
    "}",
    `assert_directory ${q(root)} REMOTE_ROOT_INVALID`,
    `assert_sha256 ${q(`${root}${STABLE_FEED}`)} ${q(contract.stableFeedSha256)} STABLE_CAS_FAILED`,
    "mutation_started=0",
    "committed=0",
    "freeze_present=0",
    "stage_new=0",
    "stage_trusted=0",
    "cleanup() {",
    "  rc=$?",
    "  trap - EXIT HUP INT TERM",
    "  set +e",
    "  if test \"$mutation_started\" = 1 && test \"$committed\" = 0; then",
    "    if restore_current_state && current_state_ok; then",
    "      if retire_stage; then echo RECOVERY_COMPENSATION_OK >&2; else rc=97; echo RECOVERY_STAGE_RETIRE_FAILED >&2; fi",
    "    else",
    "      rc=96",
    "      echo RECOVERY_COMPENSATION_FAILED_STAGE_PRESERVED >&2",
    "    fi",
    "  elif test \"$committed\" = 1; then",
    `    if test -e ${q(stage)}; then retire_stage || rc=97; fi`,
    "  elif test \"$stage_new\" = 1 && test \"$stage_trusted\" = 0; then",
    "    retire_stage || rc=97",
    "  fi",
    "  exit \"$rc\"",
    "}",
    "trap cleanup EXIT HUP INT TERM",
    `if test -e ${q(clearedFreezePath)} || test -L ${q(clearedFreezePath)}; then`,
    `  assert_sha256 ${q(clearedFreezePath)} ${q(freezeSha256)} RELEASE_FREEZE_CLEARED_CONFLICT`,
    `  if test -e ${q(freezePath)} || test -L ${q(freezePath)}; then fail RELEASE_FREEZE_STATE_CONFLICT 66; fi`,
    `  durable_sync ${q(clearedFreezePath)}`,
    `  durable_sync ${q(root)}`,
    "  committed=2",
    '  echo "REMOTE_RECOVERY_EXECUTE_OK state=freeze_already_cleared"',
    "  exit 0",
    "fi",
    `if test -e ${q(freezePath)} || test -L ${q(freezePath)}; then`,
    `  assert_sha256 ${q(freezePath)} ${q(freezeSha256)} RELEASE_FREEZE_CONFLICT`,
    `  durable_sync ${q(freezePath)}`,
    `  durable_sync ${q(root)}`,
    "  freeze_present=1",
    "fi",
    `if test -e ${q(stage)}; then`,
    `  assert_directory ${q(stage)} STAGE_INVALID`,
    `  test \"$(file_device ${q(root)})\" = \"$(file_device ${q(stage)})\" || fail STAGE_CROSS_FILESYSTEM 57`,
    `  test \"$(file_mode ${q(stage)})\" = 700 || fail STAGE_MODE_INVALID 58`,
    `  if ! hash_is ${q(`${stage}transaction.json`)} ${q(journalSha256)}; then`,
    "    if current_state_ok || recovery_state_ok; then",
    "      retire_stage || fail STAGE_RETIRE_FAILED 65",
    "    else",
    "      fail UNTRUSTED_STAGE_WITH_PARTIAL_PUBLIC_STATE 62",
    "    fi",
    "  else",
    "    stage_trusted=1",
    "    if current_state_ok && ! stage_payload_ok; then",
    "      retire_stage || fail STAGE_RETIRE_FAILED 65",
    "      stage_trusted=0",
    "    fi",
    "  fi",
    "fi",
    `if test \"$stage_trusted\" = 0 && ! test -e ${q(stage)}; then`,
    "  if recovery_state_ok; then",
    "    test \"$freeze_present\" = 1 || fail COMMITTED_STATE_WITHOUT_RELEASE_FREEZE 68",
    ...staticChecks.map((line) => `    ${line}`),
    "    committed=2",
    '    echo "REMOTE_RECOVERY_EXECUTE_OK state=already_committed"',
    "    exit 0",
    "  fi",
    // Same operator-distinct split as the rollback lane: a still-recognized
    // candidate/recovery feed hash is a genuinely partial pointer state, while
    // an unrecognized feed means a newer or cross-lane release won the Beta
    // pointer and nothing is orphaned.
    "  if ! current_state_ok; then",
    "    if beta_feed_recognized; then fail PARTIAL_PUBLIC_POINTER_STATE 63; else fail UNRECOGNIZED_BETA_FEED_STATE 63; fi",
    "  fi",
    ...staticChecks.map((line) => `  ${line}`),
    `  mkdir -m 0700 -- ${q(stage)}`,
    "  stage_new=1",
    `  test \"$(file_device ${q(root)})\" = \"$(file_device ${q(stage)})\" || fail STAGE_CROSS_FILESYSTEM 57`,
    `  test \"$(file_mode ${q(stage)})\" = 700 || fail STAGE_MODE_INVALID 58`,
    `  cp -- ${q(retainedPath)} ${q(`${stage}recovery-${BETA_FEED}`)}`,
    `  assert_sha256 ${q(`${stage}recovery-${BETA_FEED}`)} ${q(contract.recoveryFeedSha256)} RETAINED_RECOVERY_FEED_MISMATCH`,
    `  mkdir -m 0700 -- ${q(`${stage}backups`)}`,
    `  cp -- ${q(betaPath)} ${q(`${stage}backups/${BETA_FEED}`)}`,
    `  copy_metadata ${q(betaPath)} ${q(`${stage}backups/${BETA_FEED}`)}`,
  ];
  for (const alias of contract.aliases) {
    lines.push(
      `  cp -- ${q(`${root}${alias}`)} ${q(`${stage}backups/${alias}`)}`,
      `  copy_metadata ${q(`${root}${alias}`)} ${q(`${stage}backups/${alias}`)}`,
    );
  }
  lines.push(
    ...backupChecks.map((line) => `  ${line}`),
    `  durable_sync ${q(stage)}`,
    `  printf %s ${q(journalBytes.toString("utf8"))} > ${q(`${stage}transaction.json.tmp`)}`,
    `  assert_sha256 ${q(`${stage}transaction.json.tmp`)} ${q(journalSha256)} JOURNAL_HASH_MISMATCH`,
    `  mv -f -- ${q(`${stage}transaction.json.tmp`)} ${q(`${stage}transaction.json`)}`,
    `  durable_sync ${q(stage)}`,
    "  stage_trusted=1",
    "fi",
    `if test \"$stage_trusted\" = 1; then`,
    ...staticChecks.map((line) => `  ${line}`),
    "  if recovery_state_ok; then",
    "    test \"$freeze_present\" = 1 || fail COMMITTED_STATE_WITHOUT_RELEASE_FREEZE 68",
    "    committed=1",
    '    echo "REMOTE_RECOVERY_EXECUTE_OK state=recovered_committed"',
    "    exit 0",
    "  fi",
    `  assert_sha256 ${q(`${stage}transaction.json`)} ${q(journalSha256)} JOURNAL_HASH_MISMATCH`,
    `  assert_sha256 ${q(`${stage}recovery-${BETA_FEED}`)} ${q(contract.recoveryFeedSha256)} RETAINED_RECOVERY_FEED_MISMATCH`,
    ...backupChecks.map((line) => `  ${line}`),
    `  durable_sync ${q(stage)}`,
    `  durable_sync ${q(root)}`,
    "  known_pointer_state_ok || fail UNKNOWN_PARTIAL_PUBLIC_STATE 64",
    `  rm -rf -- ${q(`${stage}next`)}`,
    `  mkdir -m 0700 -- ${q(`${stage}next`)}`,
    `  cp -- ${q(`${stage}recovery-${BETA_FEED}`)} ${q(`${stage}next/${BETA_FEED}`)}`,
    `  copy_metadata ${q(`${stage}backups/${BETA_FEED}`)} ${q(`${stage}next/${BETA_FEED}`)}`,
  );
  for (const alias of contract.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    lines.push(
      `  cp -- ${q(`${root}${contract.recoveryDmgs[arch].url}`)} ${q(`${stage}next/${alias}`)}`,
      `  copy_metadata ${q(`${stage}backups/${alias}`)} ${q(`${stage}next/${alias}`)}`,
      `  same_bytes ${q(`${root}${contract.recoveryDmgs[arch].url}`)} ${q(`${stage}next/${alias}`)} || fail ${q(`STAGED_ALIAS_MISMATCH_${alias}`)} 59`,
    );
  }
  lines.push(
    `  assert_sha256 ${q(`${stage}next/${BETA_FEED}`)} ${q(contract.recoveryFeedSha256)} STAGED_FEED_MISMATCH`,
    `  durable_sync ${q(`${stage}next`)}`,
    "  if test \"$freeze_present\" = 0; then",
    "    current_state_ok || fail PARTIAL_STATE_WITHOUT_RELEASE_FREEZE 69",
    `    rm -f -- ${q(`${freezePath}.tmp`)}`,
    `    printf %s ${q(freezeBytes.toString("utf8"))} > ${q(`${freezePath}.tmp`)}`,
    `    assert_sha256 ${q(`${freezePath}.tmp`)} ${q(freezeSha256)} RELEASE_FREEZE_HASH_MISMATCH`,
    `    mv -f -- ${q(`${freezePath}.tmp`)} ${q(freezePath)}`,
    `    durable_sync ${q(freezePath)}`,
    `    durable_sync ${q(root)}`,
    "    freeze_present=1",
    "  fi",
    "  mutation_started=1",
  );
  for (const alias of contract.aliases) {
    lines.push(`  atomic_replace ${q(`${stage}next/${alias}`)} ${q(`${root}${alias}`)}`);
  }
  lines.push(
    `  atomic_replace ${q(`${stage}next/${BETA_FEED}`)} ${q(betaPath)}`,
    `  durable_sync ${q(root)}`,
    `  assert_sha256 ${q(betaPath)} ${q(contract.recoveryFeedSha256)} COMMITTED_FEED_MISMATCH`,
  );
  for (const alias of contract.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    lines.push(
      `  same_bytes ${q(`${root}${contract.recoveryDmgs[arch].url}`)} ${q(`${root}${alias}`)} || fail ${q(`COMMITTED_ALIAS_MISMATCH_${alias}`)} 61`,
    );
  }
  lines.push(
    ...staticChecks.map((line) => `  ${line}`),
    "  committed=1",
    "  mutation_started=0",
    '  echo "REMOTE_RECOVERY_EXECUTE_OK state=committed"',
    "fi",
  );
  return lines.join("\n");
}

function buildRemoteRecoveryFreezeClearInnerScript({ contract, remoteRoot = DEFAULT_REMOTE_ROOT }) {
  assertRecoveryRemoteInputs(remoteRoot, null, "preflight");
  const q = shellQuote;
  const root = remoteRoot;
  const betaPath = `${root}${BETA_FEED}`;
  const freezePath = `${root}${ROLLBACK_FREEZE_FILE}`;
  const clearedFreezePath = `${root}${recoveryActivationFreezeClearedFile(contract)}`;
  const freezeBytes = recoveryActivationFreezeBytes(contract);
  const freezeSha256 = sha256(freezeBytes);
  const stateChecks = [
    ...recoveryStaticChecks({ contract, root, q }),
    `assert_sha256 ${q(betaPath)} ${q(contract.recoveryFeedSha256)} RECOVERY_BETA_CAS_FAILED`,
  ];
  for (const alias of contract.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    stateChecks.push(
      `same_bytes ${q(`${root}${contract.recoveryDmgs[arch].url}`)} ${q(`${root}${alias}`)} || fail ${q(`RECOVERY_ALIAS_MISMATCH_${alias}`)} 61`,
    );
  }

  return [
    "set -euo pipefail",
    "umask 077",
    "fail() { echo \"RECOVERY_FAIL $1\" >&2; exit \"${2:-50}\"; }",
    "sha256_of() { sha256sum -- \"$1\" | awk '{print $1}'; }",
    "sha512_of() { sha512sum -- \"$1\" | awk '{print $1}'; }",
    "file_size() { stat -c %s -- \"$1\" 2>/dev/null || stat -f %z \"$1\"; }",
    "assert_directory() { test -d \"$1\" && test ! -L \"$1\" || fail \"$2\" 51; }",
    "assert_regular() { test -f \"$1\" && test ! -L \"$1\" || fail \"$2\" 52; }",
    "assert_sha256() { assert_regular \"$1\" \"$3\"; test \"$(sha256_of \"$1\")\" = \"$2\" || fail \"$3\" 53; }",
    "assert_size_sha512() { assert_regular \"$1\" \"$4\"; test \"$(file_size \"$1\")\" = \"$2\" || fail \"$4\" 54; test \"$(sha512_of \"$1\")\" = \"$3\" || fail \"$4\" 55; }",
    "same_bytes() { test -f \"$1\" && test ! -L \"$1\" && test -f \"$2\" && test ! -L \"$2\" && cmp -s -- \"$1\" \"$2\"; }",
    "durable_sync() { sync -f \"$1\" 2>/dev/null || sync; }",
    `assert_directory ${q(root)} REMOTE_ROOT_INVALID`,
    `if test -e ${q(clearedFreezePath)} || test -L ${q(clearedFreezePath)}; then`,
    `  assert_sha256 ${q(clearedFreezePath)} ${q(freezeSha256)} RELEASE_FREEZE_CLEARED_CONFLICT`,
    `  durable_sync ${q(clearedFreezePath)}`,
    `  durable_sync ${q(root)}`,
    `  if test -e ${q(freezePath)} || test -L ${q(freezePath)}; then`,
    `    assert_sha256 ${q(freezePath)} ${q(freezeSha256)} RELEASE_FREEZE_CONFLICT`,
    `    rm -f -- ${q(freezePath)}`,
    `    durable_sync ${q(root)}`,
    '    echo "REMOTE_RECOVERY_FREEZE_CLEAR_OK state=completed_clear"',
    "    exit 0",
    "  fi",
    '  echo "REMOTE_RECOVERY_FREEZE_CLEAR_OK state=already_cleared"',
    "  exit 0",
    "fi",
    `if ! test -e ${q(freezePath)} && ! test -L ${q(freezePath)}; then fail RELEASE_FREEZE_MISSING 70; fi`,
    `assert_sha256 ${q(freezePath)} ${q(freezeSha256)} RELEASE_FREEZE_CONFLICT`,
    ...stateChecks,
    `rm -f -- ${q(`${clearedFreezePath}.tmp`)}`,
    `cp -- ${q(freezePath)} ${q(`${clearedFreezePath}.tmp`)}`,
    `assert_sha256 ${q(`${clearedFreezePath}.tmp`)} ${q(freezeSha256)} RELEASE_FREEZE_CLEARED_HASH_MISMATCH`,
    `chmod 0400 ${q(`${clearedFreezePath}.tmp`)}`,
    `durable_sync ${q(`${clearedFreezePath}.tmp`)}`,
    `mv -- ${q(`${clearedFreezePath}.tmp`)} ${q(clearedFreezePath)}`,
    `durable_sync ${q(clearedFreezePath)}`,
    `durable_sync ${q(root)}`,
    `rm -f -- ${q(freezePath)}`,
    `durable_sync ${q(root)}`,
    'echo "REMOTE_RECOVERY_FREEZE_CLEAR_OK state=cleared"',
  ].join("\n");
}

function buildRemoteRecoveryInnerScript({ contract, mode, remoteRoot = DEFAULT_REMOTE_ROOT, stagingName = null }) {
  if (!MODES.has(mode)) throw new Error(`[recover] unsupported mode: ${mode}`);
  assertRecoveryRemoteInputs(remoteRoot, stagingName, mode);
  if (mode === "execute") {
    return buildRemoteRecoveryExecuteScript({ contract, remoteRoot, stagingName });
  }
  const q = shellQuote;
  const root = remoteRoot;
  const stage = stagingName ? `${root}${stagingName}/` : null;
  const betaPath = `${root}${BETA_FEED}`;
  const retainedPath = `${root}${recoveryRetainedFeedName(contract)}`;

  const commonChecks = [
    `assert_directory ${q(root)} REMOTE_ROOT_INVALID`,
    ...recoveryStaticChecks({ contract, root, q }),
    `assert_sha256 ${q(betaPath)} ${q(contract.candidateFeedSha256)} CANDIDATE_BETA_CAS_FAILED`,
  ];
  for (const alias of contract.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    commonChecks.push(
      `assert_sha256 ${q(`${root}${alias}`)} ${q(contract.candidateDmgs[arch].sha256)} ${q(`CANDIDATE_ALIAS_CAS_${alias}`)}`,
    );
  }

  const lines = [
    "set -euo pipefail",
    "umask 077",
    "fail() { echo \"RECOVERY_FAIL $1\" >&2; exit \"${2:-50}\"; }",
    "sha256_of() { sha256sum -- \"$1\" | awk '{print $1}'; }",
    "sha512_of() { sha512sum -- \"$1\" | awk '{print $1}'; }",
    "file_size() { stat -c %s -- \"$1\" 2>/dev/null || stat -f %z \"$1\"; }",
    "file_device() { stat -c %d -- \"$1\" 2>/dev/null || stat -f %d \"$1\"; }",
    "file_mode() { stat -c %a -- \"$1\" 2>/dev/null || stat -f %Lp \"$1\"; }",
    "file_uid() { stat -c %u -- \"$1\" 2>/dev/null || stat -f %u \"$1\"; }",
    "file_gid() { stat -c %g -- \"$1\" 2>/dev/null || stat -f %g \"$1\"; }",
    "assert_directory() { test -d \"$1\" && test ! -L \"$1\" || fail \"$2\" 51; }",
    "assert_regular() { test -f \"$1\" && test ! -L \"$1\" || fail \"$2\" 52; }",
    "assert_sha256() { assert_regular \"$1\" \"$3\"; test \"$(sha256_of \"$1\")\" = \"$2\" || fail \"$3\" 53; }",
    "assert_size_sha512() { assert_regular \"$1\" \"$4\"; test \"$(file_size \"$1\")\" = \"$2\" || fail \"$4\" 54; test \"$(sha512_of \"$1\")\" = \"$3\" || fail \"$4\" 55; }",
    "same_bytes() { test -f \"$1\" && test ! -L \"$1\" && test -f \"$2\" && test ! -L \"$2\" && cmp -s -- \"$1\" \"$2\"; }",
    "copy_metadata() { chmod \"$(file_mode \"$1\")\" \"$2\"; chown \"$(file_uid \"$1\"):$(file_gid \"$1\")\" \"$2\"; }",
    "atomic_replace() { mv -f -- \"$1\" \"$2\"; }",
    ...commonChecks,
  ];

  if (mode === "preflight") {
    lines.push('echo "REMOTE_RECOVERY_PREFLIGHT_OK"');
    return lines.join("\n");
  }

  lines.push(
    `test ! -e ${q(stage)} || fail STAGE_COLLISION 56`,
    `mkdir -m 0700 -- ${q(stage)}`,
    "cleanup() {",
    "  rc=$?",
    "  trap - EXIT HUP INT TERM",
    `  rm -rf -- ${q(stage)}`,
    "  exit \"$rc\"",
    "}",
    "trap cleanup EXIT HUP INT TERM",
    `test \"$(file_device ${q(root)})\" = \"$(file_device ${q(stage)})\" || fail STAGE_CROSS_FILESYSTEM 57`,
    `test \"$(file_mode ${q(stage)})\" = 700 || fail STAGE_MODE_INVALID 58`,
    `cp -- ${q(retainedPath)} ${q(`${stage}${BETA_FEED}`)}`,
    `copy_metadata ${q(betaPath)} ${q(`${stage}${BETA_FEED}`)}`,
    `assert_sha256 ${q(`${stage}${BETA_FEED}`)} ${q(contract.recoveryFeedSha256)} RETAINED_RECOVERY_FEED_MISMATCH`,
  );
  for (const alias of contract.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    lines.push(
      `cp -- ${q(`${root}${contract.recoveryDmgs[arch].url}`)} ${q(`${stage}${alias}`)}`,
      `copy_metadata ${q(`${root}${alias}`)} ${q(`${stage}${alias}`)}`,
      `cmp -s -- ${q(`${root}${contract.recoveryDmgs[arch].url}`)} ${q(`${stage}${alias}`)} || fail ${q(`STAGED_ALIAS_MISMATCH_${alias}`)} 59`,
    );
  }
  lines.push(
    `mkdir -m 0700 -- ${q(`${stage}drill-current`)} ${q(`${stage}drill-next`)}`,
    `cp -- ${q(betaPath)} ${q(`${stage}drill-current/${BETA_FEED}`)}`,
    `cp -- ${q(`${stage}${BETA_FEED}`)} ${q(`${stage}drill-next/${BETA_FEED}`)}`,
  );
  for (const alias of contract.aliases) {
    lines.push(
      `cp -- ${q(`${root}${alias}`)} ${q(`${stage}drill-current/${alias}`)}`,
      `cp -- ${q(`${stage}${alias}`)} ${q(`${stage}drill-next/${alias}`)}`,
      `atomic_replace ${q(`${stage}drill-next/${alias}`)} ${q(`${stage}drill-current/${alias}`)}`,
    );
  }
  lines.push(
    `atomic_replace ${q(`${stage}drill-next/${BETA_FEED}`)} ${q(`${stage}drill-current/${BETA_FEED}`)}`,
    `assert_sha256 ${q(`${stage}drill-current/${BETA_FEED}`)} ${q(contract.recoveryFeedSha256)} DRILL_FEED_MISMATCH`,
  );
  for (const alias of contract.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    lines.push(
      `cmp -s -- ${q(`${root}${contract.recoveryDmgs[arch].url}`)} ${q(`${stage}drill-current/${alias}`)} || fail ${q(`DRILL_ALIAS_MISMATCH_${alias}`)} 60`,
    );
  }
  lines.push(
    ...commonChecks,
    'echo "REMOTE_RECOVERY_DRY_RUN_OK"',
  );
  return lines.join("\n");
}

function buildRemoteRecoveryTransaction({ globalLock = GLOBAL_LOCK, ...options }) {
  const inner = buildRemoteRecoveryInnerScript(options);
  return `flock -x -w 300 ${shellQuote(assertGlobalLockPath(globalLock))} bash -c ${shellQuote(inner)}`;
}

function buildRemoteRecoveryFreezeClearTransaction({
  contract,
  remoteRoot = DEFAULT_REMOTE_ROOT,
  globalLock = GLOBAL_LOCK,
}) {
  const inner = buildRemoteRecoveryFreezeClearInnerScript({ contract, remoteRoot });
  return `flock -x -w 300 ${shellQuote(assertGlobalLockPath(globalLock))} bash -c ${shellQuote(inner)}`;
}

function runRemoteRecovery({ contract, mode, host = DEFAULT_HOST, remoteRoot = DEFAULT_REMOTE_ROOT }) {
  if (!/^[A-Za-z0-9._-]+@[A-Za-z0-9._:-]+$/.test(host)) throw new Error("[recover] unsafe release host");
  const stagingName = mode === "preflight"
    ? null
    : (mode === "execute"
      ? `.recovery-${contract.candidateId}-execute`
      : `.recovery-${contract.candidateId}-${crypto.randomUUID()}`);
  const command = buildRemoteRecoveryTransaction({ contract, mode, remoteRoot, stagingName });
  const result = spawnSync(
    "ssh",
    [
      "-o", "BatchMode=yes",
      "-o", "ConnectTimeout=15",
      "-o", "ServerAliveInterval=15",
      "-o", "ServerAliveCountMax=4",
      host,
      command,
    ],
    {
      encoding: "utf8",
      timeout: 30 * 60 * 1000,
      maxBuffer: 16 * 1024 * 1024,
    },
  );
  if (result.status !== 0) {
    const detail = `${result.stdout || ""}\n${result.stderr || ""}\n${result.error?.message || ""}`.trim();
    throw new Error(`[recover] locked remote ${mode} failed${detail ? `: ${detail}` : ""}`);
  }
  const marker = `REMOTE_RECOVERY_${mode === "dry-run" ? "DRY_RUN" : mode.toUpperCase()}_OK`;
  if (!(result.stdout || "").includes(marker)) throw new Error(`[recover] remote ${mode} completion marker missing`);
  return { marker, stdout: (result.stdout || "").trim() };
}

function runRemoteRecoveryFreezeClear({
  contract,
  host = DEFAULT_HOST,
  remoteRoot = DEFAULT_REMOTE_ROOT,
}) {
  if (!/^[A-Za-z0-9._-]+@[A-Za-z0-9._:-]+$/.test(host)) throw new Error("[recover] unsafe release host");
  const command = buildRemoteRecoveryFreezeClearTransaction({ contract, remoteRoot });
  const result = spawnSync(
    "ssh",
    [
      "-o", "BatchMode=yes",
      "-o", "ConnectTimeout=15",
      "-o", "ServerAliveInterval=15",
      "-o", "ServerAliveCountMax=4",
      host,
      command,
    ],
    {
      encoding: "utf8",
      timeout: 30 * 60 * 1000,
      maxBuffer: 16 * 1024 * 1024,
    },
  );
  if (result.status !== 0) {
    const detail = `${result.stdout || ""}\n${result.stderr || ""}\n${result.error?.message || ""}`.trim();
    throw new Error(`[recover] locked remote release-freeze clear failed${detail ? `: ${detail}` : ""}`);
  }
  const marker = "REMOTE_RECOVERY_FREEZE_CLEAR_OK";
  if (!(result.stdout || "").includes(marker)) {
    throw new Error("[recover] remote release-freeze clear completion marker missing");
  }
  return { marker, stdout: (result.stdout || "").trim() };
}

function fetchPublicFeedsForRecovery({ contract, expectedBeta, publicUrl = DEFAULT_PUBLIC_URL }) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-recovery-readback-"));
  try {
    const betaPath = path.join(temp, BETA_FEED);
    const stablePath = path.join(temp, STABLE_FEED);
    curlToFile(`${publicUrl}/${BETA_FEED}`, betaPath, BETA_FEED);
    curlToFile(`${publicUrl}/${STABLE_FEED}`, stablePath, STABLE_FEED);
    const betaBytes = fs.readFileSync(betaPath);
    const stableBytes = fs.readFileSync(stablePath);
    if (expectedBeta === "candidate") {
      assertFeedMatchesSnapshot(betaBytes, contract.candidateSnapshot, "public candidate Beta feed");
    } else {
      assertFeedMatchesSnapshot(betaBytes, contract.recoverySnapshot, "public recovery Beta feed");
    }
    assertFeedMatchesSnapshot(stableBytes, contract.stableSnapshot, "public Stable feed");
    return {
      betaBytes,
      stableBytes,
      beta: { size: betaBytes.length, sha256: sha256(betaBytes) },
      stable: { size: stableBytes.length, sha256: sha256(stableBytes) },
    };
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

function verifyPublicRecoveryAliases({ contract, publicUrl = DEFAULT_PUBLIC_URL }) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-recovery-alias-readback-"));
  try {
    const results = {};
    for (const alias of contract.aliases) {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      const expected = contract.recoveryDmgs[arch];
      const destination = path.join(temp, sha256(alias));
      curlToFile(`${publicUrl}/${alias}`, destination, alias);
      results[alias] = {
        url: `${publicUrl}/${alias}`,
        ...assertDownloadedArtifact(destination, expected, `alias ${alias}`),
        source: expected.url,
      };
    }
    return results;
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

function verifyPublicRecoveryVersionedArtifacts({ contract, publicUrl = DEFAULT_PUBLIC_URL }) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-recovery-versioned-readback-"));
  try {
    const results = {};
    for (const expected of contract.recoveryArtifacts) {
      const destination = path.join(temp, sha256(expected.name));
      curlToFile(`${publicUrl}/${expected.name}`, destination, expected.name);
      results[expected.name] = {
        url: `${publicUrl}/${expected.name}`,
        ...assertDownloadedArtifact(destination, expected, `versioned artifact ${expected.name}`),
      };
    }
    return results;
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

function recoveryEvidenceParent(evidenceRoot, contract) {
  return path.resolve(
    evidenceRoot,
    "beta",
    `${contract.candidateVersion}-${contract.candidateId}`,
    `recovery-${contract.recoveryVersion}`,
  );
}

function recoveryExecuteIntentPath(evidenceRoot, contract) {
  return path.join(recoveryEvidenceParent(evidenceRoot, contract), "execute-pending");
}

function recoveryExecuteCompletePath(evidenceRoot, contract) {
  return path.join(recoveryEvidenceParent(evidenceRoot, contract), "execute-complete");
}

function loadRecoveryExecuteIntent({ contract, evidenceRoot }) {
  const target = recoveryExecuteIntentPath(evidenceRoot, contract);
  const stat = fs.lstatSync(target, { throwIfNoEntry: false });
  if (!stat) return null;
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("[recover] execute intent path is not a real directory");
  }
  assertMode(target, 0o700, "execute intent directory");
  let intent;
  try {
    intent = JSON.parse(fs.readFileSync(path.join(target, "intent.json"), "utf8"));
  } catch (error) {
    throw new Error(`[recover] execute intent is unreadable: ${error.message}`);
  }
  if (intent?.schema_version !== 1 || intent?.kind !== "elevate-realtor-beta-recovery-activation-intent"
      || receiptId(intent, "intent_id") !== intent.intent_id
      || intent.candidate_id !== contract.candidateId
      || intent.source_receipt_id !== contract.sourceReceiptId
      || intent.candidate_receipt_sha256 !== contract.candidateReceiptSha256
      || intent.candidate_feed_sha256 !== contract.candidateFeedSha256
      || intent.recovery_feed_sha256 !== contract.recoveryFeedSha256
      || intent.stable_feed_sha256 !== contract.stableFeedSha256
      || typeof intent.started_at !== "string" || !Number.isFinite(Date.parse(intent.started_at))) {
    throw new Error("[recover] execute intent is not bound to this exact candidate");
  }
  const expectedNames = [
    "candidate-receipt.json",
    "public-before-beta-mac.yml",
    "public-before-latest-mac.yml",
  ];
  if (canonicalJson(Object.keys(intent.files || {}).sort()) !== canonicalJson(expectedNames)) {
    throw new Error("[recover] execute intent file manifest is incomplete");
  }
  for (const name of expectedNames) {
    assertFileRecord(path.join(target, name), intent.files[name], `execute intent ${name}`);
    assertMode(path.join(target, name), 0o600, `execute intent ${name}`);
  }
  assertMode(path.join(target, "intent.json"), 0o600, "execute intent manifest");
  const receiptBytes = fs.readFileSync(path.join(target, "candidate-receipt.json"));
  if (!receiptBytes.equals(contract.receiptBytes)) {
    throw new Error("[recover] execute intent candidate evidence mismatch");
  }
  const betaBytes = fs.readFileSync(path.join(target, "public-before-beta-mac.yml"));
  const stableBytes = fs.readFileSync(path.join(target, "public-before-latest-mac.yml"));
  assertFeedMatchesSnapshot(betaBytes, contract.candidateSnapshot, "execute intent candidate Beta feed");
  assertFeedMatchesSnapshot(stableBytes, contract.stableSnapshot, "execute intent Stable feed");
  syncFile(target);
  syncFile(path.dirname(target));
  return {
    path: target,
    intent,
    startedAt: intent.started_at,
    before: {
      betaBytes,
      stableBytes,
      beta: { size: betaBytes.length, sha256: sha256(betaBytes) },
      stable: { size: stableBytes.length, sha256: sha256(stableBytes) },
    },
  };
}

function writeRecoveryExecuteIntent({ contract, evidenceRoot, startedAt, before }) {
  const existing = loadRecoveryExecuteIntent({ contract, evidenceRoot });
  if (existing) return existing;
  assertFeedMatchesSnapshot(before.betaBytes, contract.candidateSnapshot, "execute intent candidate Beta feed");
  assertFeedMatchesSnapshot(before.stableBytes, contract.stableSnapshot, "execute intent Stable feed");
  const parent = recoveryEvidenceParent(evidenceRoot, contract);
  fs.mkdirSync(parent, { recursive: true, mode: 0o700 });
  const target = recoveryExecuteIntentPath(evidenceRoot, contract);
  const temp = `${target}.tmp-${process.pid}-${crypto.randomUUID()}`;
  fs.mkdirSync(temp, { mode: 0o700 });
  try {
    const files = {
      "candidate-receipt.json": contract.receiptBytes,
      "public-before-beta-mac.yml": before.betaBytes,
      "public-before-latest-mac.yml": before.stableBytes,
    };
    for (const [name, bytes] of Object.entries(files)) writeExclusive(path.join(temp, name), bytes);
    const intent = {
      schema_version: 1,
      kind: "elevate-realtor-beta-recovery-activation-intent",
      candidate_id: contract.candidateId,
      source_receipt_id: contract.sourceReceiptId,
      candidate_receipt_sha256: contract.candidateReceiptSha256,
      candidate_feed_sha256: contract.candidateFeedSha256,
      recovery_feed_sha256: contract.recoveryFeedSha256,
      stable_feed_sha256: contract.stableFeedSha256,
      started_at: startedAt,
      files: Object.fromEntries(
        Object.keys(files).sort().map((name) => [name, fileRecord(path.join(temp, name))]),
      ),
    };
    intent.intent_id = receiptId(intent, "intent_id");
    writeExclusive(path.join(temp, "intent.json"), Buffer.from(`${JSON.stringify(canonicalize(intent), null, 2)}\n`));
    syncFile(temp);
    try {
      fs.renameSync(temp, target);
    } catch (error) {
      if (!fs.existsSync(target)) throw error;
      fs.rmSync(temp, { recursive: true, force: true });
    }
    syncFile(parent);
    return loadRecoveryExecuteIntent({ contract, evidenceRoot });
  } catch (error) {
    fs.rmSync(temp, { recursive: true, force: true });
    throw error;
  }
}

function removeRecoveryExecuteIntent({ contract, evidenceRoot }) {
  const completed = loadRecoveryEvidenceArchive({
    contract,
    mode: "execute",
    target: recoveryExecuteCompletePath(evidenceRoot, contract),
  });
  if (!completed) throw new Error("[recover] refusing to retire execute intent before durable completion evidence");
  const target = recoveryExecuteIntentPath(evidenceRoot, contract);
  const stat = fs.lstatSync(target, { throwIfNoEntry: false });
  if (!stat) return false;
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("[recover] execute intent path is not a real directory");
  }
  const parent = recoveryEvidenceParent(evidenceRoot, contract);
  const tombstone = `${target}.retired-${process.pid}-${crypto.randomUUID()}`;
  fs.renameSync(target, tombstone);
  syncFile(parent);
  fs.rmSync(tombstone, { recursive: true, force: true });
  return true;
}

function loadRecoveryEvidenceArchive({ contract, mode, target }) {
  const stat = fs.lstatSync(target, { throwIfNoEntry: false });
  if (!stat) return null;
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("[recover] evidence archive path is not a real directory");
  }
  const archiveDirectoryMode = fs.statSync(target).mode & 0o777;
  if (archiveDirectoryMode !== 0o500 && archiveDirectoryMode !== 0o700) {
    throw new Error(`[recover] evidence archive directory mode ${archiveDirectoryMode.toString(8)} is unsafe`);
  }
  let evidence;
  let archive;
  try {
    evidence = JSON.parse(fs.readFileSync(path.join(target, "activation.json"), "utf8"));
    archive = JSON.parse(fs.readFileSync(path.join(target, "archive.json"), "utf8"));
  } catch (error) {
    throw new Error(`[recover] evidence archive is unreadable: ${error.message}`);
  }
  if (evidence?.kind !== "elevate-realtor-beta-recovery-activation"
      || evidence.mode !== mode || receiptId(evidence, "activation_id") !== evidence.activation_id
      || evidence.candidate_id !== contract.candidateId
      || evidence.source_receipt_id !== contract.sourceReceiptId
      || evidence.candidate_receipt_sha256 !== contract.candidateReceiptSha256
      || evidence.candidate_feed_sha256 !== contract.candidateFeedSha256
      || evidence.recovery_feed_sha256 !== contract.recoveryFeedSha256
      || evidence.stable_expected_sha256 !== contract.stableFeedSha256
      || evidence.beta_before_sha256 !== contract.candidateFeedSha256
      || evidence.beta_after_sha256 !== (mode === "execute"
        ? contract.recoveryFeedSha256
        : contract.candidateFeedSha256)
      || evidence.stable_before_sha256 !== contract.stableFeedSha256
      || evidence.stable_after_sha256 !== contract.stableFeedSha256
      || evidence.stable_untouched !== true
      || evidence.procedure_id !== REALTOR_BETA_RECOVERY_PROCEDURE_ID) {
    throw new Error("[recover] evidence archive is not bound to this exact activation");
  }
  if (archive?.kind !== "elevate-realtor-beta-recovery-activation-archive"
      || archive.mode !== mode || archive.candidate_id !== contract.candidateId
      || archive.activation_id !== evidence.activation_id
      || receiptId(archive, "archive_id") !== archive.archive_id) {
    throw new Error("[recover] evidence archive manifest is invalid");
  }
  const expectedArchiveFiles = [
    "activation.json",
    "candidate-receipt.json",
    "public-after-beta-mac.yml",
    "public-after-latest-mac.yml",
    "public-before-beta-mac.yml",
    "public-before-latest-mac.yml",
  ];
  if (canonicalJson(Object.keys(archive.files || {}).sort()) !== canonicalJson(expectedArchiveFiles)) {
    throw new Error("[recover] evidence archive file manifest is incomplete");
  }
  for (const [name, record] of Object.entries(archive.files || {})) {
    assertSafeBasename(name, "evidence archive file name");
    assertFileRecord(path.join(target, name), record, `evidence archive ${name}`);
    assertMode(path.join(target, name), 0o400, `evidence archive ${name}`);
  }
  assertMode(path.join(target, "archive.json"), 0o400, "evidence archive manifest");
  const receiptBytes = fs.readFileSync(path.join(target, "candidate-receipt.json"));
  if (!receiptBytes.equals(contract.receiptBytes)) {
    throw new Error("[recover] evidence archive candidate bytes mismatch");
  }
  if (mode === "execute") {
    const expectedFreeze = {
      active_file: ROLLBACK_FREEZE_FILE,
      cleared_file: recoveryActivationFreezeClearedFile(contract),
      freeze_id: recoveryActivationFreezeRecord(contract).freeze_id,
      sha256: sha256(recoveryActivationFreezeBytes(contract)),
      clear_after_execute_complete_archive: true,
    };
    if (canonicalJson(evidence.release_freeze) !== canonicalJson(expectedFreeze)) {
      throw new Error("[recover] execute evidence release-freeze contract mismatch");
    }
    if (canonicalJson(Object.keys(evidence.public_aliases || {}).sort())
        !== canonicalJson([...contract.aliases].sort())
        || canonicalJson(Object.keys(evidence.public_versioned_artifacts || {}).sort())
        !== canonicalJson(contract.recoveryArtifacts.map((item) => item.name).sort())) {
      throw new Error("[recover] execute evidence public artifact manifest is incomplete");
    }
    for (const alias of contract.aliases) {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      const expected = contract.recoveryDmgs[arch];
      const actual = evidence.public_aliases[alias];
      if (actual?.size !== expected.size || actual?.sha512 !== expected.sha512
          || actual?.source !== expected.url || !SHA256_RE.test(String(actual?.sha256 || ""))) {
        throw new Error(`[recover] execute evidence alias mismatch: ${alias}`);
      }
    }
    for (const expected of contract.recoveryArtifacts) {
      const actual = evidence.public_versioned_artifacts[expected.name];
      if (actual?.size !== expected.size || actual?.sha512 !== expected.sha512
          || !SHA256_RE.test(String(actual?.sha256 || ""))) {
        throw new Error(`[recover] execute evidence versioned artifact mismatch: ${expected.name}`);
      }
    }
  }
  if (archiveDirectoryMode === 0o700) fs.chmodSync(target, 0o500);
  assertMode(target, 0o500, "evidence archive directory");
  syncFile(target);
  syncFile(path.dirname(target));
  return { archivePath: target, evidence, archive };
}

function writeRecoveryEvidenceArchive({
  contract,
  mode,
  evidenceRoot,
  startedAt,
  completedAt,
  before,
  after,
  aliases,
  versionedArtifacts,
  remote,
  host,
  remoteRoot,
}) {
  const evidenceBody = {
    schema_version: 1,
    kind: "elevate-realtor-beta-recovery-activation",
    mode,
    ok: true,
    started_at: startedAt,
    completed_at: completedAt,
    candidate_id: contract.candidateId,
    source_receipt_id: contract.sourceReceiptId,
    candidate_receipt_sha256: contract.candidateReceiptSha256,
    candidate_version: contract.candidateVersion,
    recovery_version: contract.recoveryVersion,
    candidate_feed_sha256: contract.candidateFeedSha256,
    recovery_feed_sha256: contract.recoveryFeedSha256,
    retained_recovery_feed_name: recoveryRetainedFeedName(contract),
    stable_expected_sha256: contract.stableFeedSha256,
    beta_before_sha256: before.beta.sha256,
    beta_after_sha256: after.beta.sha256,
    stable_before_sha256: before.stable.sha256,
    stable_after_sha256: after.stable.sha256,
    stable_untouched: before.stable.sha256 === after.stable.sha256
      && after.stable.sha256 === contract.stableFeedSha256,
    production_mutated: mode === "execute",
    profile_data_mutations: 0,
    rpo_seconds: 0,
    global_lock: GLOBAL_LOCK,
    remote_host: host,
    remote_root: remoteRoot,
    staging: { same_filesystem: true, mode: "0700", recovery_payload_source: "remote-retained-bytes" },
    committed_paths: mode === "execute" ? [...contract.aliases, BETA_FEED] : [],
    feed_committed_last: mode === "execute",
    stable_paths_written: [],
    backend_paths_written: [],
    profile_paths_written: [],
    candidate_versioned_artifacts_retained: true,
    public_aliases: aliases,
    public_versioned_artifacts: versionedArtifacts,
    remote_completion_marker: remote.marker,
    release_freeze: mode === "execute" ? {
      active_file: ROLLBACK_FREEZE_FILE,
      cleared_file: recoveryActivationFreezeClearedFile(contract),
      freeze_id: recoveryActivationFreezeRecord(contract).freeze_id,
      sha256: sha256(recoveryActivationFreezeBytes(contract)),
      clear_after_execute_complete_archive: true,
    } : null,
    procedure_id: REALTOR_BETA_RECOVERY_PROCEDURE_ID,
  };
  evidenceBody.activation_id = receiptId(evidenceBody, "activation_id");

  const parent = recoveryEvidenceParent(evidenceRoot, contract);
  fs.mkdirSync(parent, { recursive: true, mode: 0o700 });
  const stamp = completedAt.replaceAll(/[^0-9]/g, "").slice(0, 17);
  const target = mode === "execute"
    ? recoveryExecuteCompletePath(evidenceRoot, contract)
    : path.join(parent, `${stamp}-${mode}-${evidenceBody.activation_id}`);
  if (fs.existsSync(target)) {
    if (mode === "execute") return loadRecoveryEvidenceArchive({ contract, mode, target });
    throw new Error(`[recover] immutable evidence archive already exists: ${target}`);
  }
  const temp = `${target}.tmp-${process.pid}-${crypto.randomUUID()}`;
  fs.mkdirSync(temp, { mode: 0o700 });
  let renamed = false;
  try {
    const files = {
      "candidate-receipt.json": contract.receiptBytes,
      "public-before-beta-mac.yml": before.betaBytes,
      "public-before-latest-mac.yml": before.stableBytes,
      "public-after-beta-mac.yml": after.betaBytes,
      "public-after-latest-mac.yml": after.stableBytes,
    };
    for (const [name, bytes] of Object.entries(files)) writeExclusive(path.join(temp, name), bytes);
    writeExclusive(path.join(temp, "activation.json"), Buffer.from(`${JSON.stringify(canonicalize(evidenceBody), null, 2)}\n`));
    const records = Object.fromEntries(
      fs.readdirSync(temp).sort().map((name) => [name, fileRecord(path.join(temp, name))]),
    );
    const archive = {
      schema_version: 1,
      kind: "elevate-realtor-beta-recovery-activation-archive",
      activation_id: evidenceBody.activation_id,
      candidate_id: contract.candidateId,
      mode,
      files: records,
    };
    archive.archive_id = receiptId(archive, "archive_id");
    writeExclusive(path.join(temp, "archive.json"), Buffer.from(`${JSON.stringify(canonicalize(archive), null, 2)}\n`));
    for (const name of fs.readdirSync(temp)) {
      fs.chmodSync(path.join(temp, name), 0o400);
      syncFile(path.join(temp, name));
    }
    syncFile(temp);
    fs.renameSync(temp, target);
    renamed = true;
    fs.chmodSync(target, 0o500);
    syncFile(parent);
    return loadRecoveryEvidenceArchive({ contract, mode, target });
  } catch (error) {
    if (!renamed) {
      fs.chmodSync(temp, 0o700);
      for (const name of fs.readdirSync(temp)) fs.chmodSync(path.join(temp, name), 0o600);
      fs.rmSync(temp, { recursive: true, force: true });
    }
    throw error;
  }
}

function runRecoveryWorkflow({
  contract,
  mode,
  evidenceRoot,
  host = DEFAULT_HOST,
  remoteRoot = DEFAULT_REMOTE_ROOT,
  publicUrl = DEFAULT_PUBLIC_URL,
  dependencies = {},
}) {
  if (!MODES.has(mode)) throw new Error(`[recover] unsupported mode: ${mode}`);
  const deps = {
    now: () => new Date().toISOString(),
    log: (message) => console.log(message),
    loadRecoveryEvidenceArchive,
    loadRecoveryExecuteIntent,
    writeRecoveryExecuteIntent,
    runRemoteRecovery,
    fetchPublicFeedsForRecovery,
    verifyPublicRecoveryAliases,
    verifyPublicRecoveryVersionedArtifacts,
    writeRecoveryEvidenceArchive,
    runRemoteRecoveryFreezeClear,
    removeRecoveryExecuteIntent,
    ...dependencies,
  };

  if (mode === "execute") {
    const completed = deps.loadRecoveryEvidenceArchive({
      contract,
      mode,
      target: recoveryExecuteCompletePath(evidenceRoot, contract),
    });
    if (completed) {
      // Loading revalidates and fsyncs the immutable archive. Only then may
      // the candidate-bound activation freeze be retired. A durable cleared
      // marker makes this idempotent even after a later legitimate release.
      const freezeClear = deps.runRemoteRecoveryFreezeClear({ contract, host, remoteRoot });
      deps.removeRecoveryExecuteIntent({ contract, evidenceRoot });
      return {
        ok: true,
        mode,
        candidate_id: contract.candidateId,
        activation_id: completed.evidence.activation_id,
        target_version: contract.recoveryVersion,
        production_mutated: true,
        stable_untouched: completed.evidence.stable_untouched,
        resumed_completed_evidence: true,
        release_freeze_clear_marker: freezeClear.marker,
        evidence_archive: completed.archivePath,
      };
    }
  }

  let startedAt = deps.now();
  deps.log(`[recover] ${mode}: candidate ${contract.candidateId}, candidate ${contract.candidateVersion}, recovery target ${contract.recoveryVersion}`);
  let executeIntent = mode === "execute" ? deps.loadRecoveryExecuteIntent({ contract, evidenceRoot }) : null;
  let before;
  if (executeIntent) {
    startedAt = executeIntent.startedAt;
    before = executeIntent.before;
    deps.log(`[recover] resuming durable execute intent ${executeIntent.intent.intent_id}`);
  } else {
    before = deps.fetchPublicFeedsForRecovery({ contract, expectedBeta: "candidate", publicUrl });
    if (mode === "execute") {
      executeIntent = deps.writeRecoveryExecuteIntent({ contract, evidenceRoot, startedAt, before });
      startedAt = executeIntent.startedAt;
      before = executeIntent.before;
      deps.log(`[recover] sealed durable execute intent ${executeIntent.intent.intent_id}`);
    }
  }

  const remote = deps.runRemoteRecovery({ contract, mode, host, remoteRoot });
  const after = deps.fetchPublicFeedsForRecovery({
    contract,
    expectedBeta: mode === "execute" ? "recovery" : "candidate",
    publicUrl,
  });
  const aliases = mode === "execute"
    ? deps.verifyPublicRecoveryAliases({ contract, publicUrl })
    : {};
  const versionedArtifacts = mode === "execute"
    ? deps.verifyPublicRecoveryVersionedArtifacts({ contract, publicUrl })
    : {};
  const completedAt = deps.now();
  const archived = deps.writeRecoveryEvidenceArchive({
    contract,
    mode,
    evidenceRoot,
    startedAt,
    completedAt,
    before,
    after,
    aliases,
    versionedArtifacts,
    remote,
    host,
    remoteRoot,
  });

  let freezeClear = null;
  if (mode === "execute") {
    // Archive first, unfreeze second, retire the resumable intent last.
    freezeClear = deps.runRemoteRecoveryFreezeClear({ contract, host, remoteRoot });
    deps.removeRecoveryExecuteIntent({ contract, evidenceRoot });
  }
  return {
    ok: true,
    mode,
    candidate_id: contract.candidateId,
    activation_id: archived.evidence.activation_id,
    target_version: contract.recoveryVersion,
    production_mutated: mode === "execute",
    stable_untouched: archived.evidence.stable_untouched,
    ...(freezeClear ? { release_freeze_clear_marker: freezeClear.marker } : {}),
    evidence_archive: archived.archivePath,
  };
}

function parseArguments(argv) {
  const values = {};
  const allowed = new Set([
    "--mode",
    "--lane",
    "--candidate-receipt",
    "--candidate-receipt-sha256",
    "--retained-feed",
    "--expected-failed-feed-sha256",
    "--confirm-candidate-id",
    "--evidence-root",
  ]);
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (!allowed.has(flag) || !value || value.startsWith("--") || Object.hasOwn(values, flag)) {
      throw new Error(`[rollback] invalid or duplicate argument: ${flag || "<missing>"}`);
    }
    values[flag] = value;
  }
  if (!MODES.has(values["--mode"])) {
    throw new Error("[rollback] explicit --mode preflight|dry-run|execute is required");
  }
  const lane = values["--lane"] || "rollback";
  if (!LANES.has(lane)) {
    throw new Error("[rollback] unsupported --lane; use rollback|recover");
  }
  if (lane === "recover"
      && (Object.hasOwn(values, "--retained-feed") || Object.hasOwn(values, "--expected-failed-feed-sha256"))) {
    throw new Error("[recover] recovery activation binds only to the candidate receipt; retained-feed flags are not accepted");
  }
  values["--lane"] = lane;
  return values;
}

function usage() {
  return [
    "usage: rollback-realtor-beta.js",
    "  --mode preflight|dry-run|execute",
    "  [--lane rollback|recover]  # default rollback (downgrade to 1.2.65)",
    "  --candidate-receipt /absolute/path/candidate-receipt.json",
    "  --candidate-receipt-sha256 <sha256>",
    "  [--confirm-candidate-id <candidate-id>]  # required for execute",
    "  [--evidence-root /absolute/path]",
    "rollback lane only:",
    "  --retained-feed /absolute/path/retained-beta-mac.yml",
    "  --expected-failed-feed-sha256 <sha256>",
    "recover lane (roll-forward 1.2.104 activation) takes no other inputs: every",
    "expectation is bound to receipt.recovery and the payload bytes are the",
    "retention already committed on the update host.",
  ].join("\n");
}

function assertExecuteConfirmation(mode, suppliedCandidateId, expectedCandidateId) {
  if (mode === "execute" && suppliedCandidateId !== expectedCandidateId) {
    throw new Error("[rollback] execute requires --confirm-candidate-id matching the receipt");
  }
  return true;
}

function runRollbackWorkflow({
  contract,
  mode,
  evidenceRoot,
  host = DEFAULT_HOST,
  remoteRoot = DEFAULT_REMOTE_ROOT,
  publicUrl = DEFAULT_PUBLIC_URL,
  dependencies = {},
}) {
  if (!MODES.has(mode)) throw new Error(`[rollback] unsupported mode: ${mode}`);
  const deps = {
    now: () => new Date().toISOString(),
    log: (message) => console.log(message),
    loadEvidenceArchive,
    loadExecuteIntent,
    writeExecuteIntent,
    runRemoteRollback,
    fetchPublicFeeds,
    verifyPublicRollbackAliases,
    verifyPublicRollbackVersionedArtifacts,
    writeEvidenceArchive,
    runRemoteRollbackFreezeClear,
    removeExecuteIntent,
    ...dependencies,
  };

  if (mode === "execute") {
    const completed = deps.loadEvidenceArchive({
      contract,
      mode,
      target: executeCompletePath(evidenceRoot, contract),
    });
    if (completed) {
      // Loading revalidates and fsyncs the immutable archive. Only then may the
      // candidate-bound remote freeze be retired. A durable cleared marker
      // makes this idempotent even if a later legitimate release has shipped.
      const freezeClear = deps.runRemoteRollbackFreezeClear({ contract, host, remoteRoot });
      deps.removeExecuteIntent({ contract, evidenceRoot });
      return {
        ok: true,
        mode,
        candidate_id: contract.candidateId,
        rollback_id: completed.evidence.rollback_id,
        target_version: contract.rollbackVersion,
        production_mutated: true,
        stable_untouched: completed.evidence.stable_untouched,
        resumed_completed_evidence: true,
        release_freeze_clear_marker: freezeClear.marker,
        evidence_archive: completed.archivePath,
      };
    }
  }

  let startedAt = deps.now();
  deps.log(`[rollback] ${mode}: candidate ${contract.candidateId}, failed ${contract.failedVersion}, target ${contract.rollbackVersion}`);
  let executeIntent = mode === "execute" ? deps.loadExecuteIntent({ contract, evidenceRoot }) : null;
  let before;
  if (executeIntent) {
    startedAt = executeIntent.startedAt;
    before = executeIntent.before;
    deps.log(`[rollback] resuming durable execute intent ${executeIntent.intent.intent_id}`);
  } else {
    before = deps.fetchPublicFeeds({ contract, expectedBeta: "failed", publicUrl });
    if (mode === "execute") {
      executeIntent = deps.writeExecuteIntent({ contract, evidenceRoot, startedAt, before });
      startedAt = executeIntent.startedAt;
      before = executeIntent.before;
      deps.log(`[rollback] sealed durable execute intent ${executeIntent.intent.intent_id}`);
    }
  }

  const remote = deps.runRemoteRollback({ contract, mode, host, remoteRoot });
  const after = deps.fetchPublicFeeds({
    contract,
    expectedBeta: mode === "execute" ? "rollback" : "failed",
    publicUrl,
  });
  const aliases = mode === "execute"
    ? deps.verifyPublicRollbackAliases({ contract, publicUrl })
    : {};
  const versionedArtifacts = mode === "execute"
    ? deps.verifyPublicRollbackVersionedArtifacts({ contract, publicUrl })
    : {};
  const completedAt = deps.now();
  const archived = deps.writeEvidenceArchive({
    contract,
    mode,
    evidenceRoot,
    startedAt,
    completedAt,
    before,
    after,
    aliases,
    versionedArtifacts,
    remote,
    host,
    remoteRoot,
  });

  let freezeClear = null;
  if (mode === "execute") {
    // Archive first, unfreeze second, retire the resumable intent last.
    freezeClear = deps.runRemoteRollbackFreezeClear({ contract, host, remoteRoot });
    deps.removeExecuteIntent({ contract, evidenceRoot });
  }
  return {
    ok: true,
    mode,
    candidate_id: contract.candidateId,
    rollback_id: archived.evidence.rollback_id,
    target_version: contract.rollbackVersion,
    production_mutated: mode === "execute",
    stable_untouched: archived.evidence.stable_untouched,
    ...(freezeClear ? { release_freeze_clear_marker: freezeClear.marker } : {}),
    evidence_archive: archived.archivePath,
  };
}

function main(argv = process.argv.slice(2)) {
  const args = parseArguments(argv);
  const mode = args["--mode"];
  if (args["--lane"] === "recover") {
    const contract = loadRecoveryActivationContract({
      candidateReceiptPath: args["--candidate-receipt"] ? path.resolve(args["--candidate-receipt"]) : null,
      expectedCandidateReceiptSha256: args["--candidate-receipt-sha256"],
    });
    assertExecuteConfirmation(mode, args["--confirm-candidate-id"], contract.candidateId);
    const evidenceRoot = path.resolve(
      args["--evidence-root"] || process.env.ELEVATE_ROLLBACK_EVIDENCE_ROOT
        || path.join(__dirname, "..", "dist", "rollback-receipts"),
    );
    const result = runRecoveryWorkflow({
      contract,
      mode,
      evidenceRoot,
      host: DEFAULT_HOST,
      remoteRoot: DEFAULT_REMOTE_ROOT,
      publicUrl: DEFAULT_PUBLIC_URL,
    });
    console.log(JSON.stringify(result, null, 2));
    return;
  }
  const contract = loadRollbackContract({
    candidateReceiptPath: path.resolve(args["--candidate-receipt"]),
    expectedCandidateReceiptSha256: args["--candidate-receipt-sha256"],
    retainedFeedPath: path.resolve(args["--retained-feed"]),
    expectedFailedFeedSha256: args["--expected-failed-feed-sha256"],
  });
  assertExecuteConfirmation(mode, args["--confirm-candidate-id"], contract.candidateId);
  const host = DEFAULT_HOST;
  const remoteRoot = DEFAULT_REMOTE_ROOT;
  const publicUrl = DEFAULT_PUBLIC_URL;
  const evidenceRoot = path.resolve(
    args["--evidence-root"] || process.env.ELEVATE_ROLLBACK_EVIDENCE_ROOT
      || path.join(__dirname, "..", "dist", "rollback-receipts"),
  );
  const result = runRollbackWorkflow({
    contract,
    mode,
    evidenceRoot,
    host,
    remoteRoot,
    publicUrl,
  });
  console.log(JSON.stringify(result, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error?.message || String(error));
    console.error(usage());
    process.exit(1);
  }
}

module.exports = {
  BETA_FEED,
  DEFAULT_REMOTE_ROOT,
  EXPECTED_ALIASES,
  EXPECTED_RECOVERY_VERSION,
  EXPECTED_ROLLBACK_VERSION,
  GLOBAL_LOCK,
  REALTOR_BETA_RECOVERY_PROCEDURE_ID,
  ROLLBACK_FREEZE_FILE,
  STABLE_FEED,
  assertDownloadedArtifact,
  assertExecuteConfirmation,
  assertFailedCandidateFeed,
  assertFeedMatchesSnapshot,
  buildRemoteRecoveryFreezeClearInnerScript,
  buildRemoteRecoveryFreezeClearTransaction,
  buildRemoteRecoveryInnerScript,
  buildRemoteRecoveryTransaction,
  buildRemoteRollbackInnerScript,
  buildRemoteRollbackTransaction,
  buildRemoteRollbackFreezeClearInnerScript,
  buildRemoteRollbackFreezeClearTransaction,
  canonicalJson,
  executeCompletePath,
  executeIntentPath,
  loadRecoveryActivationContract,
  loadRecoveryEvidenceArchive,
  loadRecoveryExecuteIntent,
  loadRollbackContract,
  loadEvidenceArchive,
  loadExecuteIntent,
  parseArguments,
  receiptId,
  recoveryActivationFreezeBytes,
  recoveryActivationFreezeClearedFile,
  recoveryActivationFreezeRecord,
  recoveryExecuteCompletePath,
  recoveryExecuteIntentPath,
  recoveryRetainedFeedName,
  removeExecuteIntent,
  removeRecoveryExecuteIntent,
  rollbackFreezeBytes,
  rollbackFreezeClearedFile,
  rollbackFreezeRecord,
  runRecoveryWorkflow,
  runRollbackWorkflow,
  runRemoteRecoveryFreezeClear,
  runRemoteRollbackFreezeClear,
  sha256,
  writeExecuteIntent,
  writeEvidenceArchive,
  writeRecoveryExecuteIntent,
  writeRecoveryEvidenceArchive,
};
