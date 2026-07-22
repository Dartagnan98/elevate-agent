"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const test = require("node:test");
const asar = require("@electron/asar");
const yaml = require("js-yaml");

const {
  CANDIDATE_RECEIPT_SCHEMA_VERSION,
  REQUIRED_LIVE_AI_CHECK_IDS,
  REQUIRED_REALTOR_BETA_GATE_CHECK_IDS,
  REQUIRED_SMOKE_CHECK_IDS,
  SOURCE_RECEIPT_SCHEMA_VERSION,
  archiveSuccessfulRelease,
  assertCompleteAsar,
  assertBundleManifest,
  assertCanonicalPackagedPermissions,
  assertFileRecord,
  assertGloballyNewVersion,
  assertPackagedMetadata,
  assertPublicFeedsUnchanged,
  assertRuntimeCodeContract,
  assertTrustedSignerEvidence,
  assertEmbeddedWebMatchesBuild,
  buildRemotePublishInnerScript,
  buildRemotePublishTransaction,
  canonicalJson,
  captureToolchain,
  classifyPublicCandidateFeeds,
  createPreSignEvidence,
  createSourceReceipt,
  evidenceIntegrity,
  fileRecord,
  findSuccessfulReleaseArchive,
  hashPortableTree,
  hashTree,
  normalizeArchitecture,
  portableAsarDirectoryHash,
  preSignEvidencePath,
  profileSnapshot,
  ROLLBACK_FREEZE_FILE,
  releaseCommandDefaults,
  realtorBetaRollbackClearedFile,
  realtorBetaRollbackFreezeBytes,
  receiptId,
  recoveryStaticProvenance,
  resolveReleaseCandidateForShip,
  runMacBuilders,
  sha256File,
  verifyCandidateReceipt,
  verifyPreSignEvidence,
  verifyReleaseArchive,
  verifySourceReceipt,
  validateFeed,
  validateZipEntryListing,
  validateZipEntries,
  waitForCompleteAsar,
  writeImmutableReceipt,
} = require("../scripts/candidate-receipt");
const {
  BETA_SOURCE_SAFETY_KIND,
  BETA_SOURCE_SAFETY_SCHEMA_VERSION,
  REQUIRED_SUITE_IDS,
  currentNodeAtLeast,
  npmCliPath,
  pythonDescriptor,
  suiteManifest,
  suiteManifestId,
} = require("../scripts/beta-source-safety-gate");
const { BETA, STABLE, resolveReleaseProfile } = require("../src/release-profile");
const { RECOVERY_SOURCE_FILES } = require("../electron-builder.recovery.config");

function temporaryDirectory(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-candidate-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function passingSourceSafetyExecution(contract) {
  if (contract.kind === "command") return { kind: "command", commands_executed: 1 };
  const tests = contract.expected_tests || contract.minimum_tests;
  const base = {
    kind: contract.kind,
    tests,
    passed: tests,
    failed: 0,
    skipped: 0,
    deselected: 0,
    collected_only: false,
  };
  if (contract.kind === "node-test") return { ...base, cancelled: 0, todo: 0 };
  if (contract.kind === "pytest") return { ...base, errors: 0, xfailed: 0, xpassed: 0 };
  return { ...base, todo: 0, test_files: 1, test_files_passed: 1 };
}

test("candidate IDs use canonical key ordering", () => {
  const left = { schema_version: 1, release: { version: "1.2.67", channel: "beta" } };
  const right = { release: { channel: "beta", version: "1.2.67" }, schema_version: 1 };
  assert.equal(canonicalJson(left), canonicalJson(right));
  assert.equal(receiptId(left, "candidate_id"), receiptId(right, "candidate_id"));
});

test("candidate profile binds the Beta verifier ring without changing Stable", () => {
  const beta = profileSnapshot(BETA);
  const stable = profileSnapshot(STABLE);

  assert.deepEqual(beta.entitlementAssertionAcceptedKeyIds, [
    "ent-2026-07-a",
    "ent-2026-07-b",
  ]);
  assert.equal(
    beta.entitlementAssertionKeysetSha256,
    "1d97a77a0be01aa7506fd3619ad454c709a375f8aab8febbd9818a47c5e53a0c",
  );
  assert.equal(beta.entitlementAssertionSchema, 1);
  assert.equal("entitlementAssertionAcceptedKeyIds" in stable, false);
  assert.equal("entitlementAssertionKeysetSha256" in stable, false);
  assert.equal(SOURCE_RECEIPT_SCHEMA_VERSION, 2);
  assert.equal(CANDIDATE_RECEIPT_SCHEMA_VERSION, 2);
});

test("Beta source receipts cannot be minted without exact passing source safety evidence", (t) => {
  if (!currentNodeAtLeast(22, 12)) {
    t.skip("Beta source receipt minting requires the release Node 22.12+ toolchain");
    return;
  }
  const root = temporaryDirectory(t);
  const git = (args) => {
    const result = require("node:child_process").spawnSync("git", args, { cwd: root, encoding: "utf8" });
    assert.equal(result.status, 0, result.stderr);
    return (result.stdout || "").trim();
  };
  git(["init", "-q"]);
  git(["config", "user.email", "source-gate@example.invalid"]);
  git(["config", "user.name", "Source Gate Test"]);
  fs.writeFileSync(path.join(root, ".gitignore"), "candidate-source.json\n");
  git(["add", ".gitignore"]);
  git(["commit", "-qm", "fixture"]);

  const manifest = suiteManifest();
  const python = pythonDescriptor();
  const sourceSafety = {
    schema_version: BETA_SOURCE_SAFETY_SCHEMA_VERSION,
    kind: BETA_SOURCE_SAFETY_KIND,
    channel: "beta",
    started_at: "2026-07-15T12:00:00.000Z",
    completed_at: "2026-07-15T12:05:00.000Z",
    node: process.version,
    python: python.path,
    python_version: python.version,
    manifest,
    manifest_id: suiteManifestId(manifest),
    git: {
      commit: git(["rev-parse", "HEAD"]),
      branch: git(["branch", "--show-current"]),
      clean: true,
      status_sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    },
    checkout_stable: true,
    passed: true,
    suites: REQUIRED_SUITE_IDS.map((id, index) => ({
      id,
      passed: true,
      status: 0,
      signal: null,
      duration_ms: 1,
      execution: passingSourceSafetyExecution(manifest[index].result_contract),
      output_sha256: "a".repeat(64),
    })),
  };
  const options = {
    channel: "beta",
    version: "1.2.71",
    profile: BETA,
    publicFeeds: {
      latest: { channel: "latest", version: "1.2.63", sha256: "a".repeat(64) },
      beta: { channel: "beta", version: "1.2.65", sha256: "b".repeat(64) },
    },
    repoRoot: root,
    desktopRoot: root,
    outputPath: path.join(root, "candidate-source.json"),
    inputs: {},
    toolchain: { node: process.version },
  };

  assert.throws(() => createSourceReceipt(options), /missing source safety evidence/);
  assert.throws(
    () => createSourceReceipt({ ...options, sourceSafety: { ...sourceSafety, passed: false } }),
    /did not pass/,
  );
  const receipt = createSourceReceipt({ ...options, sourceSafety });
  assert.deepEqual(receipt.source_safety, sourceSafety);
  assert.match(receipt.source_receipt_id, /^[a-f0-9]{64}$/);

  delete receipt.toolchain;
  receipt.source_receipt_id = receiptId(receipt, "source_receipt_id");
  fs.writeFileSync(options.outputPath, JSON.stringify(receipt));
  assert.equal(
    verifySourceReceipt({
      receiptPath: options.outputPath,
      repoRoot: root,
      desktopRoot: root,
      channel: "beta",
      version: "1.2.71",
    }).source_receipt_id,
    receipt.source_receipt_id,
  );

  const forgedFailure = structuredClone(receipt);
  forgedFailure.source_safety.passed = false;
  forgedFailure.source_receipt_id = receiptId(forgedFailure, "source_receipt_id");
  fs.writeFileSync(options.outputPath, JSON.stringify(forgedFailure));
  assert.throws(
    () => verifySourceReceipt({
      receiptPath: options.outputPath,
      repoRoot: root,
      desktopRoot: root,
      channel: "beta",
      version: "1.2.71",
    }),
    /did not pass/,
  );

  const stableOptions = {
    ...options,
    channel: "latest",
    profile: STABLE,
    outputPath: path.join(root, "candidate-source.json"),
  };
  const stableReceipt = createSourceReceipt(stableOptions);
  assert.equal("source_safety" in stableReceipt, false);
  assert.throws(
    () => createSourceReceipt({ ...stableOptions, sourceSafety }),
    /cannot be attached to Stable/,
  );
});

test("schema-v1 candidate artifacts are historical only, not promotion evidence", (t) => {
  const root = temporaryDirectory(t);
  const sourcePath = path.join(root, "candidate-source.json");
  const source = {
    schema_version: 1,
    kind: "elevate-candidate-source",
  };
  source.source_receipt_id = receiptId(source, "source_receipt_id");
  fs.writeFileSync(sourcePath, JSON.stringify(source));
  assert.throws(
    () => verifySourceReceipt({ receiptPath: sourcePath, repoRoot: root }),
    /unsupported source receipt schema/,
  );

  const candidatePath = path.join(root, "candidate-receipt.json");
  const candidate = {
    schema_version: 1,
    kind: "elevate-final-candidate",
  };
  candidate.candidate_id = receiptId(candidate, "candidate_id");
  fs.writeFileSync(candidatePath, JSON.stringify(candidate));
  assert.throws(
    () => verifyCandidateReceipt({
      receiptPath: candidatePath,
      desktopRoot: root,
      repoRoot: root,
      requireApps: false,
      requireSource: false,
    }),
    /unsupported final candidate receipt schema/,
  );
});

test("global version must be newer than both Stable and Beta", () => {
  const feeds = { latest: { version: "1.2.63" }, beta: { version: "1.2.66" } };
  assert.equal(assertGloballyNewVersion("1.2.67", feeds), "1.2.66");
  assert.throws(() => assertGloballyNewVersion("1.2.66", feeds), /newer than every public feed/);
  assert.throws(() => assertGloballyNewVersion("1.2.64", feeds), /highest 1\.2\.66/);
});

test("any Stable or Beta feed drift invalidates the source contract", () => {
  const expected = { latest: { sha256: "stable-a" }, beta: { sha256: "beta-a" } };
  assert.equal(assertPublicFeedsUnchanged(expected, structuredClone(expected)), true);
  assert.throws(
    () => assertPublicFeedsUnchanged(expected, { latest: expected.latest, beta: { sha256: "beta-b" } }),
    /public beta feed changed/,
  );
  assert.throws(
    () => assertPublicFeedsUnchanged(expected, { latest: { sha256: "stable-b" }, beta: expected.beta }),
    /public latest feed changed/,
  );
});

test("feed validation rejects extras, duplicates, unsafe URLs, and top-level drift", () => {
  const names = [
    "Elevate-Beta-1.2.67-mac-x64.zip",
    "Elevate-Beta-1.2.67-mac-x64.dmg",
    "Elevate-Beta-1.2.67-mac-arm64.zip",
    "Elevate-Beta-1.2.67-mac-arm64.dmg",
  ];
  const release = { version: "1.2.67", artifact_names: names };
  const artifacts = Object.fromEntries(names.map((name, index) => [name, { size: 100 + index, sha512: `hash-${index}` }]));
  const files = names.map((name) => ({ url: name, size: artifacts[name].size, sha512: artifacts[name].sha512 }));
  const valid = { version: release.version, files, path: names[0], sha512: artifacts[names[0]].sha512 };
  assert.equal(validateFeed(valid, release, artifacts), true);
  assert.throws(() => validateFeed({ ...valid, files: [...files, { ...files[0], url: "extra.zip" }] }, release, artifacts), /URL set/);
  assert.throws(() => validateFeed({ ...valid, files: [...files, files[0]] }, release, artifacts), /duplicate/);
  assert.throws(() => validateFeed({ ...valid, files: [{ ...files[0], url: "../escape" }, ...files.slice(1)] }, release, artifacts), /unsafe/);
  assert.throws(() => validateFeed({ ...valid, path: names[2], sha512: artifacts[names[2]].sha512 }, release, artifacts), /top-level/);
  assert.throws(() => validateFeed({ ...valid, files: [{ ...files[0], size: 999 }, ...files.slice(1)] }, release, artifacts), /metadata mismatch/);
});

test("release signer is pinned to the trusted Apple TeamIdentifier", () => {
  const details = [
    "Authority=Developer ID Application: Dartagnan Patricio (G5TK395RYH)",
    "TeamIdentifier=G5TK395RYH",
  ].join("\n");
  const requirement = "designated => anchor apple generic and certificate leaf[subject.OU] = G5TK395RYH";
  assert.equal(assertTrustedSignerEvidence(details, requirement), true);
  assert.throws(
    () => assertTrustedSignerEvidence(details.replaceAll("G5TK395RYH", "WRONGTEAM1"), requirement.replace("G5TK395RYH", "WRONGTEAM1")),
    /trusted TeamIdentifier/,
  );
});

function publisherFixture(t, { recovery = false } = {}) {
  const root = `${temporaryDirectory(t)}${path.sep}`;
  const candidateId = "d".repeat(64);
  const artifactNames = [
    "Elevate-Beta-1.2.67-mac-x64.dmg",
    "Elevate-Beta-1.2.67-mac-arm64.dmg",
  ];
  const aliases = [
    "Elevate-Beta-mac-x64.dmg",
    "Elevate-beta-mac-x64.dmg",
    "Elevate-Beta-mac-arm64.dmg",
    "Elevate-beta-mac-arm64.dmg",
  ];
  const bytes = {
    [artifactNames[0]]: "candidate-x64-dmg",
    [artifactNames[1]]: "candidate-arm64-dmg",
    "beta-mac.yml": "candidate-beta-feed",
  };
  const oldFeeds = { latest: "old-stable-feed", beta: "old-beta-feed" };
  const digest = (value) => crypto.createHash("sha256").update(value).digest("hex");
  const candidate = {
    candidate_id: candidateId,
    source_receipt_id: "e".repeat(64),
    public_feeds_at_finalize: {
      latest: { sha256: digest(oldFeeds.latest) },
      beta: { sha256: digest(oldFeeds.beta) },
    },
    artifacts: Object.fromEntries(Object.entries(bytes).map(([name, value]) => [name, { sha256: digest(value) }])),
    release: {
      channel: "beta",
      feed_name: "beta-mac.yml",
      artifact_names: artifactNames,
      download_aliases: aliases,
    },
    rollback_target: { sha256: digest(oldFeeds.beta) },
  };
  const recoveryNames = ["x64", "arm64"].flatMap((arch) => [
    `Elevate-Beta-Recovery-1.2.68-mac-${arch}.zip`,
    `Elevate-Beta-Recovery-1.2.68-mac-${arch}.dmg`,
  ]);
  const recoveryBytes = Object.fromEntries(recoveryNames.map((name) => [name, `recovery-${name}`]));
  const recoveryFeedBytes = "recovery-roll-forward-feed";
  const retainedFeedName = ".realtor-beta-recovery-1.2.68-beta-mac.yml";
  if (recovery) {
    candidate.recovery = {
      version: "1.2.68",
      artifact_names: recoveryNames,
      artifacts: Object.fromEntries(recoveryNames.map((name) => [name, { sha256: digest(recoveryBytes[name]) }])),
      local_feed: { sha256: digest(recoveryFeedBytes) },
    };
  }
  fs.writeFileSync(path.join(root, "latest-mac.yml"), oldFeeds.latest);
  fs.writeFileSync(path.join(root, "beta-mac.yml"), oldFeeds.beta);
  const intendedOldAliases = Object.fromEntries(aliases.map((alias, index) => [alias, `old-alias-${index}`]));
  for (const [alias, value] of Object.entries(intendedOldAliases)) fs.writeFileSync(path.join(root, alias), value);
  const oldAliases = Object.fromEntries(aliases.map((alias) => [alias, fs.readFileSync(path.join(root, alias), "utf8")]));
  const caseVariantsCollide = fs.statSync(path.join(root, aliases[0])).ino
    === fs.statSync(path.join(root, aliases[1])).ino;
  let stageNumber = 0;
  function createStage(label = "test") {
    stageNumber += 1;
    const stagingName = `.candidate-${candidateId}-${label}${stageNumber}`;
    const stagePath = path.join(root, stagingName);
    fs.mkdirSync(stagePath, { mode: 0o700 });
    for (const [name, value] of Object.entries(bytes)) fs.writeFileSync(path.join(stagePath, name), value);
    if (recovery) {
      for (const [name, value] of Object.entries(recoveryBytes)) fs.writeFileSync(path.join(stagePath, name), value);
      fs.writeFileSync(path.join(stagePath, "recovery-beta-mac.yml"), recoveryFeedBytes);
    }
    return stagingName;
  }
  function run({ label, crashAfter = 0, crashSignal = "KILL" } = {}) {
    const stagingName = createStage(label);
    const script = buildRemotePublishInnerScript({
      candidate,
      remote: root,
      stagingName,
      owner: null,
      testCrashAfterPointerMoves: crashAfter,
      testCrashSignal: crashSignal,
    });
    return spawnSync("bash", ["-c", script], { encoding: "utf8", timeout: 30_000 });
  }
  return {
    root,
    candidate,
    candidateId,
    artifactNames,
    aliases,
    bytes,
    oldFeeds,
    oldAliases,
    caseVariantsCollide,
    createStage,
    run,
    recoveryNames,
    recoveryBytes,
    recoveryFeedBytes,
    retainedFeedName,
    transactionPath: path.join(root, `.candidate-${candidateId}-publish-state`),
  };
}

function assertPublisherCommitted(fixture) {
  const { root, candidate, aliases, artifactNames, bytes, oldFeeds } = fixture;
  assert.equal(fs.readFileSync(path.join(root, "latest-mac.yml"), "utf8"), oldFeeds.latest);
  assert.equal(fs.readFileSync(path.join(root, "beta-mac.yml"), "utf8"), bytes["beta-mac.yml"]);
  for (const name of artifactNames) assert.equal(sha256File(path.join(root, name)), candidate.artifacts[name].sha256);
  for (const alias of aliases) {
    const source = alias.includes("-arm64.") ? artifactNames[1] : artifactNames[0];
    assert.equal(sha256File(path.join(root, alias)), candidate.artifacts[source].sha256);
  }
}

test("remote publication uses one bounded lock, a candidate journal, and feed-last commit", (t) => {
  const fixture = publisherFixture(t);
  const stagingName = fixture.createStage("syntax");
  const command = buildRemotePublishTransaction({
    candidate: fixture.candidate,
    remote: fixture.root,
    stagingName,
    owner: null,
    globalLock: path.join(fixture.root, "publish.lock"),
  });
  const parsed = spawnSync("bash", ["-n", "-c", command], { encoding: "utf8" });
  assert.equal(parsed.status, 0, parsed.stderr);
  assert.equal((command.match(/\bflock\b/g) || []).length, 1);
  assert.match(command, /flock -x -w 300/);
  assert.equal(ROLLBACK_FREEZE_FILE, ".realtor-beta-rollback-freeze");
  assert.match(command, /RELEASE_FREEZE_ACTIVE/);
  assert.match(command, /elevate-remote-publish-journal/);
  assert.match(command, /backups\.manifest/);
  assert.match(command, /state=already_committed/);
  assert.match(command, /state=recovered_committed/);
  const inner = buildRemotePublishInnerScript({
    candidate: fixture.candidate,
    remote: fixture.root,
    stagingName,
    owner: null,
  });
  const mutation = inner.indexOf("mutation_started=1");
  const firstAlias = inner.indexOf("atomic_replace", mutation);
  const feed = inner.indexOf(`atomic_replace '${fixture.transactionPath}/next-feed'`, mutation);
  const validation = inner.indexOf("committed_ok ||", feed);
  assert.ok(mutation >= 0 && mutation < firstAlias);
  assert.ok(firstAlias < feed);
  assert.ok(feed < validation);
  assert.match(inner, /trap 'cleanup 129' HUP/);
  assert.match(inner, /trap 'cleanup 143' TERM/);

  const shipSource = fs.readFileSync(path.resolve(__dirname, "../scripts/ship-to-hetzner.js"), "utf8");
  assert.match(shipSource, /ServerAliveInterval/);
  assert.match(shipSource, /ServerAliveCountMax/);
  assert.match(shipSource, /REMOTE_COMMAND_TIMEOUT_MS/);
  assert.match(shipSource, /completionMarkers\.length !== 1/);
  assert.match(shipSource, /classifyPublicCandidateFeeds/);
  assert.match(shipSource, /`\$\{HOST\}:\$\{stagingPath\}`/);
  assert.doesNotMatch(shipSource, /`\$\{HOST\}:\$\{REMOTE\}`/);
  const ambiguousFailure = shipSource.slice(shipSource.indexOf("const publishFeed"), shipSource.indexOf("const publicReadbackPath"));
  assert.doesNotMatch(ambiguousFailure, /rm -rf/);
  assert.throws(() => buildRemotePublishTransaction({ candidate: fixture.candidate, stagingName: "../unsafe" }), /unsafe remote staging/);
  const incomplete = structuredClone(fixture.candidate);
  delete incomplete.artifacts["beta-mac.yml"];
  assert.throws(() => buildRemotePublishTransaction({ candidate: incomplete, stagingName }), /missing SHA256/);
  const stable = structuredClone(fixture.candidate);
  stable.release.channel = "latest";
  stable.release.feed_name = "latest-mac.yml";
  stable.artifacts["latest-mac.yml"] = stable.artifacts["beta-mac.yml"];
  delete stable.artifacts["beta-mac.yml"];
  const stableCommand = buildRemotePublishTransaction({ candidate: stable, stagingName });
  assert.match(stableCommand, /\*\.zip\.blockmap/);
  assert.match(stableCommand, /-delete/);
});

test("candidate-specific cleared rollback tombstone rejects a stale staged publisher", (t) => {
  const fixture = publisherFixture(t);
  const stagingName = fixture.createStage("predates-rollback");
  const clearedPath = path.join(
    fixture.root,
    realtorBetaRollbackClearedFile(fixture.candidate),
  );
  fs.writeFileSync(clearedPath, realtorBetaRollbackFreezeBytes(fixture.candidate));
  const script = buildRemotePublishInnerScript({
    candidate: fixture.candidate,
    remote: fixture.root,
    stagingName,
    owner: null,
  });
  const result = spawnSync("bash", ["-c", script], { encoding: "utf8", timeout: 30_000 });
  assert.equal(result.status, 47, result.stderr);
  assert.match(result.stderr, /RELEASE_CANDIDATE_ALREADY_ROLLED_BACK/);
  assert.equal(fs.readFileSync(path.join(fixture.root, "beta-mac.yml"), "utf8"), fixture.oldFeeds.beta);
  assert.equal(fs.readFileSync(path.join(fixture.root, "latest-mac.yml"), "utf8"), fixture.oldFeeds.latest);
  for (const alias of fixture.aliases) {
    assert.equal(fs.readFileSync(path.join(fixture.root, alias), "utf8"), fixture.oldAliases[alias]);
  }
  for (const name of fixture.artifactNames) assert.equal(fs.existsSync(path.join(fixture.root, name)), false);
  assert.equal(fs.existsSync(fixture.transactionPath), false);
  assert.deepEqual(fs.readFileSync(clearedPath), realtorBetaRollbackFreezeBytes(fixture.candidate));
});

test("publisher resumes a journaled mixed-alias state after real SIGKILL", (t) => {
  const fixture = publisherFixture(t);
  const killed = fixture.run({ label: "midalias", crashAfter: 1 });
  assert.equal(killed.status, null);
  assert.equal(killed.signal, "SIGKILL");
  assert.equal(fs.existsSync(fixture.transactionPath), true);
  assert.equal(fs.readFileSync(path.join(fixture.root, "beta-mac.yml"), "utf8"), fixture.oldFeeds.beta);
  assert.equal(fs.readFileSync(path.join(fixture.root, fixture.aliases[0]), "utf8"), fixture.bytes[fixture.artifactNames[0]]);
  if (fixture.caseVariantsCollide) {
    assert.equal(fs.readFileSync(path.join(fixture.root, fixture.aliases[1]), "utf8"), fixture.bytes[fixture.artifactNames[0]]);
  }
  for (const alias of fixture.aliases.slice(fixture.caseVariantsCollide ? 2 : 1)) {
    assert.equal(fs.readFileSync(path.join(fixture.root, alias), "utf8"), fixture.oldAliases[alias]);
  }
  assert.equal(fs.readFileSync(path.join(fixture.root, "latest-mac.yml"), "utf8"), fixture.oldFeeds.latest);

  const resumed = fixture.run({ label: "resume" });
  assert.equal(resumed.status, 0, resumed.stderr);
  assert.match(resumed.stdout, /^REMOTE_PUBLISH_OK state=recovered_committed$/m);
  assertPublisherCommitted(fixture);
  assert.equal(fs.existsSync(fixture.transactionPath), false);
});

test("publisher seals exact committed state after disconnect at the feed acknowledgement boundary", (t) => {
  const fixture = publisherFixture(t);
  const killed = fixture.run({ label: "ackloss", crashAfter: fixture.aliases.length + 1 });
  assert.equal(killed.status, null);
  assert.equal(killed.signal, "SIGKILL");
  assertPublisherCommitted(fixture);
  assert.equal(fs.existsSync(fixture.transactionPath), true);

  const resumed = fixture.run({ label: "seal" });
  assert.equal(resumed.status, 0, resumed.stderr);
  assert.match(resumed.stdout, /^REMOTE_PUBLISH_OK state=already_committed$/m);
  assertPublisherCommitted(fixture);
  assert.equal(fs.existsSync(fixture.transactionPath), false);
});

test("publisher compensates exact old pointers on a catchable disconnect", (t) => {
  const fixture = publisherFixture(t);
  const interrupted = fixture.run({ label: "term", crashAfter: 1, crashSignal: "TERM" });
  assert.equal(interrupted.status, 143, interrupted.stderr);
  assert.equal(interrupted.signal, null);
  assert.equal(fs.readFileSync(path.join(fixture.root, "latest-mac.yml"), "utf8"), fixture.oldFeeds.latest);
  assert.equal(fs.readFileSync(path.join(fixture.root, "beta-mac.yml"), "utf8"), fixture.oldFeeds.beta);
  for (const alias of fixture.aliases) {
    assert.equal(fs.readFileSync(path.join(fixture.root, alias), "utf8"), fixture.oldAliases[alias]);
  }
  assert.equal(fs.existsSync(fixture.transactionPath), true);
  const resumed = fixture.run({ label: "afterterm" });
  assert.equal(resumed.status, 0, resumed.stderr);
  assert.match(resumed.stdout, /^REMOTE_PUBLISH_OK state=recovered_committed$/m);
  assertPublisherCommitted(fixture);
});

test("beta publication retains the recovery package before any pointer move", (t) => {
  const fixture = publisherFixture(t, { recovery: true });
  const inner = buildRemotePublishInnerScript({
    candidate: fixture.candidate,
    remote: fixture.root,
    stagingName: fixture.createStage("order"),
    owner: null,
  });
  const retention = inner.indexOf("'RECOVERY_FINAL_COLLISION");
  const candidateArtifacts = inner.indexOf("'FINAL_COLLISION");
  const mutation = inner.indexOf("mutation_started=1");
  assert.ok(retention >= 0 && retention < candidateArtifacts && candidateArtifacts < mutation);
  assert.match(inner, /retained_feed_name/);

  // Crash at the first pointer move: every recovery byte must already be
  // final while the beta feed still holds the old release.
  const crashed = fixture.run({ label: "retain", crashAfter: 1 });
  assert.notEqual(crashed.status, 0);
  for (const name of fixture.recoveryNames) {
    assert.equal(
      sha256File(path.join(fixture.root, name)),
      fixture.candidate.recovery.artifacts[name].sha256,
    );
  }
  assert.equal(fs.readFileSync(path.join(fixture.root, fixture.retainedFeedName), "utf8"), fixture.recoveryFeedBytes);
  assert.equal(fs.readFileSync(path.join(fixture.root, "beta-mac.yml"), "utf8"), fixture.oldFeeds.beta);

  const resumed = fixture.run({ label: "resume" });
  assert.equal(resumed.status, 0, resumed.stderr);
  assert.match(resumed.stdout, /^REMOTE_PUBLISH_OK state=recovered_committed$/m);
  assertPublisherCommitted(fixture);
  assert.equal(fs.readFileSync(path.join(fixture.root, fixture.retainedFeedName), "utf8"), fixture.recoveryFeedBytes);

  const rerun = fixture.run({ label: "rerun" });
  assert.equal(rerun.status, 0, rerun.stderr);
  assert.match(rerun.stdout, /^REMOTE_PUBLISH_OK state=already_committed$/m);
});

test("recovery retention fails closed on foreign bytes or missing staged recovery files", (t) => {
  const fixture = publisherFixture(t, { recovery: true });
  fs.writeFileSync(path.join(fixture.root, fixture.recoveryNames[0]), "foreign-bytes");
  const collided = fixture.run({ label: "foreign" });
  assert.notEqual(collided.status, 0);
  assert.match(collided.stderr, /PUBLISH_RECOVERY_STATE_UNKNOWN/);
  assert.equal(fs.readFileSync(path.join(fixture.root, "beta-mac.yml"), "utf8"), fixture.oldFeeds.beta);
  for (const [alias, value] of Object.entries(fixture.oldAliases)) {
    assert.equal(fs.readFileSync(path.join(fixture.root, alias), "utf8"), value);
  }

  fs.rmSync(path.join(fixture.root, fixture.recoveryNames[0]));
  const stagingName = fixture.createStage("missing");
  fs.rmSync(path.join(fixture.root, stagingName, fixture.recoveryNames[1]));
  const script = buildRemotePublishInnerScript({
    candidate: fixture.candidate,
    remote: fixture.root,
    stagingName,
    owner: null,
  });
  const missing = spawnSync("bash", ["-c", script], { encoding: "utf8", timeout: 30_000 });
  assert.notEqual(missing.status, 0);
  assert.match(missing.stderr, /STAGED_HASH_FAILED Elevate-Beta-Recovery/);
  assert.equal(fs.readFileSync(path.join(fixture.root, "beta-mac.yml"), "utf8"), fixture.oldFeeds.beta);
});

test("public feed classifier accepts only exact old or exact candidate-bound committed states", (t) => {
  const fixture = publisherFixture(t);
  const baseline = {
    latest: { sha256: fixture.candidate.public_feeds_at_finalize.latest.sha256 },
    beta: { sha256: fixture.candidate.public_feeds_at_finalize.beta.sha256 },
  };
  assert.equal(classifyPublicCandidateFeeds(fixture.candidate, baseline), "old");
  const committed = structuredClone(baseline);
  committed.beta.sha256 = fixture.candidate.artifacts["beta-mac.yml"].sha256;
  assert.equal(classifyPublicCandidateFeeds(fixture.candidate, committed), "committed");
  committed.latest.sha256 = "f".repeat(64);
  assert.throws(() => classifyPublicCandidateFeeds(fixture.candidate, committed), /neither the exact finalized baseline/);
});

test("candidate build commands and npm toolchain stay pinned to the active Node", () => {
  const npmCli = npmCliPath();
  const commands = releaseCommandDefaults({ npmCli });
  assert.deepEqual(commands.web, {
    command: process.execPath,
    args: [npmCli, "--prefix", "../cli/web", "run", "build"],
  });
  assert.deepEqual(commands.merge, {
    command: process.execPath,
    args: [npmCli, "run", "merge:mac-feed"],
  });
  assert.equal(commands.builder.command, process.execPath);
  assert.match(commands.builder.args[0], /node_modules\/electron-builder\/cli\.js$/);
  assert.throws(
    () => releaseCommandDefaults({ npmCli: "npm" }),
    /active npm CLI is missing or is not an absolute file/,
  );
  assert.throws(
    () => releaseCommandDefaults({ npmCli: path.join(os.tmpdir(), "missing-npm-cli.js") }),
    /active npm CLI is missing or is not an absolute file/,
  );

  const expectedNpm = spawnSync(process.execPath, [npmCli, "--version"], {
    encoding: "utf8",
    timeout: 30_000,
  });
  assert.equal(expectedNpm.status, 0, expectedNpm.stderr);
  const toolchain = captureToolchain({ npmCli });
  assert.equal(toolchain.node, process.version);
  assert.equal(toolchain.npm, expectedNpm.stdout.trim());
  assert.notEqual(toolchain.electron_builder, "unavailable");
});

test("the real build runner exports one verified source ID into both builder configs", (t) => {
  const root = temporaryDirectory(t);
  const builder = path.join(root, "fake-builder.js");
  const merge = path.join(root, "fake-merge.js");
  const web = path.join(root, "fake-web.js");
  const webOutput = path.join(root, "web-dist");
  const webReceipt = path.join(root, "candidate-web.json");
  const preSignEvidenceDirectory = path.join(root, "pre-sign");
  const log = path.join(root, "build-log.jsonl");
  const configPath = path.resolve(__dirname, "../electron-builder.config.js");
  fs.writeFileSync(builder, `
    const fs = require("node:fs");
    const config = require(process.env.TEST_BUILDER_CONFIG)();
    fs.appendFileSync(process.env.TEST_BUILD_LOG, JSON.stringify({
      kind: "builder",
      args: process.argv.slice(2),
      envId: process.env.ELEVATE_SOURCE_RECEIPT_ID,
      configId: config.extraMetadata.elevateSourceReceiptId,
      nodeEnv: process.env.NODE,
      nodeExecutable: process.execPath,
      npmExecPath: process.env.npm_execpath,
      npmNodeExecPath: process.env.npm_node_execpath,
      pathHead: process.env.PATH.split(require("node:path").delimiter)[0],
      preSignEvidenceExists: ["x64", "arm64"].map((arch) =>
        fs.existsSync(process.env.TEST_PRE_SIGN_DIR + "/candidate-pre-sign-" + arch + ".json")),
    }) + "\\n");
  `);
  fs.writeFileSync(merge, `
    require("node:fs").appendFileSync(process.env.TEST_BUILD_LOG, JSON.stringify({
      kind: "merge",
      envId: process.env.ELEVATE_SOURCE_RECEIPT_ID,
      nodeEnv: process.env.NODE,
      nodeExecutable: process.execPath,
      npmExecPath: process.env.npm_execpath,
      npmNodeExecPath: process.env.npm_node_execpath,
      pathHead: process.env.PATH.split(require("node:path").delimiter)[0],
    }) + "\\n");
  `);
  fs.writeFileSync(web, `
    const fs = require("node:fs");
    fs.mkdirSync(process.env.TEST_WEB_OUTPUT, { recursive: true });
    fs.writeFileSync(process.env.TEST_WEB_OUTPUT + "/index.html", "source-bound web");
  `);
  const sourceReceiptId = "b".repeat(64);
  const activeNpmCli = path.join(root, "active-npm-cli.js");
  fs.writeFileSync(activeNpmCli, "// command identity fixture\n");
  fs.mkdirSync(preSignEvidenceDirectory);
  for (const arch of ["x64", "arm64"]) {
    fs.writeFileSync(preSignEvidencePath(preSignEvidenceDirectory, arch), "stale evidence");
  }
  assert.equal(runMacBuilders({
    npmCli: activeNpmCli,
    verifySource: () => ({ source_receipt_id: sourceReceiptId }),
    builderCommand: process.execPath,
    builderPrefixArgs: [builder],
    mergeCommand: process.execPath,
    mergeArgs: [merge],
    webCommand: process.execPath,
    webArgs: [web],
    webOutputPath: webOutput,
    webReceiptPath: webReceipt,
    preSignEvidenceDirectory,
    cwd: path.resolve(__dirname, ".."),
    env: {
      ...process.env,
      ELEVATE_RELEASE_CHANNEL: "beta",
      TEST_BUILDER_CONFIG: configPath,
      TEST_BUILD_LOG: log,
      TEST_PRE_SIGN_DIR: preSignEvidenceDirectory,
      TEST_WEB_OUTPUT: webOutput,
    },
    stdio: "pipe",
  }), sourceReceiptId);
  const rows = fs.readFileSync(log, "utf8").trim().split("\n").map(JSON.parse);
  assert.equal(rows.length, 3);
  assert.deepEqual(rows.slice(0, 2).map((row) => row.envId), [sourceReceiptId, sourceReceiptId]);
  assert.deepEqual(rows.slice(0, 2).map((row) => row.configId), [sourceReceiptId, sourceReceiptId]);
  assert.deepEqual(rows[0].preSignEvidenceExists, [false, false]);
  assert.ok(rows[0].args.includes("--x64"));
  assert.ok(rows[1].args.includes("--arm64"));
  assert.equal(rows[2].envId, sourceReceiptId);
  for (const row of rows) {
    assert.equal(row.nodeEnv, process.execPath);
    assert.equal(row.nodeExecutable, process.execPath);
    assert.equal(row.npmExecPath, activeNpmCli);
    assert.equal(row.npmNodeExecPath, process.execPath);
    assert.equal(row.pathHead, path.dirname(process.execPath));
  }
  const generatedWebReceipt = JSON.parse(fs.readFileSync(webReceipt, "utf8"));
  assert.equal(generatedWebReceipt.source_receipt_id, sourceReceiptId);
  for (const arch of ["x64", "arm64"]) {
    assert.equal(fs.existsSync(preSignEvidencePath(preSignEvidenceDirectory, arch)), false);
  }
  const scripts = require("../package.json").scripts;
  assert.match(scripts["build:mac"], /candidate-receipt\.js build-mac/);
  assert.doesNotMatch(scripts["release:mac"], /ship:mac/);
  assert.match(scripts["smoke:mac"], /DESKTOP_ROOT=\$\(pwd -P\)/);
  assert.match(
    scripts["smoke:mac"],
    /--installed-app "\$DESKTOP_ROOT\/dist\/mac\/\$APP_BUNDLE"/,
  );
  assert.match(
    scripts["smoke:mac"],
    /--installed-app "\$DESKTOP_ROOT\/dist\/mac-arm64\/\$APP_BUNDLE"/,
  );
  assert.equal(
    (scripts["smoke:mac"].match(/"\$PYTHON" -B \.\.\/cli\/scripts\/installed_runtime_smoke\.py/g) || []).length,
    2,
  );
  assert.match(scripts["smoke:mac:live"], /--live-candidate/);
  assert.match(
    scripts["smoke:mac:live"],
    /"\$PYTHON" -B \.\.\/cli\/scripts\/installed_runtime_smoke\.py/,
  );
  assert.match(scripts["smoke:mac:live"], /live-ai\.json/);
  assert.doesNotMatch(scripts["smoke:mac:live"], /--skip-sidecar/);
  assert.match(scripts["smoke:mac:live"], /npm run gate:realtor-beta/);
  assert.match(
    scripts["gate:realtor-beta"],
    /"\$PYTHON" -B \.\.\/cli\/scripts\/exact_candidate_realtor_beta_gate\.py/,
  );
  assert.match(scripts["gate:realtor-beta"], /--installed-app "\$INSTALLED_APP"/);
  assert.match(scripts["gate:realtor-beta"], /realtor-beta-gate\.json/);
  assert.match(scripts["gate:realtor-beta"], /if \[ "\$CHANNEL" != beta \]/);
});

test("Beta release preflight probes the signed Codex-only runtime policy", () => {
  const scripts = require("../package.json").scripts;
  const preflight = fs.readFileSync(
    path.resolve(__dirname, "..", "scripts", "preflight-apple-release.js"),
    "utf8",
  );

  assert.match(preflight, /releaseProfile\.allowedProvider/);
  assert.equal(scripts["gate:beta-source"], "node scripts/beta-source-safety-gate.js");
  assert.match(preflight, /if \(releaseProfile\.isBeta\)/);
  assert.match(preflight, /releaseProfile\.allowedModels\[0\]/);
  assert.match(preflight, /releaseProfile\.elevateHomeName/);
  assert.match(preflight, /path\.join\(elevateHome, "auth\.json"\)/);
  assert.match(preflight, /provider = sys\.argv\[2\]/);
  assert.match(preflight, /beta-source-safety-gate\.js/);
  assert.match(preflight, /validateBetaSourceSafetyEvidence/);
  assert.match(preflight, /sourceSafety: betaSourceSafety/);
  assert.doesNotMatch(preflight, /provider="custom"/);
});

test("electron-builder numeric architecture enums normalize to release names", () => {
  assert.equal(normalizeArchitecture(1), "x64");
  assert.equal(normalizeArchitecture(3), "arm64");
  assert.equal(normalizeArchitecture("x64"), "x64");
  assert.equal(normalizeArchitecture("arm64"), "arm64");
});

test("final app metadata rejects a missing or wrong embedded source ID", () => {
  const sourceReceiptId = "c".repeat(64);
  const release = {
    version: "1.2.67",
    channel: "beta",
    profile: { packageName: "elevate-beta-desktop" },
  };
  const metadata = {
    version: release.version,
    name: release.profile.packageName,
    elevateReleaseChannel: release.channel,
    elevateSourceReceiptId: sourceReceiptId,
  };
  assert.equal(assertPackagedMetadata(metadata, release, sourceReceiptId), true);
  assert.throws(() => assertPackagedMetadata({ ...metadata, elevateSourceReceiptId: undefined }, release, sourceReceiptId), /metadata drift/);
  assert.throws(() => assertPackagedMetadata({ ...metadata, elevateSourceReceiptId: "wrong" }, release, sourceReceiptId), /metadata drift/);
});

test("portable desktop/src hash matches complete ASAR bytes and rejects truncated or altered source", async (t) => {
  const root = temporaryDirectory(t);
  const packageRoot = path.join(root, "package");
  const src = path.join(packageRoot, "src");
  fs.mkdirSync(src, { recursive: true });
  fs.writeFileSync(path.join(packageRoot, "package.json"), "{}");
  fs.writeFileSync(path.join(src, "main.js"), "module.exports = 'approved';\n");
  const approved = hashPortableTree(src);
  const approvedAsar = path.join(root, "approved.asar");
  const approvedOutput = await asar.createPackage(packageRoot, approvedAsar);
  await waitForCompleteAsar(approvedAsar, approvedOutput);
  assert.equal(portableAsarDirectoryHash(approvedAsar, "src").sha256, approved.sha256);

  const truncatedAsar = path.join(root, "truncated.asar");
  fs.copyFileSync(approvedAsar, truncatedAsar);
  fs.truncateSync(truncatedAsar, fs.statSync(truncatedAsar).size - 1);
  assert.throws(() => assertCompleteAsar(truncatedAsar), /ASAR truncated/);
  assert.throws(() => portableAsarDirectoryHash(truncatedAsar, "src"), /ASAR truncated/);

  fs.writeFileSync(path.join(src, "main.js"), "module.exports = 'altered';\n");
  const alteredAsar = path.join(root, "altered.asar");
  const alteredOutput = await asar.createPackage(packageRoot, alteredAsar);
  await waitForCompleteAsar(alteredAsar, alteredOutput);
  assert.notEqual(portableAsarDirectoryHash(alteredAsar, "src").sha256, approved.sha256);
});

test("identical cross-arch web bundles still fail when they do not match the web build receipt", () => {
  const wrong = { sha256: "wrong", portable: { sha256: "wrong-portable" } };
  const apps = { x64: { embedded_web: wrong }, arm64: { embedded_web: structuredClone(wrong) } };
  const webBuild = {
    generated_web: {
      manifest: { sha256: "approved" },
      portable: { sha256: "approved-portable" },
    },
  };
  assert.throws(() => assertEmbeddedWebMatchesBuild(apps, webBuild), /does not match/);
});

test("tree manifests change when packaged bytes change", (t) => {
  const root = temporaryDirectory(t);
  fs.mkdirSync(path.join(root, "nested"));
  fs.writeFileSync(path.join(root, "nested", "payload.txt"), "before");
  const before = hashTree(root);
  fs.writeFileSync(path.join(root, "nested", "payload.txt"), "after");
  const after = hashTree(root);
  assert.notEqual(after.sha256, before.sha256);
});

test("CLI packaging hashes canonicalize copied modes but still bind file bytes", (t) => {
  const root = temporaryDirectory(t);
  const source = path.join(root, "source");
  const packaged = path.join(root, "packaged");
  for (const directory of [source, packaged]) {
    fs.mkdirSync(path.join(directory, "nested"), { recursive: true });
    fs.writeFileSync(path.join(directory, "nested", "plain.txt"), "same bytes");
    fs.writeFileSync(path.join(directory, "nested", "run.sh"), "#!/bin/sh\nexit 0\n");
    fs.symlinkSync("plain.txt", path.join(directory, "nested", "plain-link"));
  }
  fs.chmodSync(path.join(source, "nested"), 0o700);
  fs.chmodSync(path.join(source, "nested", "plain.txt"), 0o600);
  fs.chmodSync(path.join(source, "nested", "run.sh"), 0o700);
  fs.chmodSync(path.join(packaged, "nested"), 0o755);
  fs.chmodSync(path.join(packaged, "nested", "plain.txt"), 0o644);
  fs.chmodSync(path.join(packaged, "nested", "run.sh"), 0o755);

  assert.deepEqual(
    hashTree(source, { mode: "cli-packaging" }),
    hashTree(packaged, { mode: "cli-packaging" }),
  );
  fs.writeFileSync(path.join(packaged, "nested", "plain.txt"), "byte drift");
  assert.notEqual(
    hashTree(source, { mode: "cli-packaging" }).sha256,
    hashTree(packaged, { mode: "cli-packaging" }).sha256,
  );
});

test("CLI packaging excludes generated build, dist, and tool-cache trees", (t) => {
  const root = temporaryDirectory(t);
  const source = path.join(root, "source");
  const packaged = path.join(root, "packaged");
  for (const directory of [source, packaged]) {
    fs.mkdirSync(path.join(directory, "elevate_cli"), { recursive: true });
    fs.writeFileSync(path.join(directory, "elevate_cli", "main.py"), "APPROVED = True\n");
  }
  for (const generated of ["build", "dist", ".ruff_cache"]) {
    fs.mkdirSync(path.join(source, generated, "nested"), { recursive: true });
    fs.writeFileSync(path.join(source, generated, "nested", "stale.bin"), generated);
  }

  assert.deepEqual(
    hashTree(source, { mode: "cli-packaging" }),
    hashTree(packaged, { mode: "cli-packaging" }),
  );

  const packageJson = JSON.parse(
    fs.readFileSync(path.resolve(__dirname, "..", "package.json"), "utf8"),
  );
  const cliResource = packageJson.build.extraResources.find(
    (resource) => resource.from === "../cli",
  );
  for (const pattern of ["!build/**", "!dist/**", "!.ruff_cache/**"]) {
    assert.equal(cliResource.filter.includes(pattern), true, `missing CLI packaging exclusion: ${pattern}`);
  }
});

test("packaged CLI permission policy rejects writable or noncanonical output", (t) => {
  const root = temporaryDirectory(t);
  const nested = path.join(root, "nested");
  const payload = path.join(nested, "payload.txt");
  fs.mkdirSync(nested, { mode: 0o755 });
  fs.writeFileSync(payload, "approved", { mode: 0o644 });
  fs.chmodSync(root, 0o755);
  fs.chmodSync(nested, 0o755);
  fs.chmodSync(payload, 0o644);

  assert.equal(assertCanonicalPackagedPermissions(root, "fixture CLI"), true);
  fs.chmodSync(payload, 0o666);
  assert.throws(
    () => assertCanonicalPackagedPermissions(root, "fixture CLI"),
    /unsafe\/noncanonical permissions/,
  );
});

test("pre-sign evidence is source-bound and rejects stale receipts or runtime drift", (t) => {
  const root = temporaryDirectory(t);
  const appPath = path.join(root, "Elevate Beta.app");
  const resources = path.join(appPath, "Contents", "Resources");
  const cli = path.join(resources, "cli");
  const web = path.join(cli, "elevate_cli", "web_dist");
  const whatsapp = path.join(cli, "scripts", "whatsapp-bridge");
  const runtime = path.join(resources, "runtime", "python");
  for (const directory of [web, whatsapp, runtime]) fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(cli, "elevate_cli", "core.py"), "APPROVED = True\n");
  fs.writeFileSync(path.join(web, "index.html"), "source-bound web");
  fs.writeFileSync(path.join(whatsapp, "bridge.js"), "module.exports = true;\n");
  fs.writeFileSync(path.join(runtime, "python3.12"), "unsigned runtime bytes");

  const sourceReceiptId = "a".repeat(64);
  const source = {
    source_receipt_id: sourceReceiptId,
    inputs: {
      "cli/package-input": hashTree(cli, { mode: "cli-packaging" }),
      "cli/whatsapp-bridge": hashTree(whatsapp, { mode: "whatsapp" }),
      "runtime/x64": hashTree(runtime, { mode: "runtime" }),
    },
  };
  const webBuild = {
    schema_version: 1,
    source_receipt_id: sourceReceiptId,
    generated_web: {
      manifest: hashTree(web),
      portable: hashPortableTree(web),
    },
  };
  webBuild.web_build_id = receiptId(webBuild, "web_build_id");
  const evidencePath = path.join(root, "candidate-pre-sign-x64.json");
  const written = createPreSignEvidence({
    appPath,
    architecture: "x64",
    sourceReceiptId,
    webBuildId: webBuild.web_build_id,
    outputPath: evidencePath,
    createdAt: "2026-07-14T00:00:00.000Z",
  });
  const immutableBytes = fs.readFileSync(evidencePath, "utf8");
  assert.throws(() => createPreSignEvidence({
    appPath,
    architecture: "x64",
    sourceReceiptId,
    webBuildId: webBuild.web_build_id,
    outputPath: evidencePath,
    createdAt: "2026-07-14T00:00:01.000Z",
  }), /refusing to replace immutable x64 pre-sign evidence/);
  assert.equal(fs.readFileSync(evidencePath, "utf8"), immutableBytes);
  assert.equal(verifyPreSignEvidence({
    evidencePath,
    architecture: "x64",
    source,
    webBuild,
    appBundleName: "Elevate Beta.app",
  }).pre_sign_evidence_id, written.pre_sign_evidence_id);

  assert.throws(() => verifyPreSignEvidence({
    evidencePath,
    architecture: "x64",
    source: { ...source, source_receipt_id: "b".repeat(64) },
    webBuild,
    appBundleName: "Elevate Beta.app",
  }), /pre-sign source receipt mismatch/);

  const wrongRuntimeSource = structuredClone(source);
  wrongRuntimeSource.inputs["runtime/x64"].sha256 = "c".repeat(64);
  assert.throws(() => verifyPreSignEvidence({
    evidencePath,
    architecture: "x64",
    source: wrongRuntimeSource,
    webBuild,
    appBundleName: "Elevate Beta.app",
  }), /pre-sign embedded runtime does not match/);
});

test("signature-neutral runtime contracts bind algorithm, bytes, and Mach-O count", () => {
  const approved = {
    algorithm: "elevate-runtime-code-tree-v1",
    sha256: "a".repeat(64),
    file_count: 100,
    size: 12345,
    macho_file_count: 9,
  };
  assert.equal(assertRuntimeCodeContract(structuredClone(approved), approved, "runtime"), true);
  assert.throws(
    () => assertRuntimeCodeContract({ ...approved, sha256: "b".repeat(64) }, approved, "runtime"),
    /does not match the source contract/,
  );
  assert.throws(
    () => assertRuntimeCodeContract({ ...approved, macho_file_count: 8 }, approved, "runtime"),
    /signature-neutral code manifest mismatch/,
  );
});

test("artifact and public read-back verification rejects same-size wrong bytes", (t) => {
  const root = temporaryDirectory(t);
  const artifact = path.join(root, "artifact.dmg");
  fs.writeFileSync(artifact, "approved");
  const expected = fileRecord(artifact, root);
  fs.writeFileSync(artifact, "tampered");
  assert.equal(fs.statSync(artifact).size, expected.size);
  assert.throws(() => assertFileRecord(artifact, expected, "public artifact"), /SHA256 mismatch/);
});

test("stale or mutated archive app manifests are release-blocking", () => {
  const approved = { sha256: "approved", file_count: 10, size: 100 };
  assert.equal(assertBundleManifest(structuredClone(approved), approved, "ZIP"), true);
  assert.throws(
    () => assertBundleManifest({ ...approved, sha256: "stale" }, approved, "ZIP"),
    /does not match the smoke-tested app bundle/,
  );
  assert.throws(
    () => assertBundleManifest({ ...approved, file_count: 9 }, approved, "DMG"),
    /does not match the smoke-tested app bundle/,
  );
});

test("ZIP extraction rejects traversal, absolute, foreign-root, and duplicate entries", () => {
  assert.equal(validateZipEntries(["Elevate Beta.app/", "Elevate Beta.app/Contents/a"], "Elevate Beta.app"), true);
  for (const entries of [
    ["../escape"],
    ["/absolute"],
    ["Other.app/Contents/a"],
    ["Elevate Beta.app/a", "Elevate Beta.app/a"],
    ["Elevate Beta.app\\..\\escape"],
  ]) {
    assert.throws(() => validateZipEntries(entries, "Elevate Beta.app"), /(unsafe|escapes|duplicate)/);
  }
});

test("ZIP entry validation streams listings larger than spawnSync's default buffer", (t) => {
  const root = temporaryDirectory(t);
  const listing = path.join(root, "large-zip-listing.txt");
  const entries = Array.from(
    { length: 40_000 },
    (_, index) => `Elevate Beta.app/Contents/Resources/runtime/file-${index.toString().padStart(5, "0")}.txt`,
  );
  fs.writeFileSync(listing, `${entries.join("\n")}\n`);
  assert.ok(fs.statSync(listing).size > 1024 * 1024);
  assert.equal(validateZipEntryListing(listing, "Elevate Beta.app"), true);
});

test("tampering with an immutable candidate receipt invalidates its ID", (t) => {
  const root = temporaryDirectory(t);
  const receiptPath = path.join(root, "candidate-receipt.json");
  const receipt = {
    schema_version: CANDIDATE_RECEIPT_SCHEMA_VERSION,
    kind: "elevate-final-candidate",
    release: { version: "1.2.67", channel: "beta" },
    artifacts: {},
    apps: {},
  };
  receipt.candidate_id = receiptId(receipt, "candidate_id");
  fs.writeFileSync(receiptPath, JSON.stringify(receipt));
  assert.equal(
    verifyCandidateReceipt({ receiptPath, desktopRoot: root, repoRoot: root, requireApps: false, requireSource: false }).candidate_id,
    receipt.candidate_id,
  );
  receipt.release.version = "1.2.68";
  fs.writeFileSync(receiptPath, JSON.stringify(receipt));
  assert.throws(
    () => verifyCandidateReceipt({ receiptPath, desktopRoot: root, repoRoot: root, requireApps: false, requireSource: false }),
    /receipt ID mismatch/,
  );
});

test("ship requires static dual-arch and host live-AI evidence bound to the exact candidate", (t) => {
  const root = temporaryDirectory(t);
  const home = path.join(root, "home");
  const receiptPath = path.join(root, "candidate-receipt.json");
  const candidateFeedPath = path.join(root, "desktop", "dist", "beta-mac.yml");
  fs.mkdirSync(path.dirname(candidateFeedPath), { recursive: true });
  fs.writeFileSync(candidateFeedPath, "version: 1.2.81\n");
  const profile = profileSnapshot(resolveReleaseProfile("beta"));
  const sourceReceiptId = "d".repeat(64);
  const hex = (seed) => crypto.createHash("sha256").update(seed).digest("hex");
  const signerDetails = [
    "Authority=Developer ID Application: Dartagnan Patricio (G5TK395RYH)",
    "TeamIdentifier=G5TK395RYH",
    "CodeDirectory v=20500 flags=0x10000(runtime)",
  ].join("\n");
  const signerRequirement = "designated => anchor apple generic and certificate leaf[subject.OU] = G5TK395RYH";
  const makeSigningEvidence = (seed) => Object.fromEntries([
    ["codesign_verify", ""],
    ["codesign_details", signerDetails],
    ["designated_requirement", signerRequirement],
    ["gatekeeper", "accepted"],
    ["staple", "The validate action worked!"],
  ].map(([name, output]) => [name, { ok: true, status: 0, output, output_sha256: hex(`${seed}:${name}`) }]));
  const trustFor = (evidence) => ({
    signed: true,
    notarized: true,
    stapled: true,
    verification_method: "codesign-gatekeeper-stapled-ticket",
    signing_evidence_sha256: hex(canonicalJson(evidence)),
    notarization_evidence_sha256: evidence.staple.output_sha256,
    stapling_evidence_sha256: evidence.staple.output_sha256,
  });
  const recoveryRoot = path.join(root, "desktop", "dist", "recovery");
  fs.mkdirSync(recoveryRoot, { recursive: true });
  const recoveryArtifactNames = ["x64", "arm64"].flatMap((arch) => [
    `Elevate-Beta-Recovery-1.2.82-mac-${arch}.zip`,
    `Elevate-Beta-Recovery-1.2.82-mac-${arch}.dmg`,
  ]);
  const recoveryApps = {};
  const recoveryDmgs = {};
  for (const arch of ["x64", "arm64"]) {
    const appSigning = makeSigningEvidence(`recovery-app-${arch}`);
    const dmgSigning = makeSigningEvidence(`recovery-dmg-${arch}`);
    recoveryApps[arch] = {
      architecture: arch,
      app_path: path.join("desktop", "dist", "recovery", arch === "x64" ? "mac" : "mac-arm64", profile.appBundleName),
      info_plist: {
        CFBundleIdentifier: profile.appId,
        CFBundleName: profile.productName,
        CFBundleShortVersionString: "1.2.82",
      },
      packaged_metadata: {
        name: profile.packageName,
        version: "1.2.82",
        main: "src/recovery-main.js",
        elevateReleaseChannel: "beta",
        elevateRecoveryMode: true,
        elevateRecoverySourceReceiptId: sourceReceiptId,
        asar_sha256: hex(`recovery-asar-${arch}`),
      },
      app_update: {
        provider: "generic",
        channel: "beta",
        url: "https://api.elevationrealestatehq.com/updates",
        updaterCacheDirName: `${profile.packageName.toLowerCase()}-updater`,
        sha256: hex(`recovery-app-update-${arch}`),
      },
      executable_architectures: [arch === "x64" ? "x86_64" : "arm64"],
      bundle_manifest: { file_count: 9, size: 4096, sha256: hex(`recovery-bundle-${arch}`) },
      embedded_recovery_sources: Object.fromEntries(RECOVERY_SOURCE_FILES.map((name) => [
        name,
        { size: 32, sha256: hex(`recovery-source-${name}`) },
      ])),
      signing: appSigning,
      trust: trustFor(appSigning),
    };
    recoveryDmgs[arch] = {
      artifact: `Elevate-Beta-Recovery-1.2.82-mac-${arch}.dmg`,
      evidence: dmgSigning,
      trust: trustFor(dmgSigning),
    };
  }
  const recoveryArtifacts = {};
  for (const name of recoveryArtifactNames) {
    const architecture = name.includes("-arm64.") ? "arm64" : "x64";
    const format = path.extname(name).slice(1);
    fs.writeFileSync(path.join(recoveryRoot, name), `recovery-artifact:${name}\n`);
    recoveryArtifacts[name] = {
      ...fileRecord(path.join(recoveryRoot, name), root, { includeSha512: true }),
      architecture,
      format,
      packaged_app: {
        bundle_manifest_sha256: recoveryApps[architecture].bundle_manifest.sha256,
        ...recoveryApps[architecture].trust,
      },
      container_trust: format === "dmg" ? recoveryDmgs[architecture].trust : null,
    };
  }
  const primaryRecoveryZip = "Elevate-Beta-Recovery-1.2.82-mac-x64.zip";
  const recoveryFeedPath = path.join(recoveryRoot, "beta-mac.yml");
  fs.writeFileSync(recoveryFeedPath, yaml.dump({
    version: "1.2.82",
    files: recoveryArtifactNames.map((name) => ({
      url: name,
      sha512: recoveryArtifacts[name].sha512,
      size: recoveryArtifacts[name].size,
    })),
    path: primaryRecoveryZip,
    sha512: recoveryArtifacts[primaryRecoveryZip].sha512,
  }));
  const recoveryLocalFeed = {
    ...fileRecord(recoveryFeedPath, root, { includeSha512: true }),
    manifest: yaml.load(fs.readFileSync(recoveryFeedPath, "utf8")),
  };
  const recoveryPreSignContracts = {};
  for (const arch of ["x64", "arm64"]) {
    const preSign = {
      schema_version: 1,
      kind: "elevate-beta-roll-forward-recovery-pre-sign",
      architecture: arch,
      app_bundle_name: profile.appBundleName,
      app_id: profile.appId,
      package_name: profile.packageName,
      protocol_scheme: profile.protocolScheme,
      release_channel: "beta",
      candidate_version: "1.2.81",
      recovery_version: "1.2.82",
      source_receipt_id: sourceReceiptId,
      app_asar_sha256: recoveryApps[arch].packaged_metadata.asar_sha256,
      updater_config_sha256: recoveryApps[arch].app_update.sha256,
      runtime_policy: {
        backend: false,
        cli: false,
        gateway: false,
        runtime: false,
        tools: false,
        profile_preserved: true,
      },
      asar_source_files: RECOVERY_SOURCE_FILES.slice().sort(),
    };
    preSign.evidence_id = receiptId(preSign, "evidence_id");
    fs.writeFileSync(path.join(recoveryRoot, `pre-sign-recovery-${arch}.json`), JSON.stringify(preSign));
    recoveryPreSignContracts[arch] = preSign;
  }
  const recovery = {
    schema_version: 1,
    kind: "elevate-beta-recovery-package",
    candidate_version: "1.2.81",
    version: "1.2.82",
    reserved_version: "1.2.82",
    next_full_beta_minimum_exclusive: "1.2.82",
    source_receipt_id: sourceReceiptId,
    channel: "beta",
    public_feed_name: "beta-mac.yml",
    profile,
    architectures: ["x64", "arm64"],
    artifact_names: recoveryArtifactNames,
    local_feed: recoveryLocalFeed,
    artifacts: recoveryArtifacts,
    apps: recoveryApps,
    pre_sign_contracts: recoveryPreSignContracts,
    signing: { dmgs: recoveryDmgs },
  };
  recovery.static_provenance = recoveryStaticProvenance(recovery);
  const receipt = {
    schema_version: CANDIDATE_RECEIPT_SCHEMA_VERSION,
    kind: "elevate-final-candidate",
    source_receipt_id: sourceReceiptId,
    release: {
      version: "1.2.81",
      channel: "beta",
      feed_name: "beta-mac.yml",
      profile,
    },
    artifacts: { "beta-mac.yml": fileRecord(candidateFeedPath, root) },
    apps: {
      x64: { bundle_manifest: { sha256: "app-x64" } },
      arm64: { bundle_manifest: { sha256: "app-arm64" } },
    },
    recovery,
    required_evidence: {
      x64_smoke: "desktop/dist/evidence/smoke-x64.json",
      arm64_smoke: "desktop/dist/evidence/smoke-arm64.json",
      live_ai: "desktop/dist/evidence/live-ai.json",
      realtor_beta_gate: "desktop/dist/evidence/realtor-beta-gate.json",
    },
    rollback_target: { version: "1.2.65", sha256: "b".repeat(64) },
    public_feeds_at_finalize: {
      latest: { version: "1.2.63", sha256: "c".repeat(64) },
    },
    production_feed_untouched: true,
  };
  receipt.candidate_id = receiptId(receipt, "candidate_id");
  fs.writeFileSync(receiptPath, JSON.stringify(receipt));
  const receiptHash = sha256File(receiptPath);
  const evidenceDir = path.join(root, "desktop", "dist", "evidence");
  fs.mkdirSync(evidenceDir, { recursive: true });
  const makeEvidence = (arch, { live = false } = {}) => {
    const expectedText = `live candidate ${receipt.candidate_id.slice(0, 12)} ok`;
    const evidence = {
      evidence_schema_version: 1,
      ok: true,
      failures: [],
      log_hits: [],
      check_ids: (live ? REQUIRED_LIVE_AI_CHECK_IDS : REQUIRED_SMOKE_CHECK_IDS).slice(),
      candidate_id: receipt.candidate_id,
      source_receipt_id: receipt.source_receipt_id,
      candidate_architecture: arch,
      candidate_receipt_sha256: receiptHash,
      candidate_app_version: receipt.release.version,
      candidate_app_bundle_manifest_sha256: receipt.apps[arch].bundle_manifest.sha256,
      started_at: "2026-07-10T10:00:00.000Z",
      completed_at: "2026-07-10T10:00:01.000Z",
      duration_ms: 1000,
      test_profile: {
        name: live ? "release-candidate-live-v1" : "release-candidate-static-v1",
        skip_seal: false,
        skip_parity: false,
        skip_sidecar: !live,
        telegram_fixture: false,
        telegram_hygiene_soak: false,
        desktop_compacted_followup: false,
      },
    };
    if (live) Object.assign(evidence, {
      host_architecture: arch,
      installed_app_path: path.join(home, "Applications", receipt.release.profile.appBundleName),
      release_channel: receipt.release.channel,
      release_app_bundle_name: receipt.release.profile.appBundleName,
      main_log_path: path.join(home, "Library", "Logs", receipt.release.profile.productName, "main.log"),
      prompt_text: `Reply exactly: ${expectedText}`,
      expected_text: expectedText,
      final_text: expectedText,
      terminal_status: "complete",
      persisted_session_id: "persisted-1",
      resumed_session_id: "resumed-1",
      resumed_message_count: 2,
      license_authenticated: true,
      license_expired: false,
      dashboard_port: receipt.release.profile.preferredPort,
    });
    evidence.evidence_integrity_sha256 = evidenceIntegrity(evidence);
    return evidence;
  };
  const makeRealtorBetaGateEvidence = (arch = "arm64") => {
    const evidence = {
      evidence_schema_version: 1,
      kind: "elevate-realtor-beta-prepublish-gate",
      ok: true,
      failures: [],
      check_ids: REQUIRED_REALTOR_BETA_GATE_CHECK_IDS.slice(),
      candidate_id: receipt.candidate_id,
      source_receipt_id: receipt.source_receipt_id,
      candidate_architecture: arch,
      candidate_receipt_sha256: receiptHash,
      candidate_app_version: receipt.release.version,
      candidate_app_bundle_manifest_sha256: receipt.apps[arch].bundle_manifest.sha256,
      release_channel: "beta",
      release_app_bundle_name: "Elevate Beta.app",
      installed_app_name: "Elevate Beta.app",
      started_at: "2026-07-10T10:00:00.000Z",
      completed_at: "2026-07-10T10:00:01.000Z",
      duration_ms: 1000,
      test_profile: {
        name: "exact-installed-realtor-beta-prepublish-v1",
        isolated_home: true,
        installed_profile_mutation: false,
        remote_mutation: false,
        public_feed_mutation: false,
      },
      profile: {
        identities_distinct: true,
        preferred_port: Number(profile.preferredPort),
        production_feed_untouched: true,
      },
      installed_runtime: { module_count: 7, python_major: 3, python_minor: 12 },
      tool_parity: { request_count: 2, receipt_count: 2 },
      pack: { form_count: 34, pack_sha256: "a".repeat(64) },
      action_faults: {
        forms_missing_available: false,
        forms_fake_available: false,
        artifact_rejections: 2,
        worker_retry_count: 1,
        worker_terminal_status: "failed",
      },
      session_resume: {
        session_id_preserved: true,
        message_count: 1,
        resume_pending_cleared: true,
      },
      recovery: {
        mode: "local-fixture-roll-forward",
        candidate_version: receipt.release.version,
        recovery_version: receipt.recovery.version,
        source_receipt_id: receipt.source_receipt_id,
        recovery_feed_sha256: receipt.recovery.local_feed.sha256,
        beta_after_sha256: receipt.recovery.local_feed.sha256,
        candidate_feed_sha256: receipt.artifacts["beta-mac.yml"].sha256,
        stable_before_sha256: receipt.public_feeds_at_finalize.latest.sha256,
        stable_after_sha256: receipt.public_feeds_at_finalize.latest.sha256,
        stable_expected_sha256: receipt.public_feeds_at_finalize.latest.sha256,
        stable_alias_count: 2,
        recovery_alias_count: 4,
        recovery_artifact_count: 4,
        recovery_architecture_count: 2,
        signed_app_count: 2,
        notarized_app_count: 2,
        stapled_app_count: 2,
        runtime_actor_count: 0,
        backend_actor_count: 0,
        gateway_actor_count: 0,
        tool_actor_count: 0,
        artifact_bytes_mode: "synthetic-local-fixture",
        remote_mutation: false,
        production_mutated: false,
        profile_data_mutations: 0,
        rpo_seconds: 0,
        procedure_id: "realtor-beta-recovery-roll-forward-v1",
      },
    };
    evidence.evidence_integrity_sha256 = evidenceIntegrity(evidence);
    return evidence;
  };
  for (const arch of ["x64", "arm64"]) {
    fs.writeFileSync(path.join(evidenceDir, `smoke-${arch}.json`), JSON.stringify(makeEvidence(arch)));
  }
  assert.equal(verifyCandidateReceipt({
    receiptPath,
    desktopRoot: root,
    repoRoot: root,
    requireApps: false,
    requireSource: false,
    requireEvidence: "static",
  }).candidate_id, receipt.candidate_id);
  assert.throws(() => verifyCandidateReceipt({
    receiptPath,
    desktopRoot: root,
    repoRoot: root,
    requireApps: false,
    requireSource: false,
    requireEvidence: true,
    evidenceHome: home,
    hostArchitecture: "arm64",
  }), /missing required evidence: live_ai/);
  fs.writeFileSync(path.join(evidenceDir, "live-ai.json"), JSON.stringify(makeEvidence("arm64", { live: true })));
  assert.throws(() => verifyCandidateReceipt({
    receiptPath,
    desktopRoot: root,
    repoRoot: root,
    requireApps: false,
    requireSource: false,
    requireEvidence: true,
    evidenceHome: home,
    hostArchitecture: "arm64",
  }), /missing required evidence: realtor_beta_gate/);
  fs.writeFileSync(
    path.join(evidenceDir, "realtor-beta-gate.json"),
    JSON.stringify(makeRealtorBetaGateEvidence()),
  );
  assert.equal(verifyCandidateReceipt({
    receiptPath,
    desktopRoot: root,
    repoRoot: root,
    requireApps: false,
    requireSource: false,
    requireEvidence: true,
    evidenceHome: home,
    hostArchitecture: "arm64",
  }).candidate_id, receipt.candidate_id);

  const assertGateRejected = (mutate, pattern) => {
    const invalidGate = makeRealtorBetaGateEvidence();
    mutate(invalidGate);
    invalidGate.evidence_integrity_sha256 = evidenceIntegrity(invalidGate);
    fs.writeFileSync(path.join(evidenceDir, "realtor-beta-gate.json"), JSON.stringify(invalidGate));
    assert.throws(() => verifyCandidateReceipt({
      receiptPath,
      desktopRoot: root,
      repoRoot: root,
      requireApps: false,
      requireSource: false,
      requireEvidence: true,
      evidenceHome: home,
      hostArchitecture: "arm64",
    }), pattern);
  };
  assertGateRejected((gate) => { gate.recovery.stable_after_sha256 = "f".repeat(64); }, /recovery roll-forward drill evidence is invalid/);
  assertGateRejected((gate) => { delete gate.recovery; }, /recovery roll-forward drill evidence is invalid/);
  assertGateRejected((gate) => { gate.recovery.recovery_version = receipt.release.version; }, /recovery roll-forward drill evidence is invalid/);
  assertGateRejected((gate) => { gate.recovery.remote_mutation = true; }, /recovery roll-forward drill evidence is invalid/);

  // Mutating the gate evidence body without recomputing its integrity digest
  // must fail closed on the integrity branch. python_minor is covered by the
  // digest but by no earlier field check, so the tamper reaches exactly that
  // branch instead of tripping an unrelated validation first.
  const staleIntegrityGate = makeRealtorBetaGateEvidence();
  staleIntegrityGate.installed_runtime.python_minor += 1;
  fs.writeFileSync(
    path.join(evidenceDir, "realtor-beta-gate.json"),
    JSON.stringify(staleIntegrityGate),
  );
  assert.throws(() => verifyCandidateReceipt({
    receiptPath,
    desktopRoot: root,
    repoRoot: root,
    requireApps: false,
    requireSource: false,
    requireEvidence: true,
    evidenceHome: home,
    hostArchitecture: "arm64",
  }), /Realtor Beta gate evidence integrity mismatch/);

  fs.writeFileSync(
    path.join(evidenceDir, "realtor-beta-gate.json"),
    JSON.stringify(makeRealtorBetaGateEvidence()),
  );

  const assertLiveRejected = (mutate, pattern) => {
    const evidence = makeEvidence("arm64", { live: true });
    mutate(evidence);
    evidence.evidence_integrity_sha256 = evidenceIntegrity(evidence);
    fs.writeFileSync(path.join(evidenceDir, "live-ai.json"), JSON.stringify(evidence));
    assert.throws(() => verifyCandidateReceipt({
      receiptPath,
      desktopRoot: root,
      repoRoot: root,
      requireApps: false,
      requireSource: false,
      requireEvidence: true,
      evidenceHome: home,
      hostArchitecture: "arm64",
    }), pattern);
  };
  assertLiveRejected((evidence) => { evidence.test_profile.skip_sidecar = true; }, /wrong test profile/);
  assertLiveRejected((evidence) => { evidence.installed_app_path = path.join(home, "Applications", "Other.app"); }, /invalid live AI evidence/);
  assertLiveRejected((evidence) => { evidence.candidate_architecture = "x64"; }, /invalid required smoke evidence/);
  assertLiveRejected((evidence) => { evidence.candidate_id = "wrong"; }, /invalid required smoke evidence/);
  assertLiveRejected((evidence) => { evidence.main_log_path = path.join(home, "Library", "Logs", "Elevate", "main.log"); }, /invalid live AI evidence/);

  fs.writeFileSync(path.join(evidenceDir, "smoke-arm64.json"), JSON.stringify({
    ok: true,
    candidate_id: receipt.candidate_id,
    candidate_architecture: "arm64",
    candidate_receipt_sha256: receiptHash,
  }));
  assert.throws(() => verifyCandidateReceipt({
    receiptPath,
    desktopRoot: root,
    repoRoot: root,
    requireApps: false,
    requireSource: false,
    requireEvidence: "static",
  }), /invalid required smoke evidence/);

  const missingCheck = makeEvidence("arm64");
  missingCheck.check_ids = missingCheck.check_ids.filter((check) => check !== "app_seal");
  missingCheck.evidence_integrity_sha256 = evidenceIntegrity(missingCheck);
  fs.writeFileSync(path.join(evidenceDir, "smoke-arm64.json"), JSON.stringify(missingCheck));
  assert.throws(() => verifyCandidateReceipt({
    receiptPath,
    desktopRoot: root,
    repoRoot: root,
    requireApps: false,
    requireSource: false,
    requireEvidence: "static",
  }), /missing required checks/);
});

test("recoveryStaticProvenance emits a pinned static-provenance key and shape contract", () => {
  const artifactNames = ["x64", "arm64"].flatMap((arch) => [
    `Elevate-Beta-Recovery-1.2.82-mac-${arch}.zip`,
    `Elevate-Beta-Recovery-1.2.82-mac-${arch}.dmg`,
  ]);
  const runtimePolicy = {
    backend: false,
    cli: false,
    gateway: false,
    runtime: false,
    tools: false,
    profile_preserved: true,
  };
  const recovery = {
    source_receipt_id: "d".repeat(64),
    candidate_version: "1.2.81",
    version: "1.2.82",
    profile: { productName: "Elevate Beta", appId: "com.elevationrealestate.elevate.beta" },
    local_feed: { sha256: "a".repeat(64), sha512: "ZmVlZC1zaGE1MTI=" },
    artifact_names: artifactNames,
    artifacts: Object.fromEntries(artifactNames.map((name) => {
      const architecture = name.includes("-arm64.") ? "arm64" : "x64";
      const format = name.endsWith(".dmg") ? "dmg" : "zip";
      return [name, {
        architecture,
        format,
        sha256: `sha256-${name}`,
        sha512: `sha512-${name}`,
        packaged_app: { bundle_manifest_sha256: `bundle-${architecture}` },
        container_trust: format === "dmg" ? { signing_evidence_sha256: `dmgsig-${architecture}` } : null,
      }];
    })),
    apps: Object.fromEntries(["x64", "arm64"].map((arch) => [arch, {
      bundle_manifest: { sha256: `bundle-${arch}` },
      trust: { signing_evidence_sha256: `appsig-${arch}` },
    }])),
    signing: {
      dmgs: Object.fromEntries(["x64", "arm64"].map((arch) => [arch, {
        trust: { signing_evidence_sha256: `dmgsig-${arch}` },
      }])),
    },
    pre_sign_contracts: Object.fromEntries(["x64", "arm64"].map((arch) => [arch, {
      evidence_id: `presign-${arch}`,
      runtime_policy: runtimePolicy,
    }])),
  };

  const provenance = recoveryStaticProvenance(recovery);
  assert.deepEqual(Object.keys(provenance).sort(), [
    "app_bundle_sha256",
    "app_signing_sha256",
    "artifact_provenance_sha256",
    "artifact_sha256",
    "artifact_sha512",
    "candidate_version",
    "dmg_signing_sha256",
    "feed_sha256",
    "feed_sha512",
    "kind",
    "pre_sign_evidence_id",
    "profile_sha256",
    "recovery_version",
    "runtime_policy",
    "schema_version",
    "source_receipt_id",
  ]);
  assert.equal(provenance.schema_version, 1);
  assert.equal(provenance.kind, "elevate-beta-recovery-static-provenance");
  assert.equal(provenance.source_receipt_id, recovery.source_receipt_id);
  assert.equal(provenance.candidate_version, "1.2.81");
  assert.equal(provenance.recovery_version, "1.2.82");
  assert.equal(provenance.feed_sha256, recovery.local_feed.sha256);
  assert.equal(provenance.feed_sha512, recovery.local_feed.sha512);
  assert.match(provenance.profile_sha256, /^[a-f0-9]{64}$/);
  for (const map of [
    provenance.artifact_sha256,
    provenance.artifact_sha512,
    provenance.artifact_provenance_sha256,
  ]) {
    assert.deepEqual(Object.keys(map).sort(), artifactNames.slice().sort());
  }
  for (const map of [
    provenance.app_bundle_sha256,
    provenance.app_signing_sha256,
    provenance.dmg_signing_sha256,
    provenance.pre_sign_evidence_id,
  ]) {
    assert.deepEqual(Object.keys(map).sort(), ["arm64", "x64"]);
  }
  assert.equal(provenance.app_bundle_sha256.x64, "bundle-x64");
  assert.equal(provenance.app_signing_sha256.arm64, "appsig-arm64");
  assert.equal(provenance.dmg_signing_sha256.x64, "dmgsig-x64");
  assert.equal(provenance.pre_sign_evidence_id.arm64, "presign-arm64");
  assert.deepEqual(provenance.runtime_policy, runtimePolicy);
});

test("immutable receipt creation is idempotent but refuses replacement", (t) => {
  const root = temporaryDirectory(t);
  const receiptPath = path.join(root, "candidate-receipt.json");
  const first = writeImmutableReceipt(receiptPath, { schema_version: 1, version: "1.2.67" }, "candidate_id");
  assert.deepEqual(writeImmutableReceipt(receiptPath, { schema_version: 1, version: "1.2.67" }, "candidate_id"), first);
  assert.throws(
    () => writeImmutableReceipt(receiptPath, { schema_version: 1, version: "1.2.68" }, "candidate_id"),
    /refusing to replace immutable/,
  );
});

function successfulArchiveFixture(t, version = "1.2.67") {
  const root = temporaryDirectory(t);
  const dist = path.join(root, "dist");
  const evidenceDir = path.join(dist, "evidence");
  fs.mkdirSync(evidenceDir, { recursive: true });
  const source = { schema_version: 1, source: "approved" };
  source.source_receipt_id = receiptId(source, "source_receipt_id");
  const web = { schema_version: 1, source_receipt_id: source.source_receipt_id, web: "approved" };
  web.web_build_id = receiptId(web, "web_build_id");
  const candidate = {
    schema_version: 1,
    kind: "elevate-final-candidate",
    source_receipt_id: source.source_receipt_id,
    source,
    web_build: web,
    release: {
      channel: "beta",
      version,
      feed_name: "beta-mac.yml",
      artifact_names: [
        `Elevate-Beta-${version}-mac-x64.zip`,
        `Elevate-Beta-${version}-mac-x64.dmg`,
        `Elevate-Beta-${version}-mac-arm64.zip`,
        `Elevate-Beta-${version}-mac-arm64.dmg`,
      ],
      download_aliases: [
        "Elevate-Beta-mac-x64.dmg",
        "Elevate-beta-mac-x64.dmg",
        "Elevate-Beta-mac-arm64.dmg",
        "Elevate-beta-mac-arm64.dmg",
      ],
    },
    required_evidence: {
      x64_smoke: "dist/evidence/smoke-x64.json",
      arm64_smoke: "dist/evidence/smoke-arm64.json",
      live_ai: "dist/evidence/live-ai.json",
      realtor_beta_gate: "dist/evidence/realtor-beta-gate.json",
    },
    rollback_target: { channel: "beta", version: "1.2.65", sha256: "b".repeat(64) },
  };
  candidate.artifacts = Object.fromEntries(candidate.release.artifact_names.map((name, index) => [name, {
    path: `dist/${name}`,
    size: 100 + index,
    sha256: crypto.createHash("sha256").update(name).digest("hex"),
    sha512: Buffer.alloc(64, index + 1).toString("base64"),
  }]));
  candidate.artifacts["beta-mac.yml"] = {
    path: "dist/beta-mac.yml",
    size: 321,
    sha256: "c".repeat(64),
  };
  candidate.candidate_id = receiptId(candidate, "candidate_id");
  const active = {
    source: path.join(dist, "candidate-source.json"),
    web: path.join(dist, "candidate-web.json"),
    candidate: path.join(dist, "candidate-receipt.json"),
    x64: path.join(evidenceDir, "smoke-x64.json"),
    arm64: path.join(evidenceDir, "smoke-arm64.json"),
    live: path.join(evidenceDir, "live-ai.json"),
    realtorGate: path.join(evidenceDir, "realtor-beta-gate.json"),
    public: path.join(evidenceDir, "public-readback.json"),
    ship: path.join(evidenceDir, "ship.json"),
  };
  fs.writeFileSync(active.source, JSON.stringify(source));
  fs.writeFileSync(active.web, JSON.stringify(web));
  fs.writeFileSync(active.candidate, JSON.stringify(candidate));
  for (const filePath of [active.x64, active.arm64, active.live, active.realtorGate]) {
    fs.writeFileSync(filePath, JSON.stringify({ candidate_id: candidate.candidate_id }));
  }
  const candidateReceiptSha256 = sha256File(active.candidate);
  const publicArtifacts = Object.fromEntries(candidate.release.artifact_names.map((name) => [name, {
    url: `https://api.elevationrealestatehq.com/updates/${name}`,
    size: candidate.artifacts[name].size,
    sha256: candidate.artifacts[name].sha256,
  }]));
  const publicAliases = Object.fromEntries(candidate.release.download_aliases.map((alias) => {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    const sourceName = candidate.release.artifact_names.find((name) => name.endsWith(`-mac-${arch}.dmg`));
    return [alias, {
      url: `https://api.elevationrealestatehq.com/updates/${alias}`,
      size: candidate.artifacts[sourceName].size,
      sha256: candidate.artifacts[sourceName].sha256,
    }];
  }));
  fs.writeFileSync(active.public, JSON.stringify({
    schema_version: 1,
    kind: "elevate-public-readback",
    candidate_id: candidate.candidate_id,
    source_receipt_id: candidate.source_receipt_id,
    candidate_receipt_sha256: candidateReceiptSha256,
    channel: "beta",
    version,
    verified_at: "2026-07-10T09:59:59.000Z",
    feed: {
      url: "https://api.elevationrealestatehq.com/updates/beta-mac.yml",
      size: candidate.artifacts["beta-mac.yml"].size,
      sha256: candidate.artifacts["beta-mac.yml"].sha256,
    },
    artifacts: publicArtifacts,
    aliases: publicAliases,
  }));
  fs.writeFileSync(active.ship, JSON.stringify({
    schema_version: 1,
    kind: "elevate-ship-record",
    candidate_id: candidate.candidate_id,
    source_receipt_id: candidate.source_receipt_id,
    candidate_receipt_sha256: candidateReceiptSha256,
    channel: "beta",
    version,
    shipped_at: "2026-07-10T10:00:00.000Z",
    remote_publish_state: "committed",
    rollback_target: candidate.rollback_target,
    public_feed: "https://api.elevationrealestatehq.com/updates/beta-mac.yml",
    public_artifacts: candidate.artifacts && Object.fromEntries(
      candidate.release.artifact_names.map((name) => [name, candidate.artifacts[name]]),
    ),
    live_ai_evidence_sha256: sha256File(active.live),
    public_readback_sha256: sha256File(active.public),
    stable_pruner_status: null,
  }));
  const unrelated = path.join(evidenceDir, "keep-me.txt");
  fs.writeFileSync(unrelated, "unrelated");

  return { root, dist, evidenceDir, source, web, candidate, active, unrelated };
}

test("successful release archive preserves proof and clears only active pointers for the next release", (t) => {
  const { root, dist, candidate, active, unrelated } = successfulArchiveFixture(t);
  let activeVerifierCalls = 0;
  const beforeArchive = resolveReleaseCandidateForShip({
    distRoot: dist,
    channel: "beta",
    version: candidate.release.version,
    verifyActiveCandidate: () => {
      activeVerifierCalls += 1;
      return candidate;
    },
  });
  assert.equal(beforeArchive.archiveRecovery, null);
  assert.equal(beforeArchive.candidate.candidate_id, candidate.candidate_id);
  assert.equal(activeVerifierCalls, 1);

  const archived = archiveSuccessfulRelease({
    candidate,
    distRoot: dist,
    repoRoot: root,
    archivedAt: "2026-07-10T10:00:00.000Z",
  });
  assert.equal(
    archived.archivePath,
    path.join(dist, "release-receipts", "beta", `1.2.67-${candidate.candidate_id}`),
  );
  assert.equal(verifyReleaseArchive(archived.archivePath).candidate_id, candidate.candidate_id);
  for (const filePath of Object.values(active)) assert.equal(fs.existsSync(filePath), false);
  assert.equal(fs.readFileSync(unrelated, "utf8"), "unrelated");

  writeImmutableReceipt(active.source, { schema_version: 1, source: "next" }, "source_receipt_id");
  writeImmutableReceipt(active.web, { schema_version: 1, web: "next" }, "web_build_id");
  writeImmutableReceipt(active.candidate, { schema_version: 1, version: "1.2.68" }, "candidate_id");
  assert.equal(fs.existsSync(active.candidate), true);

  fs.writeFileSync(path.join(archived.archivePath, "evidence", "smoke-x64.json"), "tampered");
  assert.throws(() => verifyReleaseArchive(archived.archivePath), /mismatch/);
});

test("successful release archive resumes after its rename and every active unlink boundary", async (t) => {
  for (let crashAfterStep = 1; crashAfterStep <= 10; crashAfterStep += 1) {
    await t.test(`crash step ${crashAfterStep}`, (child) => {
      const fixture = successfulArchiveFixture(child, `1.2.${70 + crashAfterStep}`);
      assert.throws(
        () => archiveSuccessfulRelease({
          candidate: fixture.candidate,
          distRoot: fixture.dist,
          repoRoot: fixture.root,
          crashAfterStep,
        }),
        /injected archive crash/,
      );
      let activeVerifierCalled = false;
      const resolution = resolveReleaseCandidateForShip({
        distRoot: fixture.dist,
        channel: "beta",
        version: fixture.candidate.release.version,
        verifyActiveCandidate: () => {
          activeVerifierCalled = true;
          throw new Error("active verification must not run after a durable archive commit");
        },
      });
      const recovered = resolution.archiveRecovery;
      assert.equal(activeVerifierCalled, false);
      assert.equal(recovered.candidate.candidate_id, fixture.candidate.candidate_id);
      const adopted = archiveSuccessfulRelease({
        candidate: recovered.candidate,
        distRoot: fixture.dist,
        repoRoot: fixture.root,
      });
      assert.equal(adopted.adopted, true);
      assert.equal(adopted.archive.archive_id, recovered.archive.archive_id);
      for (const filePath of Object.values(fixture.active)) assert.equal(fs.existsSync(filePath), false);
      assert.equal(fs.readFileSync(fixture.unrelated, "utf8"), "unrelated");
    });
  }
});

test("archive adoption rejects corrupt proof and never removes a replaced active pointer", (t) => {
  const fixture = successfulArchiveFixture(t, "1.2.91");
  assert.throws(() => archiveSuccessfulRelease({
    candidate: fixture.candidate,
    distRoot: fixture.dist,
    repoRoot: fixture.root,
    crashAfterStep: 1,
  }), /injected archive crash/);
  fs.writeFileSync(fixture.active.public, JSON.stringify({ candidate_id: "foreign" }));
  assert.throws(() => archiveSuccessfulRelease({
    candidate: fixture.candidate,
    distRoot: fixture.dist,
    repoRoot: fixture.root,
  }), /active evidence\/public-readback\.json .* mismatch/);
  assert.equal(fs.existsSync(fixture.active.public), true);

  const archivePath = path.join(
    fixture.dist,
    "release-receipts",
    "beta",
    `${fixture.candidate.release.version}-${fixture.candidate.candidate_id}`,
  );
  fs.writeFileSync(path.join(archivePath, "evidence", "ship.json"), "corrupt");
  assert.throws(() => findSuccessfulReleaseArchive({
    distRoot: fixture.dist,
    channel: "beta",
    version: fixture.candidate.release.version,
  }), /mismatch|JSON/);
});

test("source verification rejects dirty or changed release inputs", (t) => {
  const root = temporaryDirectory(t);
  const git = (args) => {
    const result = require("node:child_process").spawnSync("git", args, { cwd: root, encoding: "utf8" });
    assert.equal(result.status, 0, result.stderr);
    return (result.stdout || "").trim();
  };
  git(["init", "-q"]);
  git(["config", "user.email", "candidate-test@example.invalid"]);
  git(["config", "user.name", "Candidate Test"]);
  const input = path.join(root, "release-input.txt");
  fs.writeFileSync(input, "approved");
  fs.writeFileSync(path.join(root, ".gitignore"), "candidate-source.json\n");
  git(["add", "release-input.txt", ".gitignore"]);
  git(["commit", "-qm", "fixture"]);
  const receipt = {
    schema_version: SOURCE_RECEIPT_SCHEMA_VERSION,
    kind: "elevate-candidate-source",
    git: { commit: git(["rev-parse", "HEAD"]), branch: git(["branch", "--show-current"]), clean: true },
    release: {
      channel: "latest",
      version: "1.2.67",
      profile: profileSnapshot(STABLE),
    },
    inputs: { release_input: { kind: "file", ...fileRecord(input, root) } },
  };
  receipt.source_receipt_id = receiptId(receipt, "source_receipt_id");
  const receiptPath = path.join(root, "candidate-source.json");
  fs.writeFileSync(receiptPath, JSON.stringify(receipt));
  assert.equal(
    verifySourceReceipt({ receiptPath, repoRoot: root, channel: "latest", version: "1.2.67" }).source_receipt_id,
    receipt.source_receipt_id,
  );
  fs.writeFileSync(input, "tampered");
  assert.throws(
    () => verifySourceReceipt({ receiptPath, repoRoot: root, channel: "latest", version: "1.2.67" }),
    /checkout no longer matches clean source receipt/,
  );
});
