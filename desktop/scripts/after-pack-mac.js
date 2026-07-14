const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { Arch } = require("builder-util");
const {
  ARCHITECTURES,
  assertCanonicalPackagedPermissions,
  createPreSignEvidence,
  normalizeArchitecture,
  preSignEvidencePath,
  verifyPreSignEvidence,
  verifySourceReceipt,
  verifyWebBuildReceipt,
} = require("./candidate-receipt");

function packedAppPath(appOutDir) {
  const apps = fs.readdirSync(appOutDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.endsWith(".app"))
    .map((entry) => path.join(appOutDir, entry.name));
  if (apps.length !== 1) {
    throw new Error(`[after-pack] expected exactly one app bundle in ${appOutDir}; found ${apps.length}`);
  }
  return apps[0];
}

function releaseArchitecture(value) {
  return normalizeArchitecture(typeof value === "number" ? Arch[value] : value);
}

exports.releaseArchitecture = releaseArchitecture;

exports.default = async function afterPackMac(context) {
  if (context.electronPlatformName !== "darwin") return;

  const result = spawnSync("/usr/bin/xattr", ["-cr", context.appOutDir], {
    encoding: "utf8",
  });
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim();
    throw new Error(`[after-pack] failed to clear macOS extended attributes${detail ? `: ${detail}` : ""}`);
  }
  console.log(`[after-pack] cleared macOS extended attributes from ${context.appOutDir}`);

  const sourceReceiptId = String(process.env.ELEVATE_SOURCE_RECEIPT_ID || "").trim();
  if (!sourceReceiptId) {
    console.log("[after-pack] no source receipt ID; skipped release-only pre-sign evidence");
    return;
  }
  const architecture = releaseArchitecture(context.arch);
  if (!ARCHITECTURES.includes(architecture)) {
    throw new Error(`[after-pack] unsupported release architecture: ${context.arch}`);
  }
  const distRoot = path.dirname(context.appOutDir);
  const desktopRoot = path.dirname(distRoot);
  const repoRoot = path.dirname(desktopRoot);
  const source = verifySourceReceipt({
    receiptPath: path.join(distRoot, "candidate-source.json"),
    repoRoot,
    desktopRoot,
  });
  if (source.source_receipt_id !== sourceReceiptId) {
    throw new Error(`[after-pack] ${architecture} source receipt does not match the build environment`);
  }
  const webBuild = verifyWebBuildReceipt({
    receiptPath: path.join(distRoot, "candidate-web.json"),
    sourceReceiptId,
    repoRoot,
  });
  const appPath = packedAppPath(context.appOutDir);
  const expectedBundleName = source.release?.profile?.appBundleName;
  if (!expectedBundleName || path.basename(appPath) !== expectedBundleName) {
    throw new Error(
      `[after-pack] ${architecture} app bundle identity mismatch: `
      + `${path.basename(appPath)} (expected ${expectedBundleName || "<unset>"})`,
    );
  }
  assertCanonicalPackagedPermissions(
    path.join(appPath, "Contents", "Resources", "cli"),
    `${architecture} packaged CLI`,
  );
  const evidencePath = preSignEvidencePath(distRoot, architecture);
  createPreSignEvidence({
    appPath,
    architecture,
    sourceReceiptId,
    webBuildId: webBuild.web_build_id,
    outputPath: evidencePath,
  });
  const evidence = verifyPreSignEvidence({
    evidencePath,
    architecture,
    source,
    webBuild,
    appBundleName: expectedBundleName,
  });
  console.log(`[after-pack] verified ${architecture} pre-sign contract ${evidence.pre_sign_evidence_id}`);
};
