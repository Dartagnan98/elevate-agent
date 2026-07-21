"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");
const test = require("node:test");
const yaml = require("js-yaml");

const {
  BETA_FEED,
  EXPECTED_ALIASES,
  EXPECTED_RECOVERY_VERSION,
  GLOBAL_LOCK,
  REALTOR_BETA_RECOVERY_PROCEDURE_ID,
  ROLLBACK_FREEZE_FILE,
  assertDownloadedArtifact,
  assertExecuteConfirmation,
  buildRemoteRecoveryFreezeClearInnerScript,
  buildRemoteRecoveryFreezeClearTransaction,
  buildRemoteRecoveryInnerScript,
  buildRemoteRecoveryTransaction,
  buildRemoteRollbackFreezeClearInnerScript,
  buildRemoteRollbackFreezeClearTransaction,
  buildRemoteRollbackInnerScript,
  buildRemoteRollbackTransaction,
  canonicalJson,
  executeCompletePath,
  loadEvidenceArchive,
  loadExecuteIntent,
  loadRecoveryActivationContract,
  loadRecoveryEvidenceArchive,
  loadRecoveryExecuteIntent,
  loadRollbackContract,
  parseArguments,
  receiptId,
  recoveryActivationFreezeBytes,
  recoveryActivationFreezeClearedFile,
  recoveryExecuteCompletePath,
  recoveryRetainedFeedName,
  removeExecuteIntent,
  removeRecoveryExecuteIntent,
  rollbackFreezeBytes,
  rollbackFreezeClearedFile,
  runRecoveryWorkflow,
  runRollbackWorkflow,
  sha256,
  writeExecuteIntent,
  writeEvidenceArchive,
  writeRecoveryExecuteIntent,
  writeRecoveryEvidenceArchive,
} = require("../scripts/rollback-realtor-beta");
const { buildRemotePublishTransaction } = require("../scripts/candidate-receipt");

function tempDirectory(t, prefix = "elevate-rollback-test-") {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  t.after(() => {
    if (fs.existsSync(root)) {
      for (const entry of fs.readdirSync(root, { recursive: true }).reverse()) {
        const item = path.join(root, entry);
        const stat = fs.lstatSync(item, { throwIfNoEntry: false });
        if (stat?.isSymbolicLink()) fs.unlinkSync(item);
        else if (stat) fs.chmodSync(item, stat.isDirectory() ? 0o700 : 0o600);
      }
      fs.chmodSync(root, 0o700);
    }
    fs.rmSync(root, { recursive: true, force: true });
  });
  return root;
}

function sha512(bytes) {
  return crypto.createHash("sha512").update(bytes).digest("base64");
}

function record(bytes) {
  return { size: bytes.length, sha256: sha256(bytes), sha512: sha512(bytes) };
}

function feedFixture(version, prefix) {
  const artifacts = ["x64", "arm64"].flatMap((arch) => ["zip", "dmg"].map((extension) => {
    const url = `${prefix}-${version}-mac-${arch}.${extension}`;
    const bytes = Buffer.from(`${url}:signed-bytes\n`);
    return { url, bytes, ...record(bytes) };
  }));
  const files = artifacts.map(({ url, size, sha512: value }) => ({ url, size, sha512: value }));
  const primary = files.find((item) => item.url.endsWith("-mac-x64.zip"));
  const bytes = Buffer.from(yaml.dump({
    version,
    files,
    path: primary.url,
    sha512: primary.sha512,
    releaseDate: "2026-07-15T00:00:00.000Z",
  }, { lineWidth: -1, noRefs: true }));
  return { artifacts, files, bytes };
}

function snapshot(channel, version, fixture) {
  return {
    channel,
    url: `https://example.invalid/${channel}-mac.yml`,
    status: 200,
    version,
    sha256: sha256(fixture.bytes),
    files: fixture.files,
  };
}

function candidateFixture(t) {
  const root = tempDirectory(t);
  const rollbackFeed = feedFixture("1.2.65", "Elevate");
  const failedFeed = feedFixture("1.2.72", "Elevate-Beta");
  const stableFeed = feedFixture("1.2.63", "Elevate");
  const rollbackSnapshot = snapshot("beta", "1.2.65", rollbackFeed);
  const stableSnapshot = snapshot("latest", "1.2.63", stableFeed);
  const artifacts = Object.fromEntries(failedFeed.artifacts.map((item) => [item.url, {
    path: `dist/${item.url}`,
    size: item.size,
    sha256: item.sha256,
    sha512: item.sha512,
  }]));
  artifacts[BETA_FEED] = {
    path: `dist/${BETA_FEED}`,
    size: failedFeed.bytes.length,
    sha256: sha256(failedFeed.bytes),
  };
  const receipt = {
    schema_version: 2,
    kind: "elevate-final-candidate",
    source_receipt_id: "a".repeat(64),
    release: {
      channel: "beta",
      version: "1.2.72",
      feed_name: BETA_FEED,
      profile: { channel: "beta" },
      artifact_names: failedFeed.artifacts.map((item) => item.url),
      download_aliases: EXPECTED_ALIASES,
    },
    artifacts,
    rollback_target: structuredClone(rollbackSnapshot),
    public_feeds_at_finalize: {
      beta: structuredClone(rollbackSnapshot),
      latest: structuredClone(stableSnapshot),
    },
  };
  receipt.candidate_id = receiptId(receipt, "candidate_id");
  const receiptPath = path.join(root, "candidate-receipt.json");
  const retainedFeedPath = path.join(root, "retained-beta-mac.yml");
  fs.writeFileSync(retainedFeedPath, rollbackFeed.bytes);

  function writeReceipt(value = receipt) {
    const copy = structuredClone(value);
    copy.candidate_id = receiptId(copy, "candidate_id");
    const bytes = Buffer.from(`${JSON.stringify(copy, null, 2)}\n`);
    fs.writeFileSync(receiptPath, bytes);
    return { receipt: copy, sha256: sha256(bytes) };
  }
  const written = writeReceipt();
  return {
    root,
    receiptPath,
    retainedFeedPath,
    rollbackFeed,
    failedFeed,
    stableFeed,
    writeReceipt,
    ...written,
    options: {
      candidateReceiptPath: receiptPath,
      expectedCandidateReceiptSha256: written.sha256,
      retainedFeedPath,
      expectedFailedFeedSha256: sha256(failedFeed.bytes),
    },
  };
}

test("rollback contract binds exact receipt, retained feed, failed feed, Stable, DMGs, and aliases", (t) => {
  const fixture = candidateFixture(t);
  const contract = loadRollbackContract(fixture.options);
  assert.equal(contract.candidateId, fixture.receipt.candidate_id);
  assert.equal(contract.candidateReceiptSha256, fixture.options.expectedCandidateReceiptSha256);
  assert.equal(contract.expectedFailedFeedSha256, sha256(fixture.failedFeed.bytes));
  assert.equal(contract.rollbackFeedSha256, sha256(fixture.rollbackFeed.bytes));
  assert.equal(contract.stableFeedSha256, sha256(fixture.stableFeed.bytes));
  assert.equal(contract.rollbackVersion, "1.2.65");
  assert.deepEqual(contract.aliases, EXPECTED_ALIASES);
  assert.deepEqual(Object.keys(contract.rollbackDmgs), ["x64", "arm64"]);
  assert.deepEqual(Object.keys(contract.failedDmgs), ["x64", "arm64"]);
  assert.equal(contract.rollbackArtifacts.length, 4);
  assert.equal(contract.failedArtifacts.length, 4);
});

test("rollback contract fails closed for every retained-evidence mismatch", (t) => {
  const fixture = candidateFixture(t);
  assert.throws(
    () => loadRollbackContract({ ...fixture.options, expectedCandidateReceiptSha256: "0".repeat(64) }),
    /candidate receipt SHA256 mismatch/,
  );
  assert.throws(
    () => loadRollbackContract({ ...fixture.options, expectedFailedFeedSha256: "0".repeat(64) }),
    /not bound to the receipt/,
  );

  fs.appendFileSync(fixture.retainedFeedPath, "# drift\n");
  assert.throws(() => loadRollbackContract(fixture.options), /retained rollback Beta feed SHA256 mismatch/);
  fs.writeFileSync(fixture.retainedFeedPath, fixture.rollbackFeed.bytes);

  const mutations = [
    ["Stable snapshot", (receipt) => { receipt.public_feeds_at_finalize.latest.sha256 = "invalid"; }, /Stable snapshot/],
    ["rollback target identity", (receipt) => { receipt.rollback_target.sha256 = "2".repeat(64); }, /not the candidate's retained Beta snapshot/],
    ["wrong target version", (receipt) => {
      receipt.rollback_target.version = "1.2.64";
      receipt.public_feeds_at_finalize.beta.version = "1.2.64";
    }, /exact Beta 1\.2\.65/],
    ["Stable status", (receipt) => { receipt.public_feeds_at_finalize.latest.status = 500; }, /valid Stable snapshot/],
    ["alias set", (receipt) => { receipt.release.download_aliases.pop(); }, /alias contract mismatch/],
    ["channel", (receipt) => { receipt.release.channel = "latest"; }, /not an exact Beta candidate/],
    ["rollback DMG", (receipt) => {
      receipt.rollback_target.files = receipt.rollback_target.files.filter((item) => !item.url.endsWith("-mac-arm64.dmg"));
      receipt.public_feeds_at_finalize.beta = structuredClone(receipt.rollback_target);
    }, /metadata does not match|four updater artifacts/],
    ["failed artifact", (receipt) => {
      const name = receipt.release.artifact_names.find((item) => item.endsWith("-mac-x64.dmg"));
      delete receipt.artifacts[name];
    }, /missing failed artifact record/],
    ["unsafe artifact", (receipt) => { receipt.release.artifact_names[0] = "../escape.zip"; }, /unsafe failed feed artifact name/],
  ];
  for (const [label, mutate, pattern] of mutations) {
    const value = structuredClone(fixture.receipt);
    mutate(value);
    const written = fixture.writeReceipt(value);
    assert.throws(
      () => loadRollbackContract({ ...fixture.options, expectedCandidateReceiptSha256: written.sha256 }),
      pattern,
      label,
    );
  }
});

test("CLI requires an explicit mode and all dangerous inputs are value flags", () => {
  const parsed = parseArguments([
    "--mode", "dry-run",
    "--candidate-receipt", "/tmp/receipt.json",
    "--candidate-receipt-sha256", "a".repeat(64),
    "--retained-feed", "/tmp/beta.yml",
    "--expected-failed-feed-sha256", "b".repeat(64),
  ]);
  assert.equal(parsed["--mode"], "dry-run");
  assert.throws(() => parseArguments([]), /explicit --mode/);
  assert.throws(() => parseArguments(["--mode", "execute", "--mode", "preflight"]), /duplicate/);
  assert.throws(() => parseArguments(["--mode", "rollback"]), /explicit --mode/);
  assert.throws(() => parseArguments(["--mode"]), /invalid or duplicate/);
  assert.equal(assertExecuteConfirmation("preflight", undefined, "a".repeat(64)), true);
  assert.equal(assertExecuteConfirmation("dry-run", undefined, "a".repeat(64)), true);
  assert.throws(
    () => assertExecuteConfirmation("execute", "b".repeat(64), "a".repeat(64)),
    /confirm-candidate-id/,
  );
  assert.equal(assertExecuteConfirmation("execute", "a".repeat(64), "a".repeat(64)), true);
});

test("public versioned-artifact readback requires exact size and SHA512", (t) => {
  const root = tempDirectory(t);
  const artifactPath = path.join(root, "artifact.zip");
  const bytes = Buffer.from("exact retained versioned updater bytes\n");
  const expected = { size: bytes.length, sha512: sha512(bytes) };
  fs.writeFileSync(artifactPath, bytes);
  const verified = assertDownloadedArtifact(artifactPath, expected, "versioned artifact");
  assert.equal(verified.size, bytes.length);
  assert.equal(verified.sha512, expected.sha512);
  assert.equal(verified.sha256, sha256(bytes));
  assert.throws(
    () => assertDownloadedArtifact(artifactPath, { ...expected, size: expected.size + 1 }, "versioned artifact"),
    /does not match the candidate receipt/,
  );
  assert.throws(
    () => assertDownloadedArtifact(artifactPath, { ...expected, sha512: sha512(Buffer.from("wrong")) }, "versioned artifact"),
    /does not match the candidate receipt/,
  );
});

function remoteFixture(t) {
  const root = `${tempDirectory(t, "elevate-rollback-remote-")}/remote/`;
  fs.mkdirSync(root);
  const stableBytes = Buffer.from("stable-feed-exact\n");
  const failedFeedBytes = Buffer.from("failed-beta-feed-exact\n");
  const retainedFeedBytes = Buffer.from("retained-beta-1.2.65-exact\n");
  const rollbackBytes = {
    x64: Buffer.from("rollback-x64-dmg\n"),
    arm64: Buffer.from("rollback-arm64-dmg\n"),
  };
  const rollbackZipBytes = {
    x64: Buffer.from("rollback-x64-zip\n"),
    arm64: Buffer.from("rollback-arm64-zip\n"),
  };
  const failedBytes = {
    x64: Buffer.from("failed-x64-dmg\n"),
    arm64: Buffer.from("failed-arm64-dmg\n"),
  };
  const failedZipBytes = {
    x64: Buffer.from("failed-x64-zip\n"),
    arm64: Buffer.from("failed-arm64-zip\n"),
  };
  const aliases = [
    "Alias-A-mac-x64.dmg",
    "Alias-B-mac-x64.dmg",
    "Alias-A-mac-arm64.dmg",
    "Alias-B-mac-arm64.dmg",
  ];
  const rollbackDmgs = {
    x64: { name: "Elevate-1.2.65-mac-x64.dmg", url: "Elevate-1.2.65-mac-x64.dmg", size: rollbackBytes.x64.length, sha512: sha512(rollbackBytes.x64) },
    arm64: { name: "Elevate-1.2.65-mac-arm64.dmg", url: "Elevate-1.2.65-mac-arm64.dmg", size: rollbackBytes.arm64.length, sha512: sha512(rollbackBytes.arm64) },
  };
  const failedDmgs = {
    x64: { name: "Elevate-Beta-1.2.72-mac-x64.dmg", ...record(failedBytes.x64) },
    arm64: { name: "Elevate-Beta-1.2.72-mac-arm64.dmg", ...record(failedBytes.arm64) },
  };
  const rollbackArtifacts = ["x64", "arm64"].flatMap((arch) => [
    {
      name: `Elevate-1.2.65-mac-${arch}.zip`,
      size: rollbackZipBytes[arch].length,
      sha512: sha512(rollbackZipBytes[arch]),
    },
    rollbackDmgs[arch],
  ]);
  const failedArtifacts = ["x64", "arm64"].flatMap((arch) => [
    { name: `Elevate-Beta-1.2.72-mac-${arch}.zip`, ...record(failedZipBytes[arch]) },
    failedDmgs[arch],
  ]);
  const rollbackArtifactBytes = Object.fromEntries(rollbackArtifacts.map((item) => [
    item.name,
    item.name.endsWith(".zip")
      ? rollbackZipBytes[item.name.includes("-arm64.") ? "arm64" : "x64"]
      : rollbackBytes[item.name.includes("-arm64.") ? "arm64" : "x64"],
  ]));
  const failedArtifactBytes = Object.fromEntries(failedArtifacts.map((item) => [
    item.name,
    item.name.endsWith(".zip")
      ? failedZipBytes[item.name.includes("-arm64.") ? "arm64" : "x64"]
      : failedBytes[item.name.includes("-arm64.") ? "arm64" : "x64"],
  ]));
  const contract = {
    candidateId: "d".repeat(64),
    sourceReceiptId: "a".repeat(64),
    failedVersion: "1.2.72",
    rollbackVersion: "1.2.65",
    stableFeedSha256: sha256(stableBytes),
    expectedFailedFeedSha256: sha256(failedFeedBytes),
    rollbackFeedSha256: sha256(retainedFeedBytes),
    retainedFeedBytes,
    rollbackArtifacts,
    rollbackDmgs,
    failedArtifacts,
    failedDmgs,
    aliases,
  };
  fs.writeFileSync(path.join(root, "latest-mac.yml"), stableBytes);
  fs.writeFileSync(path.join(root, "beta-mac.yml"), failedFeedBytes);
  for (const [name, bytes] of Object.entries(rollbackArtifactBytes)) fs.writeFileSync(path.join(root, name), bytes);
  for (const [name, bytes] of Object.entries(failedArtifactBytes)) fs.writeFileSync(path.join(root, name), bytes);
  for (const alias of aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    fs.writeFileSync(path.join(root, alias), failedBytes[arch]);
  }
  const stagingName = `.rollback-${contract.candidateId}-execute`;
  const dryRunStagingName = `.rollback-${contract.candidateId}-00000000-0000-4000-8000-000000000000`;
  const publicNames = ["latest-mac.yml", "beta-mac.yml", ...aliases];
  const original = Object.fromEntries(publicNames.map((name) => [name, fs.readFileSync(path.join(root, name))]));
  return {
    root,
    contract,
    aliases,
    stagingName,
    dryRunStagingName,
    retainedFeedBytes,
    rollbackBytes,
    failedBytes,
    rollbackArtifactBytes,
    failedArtifactBytes,
    original,
  };
}

function runInner(script, input) {
  return spawnSync("bash", ["-c", script], {
    input,
    encoding: "utf8",
    timeout: 30_000,
    maxBuffer: 4 * 1024 * 1024,
  });
}

function fakeFlockEnvironment(t) {
  const bin = tempDirectory(t, "elevate-fake-flock-");
  const executable = path.join(bin, "flock");
  fs.writeFileSync(executable, [
    "#!/bin/bash",
    "set -euo pipefail",
    "if test \"${1:-}\" = -x; then shift; fi",
    "if test \"${1:-}\" = -w; then shift 2; fi",
    "lock=$1; shift",
    "lockdir=${lock}.test-lock-directory",
    "while ! mkdir \"$lockdir\" 2>/dev/null; do sleep 0.01; done",
    "cleanup() { rm -rf -- \"$lockdir\"; }",
    "trap cleanup EXIT HUP INT TERM",
    "\"$@\"",
  ].join("\n"), { mode: 0o700 });
  return { ...process.env, PATH: `${bin}:${process.env.PATH}` };
}

function spawnResult(command, args, { input, env } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { env, stdio: ["pipe", "pipe", "pipe"] });
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => stderr.push(chunk));
    child.once("error", reject);
    child.once("close", (status, signal) => resolve({
      status,
      signal,
      stdout: Buffer.concat(stdout).toString("utf8"),
      stderr: Buffer.concat(stderr).toString("utf8"),
    }));
    child.stdin.end(input);
  });
}

async function waitForPath(filePath, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (!fs.existsSync(filePath)) {
    if (Date.now() >= deadline) throw new Error(`timed out waiting for ${filePath}`);
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}

function publishCandidateForRemoteFixture(fixture, channel = "beta") {
  const artifactNames = fixture.contract.failedArtifacts.map((item) => item.name);
  const feedName = `${channel}-mac.yml`;
  const artifacts = Object.fromEntries(artifactNames.map((name) => {
    const item = fixture.contract.failedArtifacts.find((candidate) => candidate.name === name);
    return [name, { sha256: item.sha256 }];
  }));
  artifacts[feedName] = { sha256: "f".repeat(64) };
  return {
    candidate_id: fixture.contract.candidateId,
    source_receipt_id: fixture.contract.sourceReceiptId,
    public_feeds_at_finalize: {
      latest: { sha256: fixture.contract.stableFeedSha256 },
      beta: { sha256: fixture.contract.expectedFailedFeedSha256 },
    },
    artifacts,
    rollback_target: { sha256: fixture.contract.rollbackFeedSha256 },
    release: {
      channel,
      feed_name: feedName,
      artifact_names: artifactNames,
      download_aliases: fixture.aliases,
    },
  };
}

function assertOriginalPublicState(fixture) {
  for (const [name, bytes] of Object.entries(fixture.original)) {
    assert.deepEqual(fs.readFileSync(path.join(fixture.root, name)), bytes, name);
  }
  assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), false);
  assert.equal(fs.existsSync(path.join(fixture.root, fixture.dryRunStagingName)), false);
}

function assertVersionedArtifactsRetained(fixture) {
  for (const [name, bytes] of Object.entries(fixture.rollbackArtifactBytes)) {
    assert.deepEqual(fs.readFileSync(path.join(fixture.root, name)), bytes, `rollback artifact ${name}`);
  }
  for (const [name, bytes] of Object.entries(fixture.failedArtifactBytes)) {
    assert.deepEqual(fs.readFileSync(path.join(fixture.root, name)), bytes, `failed artifact ${name}`);
  }
}

function assertRollbackPublicState(fixture) {
  assert.deepEqual(fs.readFileSync(path.join(fixture.root, BETA_FEED)), fixture.retainedFeedBytes);
  assert.deepEqual(fs.readFileSync(path.join(fixture.root, "latest-mac.yml")), fixture.original["latest-mac.yml"]);
  for (const alias of fixture.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    assert.deepEqual(fs.readFileSync(path.join(fixture.root, alias)), fixture.rollbackBytes[arch]);
  }
  assertVersionedArtifactsRetained(fixture);
}

function activeFreezePath(fixture) {
  return path.join(fixture.root, ROLLBACK_FREEZE_FILE);
}

function clearedFreezePath(fixture) {
  return path.join(fixture.root, rollbackFreezeClearedFile(fixture.contract));
}

function assertActiveExactFreeze(fixture) {
  assert.deepEqual(fs.readFileSync(activeFreezePath(fixture)), rollbackFreezeBytes(fixture.contract));
  assert.equal(fs.existsSync(clearedFreezePath(fixture)), false);
}

test("remote modes are globally locked, candidate-CAS bound, same-filesystem, and scoped to Beta", (t) => {
  const fixture = remoteFixture(t);
  const transaction = buildRemoteRollbackTransaction({
    contract: fixture.contract,
    mode: "execute",
    remoteRoot: fixture.root,
    stagingName: fixture.stagingName,
  });
  assert.match(transaction, new RegExp(`^flock -x -w 300 '${GLOBAL_LOCK.replaceAll("/", "\\/")}'`));
  const clearTransaction = buildRemoteRollbackFreezeClearTransaction({
    contract: fixture.contract,
    remoteRoot: fixture.root,
  });
  assert.match(clearTransaction, new RegExp(`^flock -x -w 300 '${GLOBAL_LOCK.replaceAll("/", "\\/")}'`));
  assert.doesNotMatch(clearTransaction, /atomic_replace/);
  const script = buildRemoteRollbackInnerScript({
    contract: fixture.contract,
    mode: "execute",
    remoteRoot: fixture.root,
    stagingName: fixture.stagingName,
  });
  for (const code of [
    "STABLE_CAS_FAILED", "PARTIAL_PUBLIC_POINTER_STATE", "UNRECOGNIZED_BETA_FEED_STATE",
    "UNKNOWN_PARTIAL_PUBLIC_STATE",
    "ROLLBACK_X64_ZIP_MISMATCH", "ROLLBACK_X64_DMG_MISMATCH",
    "ROLLBACK_ARM64_ZIP_MISMATCH", "ROLLBACK_ARM64_DMG_MISMATCH",
    "FAILED_X64_ZIP_MISMATCH", "FAILED_X64_DMG_MISMATCH",
    "FAILED_ARM64_ZIP_MISMATCH", "FAILED_ARM64_DMG_MISMATCH",
    "JOURNAL_HASH_MISMATCH", "UNTRUSTED_STAGE_WITH_PARTIAL_PUBLIC_STATE",
    "STAGE_CROSS_FILESYSTEM", "STAGE_MODE_INVALID", "RETAINED_FEED_MISMATCH", "STAGED_FEED_MISMATCH",
    "STAGED_ALIAS_MISMATCH_", "BACKUP_FEED_MISMATCH", "BACKUP_ALIAS_MISMATCH_", "COMMITTED_FEED_MISMATCH",
    "COMMITTED_ALIAS_MISMATCH_", "ROLLBACK_COMPENSATION_FAILED_STAGE_PRESERVED",
  ]) assert.match(script, new RegExp(code));
  assert.match(script, /mkdir -m 0700/);
  assert.match(script, /file_device/);
  assert.doesNotMatch(script, /latest-mac\.yml'\s*\)??\s*$/m);
  assert.doesNotMatch(script, /\.elevate|backend|profile/i);

  const destinations = [...script.matchAll(/^\s*atomic_replace '[^']+' '([^']+)'$/gm)]
    .map((match) => path.basename(match[1]));
  assert.deepEqual(destinations, [...fixture.aliases, BETA_FEED]);
  assert.equal(destinations.at(-1), BETA_FEED);
  assert.equal(destinations.includes("latest-mac.yml"), false);

  const preflight = buildRemoteRollbackInnerScript({
    contract: fixture.contract,
    mode: "preflight",
    remoteRoot: fixture.root,
  });
  assert.equal(/^atomic_replace /m.test(preflight), false);
  assert.equal(/mkdir -m 0700/m.test(preflight), false);

  const dryRun = buildRemoteRollbackInnerScript({
    contract: fixture.contract,
    mode: "dry-run",
    remoteRoot: fixture.root,
    stagingName: fixture.dryRunStagingName,
  });
  for (const match of dryRun.matchAll(/^atomic_replace '[^']+' '([^']+)'$/gm)) {
    assert.ok(match[1].startsWith(`${fixture.root}${fixture.dryRunStagingName}/drill-current/`));
  }
});

test("real dry-run exercises the five replacements but leaves every public byte untouched", (t) => {
  const fixture = remoteFixture(t);
  const script = buildRemoteRollbackInnerScript({
    contract: fixture.contract,
    mode: "dry-run",
    remoteRoot: fixture.root,
    stagingName: fixture.dryRunStagingName,
  });
  const result = runInner(script, fixture.retainedFeedBytes);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /REMOTE_ROLLBACK_DRY_RUN_OK/);
  assertOriginalPublicState(fixture);
});

test("real execute replaces exactly four Beta aliases and commits the retained feed last", (t) => {
  const fixture = remoteFixture(t);
  const script = buildRemoteRollbackInnerScript({
    contract: fixture.contract,
    mode: "execute",
    remoteRoot: fixture.root,
    stagingName: fixture.stagingName,
  });
  const result = runInner(script, fixture.retainedFeedBytes);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /REMOTE_ROLLBACK_EXECUTE_OK/);
  assertRollbackPublicState(fixture);
  assert.deepEqual(fs.readFileSync(activeFreezePath(fixture)), rollbackFreezeBytes(fixture.contract));
  assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), false);
});

test("brand-new execute never freezes an inapplicable or invalid candidate", async (t) => {
  const cases = [
    ["newer Beta feed won", "UNRECOGNIZED_BETA_FEED_STATE", (fixture) => {
      fs.writeFileSync(path.join(fixture.root, BETA_FEED), "newer-beta-release\n");
    }],
    ["alias drifted", "PARTIAL_PUBLIC_POINTER_STATE", (fixture) => {
      fs.appendFileSync(path.join(fixture.root, fixture.aliases[0]), "drift");
    }],
    ["Stable drifted", "STABLE_CAS_FAILED", (fixture) => {
      fs.appendFileSync(path.join(fixture.root, "latest-mac.yml"), "drift");
    }],
    ["retained artifact drifted", "ROLLBACK_X64_ZIP_MISMATCH", (fixture) => {
      const target = fixture.contract.rollbackArtifacts.find((item) => item.name.includes("-x64.zip"));
      fs.appendFileSync(path.join(fixture.root, target.name), "drift");
    }],
  ];
  for (const [label, code, mutate] of cases) {
    await t.test(label, (child) => {
      const fixture = remoteFixture(child);
      mutate(fixture);
      const script = buildRemoteRollbackInnerScript({
        contract: fixture.contract,
        mode: "execute",
        remoteRoot: fixture.root,
        stagingName: fixture.stagingName,
      });
      const result = runInner(script, fixture.retainedFeedBytes);
      assert.notEqual(result.status, 0);
      assert.match(result.stderr, new RegExp(code));
      assert.equal(fs.existsSync(activeFreezePath(fixture)), false);
      assert.equal(fs.existsSync(clearedFreezePath(fixture)), false);
    });
  }
});

test("SIGKILL immediately after freeze durability resumes without changing Stable", (t) => {
  const fixture = remoteFixture(t);
  const clean = buildRemoteRollbackInnerScript({
    contract: fixture.contract,
    mode: "execute",
    remoteRoot: fixture.root,
    stagingName: fixture.stagingName,
  });
  const freezeDurable = `    durable_sync '${fixture.root}'\n    freeze_present=1`;
  assert.ok(clean.includes(freezeDurable));
  const killed = runInner(
    clean.replace(freezeDurable, () => `${freezeDurable}\n    kill -KILL \"$$\"`),
    fixture.retainedFeedBytes,
  );
  assert.equal(killed.signal, "SIGKILL", `status=${killed.status} stderr=${killed.stderr}`);
  assertActiveExactFreeze(fixture);
  for (const [name, bytes] of Object.entries(fixture.original)) {
    assert.deepEqual(fs.readFileSync(path.join(fixture.root, name)), bytes, name);
  }
  const resumed = runInner(clean, fixture.retainedFeedBytes);
  assert.equal(resumed.status, 0, resumed.stderr);
  assertRollbackPublicState(fixture);
  assertActiveExactFreeze(fixture);
});

test("SIGKILL after freeze rename is re-fsynced on adoption before pointer mutation", (t) => {
  const fixture = remoteFixture(t);
  const clean = buildRemoteRollbackInnerScript({
    contract: fixture.contract,
    mode: "execute",
    remoteRoot: fixture.root,
    stagingName: fixture.stagingName,
  });
  const freezeMove = `    mv -f -- '${activeFreezePath(fixture)}.tmp' '${activeFreezePath(fixture)}'`;
  assert.ok(clean.includes(freezeMove));
  const killed = runInner(clean.replace(freezeMove, () => `${freezeMove}\n    kill -KILL \"$$\"`), fixture.retainedFeedBytes);
  assert.equal(killed.signal, "SIGKILL", `status=${killed.status} stderr=${killed.stderr}`);
  assertActiveExactFreeze(fixture);
  for (const [name, bytes] of Object.entries(fixture.original)) {
    assert.deepEqual(fs.readFileSync(path.join(fixture.root, name)), bytes, name);
  }
  const adoptedFreezeCheck = `  assert_sha256 '${activeFreezePath(fixture)}'`;
  const adoptedFreezeSync = `  durable_sync '${activeFreezePath(fixture)}'`;
  assert.ok(clean.indexOf(adoptedFreezeCheck) < clean.indexOf(adoptedFreezeSync));
  assert.ok(clean.indexOf(adoptedFreezeSync) < clean.indexOf("  mutation_started=1"));
  const resumed = runInner(clean, fixture.retainedFeedBytes);
  assert.equal(resumed.status, 0, resumed.stderr);
  assertRollbackPublicState(fixture);
  assertActiveExactFreeze(fixture);
});

test("concurrent publisher waits for rollback lock then rejects the durable freeze", async (t) => {
  const fixture = remoteFixture(t);
  const env = fakeFlockEnvironment(t);
  const lock = path.join(tempDirectory(t, "elevate-release-lock-"), "release.lock");
  const ready = path.join(tempDirectory(t, "elevate-freeze-ready-"), "ready");
  const clean = buildRemoteRollbackInnerScript({
    contract: fixture.contract,
    mode: "execute",
    remoteRoot: fixture.root,
    stagingName: fixture.stagingName,
  });
  const freezeReady = "    freeze_present=1";
  const insertion = clean.lastIndexOf(freezeReady);
  assert.notEqual(insertion, -1);
  const slow = `${clean.slice(0, insertion)}${freezeReady}\n    : > '${ready}'\n    sleep 1${clean.slice(insertion + freezeReady.length)}`;
  const rollback = spawnResult("flock", ["-x", "-w", "300", lock, "bash", "-c", slow], {
    input: fixture.retainedFeedBytes,
    env,
  });
  await waitForPath(ready);
  assertActiveExactFreeze(fixture);

  const stagingName = `.candidate-${fixture.contract.candidateId}-concurrent`;
  fs.mkdirSync(path.join(fixture.root, stagingName), { mode: 0o700 });
  const publish = buildRemotePublishTransaction({
    candidate: publishCandidateForRemoteFixture(fixture, "beta"),
    remote: fixture.root,
    stagingName,
  }).replace(GLOBAL_LOCK, lock);
  const publisher = spawnSync("bash", ["-c", publish], { env, encoding: "utf8", timeout: 10_000 });
  const rollbackResult = await rollback;
  assert.equal(rollbackResult.status, 0, rollbackResult.stderr);
  assert.equal(publisher.status, 46, publisher.stderr);
  assert.match(publisher.stderr, /RELEASE_FREEZE_ACTIVE/);
  assertRollbackPublicState(fixture);
  assertActiveExactFreeze(fixture);
});

test("Beta and Stable publishers reject regular and broken-symlink freezes before mutation", async (t) => {
  for (const freezeKind of ["regular", "broken-symlink"]) {
    for (const channel of ["beta", "latest"]) {
      await t.test(`${channel} ${freezeKind}`, (child) => {
      const fixture = remoteFixture(child);
      const env = fakeFlockEnvironment(child);
      const lock = path.join(tempDirectory(child, "elevate-release-lock-"), "release.lock");
      if (freezeKind === "regular") fs.writeFileSync(activeFreezePath(fixture), "active-freeze\n");
      else fs.symlinkSync(path.join(fixture.root, "missing-freeze-target"), activeFreezePath(fixture));
      const stagingName = `.candidate-${fixture.contract.candidateId}-${channel}`;
      fs.mkdirSync(path.join(fixture.root, stagingName), { mode: 0o700 });
      const publish = buildRemotePublishTransaction({
        candidate: publishCandidateForRemoteFixture(fixture, channel),
        remote: fixture.root,
        stagingName,
      }).replace(GLOBAL_LOCK, lock);
      const result = spawnSync("bash", ["-c", publish], { env, encoding: "utf8", timeout: 10_000 });
      assert.equal(result.status, 46, result.stderr);
      assert.match(result.stderr, /RELEASE_FREEZE_ACTIVE/);
      for (const [name, bytes] of Object.entries(fixture.original)) {
        assert.deepEqual(fs.readFileSync(path.join(fixture.root, name)), bytes, `${channel}:${freezeKind}:${name}`);
      }
      });
    }
  }
});

test("every preflight CAS/artifact/alias mismatch fails before mutation", async (t) => {
  const cases = [
    ["Stable", "STABLE_CAS_FAILED", (fixture) => fs.appendFileSync(path.join(fixture.root, "latest-mac.yml"), "x")],
    ["failed feed", "FAILED_BETA_CAS_FAILED", (fixture) => fs.appendFileSync(path.join(fixture.root, BETA_FEED), "x")],
    ...["x64", "arm64"].flatMap((arch) => ["zip", "dmg"].map((kind) => [
      `rollback ${arch} ${kind}`,
      `ROLLBACK_${arch.toUpperCase()}_${kind.toUpperCase()}_MISMATCH`,
      (fixture) => {
        const artifact = fixture.contract.rollbackArtifacts.find((item) => (
          item.name.includes(`-mac-${arch}.`) && item.name.endsWith(`.${kind}`)
        ));
        fs.appendFileSync(path.join(fixture.root, artifact.name), "x");
      },
    ])),
    ...["x64", "arm64"].flatMap((arch) => ["zip", "dmg"].map((kind) => [
      `failed ${arch} ${kind}`,
      `FAILED_${arch.toUpperCase()}_${kind.toUpperCase()}_MISMATCH`,
      (fixture) => {
        const artifact = fixture.contract.failedArtifacts.find((item) => (
          item.name.includes(`-mac-${arch}.`) && item.name.endsWith(`.${kind}`)
        ));
        fs.appendFileSync(path.join(fixture.root, artifact.name), "x");
      },
    ])),
    ...[0, 1, 2, 3].map((index) => [
      `alias ${index}`,
      "FAILED_ALIAS_CAS_",
      (fixture) => fs.appendFileSync(path.join(fixture.root, fixture.aliases[index]), "x"),
    ]),
  ];
  for (const [label, code, mutate] of cases) {
    await t.test(label, (child) => {
      const fixture = remoteFixture(child);
      mutate(fixture);
      const script = buildRemoteRollbackInnerScript({
        contract: fixture.contract,
        mode: "preflight",
        remoteRoot: fixture.root,
      });
      const result = runInner(script);
      assert.notEqual(result.status, 0);
      assert.match(result.stderr, new RegExp(code));
      assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), false);
    });
  }
});

function injectMoveFailure(script, moveNumber, afterMove) {
  const original = 'atomic_replace() { mv -f -- "$1" "$2"; }';
  const body = afterMove
    ? `move_count=$((move_count + 1)); mv -f -- "$1" "$2"; if test "$move_count" = ${moveNumber}; then return 88; fi`
    : `move_count=$((move_count + 1)); if test "$move_count" = ${moveNumber}; then return 88; fi; mv -f -- "$1" "$2"`;
  const replacement = `move_count=0\natomic_replace() { ${body}; }`;
  assert.ok(script.includes(original));
  return script.replace(original, replacement);
}

function injectHardKillAfterMove(script, moveNumber) {
  const original = 'atomic_replace() { mv -f -- "$1" "$2"; }';
  const replacement = [
    "move_count=0",
    "atomic_replace() {",
    "  move_count=$((move_count + 1))",
    "  mv -f -- \"$1\" \"$2\"",
    `  if test \"$move_count\" = ${moveNumber}; then kill -KILL \"$$\"; fi`,
    "}",
  ].join("\n");
  assert.ok(script.includes(original));
  return script.replace(original, () => replacement);
}

test("every partial replacement point compensates to the exact failed candidate", async (t) => {
  for (const phase of ["before", "after"]) {
    for (let move = 1; move <= 5; move += 1) {
      await t.test(`${phase} move ${move}`, (child) => {
        const fixture = remoteFixture(child);
        const clean = buildRemoteRollbackInnerScript({
          contract: fixture.contract,
          mode: "execute",
          remoteRoot: fixture.root,
          stagingName: fixture.stagingName,
        });
        const script = injectMoveFailure(clean, move, phase === "after");
        const result = runInner(script, fixture.retainedFeedBytes);
        assert.notEqual(result.status, 0);
        assert.match(result.stderr, /ROLLBACK_COMPENSATION_OK/);
        assertOriginalPublicState(fixture);
        assertVersionedArtifactsRetained(fixture);
      });
    }
  }
});

test("SIGKILL after every public replacement resumes from the durable journal", async (t) => {
  for (let move = 1; move <= 5; move += 1) {
    await t.test(`after move ${move}`, (child) => {
      const fixture = remoteFixture(child);
      const clean = buildRemoteRollbackInnerScript({
        contract: fixture.contract,
        mode: "execute",
        remoteRoot: fixture.root,
        stagingName: fixture.stagingName,
      });
      const killed = runInner(injectHardKillAfterMove(clean, move), fixture.retainedFeedBytes);
      assert.equal(killed.signal, "SIGKILL");
      assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), true);
      assertActiveExactFreeze(fixture);
      assert.deepEqual(fs.readFileSync(path.join(fixture.root, "latest-mac.yml")), fixture.original["latest-mac.yml"]);

      const resumed = runInner(clean, fixture.retainedFeedBytes);
      assert.equal(resumed.status, 0, resumed.stderr);
      assert.match(resumed.stdout, /REMOTE_ROLLBACK_EXECUTE_OK state=(committed|recovered_committed)/);
      assertRollbackPublicState(fixture);
      assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), false);
    });
  }
});

test("execute resumes hard kills around journal creation and ambiguous remote completion", async (t) => {
  await t.test("before durable journal", (child) => {
    const fixture = remoteFixture(child);
    const clean = buildRemoteRollbackInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    const marker = `mkdir -m 0700 -- '${fixture.root}${fixture.stagingName}/backups'`;
    assert.ok(clean.includes(marker));
    const killed = runInner(clean.replace(marker, () => `${marker}\nkill -KILL \"$$\"`), fixture.retainedFeedBytes);
    assert.equal(killed.signal, "SIGKILL");
    assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), true);
    const resumed = runInner(clean, fixture.retainedFeedBytes);
    assert.equal(resumed.status, 0, resumed.stderr);
    assertRollbackPublicState(fixture);
  });

  await t.test("after journal rename before directory fsync", (child) => {
    const fixture = remoteFixture(child);
    const clean = buildRemoteRollbackInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    const journalMove = `  mv -f -- '${fixture.root}${fixture.stagingName}/transaction.json.tmp' '${fixture.root}${fixture.stagingName}/transaction.json'`;
    assert.ok(clean.includes(journalMove));
    const killed = runInner(
      clean.replace(journalMove, () => `${journalMove}\n  kill -KILL \"$$\"`),
      fixture.retainedFeedBytes,
    );
    assert.equal(killed.signal, "SIGKILL", killed.stderr);
    assert.equal(fs.existsSync(activeFreezePath(fixture)), false);
    for (const [name, bytes] of Object.entries(fixture.original)) {
      assert.deepEqual(fs.readFileSync(path.join(fixture.root, name)), bytes, name);
    }
    const adoptedStageSync = `  durable_sync '${fixture.root}${fixture.stagingName}/'`;
    assert.ok(clean.lastIndexOf(adoptedStageSync) < clean.indexOf("  mutation_started=1"));
    const resumed = runInner(clean, fixture.retainedFeedBytes);
    assert.equal(resumed.status, 0, resumed.stderr);
    assertRollbackPublicState(fixture);
    assertActiveExactFreeze(fixture);
  });

  await t.test("after remote commit before caller acknowledgement", (child) => {
    const fixture = remoteFixture(child);
    const clean = buildRemoteRollbackInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    const first = runInner(clean, fixture.retainedFeedBytes);
    assert.equal(first.status, 0, first.stderr);
    const resumed = runInner(clean, fixture.retainedFeedBytes);
    assert.equal(resumed.status, 0, resumed.stderr);
    assert.match(resumed.stdout, /state=already_committed/);
    assertRollbackPublicState(fixture);
  });

  await t.test("hard kill during stage retirement cannot strand the deterministic journal", (child) => {
    const fixture = remoteFixture(child);
    const clean = buildRemoteRollbackInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    const retireMove = `mv -- '${fixture.root}${fixture.stagingName}/' \"$tombstone\" || return 1`;
    assert.ok(clean.includes(retireMove));
    const killedScript = clean.replace(
      retireMove,
      () => `${retireMove}\n  kill -KILL \"$$\"`,
    );
    const killed = runInner(killedScript, fixture.retainedFeedBytes);
    assert.equal(killed.signal, "SIGKILL");
    assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), false);
    assertRollbackPublicState(fixture);
    const resumed = runInner(clean, fixture.retainedFeedBytes);
    assert.equal(resumed.status, 0, resumed.stderr);
    assert.match(resumed.stdout, /state=already_committed/);
    assertRollbackPublicState(fixture);
  });

  await t.test("committed public state wins over a partially deleted trusted stage", (child) => {
    const fixture = remoteFixture(child);
    const clean = buildRemoteRollbackInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    const killed = runInner(injectHardKillAfterMove(clean, 5), fixture.retainedFeedBytes);
    assert.equal(killed.signal, "SIGKILL");
    assertRollbackPublicState(fixture);
    const stage = path.join(fixture.root, fixture.stagingName);
    fs.rmSync(path.join(stage, "backups"), { recursive: true, force: true });
    fs.rmSync(path.join(stage, `retained-${BETA_FEED}`), { force: true });
    const resumed = runInner(clean, fixture.retainedFeedBytes);
    assert.equal(resumed.status, 0, resumed.stderr);
    assert.match(resumed.stdout, /state=recovered_committed/);
    assert.equal(fs.existsSync(stage), false);
    assertRollbackPublicState(fixture);
  });

  await t.test("failed compensation keeps the journal and backups recoverable", (child) => {
    const fixture = remoteFixture(child);
    const clean = buildRemoteRollbackInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    let broken = injectMoveFailure(clean, 1, true);
    broken = broken.replace("restore_one() {\n", "restore_one() {\n  return 1\n");
    const failed = runInner(broken, fixture.retainedFeedBytes);
    assert.equal(failed.status, 96);
    assert.match(failed.stderr, /ROLLBACK_COMPENSATION_FAILED_STAGE_PRESERVED/);
    assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), true);
    const resumed = runInner(clean, fixture.retainedFeedBytes);
    assert.equal(resumed.status, 0, resumed.stderr);
    assertRollbackPublicState(fixture);
  });
});

test("release-freeze clear is exact, archive-ready, and idempotent after later releases", (t) => {
  const fixture = remoteFixture(t);
  const execute = buildRemoteRollbackInnerScript({
    contract: fixture.contract,
    mode: "execute",
    remoteRoot: fixture.root,
    stagingName: fixture.stagingName,
  });
  const committed = runInner(execute, fixture.retainedFeedBytes);
  assert.equal(committed.status, 0, committed.stderr);
  assertActiveExactFreeze(fixture);

  const clear = buildRemoteRollbackFreezeClearInnerScript({
    contract: fixture.contract,
    remoteRoot: fixture.root,
  });
  const cleared = runInner(clear);
  assert.equal(cleared.status, 0, cleared.stderr);
  assert.match(cleared.stdout, /REMOTE_ROLLBACK_FREEZE_CLEAR_OK state=cleared/);
  assert.equal(fs.existsSync(activeFreezePath(fixture)), false);
  assert.deepEqual(fs.readFileSync(clearedFreezePath(fixture)), rollbackFreezeBytes(fixture.contract));
  assert.equal(fs.statSync(clearedFreezePath(fixture)).mode & 0o777, 0o400);
  assertRollbackPublicState(fixture);

  // A release that legitimately starts after unfreeze may move both feeds.
  // The exact cleared marker, not stale public bytes, is the retry receipt.
  const laterBeta = Buffer.from("later-legitimate-beta\n");
  const laterStable = Buffer.from("later-legitimate-stable\n");
  fs.writeFileSync(path.join(fixture.root, BETA_FEED), laterBeta);
  fs.writeFileSync(path.join(fixture.root, "latest-mac.yml"), laterStable);
  const retried = runInner(clear);
  assert.equal(retried.status, 0, retried.stderr);
  assert.match(retried.stdout, /state=already_cleared/);
  assert.deepEqual(fs.readFileSync(path.join(fixture.root, BETA_FEED)), laterBeta);
  assert.deepEqual(fs.readFileSync(path.join(fixture.root, "latest-mac.yml")), laterStable);
});

test("release-freeze clear rejects every exact-candidate drift and leaves freeze active", async (t) => {
  const cases = [
    ["freeze", "RELEASE_FREEZE_CONFLICT", (fixture) => fs.appendFileSync(activeFreezePath(fixture), "drift")],
    ["Beta feed", "ROLLBACK_BETA_CAS_FAILED", (fixture) => fs.appendFileSync(path.join(fixture.root, BETA_FEED), "drift")],
    ["Stable feed", "STABLE_CAS_FAILED", (fixture) => fs.appendFileSync(path.join(fixture.root, "latest-mac.yml"), "drift")],
    ["alias", "ROLLBACK_ALIAS_MISMATCH_", (fixture) => fs.appendFileSync(path.join(fixture.root, fixture.aliases[0]), "drift")],
    ["rollback artifact", "ROLLBACK_X64_ZIP_MISMATCH", (fixture) => {
      const target = fixture.contract.rollbackArtifacts.find((item) => item.name.includes("-x64.zip"));
      fs.appendFileSync(path.join(fixture.root, target.name), "drift");
    }],
    ["failed artifact", "FAILED_ARM64_DMG_MISMATCH", (fixture) => {
      const target = fixture.contract.failedArtifacts.find((item) => item.name.includes("-arm64.dmg"));
      fs.appendFileSync(path.join(fixture.root, target.name), "drift");
    }],
  ];
  for (const [label, code, mutate] of cases) {
    await t.test(label, (child) => {
      const fixture = remoteFixture(child);
      const execute = buildRemoteRollbackInnerScript({
        contract: fixture.contract,
        mode: "execute",
        remoteRoot: fixture.root,
        stagingName: fixture.stagingName,
      });
      assert.equal(runInner(execute, fixture.retainedFeedBytes).status, 0);
      mutate(fixture);
      const clear = buildRemoteRollbackFreezeClearInnerScript({
        contract: fixture.contract,
        remoteRoot: fixture.root,
      });
      const result = runInner(clear);
      assert.notEqual(result.status, 0);
      assert.match(result.stderr, new RegExp(code));
      assert.equal(fs.existsSync(activeFreezePath(fixture)), true);
      assert.equal(fs.existsSync(clearedFreezePath(fixture)), false);
    });
  }
});

test("SIGKILL during active-freeze retirement resumes from the durable cleared marker", (t) => {
  const fixture = remoteFixture(t);
  const execute = buildRemoteRollbackInnerScript({
    contract: fixture.contract,
    mode: "execute",
    remoteRoot: fixture.root,
    stagingName: fixture.stagingName,
  });
  assert.equal(runInner(execute, fixture.retainedFeedBytes).status, 0);
  const clear = buildRemoteRollbackFreezeClearInnerScript({ contract: fixture.contract, remoteRoot: fixture.root });
  const retirement = `durable_sync '${fixture.root}'\nrm -f -- '${activeFreezePath(fixture)}'`;
  assert.ok(clear.includes(retirement));
  const killed = runInner(clear.replace(retirement, () => `durable_sync '${fixture.root}'\nkill -KILL \"$$\"\nrm -f -- '${activeFreezePath(fixture)}'`));
  assert.equal(killed.signal, "SIGKILL");
  assert.deepEqual(fs.readFileSync(activeFreezePath(fixture)), rollbackFreezeBytes(fixture.contract));
  assert.deepEqual(fs.readFileSync(clearedFreezePath(fixture)), rollbackFreezeBytes(fixture.contract));
  const resumed = runInner(clear);
  assert.equal(resumed.status, 0, resumed.stderr);
  assert.match(resumed.stdout, /state=completed_clear/);
  assert.equal(fs.existsSync(activeFreezePath(fixture)), false);
  assertRollbackPublicState(fixture);
});

test("two-phase clear resumes real SIGKILL on both sides of active-freeze unlink", async (t) => {
  const phases = [
    ["after cleared marker rename before fsync", (fixture, clear) => {
      const markerMove = `mv -- '${clearedFreezePath(fixture)}.tmp' '${clearedFreezePath(fixture)}'`;
      assert.ok(clear.includes(markerMove));
      return clear.replace(markerMove, () => `${markerMove}\nkill -KILL \"$$\"`);
    }, true],
    ["after active unlink before directory fsync", (fixture, clear) => {
      const unlink = `rm -f -- '${activeFreezePath(fixture)}'\ndurable_sync '${fixture.root}'`;
      assert.ok(clear.includes(unlink));
      return clear.replace(unlink, () => `rm -f -- '${activeFreezePath(fixture)}'\nkill -KILL \"$$\"\ndurable_sync '${fixture.root}'`);
    }, false],
  ];
  for (const [label, inject, expectActive] of phases) {
    await t.test(label, (child) => {
      const fixture = remoteFixture(child);
      const execute = buildRemoteRollbackInnerScript({
        contract: fixture.contract,
        mode: "execute",
        remoteRoot: fixture.root,
        stagingName: fixture.stagingName,
      });
      assert.equal(runInner(execute, fixture.retainedFeedBytes).status, 0);
      const clear = buildRemoteRollbackFreezeClearInnerScript({ contract: fixture.contract, remoteRoot: fixture.root });
      const killed = runInner(inject(fixture, clear));
      assert.equal(killed.signal, "SIGKILL");
      assert.equal(fs.existsSync(activeFreezePath(fixture)), expectActive);
      assert.deepEqual(fs.readFileSync(clearedFreezePath(fixture)), rollbackFreezeBytes(fixture.contract));
      const resumed = runInner(clear);
      assert.equal(resumed.status, 0, resumed.stderr);
      assert.match(resumed.stdout, /state=(completed_clear|already_cleared)/);
      assert.equal(fs.existsSync(activeFreezePath(fixture)), false);
      assertRollbackPublicState(fixture);
    });
  }
});

test("every post-commit versioned-artifact mismatch is detected and public pointers compensate", async (t) => {
  const cases = [
    ...["x64", "arm64"].flatMap((arch) => ["zip", "dmg"].map((kind) => ({
      family: "rollback",
      arch,
      kind,
      code: `ROLLBACK_${arch.toUpperCase()}_${kind.toUpperCase()}_MISMATCH`,
    }))),
    ...["x64", "arm64"].flatMap((arch) => ["zip", "dmg"].map((kind) => ({
      family: "failed",
      arch,
      kind,
      code: `FAILED_${arch.toUpperCase()}_${kind.toUpperCase()}_MISMATCH`,
    }))),
  ];
  for (const item of cases) {
    await t.test(`${item.family} ${item.arch} ${item.kind}`, (child) => {
      const fixture = remoteFixture(child);
      const artifact = fixture.contract[`${item.family}Artifacts`].find((candidate) => (
        candidate.name.includes(`-mac-${item.arch}.`) && candidate.name.endsWith(`.${item.kind}`)
      ));
      const clean = buildRemoteRollbackInnerScript({
        contract: fixture.contract,
        mode: "execute",
        remoteRoot: fixture.root,
        stagingName: fixture.stagingName,
      });
      const postCommitMarker = `assert_sha256 '${fixture.root}latest-mac.yml' '${fixture.contract.stableFeedSha256}' STABLE_CAS_FAILED`;
      const markerIndex = clean.lastIndexOf(postCommitMarker);
      assert.notEqual(markerIndex, -1);
      const script = `${clean.slice(0, markerIndex)}printf x >> '${fixture.root}${artifact.name}'\n${clean.slice(markerIndex)}`;
      const result = runInner(script, fixture.retainedFeedBytes);
      assert.notEqual(result.status, 0);
      assert.match(result.stderr, new RegExp(item.code));
      assert.match(result.stderr, /ROLLBACK_COMPENSATION_OK/);
      assertOriginalPublicState(fixture);
    });
  }
});

test("retained-feed and stage collisions fail with zero public changes", async (t) => {
  await t.test("wrong streamed retained bytes", (child) => {
    const fixture = remoteFixture(child);
    const script = buildRemoteRollbackInnerScript({
      contract: fixture.contract,
      mode: "dry-run",
      remoteRoot: fixture.root,
      stagingName: fixture.dryRunStagingName,
    });
    const result = runInner(script, Buffer.from("wrong retained bytes\n"));
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /RETAINED_FEED_MISMATCH/);
    assertOriginalPublicState(fixture);
  });
  await t.test("pre-existing stage", (child) => {
    const fixture = remoteFixture(child);
    fs.mkdirSync(path.join(fixture.root, fixture.dryRunStagingName));
    const script = buildRemoteRollbackInnerScript({
      contract: fixture.contract,
      mode: "dry-run",
      remoteRoot: fixture.root,
      stagingName: fixture.dryRunStagingName,
    });
    const result = runInner(script, fixture.retainedFeedBytes);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /STAGE_COLLISION/);
    for (const [name, bytes] of Object.entries(fixture.original)) {
      assert.deepEqual(fs.readFileSync(path.join(fixture.root, name)), bytes);
    }
  });
});

test("immutable evidence archive contains exact receipt/feed/readback bytes and no operational data", (t) => {
  const fixture = candidateFixture(t);
  const contract = loadRollbackContract(fixture.options);
  const evidenceRoot = path.join(fixture.root, "evidence");
  const before = {
    betaBytes: fixture.failedFeed.bytes,
    stableBytes: fixture.stableFeed.bytes,
    beta: { size: fixture.failedFeed.bytes.length, sha256: sha256(fixture.failedFeed.bytes) },
    stable: { size: fixture.stableFeed.bytes.length, sha256: sha256(fixture.stableFeed.bytes) },
  };
  const after = {
    betaBytes: fixture.rollbackFeed.bytes,
    stableBytes: fixture.stableFeed.bytes,
    beta: { size: fixture.rollbackFeed.bytes.length, sha256: sha256(fixture.rollbackFeed.bytes) },
    stable: { size: fixture.stableFeed.bytes.length, sha256: sha256(fixture.stableFeed.bytes) },
  };
  const options = {
    contract,
    mode: "execute",
    evidenceRoot,
    startedAt: "2026-07-15T10:00:00.000Z",
    completedAt: "2026-07-15T10:01:00.000Z",
    before,
    after,
    aliases: Object.fromEntries(EXPECTED_ALIASES.map((alias) => {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      const expected = contract.rollbackDmgs[arch];
      return [alias, {
        size: expected.size,
        sha256: "1".repeat(64),
        sha512: expected.sha512,
        source: expected.url,
      }];
    })),
    versionedArtifacts: Object.fromEntries(
      contract.rollbackArtifacts.map((item) => [item.name, {
        size: item.size,
        sha256: "2".repeat(64),
        sha512: item.sha512,
      }]),
    ),
    remote: { marker: "REMOTE_ROLLBACK_EXECUTE_OK" },
    host: "root@example.invalid",
    remoteRoot: "/var/www/elevate-updates/",
  };
  const intent = writeExecuteIntent({
    contract,
    evidenceRoot,
    startedAt: options.startedAt,
    before,
  });
  assert.equal(intent.intent.candidate_id, contract.candidateId);
  assert.equal(intent.before.beta.sha256, contract.expectedFailedFeedSha256);
  const loadedIntent = loadExecuteIntent({ contract, evidenceRoot });
  assert.equal(loadedIntent.intent.intent_id, intent.intent.intent_id);
  assert.deepEqual(loadedIntent.before.betaBytes, before.betaBytes);

  const result = writeEvidenceArchive(options);
  const evidence = JSON.parse(fs.readFileSync(path.join(result.archivePath, "rollback.json")));
  const archive = JSON.parse(fs.readFileSync(path.join(result.archivePath, "archive.json")));
  assert.equal(evidence.candidate_id, contract.candidateId);
  assert.equal(evidence.candidate_receipt_sha256, contract.candidateReceiptSha256);
  assert.equal(evidence.stable_untouched, true);
  assert.deepEqual(evidence.committed_paths, [...EXPECTED_ALIASES, BETA_FEED]);
  assert.equal(Object.keys(evidence.public_versioned_artifacts).length, 4);
  assert.deepEqual(evidence.stable_paths_written, []);
  assert.equal(evidence.profile_data_mutations, 0);
  assert.equal(receiptId(evidence, "rollback_id"), evidence.rollback_id);
  assert.equal(receiptId(archive, "archive_id"), archive.archive_id);
  assert.deepEqual(fs.readFileSync(path.join(result.archivePath, "candidate-receipt.json")), contract.receiptBytes);
  assert.deepEqual(fs.readFileSync(path.join(result.archivePath, "retained-beta-mac.yml")), contract.retainedFeedBytes);
  for (const [name, item] of Object.entries(archive.files)) {
    const bytes = fs.readFileSync(path.join(result.archivePath, name));
    assert.equal(bytes.length, item.size);
    assert.equal(sha256(bytes), item.sha256);
    assert.equal(fs.statSync(path.join(result.archivePath, name)).mode & 0o777, 0o400);
  }
  assert.equal(fs.statSync(result.archivePath).mode & 0o777, 0o500);
  const resumed = writeEvidenceArchive(options);
  assert.equal(resumed.archivePath, result.archivePath);
  assert.equal(resumed.evidence.rollback_id, result.evidence.rollback_id);

  fs.rmSync(path.join(intent.path, "retained-beta-mac.yml"));
  assert.throws(
    () => loadExecuteIntent({ contract, evidenceRoot }),
    /record mismatch|ENOENT/,
  );
  assert.equal(removeExecuteIntent({ contract, evidenceRoot }), true);
  assert.equal(loadExecuteIntent({ contract, evidenceRoot }), null);

  const recreated = writeExecuteIntent({
    contract,
    evidenceRoot,
    startedAt: options.startedAt,
    before,
  });
  const retiredByCrash = `${recreated.path}.retired-crash-fixture`;
  fs.renameSync(recreated.path, retiredByCrash);
  assert.equal(loadExecuteIntent({ contract, evidenceRoot }), null);
  assert.equal(writeEvidenceArchive(options).archivePath, result.archivePath);
  assert.equal(removeExecuteIntent({ contract, evidenceRoot }), false);
});

test("dependency-injected orchestration seals execute-complete before unfreeze and retires intent last", async (t) => {
  const fixture = candidateFixture(t);
  const contract = loadRollbackContract(fixture.options);
  const evidenceRoot = path.join(fixture.root, "orchestration-evidence");
  const before = {
    betaBytes: fixture.failedFeed.bytes,
    stableBytes: fixture.stableFeed.bytes,
    beta: { size: fixture.failedFeed.bytes.length, sha256: sha256(fixture.failedFeed.bytes) },
    stable: { size: fixture.stableFeed.bytes.length, sha256: sha256(fixture.stableFeed.bytes) },
  };
  const after = {
    betaBytes: fixture.rollbackFeed.bytes,
    stableBytes: fixture.stableFeed.bytes,
    beta: { size: fixture.rollbackFeed.bytes.length, sha256: sha256(fixture.rollbackFeed.bytes) },
    stable: { size: fixture.stableFeed.bytes.length, sha256: sha256(fixture.stableFeed.bytes) },
  };
  const archived = {
    archivePath: executeCompletePath(evidenceRoot, contract),
    evidence: { rollback_id: "rollback-proof", stable_untouched: true },
  };

  await t.test("new execution is archive then clear then intent retirement", () => {
    const calls = [];
    let archiveDurable = false;
    const result = runRollbackWorkflow({
      contract,
      mode: "execute",
      evidenceRoot,
      dependencies: {
        now: (() => {
          const values = ["2026-07-16T00:00:00.000Z", "2026-07-16T00:01:00.000Z"];
          return () => values.shift();
        })(),
        log: () => {},
        loadEvidenceArchive: () => null,
        loadExecuteIntent: () => null,
        fetchPublicFeeds: ({ expectedBeta }) => expectedBeta === "failed" ? before : after,
        writeExecuteIntent: ({ startedAt }) => ({
          startedAt,
          before,
          intent: { intent_id: "intent-proof" },
        }),
        runRemoteRollback: () => {
          calls.push("remote-commit");
          return { marker: "REMOTE_ROLLBACK_EXECUTE_OK" };
        },
        verifyPublicRollbackAliases: () => ({}),
        verifyPublicRollbackVersionedArtifacts: () => ({}),
        writeEvidenceArchive: () => {
          calls.push("execute-complete-archive");
          archiveDurable = true;
          return archived;
        },
        runRemoteRollbackFreezeClear: () => {
          assert.equal(archiveDurable, true);
          calls.push("release-freeze-clear");
          return { marker: "REMOTE_ROLLBACK_FREEZE_CLEAR_OK" };
        },
        removeExecuteIntent: () => calls.push("intent-retired"),
      },
    });
    assert.deepEqual(calls, [
      "remote-commit",
      "execute-complete-archive",
      "release-freeze-clear",
      "intent-retired",
    ]);
    assert.equal(result.release_freeze_clear_marker, "REMOTE_ROLLBACK_FREEZE_CLEAR_OK");
  });

  await t.test("unfreeze failure preserves the durable intent for retry", () => {
    const calls = [];
    assert.throws(() => runRollbackWorkflow({
      contract,
      mode: "execute",
      evidenceRoot,
      dependencies: {
        now: () => "2026-07-16T00:00:00.000Z",
        log: () => {},
        loadEvidenceArchive: () => null,
        loadExecuteIntent: () => null,
        fetchPublicFeeds: ({ expectedBeta }) => expectedBeta === "failed" ? before : after,
        writeExecuteIntent: ({ startedAt }) => ({ startedAt, before, intent: { intent_id: "intent-proof" } }),
        runRemoteRollback: () => ({ marker: "REMOTE_ROLLBACK_EXECUTE_OK" }),
        verifyPublicRollbackAliases: () => ({}),
        verifyPublicRollbackVersionedArtifacts: () => ({}),
        writeEvidenceArchive: () => {
          calls.push("execute-complete-archive");
          return archived;
        },
        runRemoteRollbackFreezeClear: () => {
          calls.push("release-freeze-clear-failed");
          throw new Error("clear transport lost");
        },
        removeExecuteIntent: () => calls.push("intent-retired"),
      },
    }), /clear transport lost/);
    assert.deepEqual(calls, ["execute-complete-archive", "release-freeze-clear-failed"]);
  });

  await t.test("completed retry adopts archive before idempotent clear without stale readback", () => {
    const calls = [];
    const result = runRollbackWorkflow({
      contract,
      mode: "execute",
      evidenceRoot,
      dependencies: {
        loadEvidenceArchive: () => {
          calls.push("archive-validated-and-fsynced");
          return archived;
        },
        fetchPublicFeeds: () => assert.fail("completed retry must not require stale public bytes"),
        runRemoteRollback: () => assert.fail("completed retry must not rerun rollback mutation"),
        runRemoteRollbackFreezeClear: () => {
          calls.push("release-freeze-clear");
          return { marker: "REMOTE_ROLLBACK_FREEZE_CLEAR_OK" };
        },
        removeExecuteIntent: () => calls.push("intent-retired"),
      },
    });
    assert.deepEqual(calls, ["archive-validated-and-fsynced", "release-freeze-clear", "intent-retired"]);
    assert.equal(result.resumed_completed_evidence, true);
  });
});

// ---------------------------------------------------------------------------
// Roll-forward recovery activation (realtor-beta-recovery-roll-forward-v1)
// ---------------------------------------------------------------------------

function recoveryCandidateFixture(t) {
  const root = tempDirectory(t, "elevate-recovery-candidate-");
  const candidateFeed = feedFixture("1.2.75", "Elevate-Beta");
  const recoveryFeed = feedFixture("1.2.76", "Elevate-Beta-Recovery");
  const rollbackFeed = feedFixture("1.2.65", "Elevate");
  const stableFeed = feedFixture("1.2.63", "Elevate");
  const rollbackSnapshot = snapshot("beta", "1.2.65", rollbackFeed);
  const stableSnapshot = snapshot("latest", "1.2.63", stableFeed);
  const artifacts = Object.fromEntries(candidateFeed.artifacts.map((item) => [item.url, {
    path: `dist/${item.url}`,
    size: item.size,
    sha256: item.sha256,
    sha512: item.sha512,
  }]));
  artifacts[BETA_FEED] = {
    path: `dist/${BETA_FEED}`,
    size: candidateFeed.bytes.length,
    sha256: sha256(candidateFeed.bytes),
  };
  const recovery = {
    schema_version: 1,
    kind: "elevate-beta-recovery-package",
    candidate_version: "1.2.75",
    version: EXPECTED_RECOVERY_VERSION,
    reserved_version: EXPECTED_RECOVERY_VERSION,
    next_full_beta_minimum_exclusive: EXPECTED_RECOVERY_VERSION,
    source_receipt_id: "a".repeat(64),
    channel: "beta",
    public_feed_name: BETA_FEED,
    artifact_names: recoveryFeed.artifacts.map((item) => item.url),
    local_feed: {
      path: "desktop/dist/recovery/beta-mac.yml",
      size: recoveryFeed.bytes.length,
      sha256: sha256(recoveryFeed.bytes),
      sha512: sha512(recoveryFeed.bytes),
      manifest: yaml.load(recoveryFeed.bytes.toString("utf8")),
    },
    artifacts: Object.fromEntries(recoveryFeed.artifacts.map((item) => [item.url, {
      path: `dist/recovery/${item.url}`,
      size: item.size,
      sha256: item.sha256,
      sha512: item.sha512,
      architecture: item.url.includes("-arm64.") ? "arm64" : "x64",
      format: item.url.endsWith(".zip") ? "zip" : "dmg",
    }])),
    static_provenance: {
      runtime_policy: {
        backend: false, cli: false, gateway: false, runtime: false, tools: false, profile_preserved: true,
      },
    },
  };
  const receipt = {
    schema_version: 2,
    kind: "elevate-final-candidate",
    source_receipt_id: "a".repeat(64),
    release: {
      channel: "beta",
      version: "1.2.75",
      feed_name: BETA_FEED,
      profile: { channel: "beta" },
      artifact_names: candidateFeed.artifacts.map((item) => item.url),
      download_aliases: EXPECTED_ALIASES,
    },
    artifacts,
    recovery,
    rollback_target: structuredClone(rollbackSnapshot),
    public_feeds_at_finalize: {
      beta: structuredClone(rollbackSnapshot),
      latest: structuredClone(stableSnapshot),
    },
  };
  receipt.candidate_id = receiptId(receipt, "candidate_id");
  const receiptPath = path.join(root, "candidate-receipt.json");

  function writeReceipt(value = receipt) {
    const copy = structuredClone(value);
    copy.candidate_id = receiptId(copy, "candidate_id");
    const bytes = Buffer.from(`${JSON.stringify(copy, null, 2)}\n`);
    fs.writeFileSync(receiptPath, bytes);
    return { receipt: copy, sha256: sha256(bytes) };
  }
  const written = writeReceipt();
  return {
    root,
    receiptPath,
    candidateFeed,
    recoveryFeed,
    stableFeed,
    writeReceipt,
    ...written,
    options: {
      candidateReceiptPath: receiptPath,
      expectedCandidateReceiptSha256: written.sha256,
    },
  };
}

function recoveryRemoteFixture(t) {
  const root = `${tempDirectory(t, "elevate-recovery-remote-")}/remote/`;
  fs.mkdirSync(root);
  const stableBytes = Buffer.from("stable-feed-exact\n");
  const candidateFeedBytes = Buffer.from("candidate-beta-feed-1.2.75-exact\n");
  const recoveryFeedBytes = Buffer.from("retained-recovery-feed-1.2.76-exact\n");
  const candidateDmgBytes = {
    x64: Buffer.from("candidate-x64-dmg\n"),
    arm64: Buffer.from("candidate-arm64-dmg\n"),
  };
  const candidateZipBytes = {
    x64: Buffer.from("candidate-x64-zip\n"),
    arm64: Buffer.from("candidate-arm64-zip\n"),
  };
  const recoveryDmgBytesByArch = {
    x64: Buffer.from("recovery-x64-dmg\n"),
    arm64: Buffer.from("recovery-arm64-dmg\n"),
  };
  const recoveryZipBytes = {
    x64: Buffer.from("recovery-x64-zip\n"),
    arm64: Buffer.from("recovery-arm64-zip\n"),
  };
  const aliases = [
    "Alias-A-mac-x64.dmg",
    "Alias-B-mac-x64.dmg",
    "Alias-A-mac-arm64.dmg",
    "Alias-B-mac-arm64.dmg",
  ];
  const candidateArtifacts = ["x64", "arm64"].flatMap((arch) => [
    { name: `Elevate-Beta-1.2.75-mac-${arch}.zip`, ...record(candidateZipBytes[arch]) },
    { name: `Elevate-Beta-1.2.75-mac-${arch}.dmg`, ...record(candidateDmgBytes[arch]) },
  ]);
  const recoveryArtifacts = ["x64", "arm64"].flatMap((arch) => [
    { name: `Elevate-Beta-Recovery-1.2.76-mac-${arch}.zip`, ...record(recoveryZipBytes[arch]) },
    { name: `Elevate-Beta-Recovery-1.2.76-mac-${arch}.dmg`, ...record(recoveryDmgBytesByArch[arch]) },
  ]);
  const candidateDmgs = Object.fromEntries(["x64", "arm64"].map((arch) => [
    arch,
    candidateArtifacts.find((item) => item.name.endsWith(`-mac-${arch}.dmg`)),
  ]));
  const recoveryDmgs = Object.fromEntries(["x64", "arm64"].map((arch) => {
    const item = recoveryArtifacts.find((entry) => entry.name.endsWith(`-mac-${arch}.dmg`));
    return [arch, { ...item, url: item.name }];
  }));
  const candidateArtifactBytes = Object.fromEntries(candidateArtifacts.map((item) => [
    item.name,
    item.name.endsWith(".zip")
      ? candidateZipBytes[item.name.includes("-arm64.") ? "arm64" : "x64"]
      : candidateDmgBytes[item.name.includes("-arm64.") ? "arm64" : "x64"],
  ]));
  const recoveryArtifactBytes = Object.fromEntries(recoveryArtifacts.map((item) => [
    item.name,
    item.name.endsWith(".zip")
      ? recoveryZipBytes[item.name.includes("-arm64.") ? "arm64" : "x64"]
      : recoveryDmgBytesByArch[item.name.includes("-arm64.") ? "arm64" : "x64"],
  ]));
  const contract = {
    candidateId: "e".repeat(64),
    sourceReceiptId: "a".repeat(64),
    candidateVersion: "1.2.75",
    recoveryVersion: EXPECTED_RECOVERY_VERSION,
    stableFeedSha256: sha256(stableBytes),
    candidateFeedSha256: sha256(candidateFeedBytes),
    recoveryFeedSha256: sha256(recoveryFeedBytes),
    candidateArtifacts,
    candidateDmgs,
    recoveryArtifacts,
    recoveryDmgs,
    aliases,
  };
  const retainedFeedName = recoveryRetainedFeedName(contract);
  fs.writeFileSync(path.join(root, "latest-mac.yml"), stableBytes);
  fs.writeFileSync(path.join(root, "beta-mac.yml"), candidateFeedBytes);
  fs.writeFileSync(path.join(root, retainedFeedName), recoveryFeedBytes);
  for (const [name, bytes] of Object.entries(candidateArtifactBytes)) fs.writeFileSync(path.join(root, name), bytes);
  for (const [name, bytes] of Object.entries(recoveryArtifactBytes)) fs.writeFileSync(path.join(root, name), bytes);
  for (const alias of aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    fs.writeFileSync(path.join(root, alias), candidateDmgBytes[arch]);
  }
  const stagingName = `.recovery-${contract.candidateId}-execute`;
  const dryRunStagingName = `.recovery-${contract.candidateId}-00000000-0000-4000-8000-000000000000`;
  const publicNames = ["latest-mac.yml", "beta-mac.yml", ...aliases];
  const original = Object.fromEntries(publicNames.map((name) => [name, fs.readFileSync(path.join(root, name))]));
  return {
    root,
    contract,
    aliases,
    stagingName,
    dryRunStagingName,
    retainedFeedName,
    stableBytes,
    candidateFeedBytes,
    recoveryFeedBytes,
    candidateDmgBytes,
    recoveryDmgBytesByArch,
    candidateArtifactBytes,
    recoveryArtifactBytes,
    original,
  };
}

function assertRecoveryRetainedBytes(fixture) {
  assert.deepEqual(fs.readFileSync(path.join(fixture.root, fixture.retainedFeedName)), fixture.recoveryFeedBytes);
  for (const [name, bytes] of Object.entries(fixture.candidateArtifactBytes)) {
    assert.deepEqual(fs.readFileSync(path.join(fixture.root, name)), bytes, `candidate artifact ${name}`);
  }
  for (const [name, bytes] of Object.entries(fixture.recoveryArtifactBytes)) {
    assert.deepEqual(fs.readFileSync(path.join(fixture.root, name)), bytes, `recovery artifact ${name}`);
  }
}

function assertRecoveryOriginalPublicState(fixture) {
  for (const [name, bytes] of Object.entries(fixture.original)) {
    assert.deepEqual(fs.readFileSync(path.join(fixture.root, name)), bytes, name);
  }
  assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), false);
  assert.equal(fs.existsSync(path.join(fixture.root, fixture.dryRunStagingName)), false);
}

function assertRecoveryActivatedState(fixture) {
  assert.deepEqual(fs.readFileSync(path.join(fixture.root, BETA_FEED)), fixture.recoveryFeedBytes);
  assert.deepEqual(fs.readFileSync(path.join(fixture.root, "latest-mac.yml")), fixture.original["latest-mac.yml"]);
  for (const alias of fixture.aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    assert.deepEqual(fs.readFileSync(path.join(fixture.root, alias)), fixture.recoveryDmgBytesByArch[arch]);
  }
  assertRecoveryRetainedBytes(fixture);
}

function activationFreezePath(fixture) {
  return path.join(fixture.root, ROLLBACK_FREEZE_FILE);
}

function activationClearedPath(fixture) {
  return path.join(fixture.root, recoveryActivationFreezeClearedFile(fixture.contract));
}

function assertActiveExactActivationFreeze(fixture) {
  assert.deepEqual(fs.readFileSync(activationFreezePath(fixture)), recoveryActivationFreezeBytes(fixture.contract));
  assert.equal(fs.existsSync(activationClearedPath(fixture)), false);
}

test("recovery activation contract binds the exact receipt, recovery package, Stable, DMGs, and aliases", (t) => {
  const fixture = recoveryCandidateFixture(t);
  const contract = loadRecoveryActivationContract(fixture.options);
  assert.equal(contract.candidateId, fixture.receipt.candidate_id);
  assert.equal(contract.candidateReceiptSha256, fixture.options.expectedCandidateReceiptSha256);
  assert.equal(contract.candidateVersion, "1.2.75");
  assert.equal(contract.recoveryVersion, EXPECTED_RECOVERY_VERSION);
  assert.equal(contract.candidateFeedSha256, sha256(fixture.candidateFeed.bytes));
  assert.equal(contract.recoveryFeedSha256, sha256(fixture.recoveryFeed.bytes));
  assert.equal(contract.stableFeedSha256, sha256(fixture.stableFeed.bytes));
  assert.equal(contract.retainedFeedName, `.realtor-beta-recovery-${EXPECTED_RECOVERY_VERSION}-${BETA_FEED}`);
  assert.deepEqual(contract.aliases, EXPECTED_ALIASES);
  assert.deepEqual(Object.keys(contract.candidateDmgs), ["x64", "arm64"]);
  assert.deepEqual(Object.keys(contract.recoveryDmgs), ["x64", "arm64"]);
  assert.equal(contract.candidateArtifacts.length, 4);
  assert.equal(contract.recoveryArtifacts.length, 4);
  assert.equal(contract.recoverySnapshot.version, EXPECTED_RECOVERY_VERSION);
});

test("recovery activation contract fails closed for every receipt or package drift", (t) => {
  const fixture = recoveryCandidateFixture(t);
  assert.throws(
    () => loadRecoveryActivationContract({ ...fixture.options, expectedCandidateReceiptSha256: "0".repeat(64) }),
    /candidate receipt SHA256 mismatch/,
  );

  const forged = structuredClone(fixture.receipt);
  forged.candidate_id = "b".repeat(64);
  const forgedBytes = Buffer.from(`${JSON.stringify(forged, null, 2)}\n`);
  fs.writeFileSync(fixture.receiptPath, forgedBytes);
  assert.throws(
    () => loadRecoveryActivationContract({ ...fixture.options, expectedCandidateReceiptSha256: sha256(forgedBytes) }),
    /invalid or forged final candidate receipt/,
  );

  const mutations = [
    ["missing recovery package", (receipt) => { delete receipt.recovery; }, /no bound roll-forward recovery package/],
    ["recovery bound to another candidate", (receipt) => { receipt.recovery.candidate_version = "1.2.72"; }, /not bound to this exact candidate/],
    ["recovery not the pinned target", (receipt) => {
      receipt.recovery.version = "1.2.77";
      receipt.recovery.reserved_version = "1.2.77";
    }, /exact Beta 1\.2\.76/],
    ["recovery not a roll-forward", (receipt) => {
      receipt.release.version = "1.2.76";
      receipt.recovery.candidate_version = "1.2.76";
      receipt.release.artifact_names = receipt.release.artifact_names.map((name) => name.replace("1.2.75", "1.2.76"));
      receipt.artifacts = Object.fromEntries(Object.entries(receipt.artifacts).map(([name, value]) => [
        name.replace("1.2.75", "1.2.76"), value,
      ]));
    }, /strictly newer than the candidate/],
    ["runtime policy not minimal", (receipt) => { receipt.recovery.static_provenance.runtime_policy.gateway = true; }, /minimal profile-preserving/],
    ["recovery artifact set drift", (receipt) => { receipt.recovery.artifact_names[0] = "Elevate-Beta-Recovery-1.2.76-mac-x64.pkg"; }, /exact retained recovery set/],
    ["recovery bytes reuse candidate bytes", (receipt) => {
      const name = receipt.recovery.artifact_names.find((item) => item.endsWith("-mac-x64.dmg"));
      const candidateName = receipt.release.artifact_names.find((item) => item.endsWith("-mac-x64.dmg"));
      receipt.recovery.artifacts[name].sha256 = receipt.artifacts[candidateName].sha256;
    }, /reuses candidate bytes/],
    ["recovery feed manifest drift", (receipt) => { receipt.recovery.local_feed.manifest.files[0].size += 1; }, /manifest does not match/],
    ["recovery feed reuses candidate feed", (receipt) => {
      receipt.recovery.local_feed.sha256 = receipt.artifacts[BETA_FEED].sha256;
    }, /reuses the candidate feed bytes/],
    ["alias contract", (receipt) => { receipt.release.download_aliases = receipt.release.download_aliases.slice(0, 3); }, /alias contract mismatch/],
    ["Stable snapshot", (receipt) => { receipt.public_feeds_at_finalize.latest.status = 500; }, /valid Stable snapshot/],
    ["channel", (receipt) => { receipt.release.channel = "latest"; }, /not an exact Beta candidate/],
    ["candidate artifact record", (receipt) => {
      const name = receipt.release.artifact_names.find((item) => item.endsWith("-mac-x64.dmg"));
      delete receipt.artifacts[name];
    }, /missing failed artifact record/],
  ];
  for (const [label, mutate, pattern] of mutations) {
    const value = structuredClone(fixture.receipt);
    mutate(value);
    const written = fixture.writeReceipt(value);
    assert.throws(
      () => loadRecoveryActivationContract({ ...fixture.options, expectedCandidateReceiptSha256: written.sha256 }),
      pattern,
      label,
    );
  }
});

test("recover lane CLI binds only to the receipt and rejects rollback-only inputs", () => {
  const base = [
    "--mode", "dry-run",
    "--candidate-receipt", "/tmp/receipt.json",
    "--candidate-receipt-sha256", "a".repeat(64),
  ];
  assert.equal(parseArguments([...base])["--lane"], "rollback");
  assert.equal(parseArguments([...base, "--lane", "recover"])["--lane"], "recover");
  assert.throws(() => parseArguments([...base, "--lane", "downgrade"]), /unsupported --lane/);
  assert.throws(
    () => parseArguments([...base, "--lane", "recover", "--retained-feed", "/tmp/x.yml"]),
    /binds only to the candidate receipt/,
  );
  assert.throws(
    () => parseArguments([...base, "--lane", "recover", "--expected-failed-feed-sha256", "b".repeat(64)]),
    /binds only to the candidate receipt/,
  );
});

test("remote recovery modes are globally locked, retention-verified, and scoped to Beta", (t) => {
  const fixture = recoveryRemoteFixture(t);
  const transaction = buildRemoteRecoveryTransaction({
    contract: fixture.contract,
    mode: "execute",
    remoteRoot: fixture.root,
    stagingName: fixture.stagingName,
  });
  assert.match(transaction, new RegExp(`^flock -x -w 300 '${GLOBAL_LOCK.replaceAll("/", "\\/")}'`));
  const clearTransaction = buildRemoteRecoveryFreezeClearTransaction({
    contract: fixture.contract,
    remoteRoot: fixture.root,
  });
  assert.match(clearTransaction, new RegExp(`^flock -x -w 300 '${GLOBAL_LOCK.replaceAll("/", "\\/")}'`));
  assert.doesNotMatch(clearTransaction, /atomic_replace/);
  const script = buildRemoteRecoveryInnerScript({
    contract: fixture.contract,
    mode: "execute",
    remoteRoot: fixture.root,
    stagingName: fixture.stagingName,
  });
  for (const code of [
    "STABLE_CAS_FAILED", "RETAINED_RECOVERY_FEED_MISMATCH",
    "PARTIAL_PUBLIC_POINTER_STATE", "UNRECOGNIZED_BETA_FEED_STATE",
    "UNKNOWN_PARTIAL_PUBLIC_STATE",
    "RECOVERY_X64_ZIP_MISMATCH", "RECOVERY_X64_DMG_MISMATCH",
    "RECOVERY_ARM64_ZIP_MISMATCH", "RECOVERY_ARM64_DMG_MISMATCH",
    "CANDIDATE_X64_ZIP_MISMATCH", "CANDIDATE_X64_DMG_MISMATCH",
    "CANDIDATE_ARM64_ZIP_MISMATCH", "CANDIDATE_ARM64_DMG_MISMATCH",
    "JOURNAL_HASH_MISMATCH", "UNTRUSTED_STAGE_WITH_PARTIAL_PUBLIC_STATE",
    "STAGE_CROSS_FILESYSTEM", "STAGE_MODE_INVALID", "STAGED_FEED_MISMATCH",
    "STAGED_ALIAS_MISMATCH_", "BACKUP_FEED_MISMATCH", "BACKUP_ALIAS_MISMATCH_",
    "COMMITTED_FEED_MISMATCH", "COMMITTED_ALIAS_MISMATCH_",
    "RECOVERY_COMPENSATION_FAILED_STAGE_PRESERVED",
    "PARTIAL_STATE_WITHOUT_RELEASE_FREEZE", "COMMITTED_STATE_WITHOUT_RELEASE_FREEZE",
  ]) assert.match(script, new RegExp(code));
  assert.match(script, /mkdir -m 0700/);
  assert.match(script, /file_device/);
  assert.ok(script.includes(`cp -- '${fixture.root}${fixture.retainedFeedName}'`));
  assert.doesNotMatch(script, /scp|rsync/);

  const destinations = [...script.matchAll(/^\s*atomic_replace '[^']+' '([^']+)'$/gm)]
    .map((match) => path.basename(match[1]));
  assert.deepEqual(destinations, [...fixture.aliases, BETA_FEED]);
  assert.equal(destinations.at(-1), BETA_FEED);
  assert.equal(destinations.includes("latest-mac.yml"), false);

  const preflight = buildRemoteRecoveryInnerScript({
    contract: fixture.contract,
    mode: "preflight",
    remoteRoot: fixture.root,
  });
  assert.equal(/^atomic_replace /m.test(preflight), false);
  assert.equal(/mkdir -m 0700/m.test(preflight), false);

  const dryRun = buildRemoteRecoveryInnerScript({
    contract: fixture.contract,
    mode: "dry-run",
    remoteRoot: fixture.root,
    stagingName: fixture.dryRunStagingName,
  });
  for (const match of dryRun.matchAll(/^atomic_replace '[^']+' '([^']+)'$/gm)) {
    assert.ok(match[1].startsWith(`${fixture.root}${fixture.dryRunStagingName}/drill-current/`));
  }
});

test("real recovery preflight and dry-run stage retained bytes but leave every public byte untouched", (t) => {
  const fixture = recoveryRemoteFixture(t);
  const preflight = buildRemoteRecoveryInnerScript({
    contract: fixture.contract,
    mode: "preflight",
    remoteRoot: fixture.root,
  });
  const preflightResult = runInner(preflight);
  assert.equal(preflightResult.status, 0, preflightResult.stderr);
  assert.match(preflightResult.stdout, /REMOTE_RECOVERY_PREFLIGHT_OK/);
  const script = buildRemoteRecoveryInnerScript({
    contract: fixture.contract,
    mode: "dry-run",
    remoteRoot: fixture.root,
    stagingName: fixture.dryRunStagingName,
  });
  const result = runInner(script);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /REMOTE_RECOVERY_DRY_RUN_OK/);
  assertRecoveryOriginalPublicState(fixture);
  assertRecoveryRetainedBytes(fixture);
  assert.equal(fs.existsSync(activationFreezePath(fixture)), false);
});

test("real recovery execute activates 1.2.76 from retained bytes only and commits the feed last", (t) => {
  const fixture = recoveryRemoteFixture(t);
  const script = buildRemoteRecoveryInnerScript({
    contract: fixture.contract,
    mode: "execute",
    remoteRoot: fixture.root,
    stagingName: fixture.stagingName,
  });
  const result = runInner(script);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /REMOTE_RECOVERY_EXECUTE_OK state=committed/);
  assertRecoveryActivatedState(fixture);
  assertActiveExactActivationFreeze(fixture);
  assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), false);
});

test("missing or foreign retained recovery bytes fail closed with the candidate state intact", async (t) => {
  const cases = [
    ["retained recovery feed missing", "RETAINED_RECOVERY_FEED_MISMATCH", (fixture) => {
      fs.rmSync(path.join(fixture.root, fixture.retainedFeedName));
    }],
    ["retained recovery feed foreign bytes", "RETAINED_RECOVERY_FEED_MISMATCH", (fixture) => {
      fs.writeFileSync(path.join(fixture.root, fixture.retainedFeedName), "foreign-feed-bytes\n");
    }],
    ...["x64", "arm64"].flatMap((arch) => ["zip", "dmg"].map((kind) => [
      `recovery ${arch} ${kind} drifted`,
      `RECOVERY_${arch.toUpperCase()}_${kind.toUpperCase()}_MISMATCH`,
      (fixture) => {
        const artifact = fixture.contract.recoveryArtifacts.find((item) => (
          item.name.includes(`-mac-${arch}.`) && item.name.endsWith(`.${kind}`)
        ));
        fs.appendFileSync(path.join(fixture.root, artifact.name), "drift");
      },
    ])),
    ["recovery artifact missing", "RECOVERY_X64_DMG_MISMATCH", (fixture) => {
      fs.rmSync(path.join(fixture.root, fixture.contract.recoveryDmgs.x64.name));
    }],
    ["candidate versioned artifact drifted", "CANDIDATE_X64_ZIP_MISMATCH", (fixture) => {
      const artifact = fixture.contract.candidateArtifacts.find((item) => item.name.endsWith("-mac-x64.zip"));
      fs.appendFileSync(path.join(fixture.root, artifact.name), "drift");
    }],
    ["Stable drifted", "STABLE_CAS_FAILED", (fixture) => {
      fs.appendFileSync(path.join(fixture.root, "latest-mac.yml"), "drift");
    }],
    ["newer Beta feed won", "UNRECOGNIZED_BETA_FEED_STATE", (fixture) => {
      fs.writeFileSync(path.join(fixture.root, BETA_FEED), "newer-beta-release\n");
    }],
    ["alias drifted", "PARTIAL_PUBLIC_POINTER_STATE", (fixture) => {
      fs.appendFileSync(path.join(fixture.root, fixture.aliases[0]), "drift");
    }],
  ];
  for (const [label, code, mutate] of cases) {
    await t.test(label, (child) => {
      const fixture = recoveryRemoteFixture(child);
      mutate(fixture);
      const script = buildRemoteRecoveryInnerScript({
        contract: fixture.contract,
        mode: "execute",
        remoteRoot: fixture.root,
        stagingName: fixture.stagingName,
      });
      const result = runInner(script);
      assert.notEqual(result.status, 0);
      assert.match(result.stderr, new RegExp(code));
      assert.equal(fs.existsSync(activationFreezePath(fixture)), false);
      assert.equal(fs.existsSync(activationClearedPath(fixture)), false);
      assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), false);
    });
  }
});

test("every recovery partial replacement point compensates to the exact candidate state", async (t) => {
  for (const phase of ["before", "after"]) {
    for (let move = 1; move <= 5; move += 1) {
      await t.test(`${phase} move ${move}`, (child) => {
        const fixture = recoveryRemoteFixture(child);
        const clean = buildRemoteRecoveryInnerScript({
          contract: fixture.contract,
          mode: "execute",
          remoteRoot: fixture.root,
          stagingName: fixture.stagingName,
        });
        const script = injectMoveFailure(clean, move, phase === "after");
        const result = runInner(script);
        assert.notEqual(result.status, 0);
        assert.match(result.stderr, /RECOVERY_COMPENSATION_OK/);
        assertRecoveryOriginalPublicState(fixture);
        assertRecoveryRetainedBytes(fixture);
      });
    }
  }
});

test("SIGKILL after every recovery pointer move resumes from the durable journal", async (t) => {
  for (let move = 1; move <= 5; move += 1) {
    await t.test(`after move ${move}`, (child) => {
      const fixture = recoveryRemoteFixture(child);
      const clean = buildRemoteRecoveryInnerScript({
        contract: fixture.contract,
        mode: "execute",
        remoteRoot: fixture.root,
        stagingName: fixture.stagingName,
      });
      const killed = runInner(injectHardKillAfterMove(clean, move));
      assert.equal(killed.signal, "SIGKILL");
      assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), true);
      assertActiveExactActivationFreeze(fixture);
      assert.deepEqual(fs.readFileSync(path.join(fixture.root, "latest-mac.yml")), fixture.original["latest-mac.yml"]);

      const resumed = runInner(clean);
      assert.equal(resumed.status, 0, resumed.stderr);
      assert.match(resumed.stdout, /REMOTE_RECOVERY_EXECUTE_OK state=(committed|recovered_committed)/);
      assertRecoveryActivatedState(fixture);
      assertActiveExactActivationFreeze(fixture);
      assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), false);
    });
  }
});

test("recovery execute resumes crashes around freeze and journal creation and is idempotent", async (t) => {
  await t.test("SIGKILL immediately after freeze durability resumes without changing Stable", (child) => {
    const fixture = recoveryRemoteFixture(child);
    const clean = buildRemoteRecoveryInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    const freezeDurable = `    durable_sync '${fixture.root}'\n    freeze_present=1`;
    assert.ok(clean.includes(freezeDurable));
    const killed = runInner(clean.replace(freezeDurable, () => `${freezeDurable}\n    kill -KILL \"$$\"`));
    assert.equal(killed.signal, "SIGKILL", `status=${killed.status} stderr=${killed.stderr}`);
    assertActiveExactActivationFreeze(fixture);
    for (const [name, bytes] of Object.entries(fixture.original)) {
      assert.deepEqual(fs.readFileSync(path.join(fixture.root, name)), bytes, name);
    }
    const resumed = runInner(clean);
    assert.equal(resumed.status, 0, resumed.stderr);
    assertRecoveryActivatedState(fixture);
    assertActiveExactActivationFreeze(fixture);
  });

  await t.test("SIGKILL after journal rename resumes before pointer mutation", (child) => {
    const fixture = recoveryRemoteFixture(child);
    const clean = buildRemoteRecoveryInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    const journalMove = `  mv -f -- '${fixture.root}${fixture.stagingName}/transaction.json.tmp' '${fixture.root}${fixture.stagingName}/transaction.json'`;
    assert.ok(clean.includes(journalMove));
    const killed = runInner(clean.replace(journalMove, () => `${journalMove}\n  kill -KILL \"$$\"`));
    assert.equal(killed.signal, "SIGKILL", killed.stderr);
    assert.equal(fs.existsSync(activationFreezePath(fixture)), false);
    for (const [name, bytes] of Object.entries(fixture.original)) {
      assert.deepEqual(fs.readFileSync(path.join(fixture.root, name)), bytes, name);
    }
    const resumed = runInner(clean);
    assert.equal(resumed.status, 0, resumed.stderr);
    assertRecoveryActivatedState(fixture);
    assertActiveExactActivationFreeze(fixture);
  });

  await t.test("after remote commit before caller acknowledgement", (child) => {
    const fixture = recoveryRemoteFixture(child);
    const clean = buildRemoteRecoveryInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    const first = runInner(clean);
    assert.equal(first.status, 0, first.stderr);
    const resumed = runInner(clean);
    assert.equal(resumed.status, 0, resumed.stderr);
    assert.match(resumed.stdout, /state=already_committed/);
    assertRecoveryActivatedState(fixture);
  });

  await t.test("committed public state wins over a partially deleted trusted stage", (child) => {
    const fixture = recoveryRemoteFixture(child);
    const clean = buildRemoteRecoveryInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    const killed = runInner(injectHardKillAfterMove(clean, 5));
    assert.equal(killed.signal, "SIGKILL");
    assertRecoveryActivatedState(fixture);
    const stage = path.join(fixture.root, fixture.stagingName);
    fs.rmSync(path.join(stage, "backups"), { recursive: true, force: true });
    fs.rmSync(path.join(stage, `recovery-${BETA_FEED}`), { force: true });
    const resumed = runInner(clean);
    assert.equal(resumed.status, 0, resumed.stderr);
    assert.match(resumed.stdout, /state=recovered_committed/);
    assert.equal(fs.existsSync(stage), false);
    assertRecoveryActivatedState(fixture);
  });

  await t.test("failed compensation keeps the journal and backups recoverable", (child) => {
    const fixture = recoveryRemoteFixture(child);
    const clean = buildRemoteRecoveryInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    let broken = injectMoveFailure(clean, 1, true);
    broken = broken.replace("restore_one() {\n", "restore_one() {\n  return 1\n");
    const failed = runInner(broken);
    assert.equal(failed.status, 96);
    assert.match(failed.stderr, /RECOVERY_COMPENSATION_FAILED_STAGE_PRESERVED/);
    assert.equal(fs.existsSync(path.join(fixture.root, fixture.stagingName)), true);
    const resumed = runInner(clean);
    assert.equal(resumed.status, 0, resumed.stderr);
    assertRecoveryActivatedState(fixture);
  });
});

function stalePublishCandidateForRecoveryFixture(fixture, oldBetaSha) {
  const artifacts = Object.fromEntries(fixture.contract.candidateArtifacts.map((item) => [item.name, { sha256: item.sha256 }]));
  artifacts[BETA_FEED] = { sha256: fixture.contract.candidateFeedSha256 };
  return {
    candidate_id: fixture.contract.candidateId,
    source_receipt_id: fixture.contract.sourceReceiptId,
    public_feeds_at_finalize: {
      latest: { sha256: fixture.contract.stableFeedSha256 },
      beta: { sha256: oldBetaSha },
    },
    artifacts,
    rollback_target: { sha256: oldBetaSha },
    release: {
      channel: "beta",
      feed_name: BETA_FEED,
      artifact_names: fixture.contract.candidateArtifacts.map((item) => item.name),
      download_aliases: fixture.aliases,
    },
    recovery: {
      version: fixture.contract.recoveryVersion,
      artifact_names: fixture.contract.recoveryArtifacts.map((item) => item.name),
      local_feed: { sha256: fixture.contract.recoveryFeedSha256 },
      artifacts: Object.fromEntries(fixture.contract.recoveryArtifacts.map((item) => [item.name, { sha256: item.sha256 }])),
    },
  };
}

function stageStaleShip(fixture, stagingName) {
  const stage = path.join(fixture.root, stagingName);
  fs.mkdirSync(stage, { mode: 0o700 });
  fs.writeFileSync(path.join(stage, BETA_FEED), fixture.candidateFeedBytes);
  for (const item of fixture.contract.candidateArtifacts) {
    fs.writeFileSync(path.join(stage, item.name), fixture.candidateArtifactBytes[item.name]);
  }
  for (const item of fixture.contract.recoveryArtifacts) {
    fs.writeFileSync(path.join(stage, item.name), fixture.recoveryArtifactBytes[item.name]);
  }
  fs.writeFileSync(path.join(stage, `recovery-${BETA_FEED}`), fixture.recoveryFeedBytes);
  return stage;
}

test("activation freeze blocks a stale ship of the superseded candidate; CAS refuses it after clear", async (t) => {
  await t.test("freeze active then cleared", (child) => {
    const fixture = recoveryRemoteFixture(child);
    const env = fakeFlockEnvironment(child);
    const lock = path.join(tempDirectory(child, "elevate-release-lock-"), "release.lock");
    const oldBetaSha = sha256(Buffer.from("pre-candidate-old-beta\n"));
    const execute = buildRemoteRecoveryInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    assert.equal(runInner(execute).status, 0);
    assertRecoveryActivatedState(fixture);
    assertActiveExactActivationFreeze(fixture);

    const candidate = stalePublishCandidateForRecoveryFixture(fixture, oldBetaSha);
    const frozenStage = `.candidate-${fixture.contract.candidateId}-stale-frozen`;
    stageStaleShip(fixture, frozenStage);
    const frozenPublish = buildRemotePublishTransaction({
      candidate,
      remote: fixture.root,
      stagingName: frozenStage,
    }).replace(GLOBAL_LOCK, lock);
    const frozenResult = spawnSync("bash", ["-c", frozenPublish], { env, encoding: "utf8", timeout: 10_000 });
    assert.equal(frozenResult.status, 46, frozenResult.stderr);
    assert.match(frozenResult.stderr, /RELEASE_FREEZE_ACTIVE/);
    assertRecoveryActivatedState(fixture);
    assertActiveExactActivationFreeze(fixture);

    const clear = buildRemoteRecoveryFreezeClearInnerScript({ contract: fixture.contract, remoteRoot: fixture.root });
    const cleared = runInner(clear);
    assert.equal(cleared.status, 0, cleared.stderr);
    assert.equal(fs.existsSync(activationFreezePath(fixture)), false);

    const staleStage = `.candidate-${fixture.contract.candidateId}-stale-cleared`;
    stageStaleShip(fixture, staleStage);
    const stalePublish = buildRemotePublishTransaction({
      candidate,
      remote: fixture.root,
      stagingName: staleStage,
    }).replace(GLOBAL_LOCK, lock);
    const staleResult = spawnSync("bash", ["-c", stalePublish], { env, encoding: "utf8", timeout: 10_000 });
    assert.equal(staleResult.status, 42, staleResult.stderr);
    assert.match(staleResult.stderr, /PUBLISH_STATE_NOT_OLD/);
    assertRecoveryActivatedState(fixture);
    assert.deepEqual(fs.readFileSync(activationClearedPath(fixture)), recoveryActivationFreezeBytes(fixture.contract));
  });

  await t.test("recovery execute rejects a foreign rollback-lane freeze", (child) => {
    const fixture = recoveryRemoteFixture(child);
    fs.writeFileSync(activationFreezePath(fixture), "foreign-rollback-freeze\n");
    const execute = buildRemoteRecoveryInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    const result = runInner(execute);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /RELEASE_FREEZE_CONFLICT/);
    assertRecoveryOriginalPublicState(fixture);
    assert.deepEqual(fs.readFileSync(activationFreezePath(fixture)), Buffer.from("foreign-rollback-freeze\n"));
  });

  await t.test("rollback execute rejects a foreign activation-lane freeze", (child) => {
    const fixture = remoteFixture(child);
    fs.writeFileSync(activeFreezePath(fixture), "foreign-activation-freeze\n");
    const execute = buildRemoteRollbackInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    const result = runInner(execute, fixture.retainedFeedBytes);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /RELEASE_FREEZE_CONFLICT/);
    assertOriginalPublicState(fixture);
    assert.deepEqual(fs.readFileSync(activeFreezePath(fixture)), Buffer.from("foreign-activation-freeze\n"));
  });
});

test("recovery release-freeze clear is exact, two-phase durable, and idempotent after later releases", async (t) => {
  await t.test("clear then idempotent retry after a later legitimate release", (child) => {
    const fixture = recoveryRemoteFixture(child);
    const execute = buildRemoteRecoveryInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    assert.equal(runInner(execute).status, 0);
    const clear = buildRemoteRecoveryFreezeClearInnerScript({ contract: fixture.contract, remoteRoot: fixture.root });
    const cleared = runInner(clear);
    assert.equal(cleared.status, 0, cleared.stderr);
    assert.match(cleared.stdout, /REMOTE_RECOVERY_FREEZE_CLEAR_OK state=cleared/);
    assert.equal(fs.existsSync(activationFreezePath(fixture)), false);
    assert.deepEqual(fs.readFileSync(activationClearedPath(fixture)), recoveryActivationFreezeBytes(fixture.contract));
    assert.equal(fs.statSync(activationClearedPath(fixture)).mode & 0o777, 0o400);
    assertRecoveryActivatedState(fixture);

    const laterBeta = Buffer.from("later-legitimate-beta\n");
    const laterStable = Buffer.from("later-legitimate-stable\n");
    fs.writeFileSync(path.join(fixture.root, BETA_FEED), laterBeta);
    fs.writeFileSync(path.join(fixture.root, "latest-mac.yml"), laterStable);
    const retried = runInner(clear);
    assert.equal(retried.status, 0, retried.stderr);
    assert.match(retried.stdout, /state=already_cleared/);
    assert.deepEqual(fs.readFileSync(path.join(fixture.root, BETA_FEED)), laterBeta);
    assert.deepEqual(fs.readFileSync(path.join(fixture.root, "latest-mac.yml")), laterStable);
  });

  await t.test("clear rejects drift from the exact activated state and leaves the freeze active", async (child) => {
    const cases = [
      ["freeze", "RELEASE_FREEZE_CONFLICT", (fixture) => fs.appendFileSync(activationFreezePath(fixture), "drift")],
      ["Beta feed", "RECOVERY_BETA_CAS_FAILED", (fixture) => fs.appendFileSync(path.join(fixture.root, BETA_FEED), "drift")],
      ["Stable feed", "STABLE_CAS_FAILED", (fixture) => fs.appendFileSync(path.join(fixture.root, "latest-mac.yml"), "drift")],
      ["alias", "RECOVERY_ALIAS_MISMATCH_", (fixture) => fs.appendFileSync(path.join(fixture.root, fixture.aliases[0]), "drift")],
      ["retained recovery feed", "RETAINED_RECOVERY_FEED_MISMATCH", (fixture) => {
        fs.appendFileSync(path.join(fixture.root, fixture.retainedFeedName), "drift");
      }],
      ["retained recovery artifact", "RECOVERY_X64_ZIP_MISMATCH", (fixture) => {
        const target = fixture.contract.recoveryArtifacts.find((item) => item.name.includes("-x64.zip"));
        fs.appendFileSync(path.join(fixture.root, target.name), "drift");
      }],
      ["candidate versioned artifact", "CANDIDATE_ARM64_DMG_MISMATCH", (fixture) => {
        const target = fixture.contract.candidateArtifacts.find((item) => item.name.includes("-arm64.dmg"));
        fs.appendFileSync(path.join(fixture.root, target.name), "drift");
      }],
    ];
    for (const [label, code, mutate] of cases) {
      await child.test(label, (grandchild) => {
        const fixture = recoveryRemoteFixture(grandchild);
        const execute = buildRemoteRecoveryInnerScript({
          contract: fixture.contract,
          mode: "execute",
          remoteRoot: fixture.root,
          stagingName: fixture.stagingName,
        });
        assert.equal(runInner(execute).status, 0);
        mutate(fixture);
        const clear = buildRemoteRecoveryFreezeClearInnerScript({ contract: fixture.contract, remoteRoot: fixture.root });
        const result = runInner(clear);
        assert.notEqual(result.status, 0);
        assert.match(result.stderr, new RegExp(code));
        assert.equal(fs.existsSync(activationFreezePath(fixture)), true);
        assert.equal(fs.existsSync(activationClearedPath(fixture)), false);
      });
    }
  });

  await t.test("SIGKILL after cleared-marker rename resumes the two-phase clear", (child) => {
    const fixture = recoveryRemoteFixture(child);
    const execute = buildRemoteRecoveryInnerScript({
      contract: fixture.contract,
      mode: "execute",
      remoteRoot: fixture.root,
      stagingName: fixture.stagingName,
    });
    assert.equal(runInner(execute).status, 0);
    const clear = buildRemoteRecoveryFreezeClearInnerScript({ contract: fixture.contract, remoteRoot: fixture.root });
    const markerMove = `mv -- '${activationClearedPath(fixture)}.tmp' '${activationClearedPath(fixture)}'`;
    assert.ok(clear.includes(markerMove));
    const killed = runInner(clear.replace(markerMove, () => `${markerMove}\nkill -KILL \"$$\"`));
    assert.equal(killed.signal, "SIGKILL");
    assert.deepEqual(fs.readFileSync(activationFreezePath(fixture)), recoveryActivationFreezeBytes(fixture.contract));
    assert.deepEqual(fs.readFileSync(activationClearedPath(fixture)), recoveryActivationFreezeBytes(fixture.contract));
    const resumed = runInner(clear);
    assert.equal(resumed.status, 0, resumed.stderr);
    assert.match(resumed.stdout, /state=completed_clear/);
    assert.equal(fs.existsSync(activationFreezePath(fixture)), false);
    assertRecoveryActivatedState(fixture);
  });
});

test("immutable recovery activation evidence archive is receipt-bound with RPO 0", (t) => {
  const fixture = recoveryCandidateFixture(t);
  const contract = loadRecoveryActivationContract(fixture.options);
  const evidenceRoot = path.join(fixture.root, "evidence");
  const before = {
    betaBytes: fixture.candidateFeed.bytes,
    stableBytes: fixture.stableFeed.bytes,
    beta: { size: fixture.candidateFeed.bytes.length, sha256: sha256(fixture.candidateFeed.bytes) },
    stable: { size: fixture.stableFeed.bytes.length, sha256: sha256(fixture.stableFeed.bytes) },
  };
  const after = {
    betaBytes: fixture.recoveryFeed.bytes,
    stableBytes: fixture.stableFeed.bytes,
    beta: { size: fixture.recoveryFeed.bytes.length, sha256: sha256(fixture.recoveryFeed.bytes) },
    stable: { size: fixture.stableFeed.bytes.length, sha256: sha256(fixture.stableFeed.bytes) },
  };
  const options = {
    contract,
    mode: "execute",
    evidenceRoot,
    startedAt: "2026-07-16T10:00:00.000Z",
    completedAt: "2026-07-16T10:01:00.000Z",
    before,
    after,
    aliases: Object.fromEntries(EXPECTED_ALIASES.map((alias) => {
      const arch = alias.includes("-arm64.") ? "arm64" : "x64";
      const expected = contract.recoveryDmgs[arch];
      return [alias, {
        size: expected.size,
        sha256: "1".repeat(64),
        sha512: expected.sha512,
        source: expected.url,
      }];
    })),
    versionedArtifacts: Object.fromEntries(
      contract.recoveryArtifacts.map((item) => [item.name, {
        size: item.size,
        sha256: "2".repeat(64),
        sha512: item.sha512,
      }]),
    ),
    remote: { marker: "REMOTE_RECOVERY_EXECUTE_OK" },
    host: "root@example.invalid",
    remoteRoot: "/var/www/elevate-updates/",
  };
  const intent = writeRecoveryExecuteIntent({
    contract,
    evidenceRoot,
    startedAt: options.startedAt,
    before,
  });
  assert.equal(intent.intent.candidate_id, contract.candidateId);
  assert.equal(intent.before.beta.sha256, contract.candidateFeedSha256);
  const loadedIntent = loadRecoveryExecuteIntent({ contract, evidenceRoot });
  assert.equal(loadedIntent.intent.intent_id, intent.intent.intent_id);
  assert.deepEqual(loadedIntent.before.betaBytes, before.betaBytes);

  const result = writeRecoveryEvidenceArchive(options);
  const evidence = JSON.parse(fs.readFileSync(path.join(result.archivePath, "activation.json")));
  const archive = JSON.parse(fs.readFileSync(path.join(result.archivePath, "archive.json")));
  assert.equal(evidence.candidate_id, contract.candidateId);
  assert.equal(evidence.candidate_receipt_sha256, contract.candidateReceiptSha256);
  assert.equal(evidence.procedure_id, REALTOR_BETA_RECOVERY_PROCEDURE_ID);
  assert.equal(evidence.recovery_version, EXPECTED_RECOVERY_VERSION);
  assert.equal(evidence.retained_recovery_feed_name, contract.retainedFeedName);
  assert.equal(evidence.beta_before_sha256, contract.candidateFeedSha256);
  assert.equal(evidence.beta_after_sha256, contract.recoveryFeedSha256);
  assert.equal(evidence.stable_untouched, true);
  assert.equal(evidence.rpo_seconds, 0);
  assert.equal(evidence.profile_data_mutations, 0);
  assert.deepEqual(evidence.committed_paths, [...EXPECTED_ALIASES, BETA_FEED]);
  assert.equal(evidence.feed_committed_last, true);
  assert.equal(Object.keys(evidence.public_versioned_artifacts).length, 4);
  assert.deepEqual(evidence.stable_paths_written, []);
  assert.equal(receiptId(evidence, "activation_id"), evidence.activation_id);
  assert.equal(receiptId(archive, "archive_id"), archive.archive_id);
  assert.deepEqual(fs.readFileSync(path.join(result.archivePath, "candidate-receipt.json")), contract.receiptBytes);
  for (const [name, item] of Object.entries(archive.files)) {
    const bytes = fs.readFileSync(path.join(result.archivePath, name));
    assert.equal(bytes.length, item.size);
    assert.equal(sha256(bytes), item.sha256);
    assert.equal(fs.statSync(path.join(result.archivePath, name)).mode & 0o777, 0o400);
  }
  assert.equal(fs.statSync(result.archivePath).mode & 0o777, 0o500);
  const resumed = writeRecoveryEvidenceArchive(options);
  assert.equal(resumed.archivePath, result.archivePath);
  assert.equal(resumed.evidence.activation_id, result.evidence.activation_id);

  fs.rmSync(path.join(intent.path, "public-before-beta-mac.yml"));
  assert.throws(
    () => loadRecoveryExecuteIntent({ contract, evidenceRoot }),
    /record mismatch|ENOENT/,
  );
  assert.equal(removeRecoveryExecuteIntent({ contract, evidenceRoot }), true);
  assert.equal(loadRecoveryExecuteIntent({ contract, evidenceRoot }), null);

  const recreated = writeRecoveryExecuteIntent({
    contract,
    evidenceRoot,
    startedAt: options.startedAt,
    before,
  });
  const retiredByCrash = `${recreated.path}.retired-crash-fixture`;
  fs.renameSync(recreated.path, retiredByCrash);
  assert.equal(loadRecoveryExecuteIntent({ contract, evidenceRoot }), null);
  assert.equal(writeRecoveryEvidenceArchive(options).archivePath, result.archivePath);
  assert.equal(removeRecoveryExecuteIntent({ contract, evidenceRoot }), false);
});

test("recovery orchestration seals execute-complete before unfreeze and retires intent last", async (t) => {
  const fixture = recoveryCandidateFixture(t);
  const contract = loadRecoveryActivationContract(fixture.options);
  const evidenceRoot = path.join(fixture.root, "orchestration-evidence");
  const before = {
    betaBytes: fixture.candidateFeed.bytes,
    stableBytes: fixture.stableFeed.bytes,
    beta: { size: fixture.candidateFeed.bytes.length, sha256: sha256(fixture.candidateFeed.bytes) },
    stable: { size: fixture.stableFeed.bytes.length, sha256: sha256(fixture.stableFeed.bytes) },
  };
  const after = {
    betaBytes: fixture.recoveryFeed.bytes,
    stableBytes: fixture.stableFeed.bytes,
    beta: { size: fixture.recoveryFeed.bytes.length, sha256: sha256(fixture.recoveryFeed.bytes) },
    stable: { size: fixture.stableFeed.bytes.length, sha256: sha256(fixture.stableFeed.bytes) },
  };
  const archived = {
    archivePath: recoveryExecuteCompletePath(evidenceRoot, contract),
    evidence: { activation_id: "activation-proof", stable_untouched: true },
  };

  await t.test("new execution is archive then clear then intent retirement", () => {
    const calls = [];
    let archiveDurable = false;
    const result = runRecoveryWorkflow({
      contract,
      mode: "execute",
      evidenceRoot,
      dependencies: {
        now: (() => {
          const values = ["2026-07-16T00:00:00.000Z", "2026-07-16T00:01:00.000Z"];
          return () => values.shift();
        })(),
        log: () => {},
        loadRecoveryEvidenceArchive: () => null,
        loadRecoveryExecuteIntent: () => null,
        fetchPublicFeedsForRecovery: ({ expectedBeta }) => expectedBeta === "candidate" ? before : after,
        writeRecoveryExecuteIntent: ({ startedAt }) => ({
          startedAt,
          before,
          intent: { intent_id: "intent-proof" },
        }),
        runRemoteRecovery: () => {
          calls.push("remote-commit");
          return { marker: "REMOTE_RECOVERY_EXECUTE_OK" };
        },
        verifyPublicRecoveryAliases: () => ({}),
        verifyPublicRecoveryVersionedArtifacts: () => ({}),
        writeRecoveryEvidenceArchive: () => {
          calls.push("execute-complete-archive");
          archiveDurable = true;
          return archived;
        },
        runRemoteRecoveryFreezeClear: () => {
          assert.equal(archiveDurable, true);
          calls.push("release-freeze-clear");
          return { marker: "REMOTE_RECOVERY_FREEZE_CLEAR_OK" };
        },
        removeRecoveryExecuteIntent: () => calls.push("intent-retired"),
      },
    });
    assert.deepEqual(calls, [
      "remote-commit",
      "execute-complete-archive",
      "release-freeze-clear",
      "intent-retired",
    ]);
    assert.equal(result.release_freeze_clear_marker, "REMOTE_RECOVERY_FREEZE_CLEAR_OK");
    assert.equal(result.target_version, EXPECTED_RECOVERY_VERSION);
  });

  await t.test("unfreeze failure preserves the durable intent for retry", () => {
    const calls = [];
    assert.throws(() => runRecoveryWorkflow({
      contract,
      mode: "execute",
      evidenceRoot,
      dependencies: {
        now: () => "2026-07-16T00:00:00.000Z",
        log: () => {},
        loadRecoveryEvidenceArchive: () => null,
        loadRecoveryExecuteIntent: () => null,
        fetchPublicFeedsForRecovery: ({ expectedBeta }) => expectedBeta === "candidate" ? before : after,
        writeRecoveryExecuteIntent: ({ startedAt }) => ({ startedAt, before, intent: { intent_id: "intent-proof" } }),
        runRemoteRecovery: () => ({ marker: "REMOTE_RECOVERY_EXECUTE_OK" }),
        verifyPublicRecoveryAliases: () => ({}),
        verifyPublicRecoveryVersionedArtifacts: () => ({}),
        writeRecoveryEvidenceArchive: () => {
          calls.push("execute-complete-archive");
          return archived;
        },
        runRemoteRecoveryFreezeClear: () => {
          calls.push("release-freeze-clear-failed");
          throw new Error("clear transport lost");
        },
        removeRecoveryExecuteIntent: () => calls.push("intent-retired"),
      },
    }), /clear transport lost/);
    assert.deepEqual(calls, ["execute-complete-archive", "release-freeze-clear-failed"]);
  });

  await t.test("completed retry adopts archive before idempotent clear without stale readback", () => {
    const calls = [];
    const result = runRecoveryWorkflow({
      contract,
      mode: "execute",
      evidenceRoot,
      dependencies: {
        loadRecoveryEvidenceArchive: () => {
          calls.push("archive-validated-and-fsynced");
          return archived;
        },
        fetchPublicFeedsForRecovery: () => assert.fail("completed retry must not require stale public bytes"),
        runRemoteRecovery: () => assert.fail("completed retry must not rerun activation mutation"),
        runRemoteRecoveryFreezeClear: () => {
          calls.push("release-freeze-clear");
          return { marker: "REMOTE_RECOVERY_FREEZE_CLEAR_OK" };
        },
        removeRecoveryExecuteIntent: () => calls.push("intent-retired"),
      },
    });
    assert.deepEqual(calls, ["archive-validated-and-fsynced", "release-freeze-clear", "intent-retired"]);
    assert.equal(result.resumed_completed_evidence, true);
  });
});
