"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const asar = require("@electron/asar");

const {
  REQUIRED_LIVE_AI_CHECK_IDS,
  REQUIRED_SMOKE_CHECK_IDS,
  archiveSuccessfulRelease,
  assertBundleManifest,
  assertCanonicalPackagedPermissions,
  assertFileRecord,
  assertGloballyNewVersion,
  assertPackagedMetadata,
  assertPublicFeedsUnchanged,
  assertRuntimeCodeContract,
  assertTrustedSignerEvidence,
  assertEmbeddedWebMatchesBuild,
  buildRemotePublishTransaction,
  canonicalJson,
  createPreSignEvidence,
  evidenceIntegrity,
  fileRecord,
  hashPortableTree,
  hashTree,
  normalizeArchitecture,
  portableAsarDirectoryHash,
  preSignEvidencePath,
  receiptId,
  runMacBuilders,
  sha256File,
  verifyCandidateReceipt,
  verifyPreSignEvidence,
  verifyReleaseArchive,
  verifySourceReceipt,
  validateFeed,
  validateZipEntryListing,
  validateZipEntries,
  writeImmutableReceipt,
} = require("../scripts/candidate-receipt");

function temporaryDirectory(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-candidate-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

test("candidate IDs use canonical key ordering", () => {
  const left = { schema_version: 1, release: { version: "1.2.67", channel: "beta" } };
  const right = { release: { channel: "beta", version: "1.2.67" }, schema_version: 1 };
  assert.equal(canonicalJson(left), canonicalJson(right));
  assert.equal(receiptId(left, "candidate_id"), receiptId(right, "candidate_id"));
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

test("remote publication verifies staged artifacts under one lock before aliases and feed", () => {
  const candidateId = "d".repeat(64);
  const artifactNames = [
    "Elevate-Beta-1.2.67-mac-x64.dmg",
    "Elevate-Beta-1.2.67-mac-arm64.dmg",
  ];
  const candidate = {
    candidate_id: candidateId,
    public_feeds_at_finalize: {
      latest: { sha256: "latest-baseline" },
      beta: { sha256: "beta-baseline" },
    },
    artifacts: {
      [artifactNames[0]]: { sha256: "a".repeat(64) },
      [artifactNames[1]]: { sha256: "b".repeat(64) },
      "beta-mac.yml": { sha256: "c".repeat(64) },
    },
    release: {
      channel: "beta",
      feed_name: "beta-mac.yml",
      artifact_names: artifactNames,
      download_aliases: [
        "Elevate-Beta-mac-x64.dmg",
        "Elevate-beta-mac-x64.dmg",
        "Elevate-Beta-mac-arm64.dmg",
        "Elevate-beta-mac-arm64.dmg",
      ],
    },
  };
  const stagingName = `.candidate-${candidateId}-test`;
  const command = buildRemotePublishTransaction({ candidate, stagingName });
  const parsed = require("node:child_process").spawnSync("bash", ["-n", "-c", command], { encoding: "utf8" });
  assert.equal(parsed.status, 0, parsed.stderr);
  assert.equal((command.match(/\bflock\b/g) || []).length, 1);
  assert.match(command, /flock -x \/var\/lock\/elevate-release-publish\.lock/);
  assert.match(command, new RegExp(stagingName));
  assert.match(command, /latest-mac\.yml/);
  assert.match(command, /beta-mac\.yml/);
  assert.match(command, /Elevate-Beta-mac-arm64\.dmg/);
  assert.match(command, /Elevate-beta-mac-arm64\.dmg/);
  const firstStagedCheck = command.indexOf("STAGED_HASH_FAILED");
  const lastStagedCheck = command.lastIndexOf("STAGED_HASH_FAILED");
  const firstCollision = command.indexOf("FINAL_COLLISION");
  const lastCollision = command.lastIndexOf("FINAL_COLLISION");
  const firstArtifactMove = command.indexOf("else mv");
  const lastArtifactMove = command.lastIndexOf("else mv");
  const firstAliasMove = command.indexOf("mv -f");
  const feedMove = command.lastIndexOf("mv -f");
  assert.ok(command.indexOf("CAS_FAILED latest") < firstStagedCheck);
  assert.ok(command.indexOf("CAS_FAILED beta") < firstStagedCheck);
  assert.ok(lastStagedCheck < firstCollision);
  assert.ok(lastCollision < firstArtifactMove);
  assert.ok(lastArtifactMove < firstAliasMove);
  assert.ok(command.lastIndexOf("Elevate-beta-mac-arm64.dmg") < feedMove);
  assert.match(command, /trap .*rm -rf -- .*\.candidate-/);
  for (const record of Object.values(candidate.artifacts)) assert.match(command, new RegExp(record.sha256));
  assert.doesNotMatch(command, /mv -f .*Elevate-Beta-1\.2\.67-mac-(x64|arm64)\.dmg/);

  const shipSource = fs.readFileSync(path.resolve(__dirname, "../scripts/ship-to-hetzner.js"), "utf8");
  assert.match(shipSource, /`\$\{HOST\}:\$\{stagingPath\}`/);
  assert.doesNotMatch(shipSource, /`\$\{HOST\}:\$\{REMOTE\}`/);
  assert.throws(() => buildRemotePublishTransaction({ candidate, stagingName: "../unsafe" }), /unsafe remote staging/);
  const incomplete = structuredClone(candidate);
  delete incomplete.artifacts["beta-mac.yml"];
  assert.throws(() => buildRemotePublishTransaction({ candidate: incomplete, stagingName }), /missing SHA256/);

  const stable = structuredClone(candidate);
  stable.release.channel = "latest";
  const stableCommand = buildRemotePublishTransaction({ candidate: stable, stagingName });
  assert.match(stableCommand, /find .* -maxdepth 1 -type f -name/);
  assert.match(stableCommand, /\*\.zip\.blockmap/);
  assert.match(stableCommand, /-delete/);
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
      preSignEvidenceExists: ["x64", "arm64"].map((arch) =>
        fs.existsSync(process.env.TEST_PRE_SIGN_DIR + "/candidate-pre-sign-" + arch + ".json")),
    }) + "\\n");
  `);
  fs.writeFileSync(merge, `
    require("node:fs").appendFileSync(process.env.TEST_BUILD_LOG, JSON.stringify({
      kind: "merge",
      envId: process.env.ELEVATE_SOURCE_RECEIPT_ID,
    }) + "\\n");
  `);
  fs.writeFileSync(web, `
    const fs = require("node:fs");
    fs.mkdirSync(process.env.TEST_WEB_OUTPUT, { recursive: true });
    fs.writeFileSync(process.env.TEST_WEB_OUTPUT + "/index.html", "source-bound web");
  `);
  const sourceReceiptId = "b".repeat(64);
  fs.mkdirSync(preSignEvidenceDirectory);
  for (const arch of ["x64", "arm64"]) {
    fs.writeFileSync(preSignEvidencePath(preSignEvidenceDirectory, arch), "stale evidence");
  }
  assert.equal(runMacBuilders({
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
  const generatedWebReceipt = JSON.parse(fs.readFileSync(webReceipt, "utf8"));
  assert.equal(generatedWebReceipt.source_receipt_id, sourceReceiptId);
  for (const arch of ["x64", "arm64"]) {
    assert.equal(fs.existsSync(preSignEvidencePath(preSignEvidenceDirectory, arch)), false);
  }
  const scripts = require("../package.json").scripts;
  assert.match(scripts["build:mac"], /candidate-receipt\.js build-mac/);
  assert.doesNotMatch(scripts["release:mac"], /ship:mac/);
  assert.match(scripts["smoke:mac:live"], /--live-candidate/);
  assert.match(scripts["smoke:mac:live"], /live-ai\.json/);
  assert.doesNotMatch(scripts["smoke:mac:live"], /--skip-sidecar/);
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

test("portable desktop/src hash matches ASAR bytes and rejects altered packaged source", async (t) => {
  const root = temporaryDirectory(t);
  const packageRoot = path.join(root, "package");
  const src = path.join(packageRoot, "src");
  fs.mkdirSync(src, { recursive: true });
  fs.writeFileSync(path.join(packageRoot, "package.json"), "{}");
  fs.writeFileSync(path.join(src, "main.js"), "module.exports = 'approved';\n");
  const approved = hashPortableTree(src);
  const approvedAsar = path.join(root, "approved.asar");
  await asar.createPackage(packageRoot, approvedAsar);
  assert.equal(portableAsarDirectoryHash(approvedAsar, "src").sha256, approved.sha256);

  fs.writeFileSync(path.join(src, "main.js"), "module.exports = 'altered';\n");
  const alteredAsar = path.join(root, "altered.asar");
  await asar.createPackage(packageRoot, alteredAsar);
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
    schema_version: 1,
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
  const receipt = {
    schema_version: 1,
    kind: "elevate-final-candidate",
    source_receipt_id: "source-123",
    release: {
      version: "1.2.67",
      channel: "beta",
      profile: {
        appBundleName: "Elevate Beta.app",
        productName: "Elevate Beta",
        preferredPort: 9139,
      },
    },
    artifacts: {},
    apps: {
      x64: { bundle_manifest: { sha256: "app-x64" } },
      arm64: { bundle_manifest: { sha256: "app-arm64" } },
    },
    required_evidence: {
      x64_smoke: "desktop/dist/evidence/smoke-x64.json",
      arm64_smoke: "desktop/dist/evidence/smoke-arm64.json",
      live_ai: "desktop/dist/evidence/live-ai.json",
    },
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

test("successful release archive preserves proof and clears only active pointers for the next release", (t) => {
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
    release: { channel: "beta", version: "1.2.67" },
    required_evidence: {
      x64_smoke: "dist/evidence/smoke-x64.json",
      arm64_smoke: "dist/evidence/smoke-arm64.json",
      live_ai: "dist/evidence/live-ai.json",
    },
  };
  candidate.candidate_id = receiptId(candidate, "candidate_id");
  const active = {
    source: path.join(dist, "candidate-source.json"),
    web: path.join(dist, "candidate-web.json"),
    candidate: path.join(dist, "candidate-receipt.json"),
    x64: path.join(evidenceDir, "smoke-x64.json"),
    arm64: path.join(evidenceDir, "smoke-arm64.json"),
    live: path.join(evidenceDir, "live-ai.json"),
    public: path.join(evidenceDir, "public-readback.json"),
    ship: path.join(evidenceDir, "ship.json"),
  };
  fs.writeFileSync(active.source, JSON.stringify(source));
  fs.writeFileSync(active.web, JSON.stringify(web));
  fs.writeFileSync(active.candidate, JSON.stringify(candidate));
  for (const filePath of [active.x64, active.arm64, active.live, active.ship]) {
    fs.writeFileSync(filePath, JSON.stringify({ candidate_id: candidate.candidate_id }));
  }
  const unrelated = path.join(evidenceDir, "keep-me.txt");
  fs.writeFileSync(unrelated, "unrelated");

  assert.throws(() => archiveSuccessfulRelease({ candidate, distRoot: dist, repoRoot: root }), /archive input is missing/);
  for (const filePath of Object.values(active).filter((filePath) => filePath !== active.public)) {
    assert.equal(fs.existsSync(filePath), true);
  }

  fs.writeFileSync(active.public, JSON.stringify({ candidate_id: candidate.candidate_id }));
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
    schema_version: 1,
    git: { commit: git(["rev-parse", "HEAD"]), branch: git(["branch", "--show-current"]), clean: true },
    release: { channel: "beta", version: "1.2.67" },
    inputs: { release_input: { kind: "file", ...fileRecord(input, root) } },
  };
  receipt.source_receipt_id = receiptId(receipt, "source_receipt_id");
  const receiptPath = path.join(root, "candidate-source.json");
  fs.writeFileSync(receiptPath, JSON.stringify(receipt));
  assert.equal(
    verifySourceReceipt({ receiptPath, repoRoot: root, channel: "beta", version: "1.2.67" }).source_receipt_id,
    receipt.source_receipt_id,
  );
  fs.writeFileSync(input, "tampered");
  assert.throws(
    () => verifySourceReceipt({ receiptPath, repoRoot: root, channel: "beta", version: "1.2.67" }),
    /checkout no longer matches clean source receipt/,
  );
});
