const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const mainPath = path.resolve(__dirname, "../src/main.js");
const overlayManagerPath = path.resolve(__dirname, "../src/computer-use-overlay.js");
const overlayPath = path.resolve(__dirname, "../src/overlay.html");

function read(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

test("computer-use overlay window cannot steal focus or clicks", () => {
  const overlayBlock = read(overlayManagerPath);

  assert.match(overlayBlock, /focusable:\s*false/);
  assert.match(overlayBlock, /skipTaskbar:\s*true/);
  assert.match(overlayBlock, /acceptFirstMouse:\s*false/);
  assert.match(overlayBlock, /setIgnoreMouseEvents\(true,\s*\{\s*forward:\s*true\s*\}\)/);
  assert.match(overlayBlock, /setAlwaysOnTop\(true,\s*"screen-saver"\)/);
  assert.match(overlayBlock, /setVisibleOnAllWorkspaces\(true,\s*\{\s*visibleOnFullScreen:\s*true/);
});

test("computer-use overlay is shown inactive and only while flag is fresh", () => {
  const main = read(mainPath);
  const overlay = read(overlayManagerPath);

  assert.match(main, /const COMPUTER_USE_FLAG = path\.join\(HOME, "\.elevate", "computer-use-active"\)/);
  assert.match(main, /const COMPUTER_USE_FRESH_MS = 6000/);
  assert.match(overlay, /fresh = Date\.now\(\) - stat\.mtimeMs < freshMs/);
  assert.match(overlay, /setOverlayVisible\(fresh\)/);
  assert.match(overlay, /if \(visible\) \{\s*createOverlay\(\);\s*}/s);
  assert.match(overlay, /overlayWindow\.showInactive\(\)/);
  assert.match(overlay, /overlayWindow\.destroy\(\);\s*overlayWindow = null;/s);
  assert.doesNotMatch(overlay, /overlayWindow\.show\(\)/);
});

test("computer-use overlay renderer is not created while idle", () => {
  const main = read(mainPath);
  const start = main.indexOf("async function startDesktop()");
  const end = main.indexOf('loadLocalPage("loading.html")', start);
  const startupBlock = main.slice(start, end);

  assert.match(startupBlock, /startOverlayWatcher\(\)/);
  assert.doesNotMatch(startupBlock, /createOverlay\(\)/);
});

test("overlay html is pointer-events none with visible computer-use label", () => {
  const html = read(overlayPath);

  assert.match(html, /pointer-events:\s*none/);
  assert.match(html, />Computer Use</);
  assert.match(html, /aria-hidden|id="badge"|id="glow"/);
});
