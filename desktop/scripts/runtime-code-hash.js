"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const ALGORITHM = "elevate-runtime-code-tree-v1";
const CODESIGN = "/usr/bin/codesign";
const NORMALIZED_IDENTIFIER = "com.elevationrealestate.elevate.runtime-normalized";
const MACH_O_MAGICS = new Set([
  0xfeedface, 0xcefaedfe,
  0xfeedfacf, 0xcffaedfe,
  0xcafebabe, 0xbebafeca,
  0xcafebabf, 0xbfbafeca,
]);

function defaultCommandRunner(command, args, options = {}) {
  return spawnSync(command, args, {
    encoding: "utf8",
    timeout: 120_000,
    ...options,
  });
}

function commandOutput(result) {
  return `${result?.stdout || ""}\n${result?.stderr || ""}`.trim();
}

function requireCommand(result, label, { tolerateUnsigned = false } = {}) {
  if (result?.status === 0 && !result?.error) return;
  const output = commandOutput(result);
  if (tolerateUnsigned && /^[^\r\n]+: code object is not signed at all$/i.test(output)) return;
  const error = result?.error?.message || output || `exit ${result?.status ?? "unknown"}`;
  throw new Error(`[runtime-code-hash] ${label} failed: ${error}`);
}

function isMachOMagic(buffer) {
  return Buffer.isBuffer(buffer)
    && buffer.length >= 4
    && MACH_O_MAGICS.has(buffer.readUInt32BE(0));
}

function isMachOFile(filePath) {
  const fd = fs.openSync(filePath, "r");
  const buffer = Buffer.alloc(4);
  try {
    return fs.readSync(fd, buffer, 0, buffer.length, 0) === 4 && isMachOMagic(buffer);
  } finally {
    fs.closeSync(fd);
  }
}

function isExcludedRuntimePath(relativePath) {
  const parts = relativePath.split(path.sep);
  const name = parts.at(-1) || "";
  return name === ".DS_Store"
    || parts.includes("__pycache__")
    || /\.py[co]$/.test(name);
}

function streamFileIntoHash(filePath, hash) {
  const fd = fs.openSync(filePath, "r");
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  try {
    let bytes = 0;
    while ((bytes = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) {
      hash.update(buffer.subarray(0, bytes));
    }
  } finally {
    fs.closeSync(fd);
  }
}

function normalizeMachO(filePath, tempFile, runCommand) {
  fs.copyFileSync(filePath, tempFile);
  fs.chmodSync(tempFile, 0o600);
  requireCommand(
    runCommand(CODESIGN, ["--remove-signature", tempFile]),
    `removing the existing signature from ${path.basename(filePath)}`,
    { tolerateUnsigned: true },
  );
  requireCommand(
    runCommand(CODESIGN, [
      "--force", "--sign", "-", "--timestamp=none",
      "--identifier", NORMALIZED_IDENTIFIER, tempFile,
    ]),
    `normalizing ${path.basename(filePath)}`,
  );
  return tempFile;
}

function hashRuntimeCodeTree(root, {
  commandRunner = defaultCommandRunner,
  tempRoot = os.tmpdir(),
} = {}) {
  if (!root || !fs.existsSync(root) || !fs.statSync(root).isDirectory()) {
    throw new Error(`[runtime-code-hash] missing runtime tree: ${root || "<unset>"}`);
  }
  if (typeof commandRunner !== "function") {
    throw new TypeError("[runtime-code-hash] commandRunner must be a function");
  }
  fs.mkdirSync(tempRoot, { recursive: true });
  const tempDirectory = fs.mkdtempSync(path.join(tempRoot, "elevate-runtime-code-"));
  const hash = crypto.createHash("sha256");
  hash.update(`${ALGORITHM}\0`);
  let fileCount = 0;
  let totalSize = 0;
  let machOFileCount = 0;

  function walk(directory, relativeDirectory = "") {
    const entries = fs.readdirSync(directory, { withFileTypes: true })
      .sort((left, right) => left.name.localeCompare(right.name, "en"));
    for (const entry of entries) {
      const relative = relativeDirectory ? path.join(relativeDirectory, entry.name) : entry.name;
      if (isExcludedRuntimePath(relative)) continue;
      const absolute = path.join(directory, entry.name);
      const stat = fs.lstatSync(absolute);
      const permissions = (stat.mode & 0o777).toString(8).padStart(3, "0");
      if (stat.isSymbolicLink()) {
        hash.update(`l\0${relative}\0${permissions}\0${fs.readlinkSync(absolute)}\0`);
      } else if (stat.isDirectory()) {
        hash.update(`d\0${relative}\0${permissions}\0`);
        walk(absolute, relative);
      } else if (stat.isFile()) {
        let contentPath = absolute;
        let tempFile = null;
        if (isMachOFile(absolute)) {
          tempFile = path.join(tempDirectory, `macho-${machOFileCount}`);
          contentPath = normalizeMachO(absolute, tempFile, commandRunner);
          machOFileCount += 1;
        }
        try {
          const normalizedSize = fs.statSync(contentPath).size;
          hash.update(`f\0${relative}\0${permissions}\0${normalizedSize}\0`);
          streamFileIntoHash(contentPath, hash);
          hash.update("\0");
          fileCount += 1;
          totalSize += normalizedSize;
        } finally {
          if (tempFile) fs.rmSync(tempFile, { force: true });
        }
      } else {
        throw new Error(`[runtime-code-hash] unsupported runtime entry type: ${relative}`);
      }
    }
  }

  try {
    walk(path.resolve(root));
    return {
      algorithm: ALGORITHM,
      sha256: hash.digest("hex"),
      file_count: fileCount,
      size: totalSize,
      macho_file_count: machOFileCount,
    };
  } finally {
    fs.rmSync(tempDirectory, { recursive: true, force: true });
  }
}

module.exports = {
  ALGORITHM,
  MACH_O_MAGICS,
  NORMALIZED_IDENTIFIER,
  hashRuntimeCodeTree,
  isExcludedRuntimePath,
  isMachOFile,
  isMachOMagic,
};
