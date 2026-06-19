const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { pathToFileURL } = require("node:url");

const { isTrustedNavigationUrl } = require("../src/navigation-guard");

const appRoot = path.join(__dirname, "..", "src");
const backendUrl = "http://127.0.0.1:9119";

test("navigation guard allows dashboard and app-owned files", () => {
  assert.equal(isTrustedNavigationUrl(`${backendUrl}/chat`, { backendUrl, appRoot }), true);
  assert.equal(isTrustedNavigationUrl("http://127.0.0.1:91190/chat", { backendUrl, appRoot }), false);
  assert.equal(
    isTrustedNavigationUrl(pathToFileURL(path.join(appRoot, "install.html")).href, {
      backendUrl,
      appRoot,
    }),
    true,
  );
});

test("navigation guard blocks arbitrary file and external schemes", () => {
  assert.equal(
    isTrustedNavigationUrl(pathToFileURL(path.join(__dirname, "outside.html")).href, {
      backendUrl,
      appRoot,
    }),
    false,
  );
  assert.equal(isTrustedNavigationUrl("file:///etc/passwd", { backendUrl, appRoot }), false);
  assert.equal(isTrustedNavigationUrl("https://example.com", { backendUrl, appRoot }), false);
  assert.equal(isTrustedNavigationUrl("mailto:test@example.com", { backendUrl, appRoot }), false);
});
