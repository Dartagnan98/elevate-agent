const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const mainPath = path.resolve(__dirname, "../src/main.js");
const overlayPath = path.resolve(__dirname, "../src/overlay.html");

function read(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

test("computer-use overlay window cannot steal focus or clicks", () => {
  const main = read(mainPath);
  const start = main.indexOf("function createOverlay()");
  const end = main.indexOf("function setOverlayVisible", start);
  const overlayBlock = main.slice(start, end);

  assert.match(overlayBlock, /focusable:\s*false/);
  assert.match(overlayBlock, /skipTaskbar:\s*true/);
  assert.match(overlayBlock, /acceptFirstMouse:\s*false/);
  assert.match(overlayBlock, /setIgnoreMouseEvents\(true,\s*\{\s*forward:\s*true\s*\}\)/);
  assert.match(overlayBlock, /setAlwaysOnTop\(true,\s*"screen-saver"\)/);
  assert.match(overlayBlock, /setVisibleOnAllWorkspaces\(true,\s*\{\s*visibleOnFullScreen:\s*true/);
});

test("computer-use overlay is shown inactive and only while flag is fresh", () => {
  const main = read(mainPath);

  assert.match(main, /const COMPUTER_USE_FLAG = path\.join\(HOME, "\.elevate", "computer-use-active"\)/);
  assert.match(main, /const COMPUTER_USE_FRESH_MS = 6000/);
  assert.match(main, /fresh = Date\.now\(\) - stat\.mtimeMs < COMPUTER_USE_FRESH_MS/);
  assert.match(main, /setOverlayVisible\(fresh\)/);
  assert.match(main, /overlayWindow\.showInactive\(\)/);
  assert.doesNotMatch(main, /overlayWindow\.show\(\)/);
});

test("overlay html is pointer-events none with visible computer-use label", () => {
  const html = read(overlayPath);

  assert.match(html, /pointer-events:\s*none/);
  assert.match(html, />Computer Use</);
  assert.match(html, /aria-hidden|id="badge"|id="glow"/);
});
