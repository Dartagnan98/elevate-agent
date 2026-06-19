#!/usr/bin/env node
// Push electron-builder artifacts to the Hetzner ctrl-flow box so
// electron-updater (generic provider) can pull them from
// https://api.elevationrealestatehq.com/updates/
//
// Flow:
//   1. `npm run release:mac` builds + invokes this script
//   2. We rsync the relevant files from ./dist into /var/www/elevate-updates/
//   3. Verify the public feed/artifacts before declaring the release live.
//   4. Running apps poll the feed every ~3min (and on window focus).
//
// Requirements:
//   - SSH key auth set up for root@5.78.46.234
//   - rsync installed locally (default on macOS)

const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");
const yaml = require("js-yaml");

const DIST = path.resolve(__dirname, "..", "dist");
const FEED = path.join(DIST, "latest-mac.yml");
const PKG_VERSION = require(path.resolve(__dirname, "..", "package.json")).version;
const HOST = "root@5.78.46.234";
const REMOTE = "/var/www/elevate-updates/";
const PUBLIC_URL = "https://api.elevationrealestatehq.com/updates";

function curl(args, label) {
  const result = spawnSync(
    "curl",
    ["--fail", "--silent", "--show-error", "--location", "--retry", "5", "--retry-delay", "2", ...args],
    { encoding: "utf8" },
  );
  if (result.status !== 0) {
    const error = (result.stderr || result.stdout || "").trim();
    throw new Error(`${label} failed${error ? `: ${error}` : ""}`);
  }
  return result.stdout || "";
}

function contentLength(headers) {
  const match = String(headers || "").match(/^content-length:\s*(\d+)/im);
  return match ? Number(match[1]) : null;
}

function verifyRemoteFile(name, expectedSize) {
  const headers = curl(["--head", `${PUBLIC_URL}/${name}`], `verify ${name}`);
  const actualSize = contentLength(headers);
  if (expectedSize && actualSize !== expectedSize) {
    throw new Error(`[ship] public ${name} size ${actualSize || "missing"} != ${expectedSize}`);
  }
}

function verifyPublicRelease(feed, expectedVersion) {
  console.log("[ship] verifying public feed and artifacts");
  const remoteText = curl([`${PUBLIC_URL}/latest-mac.yml`], "fetch public latest-mac.yml");
  const remoteFeed = yaml.load(remoteText);
  if (remoteFeed.version !== expectedVersion) {
    throw new Error(`[ship] public feed version ${remoteFeed.version || "missing"} != ${expectedVersion}`);
  }

  const localFiles = feed.files || [];
  const remoteFiles = new Map((remoteFeed.files || []).map((file) => [file.url, file]));
  for (const file of localFiles) {
    if (!file.url) continue;
    const remoteFile = remoteFiles.get(file.url);
    if (!remoteFile) throw new Error(`[ship] public feed is missing ${file.url}`);
    if (remoteFile.sha512 !== file.sha512) {
      throw new Error(`[ship] public feed sha512 mismatch for ${file.url}`);
    }
    if (Number(remoteFile.size || 0) !== Number(file.size || 0)) {
      throw new Error(`[ship] public feed size mismatch for ${file.url}`);
    }
    verifyRemoteFile(file.url, Number(file.size || 0));
  }

  for (const arch of ["arm64", "x64"]) {
    const src = `Elevate-${expectedVersion}-mac-${arch}.dmg`;
    const alias = `Elevate-latest-mac-${arch}.dmg`;
    const localDmg = path.join(DIST, src);
    if (fs.existsSync(localDmg)) {
      verifyRemoteFile(alias, fs.statSync(localDmg).size);
    }
  }
  console.log(`[ship] verified public ${expectedVersion} feed and artifacts`);
}

function hashFile(filePath) {
  return crypto.createHash("sha512").update(fs.readFileSync(filePath)).digest("base64");
}

function verifyLocalRelease(feed, expectedVersion) {
  if (feed.version !== expectedVersion) {
    throw new Error(`[ship] local feed version ${feed.version || "missing"} != ${expectedVersion}`);
  }
  const files = new Map((feed.files || []).map((file) => [file.url, file]));
  for (const name of [
    `Elevate-${expectedVersion}-mac-x64.zip`,
    `Elevate-${expectedVersion}-mac-arm64.zip`,
    `Elevate-${expectedVersion}-mac-x64.dmg`,
    `Elevate-${expectedVersion}-mac-arm64.dmg`,
  ]) {
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

if (!fs.existsSync(DIST)) {
  console.error(`[ship] no dist/ folder at ${DIST} — did the build run?`);
  process.exit(1);
}

if (!fs.existsSync(FEED)) {
  console.error(`[ship] no latest-mac.yml at ${FEED} — did the build run?`);
  process.exit(1);
}

// electron-builder emits latest-mac.yml (the feed file electron-updater polls).
// Ship exactly the files referenced by the feed, plus matching blockmaps when
// present, so stale artifacts in dist/ never leak into the update directory.
const feed = yaml.load(fs.readFileSync(FEED, "utf8"));
try {
  verifyLocalRelease(feed, PKG_VERSION);
} catch (err) {
  console.error(err && err.message ? err.message : String(err));
  process.exit(1);
}

const selected = new Set(["latest-mac.yml"]);
for (const file of feed.files || []) {
  selected.add(file.url);
  // Intentionally DO NOT ship zip blockmaps. Blockmaps are what enable
  // differential updates, and differential reconstruction off a locally-mutated
  // install is exactly what corrupts the new bundle's signature ("a sealed
  // resource is missing or invalid" → ShipIt aborts → customer stuck).
  // The app now sets autoUpdater.disableDifferentialDownload = true, but OLD
  // installs predating that flag will still attempt a differential. With no
  // blockmap on the server, their differential lookup 404s and they fall back
  // to a full-zip download — pristine + notarized — which installs cleanly and
  // lands them on a build that has the flag. That is how every stuck client
  // self-recovers with no manual reinstall. Keep blockmaps off the server.
}

// Fresh-download DMGs: electron-updater never uses these (auto-update is the zip),
// but they're the first-time MANUAL download. The feed only listed zips, so the
// public .dmg used to go stale every release. Ship this version's DMGs too, and
// refresh stable "latest" aliases (below) so the download link is permanent.
for (const name of fs.readdirSync(DIST)) {
  if (name.endsWith(".dmg") && name.includes(`-${PKG_VERSION}-`)) selected.add(name);
}

const matches = Array.from(selected).filter((name) => fs.existsSync(path.join(DIST, name)));

if (matches.length === 0) {
  console.error(`[ship] no matching artifacts in ${DIST}`);
  process.exit(1);
}

console.log(`[ship] uploading ${matches.length} files to ${HOST}:${REMOTE}`);
for (const name of matches) {
  const size = (fs.statSync(path.join(DIST, name)).size / (1024 * 1024)).toFixed(1);
  console.log(`  - ${name} (${size} MB)`);
}

// rsync with progress, preserve mtime so cache headers are sensible.
const args = [
  "-avh",
  "--progress",
  ...matches.map((name) => path.join(DIST, name)),
  `${HOST}:${REMOTE}`,
];

const result = spawnSync("rsync", args, { stdio: "inherit" });

if (result.status !== 0) {
  console.error(`[ship] rsync failed with exit ${result.status}`);
  process.exit(result.status || 1);
}

// Fix ownership on the remote so nginx (www-data) can read.
const chown = spawnSync(
  "ssh",
  [HOST, `chown www-data:www-data ${REMOTE}* && ls -lh ${REMOTE}`],
  { stdio: "inherit" },
);

if (chown.status !== 0) {
  console.error("[ship] chown failed — may need to fix permissions manually");
}

// Purge any zip blockmaps already on the server. While a blockmap for the
// current feed version exists, old (pre-flag) clients keep attempting the
// differential path that corrupts the signature. Removing them forces the
// full-zip fallback so stuck clients recover on their next poll.
const dropBlockmaps = spawnSync(
  "ssh",
  [HOST, `rm -f ${REMOTE}*.zip.blockmap && echo "[remote] blockmaps purged"`],
  { stdio: "inherit" },
);
if (dropBlockmaps.status !== 0) {
  console.error("[ship] blockmap purge failed — remove them manually so old clients fall back to full download");
  process.exit(dropBlockmaps.status || 1);
}

// Refresh the stable "latest" fresh-download aliases so a single permanent URL
// always serves the newest DMG — e.g. https://api.elevationrealestatehq.com/
// updates/Elevate-latest-mac-arm64.dmg — so the public download link never needs
// a per-release change again.
for (const arch of ["arm64", "x64"]) {
  const src = `Elevate-${PKG_VERSION}-mac-${arch}.dmg`;
  if (!fs.existsSync(path.join(DIST, src))) continue;
  const dst = `Elevate-latest-mac-${arch}.dmg`;
  const alias = spawnSync(
    "ssh",
    [HOST, `cp -f ${REMOTE}${src} ${REMOTE}${dst} && chown www-data:www-data ${REMOTE}${dst}`],
    { stdio: "inherit" },
  );
  if (alias.status === 0) console.log(`[ship] fresh-download alias ${dst} -> ${src}`);
  else console.error(`[ship] failed to refresh alias ${dst}`);
}

// Prune old build artifacts on the remote — keep last 3 versioned builds.
// Script lives at /root/prune-elevate-updates.sh on ctrl-flow.
const prune = spawnSync("ssh", [HOST, "bash /root/prune-elevate-updates.sh"], { stdio: "inherit" });
if (prune.status !== 0) console.warn("[ship] artifact prune exited non-zero — disk may be growing");

try {
  verifyPublicRelease(feed, PKG_VERSION);
} catch (err) {
  console.error(err && err.message ? err.message : String(err));
  process.exit(1);
}

console.log(`\n[ship] live at ${PUBLIC_URL}/`);
console.log("[ship] running apps poll every ~3min (and on window focus), so it lands within minutes.");

// Cleanup: electron-builder leaves unpacked .app bundles in dist/mac and
// dist/mac-arm64. macOS Spotlight indexes those as standalone "Elevate" apps,
// which then clutter the launcher as ghost duplicates of the real install.
// The shippable artifacts (zip/dmg/yml) are already on Hetzner, so drop the
// unpacked bundles after every successful ship. Keep the dmg/zip as a local
// release archive.
for (const sub of ["mac", "mac-arm64"]) {
  const dir = path.join(DIST, sub);
  if (fs.existsSync(dir)) {
    fs.rmSync(dir, { recursive: true, force: true });
    console.log(`[ship] cleaned unpacked bundle dist/${sub}/ (no Spotlight ghost)`);
  }
}
