"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { signAsync } = require("@electron/osx-sign");

const MACH_O_MAGICS = new Set([
  "feedface", "feedfacf", "cefaedfe", "cffaedfe",
  "cafebabe", "bebafeca", "cafebabf", "bfbafeca",
]);

function isMachO(filePath) {
  const descriptor = fs.openSync(filePath, "r");
  try {
    const magic = Buffer.allocUnsafe(4);
    return fs.readSync(descriptor, magic, 0, magic.length, 0) === magic.length
      && MACH_O_MAGICS.has(magic.toString("hex"));
  } finally {
    fs.closeSync(descriptor);
  }
}

function isSignableCode(filePath) {
  if (fs.lstatSync(filePath).isSymbolicLink()) return false;
  const stat = fs.statSync(filePath);
  return stat.isDirectory() || (stat.isFile() && stat.size >= 4 && isMachO(filePath));
}

function commandOrThrow(command, args, message) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  if (result.status === 0) return;
  const detail = String(result.stderr || result.stdout || result.error?.message || "command failed").trim();
  throw new Error(`${message}${detail ? `: ${detail}` : ""}`);
}

function cleanSigningTarget(filePath) {
  if (fs.statSync(filePath).isDirectory()) {
    commandOrThrow("/usr/bin/xattr", ["-cr", filePath], `[mac-sign] failed to clean ${filePath}`);
    return;
  }

  const cleanPath = path.join(
    path.dirname(filePath),
    `.${path.basename(filePath)}.elevate-sign-clean-${process.pid}`,
  );
  try {
    commandOrThrow("/bin/cp", ["-pX", filePath, cleanPath], `[mac-sign] failed to clean ${filePath}`);
    fs.renameSync(cleanPath, filePath);
  } finally {
    fs.rmSync(cleanPath, { force: true });
  }
}

function matchesIgnore(ignore, filePath) {
  if (!ignore) return false;
  return (Array.isArray(ignore) ? ignore : [ignore]).some((entry) => (
    typeof entry === "function" ? entry(filePath) : Boolean(filePath.match(entry))
  ));
}

async function signMac(options) {
  const originalOptionsForFile = options.optionsForFile;
  const originalIgnore = options.ignore;
  return signAsync({
    ...options,
    ignore: (filePath) => matchesIgnore(originalIgnore, filePath) || !isSignableCode(filePath),
    optionsForFile: (filePath) => {
      cleanSigningTarget(filePath);
      return originalOptionsForFile ? originalOptionsForFile(filePath) : null;
    },
  });
}

module.exports = { cleanSigningTarget, default: signMac, isSignableCode };
