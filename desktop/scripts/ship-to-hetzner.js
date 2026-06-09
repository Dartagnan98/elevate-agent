#!/usr/bin/env node
// Push electron-builder artifacts to the Hetzner ctrl-flow box so
// electron-updater (generic provider) can pull them from
// https://api.elevationrealestatehq.com/updates/
//
// Flow:
//   1. `npm run release:mac` builds + invokes this script
//   2. We rsync the relevant files from ./dist into /var/www/elevate-updates/
//   3. Done. Running apps poll the feed every 2hr (or on next launch).
//
// Requirements:
//   - SSH key auth set up for root@5.78.46.234
//   - rsync installed locally (default on macOS)

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const yaml = require("js-yaml");

const DIST = path.resolve(__dirname, "..", "dist");
const FEED = path.join(DIST, "latest-mac.yml");
const HOST = "root@5.78.46.234";
const REMOTE = "/var/www/elevate-updates/";

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
const PKG_VERSION = require(path.resolve(__dirname, "..", "package.json")).version;
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

console.log("\n[ship] live at https://api.elevationrealestatehq.com/updates/");
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
