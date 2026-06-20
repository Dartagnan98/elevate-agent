const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const mainPath = path.resolve(__dirname, "../src/main.js");
const authPath = path.resolve(__dirname, "../src/desktop-auth.js");

function readMain() {
  return fs.readFileSync(mainPath, "utf8");
}

function readAuth() {
  return fs.readFileSync(authPath, "utf8");
}

test("desktop HQ auth requests include request-id headers and safe log breadcrumbs", () => {
  const main = readMain();
  const auth = readAuth();

  assert.match(main, /createDesktopAuth\(\{/);
  assert.match(auth, /const crypto = require\("crypto"\)/);
  assert.match(main, /function hqJsonRequestHeaders\(scope\)/);
  assert.match(auth, /`desktop-\$\{scope\}-\$\{crypto\.randomUUID\(\)\}`/);
  assert.match(auth, /"X-Request-Id": requestId/);
  assert.match(auth, /\[desktop:request\] request_id=\$\{requestId\} scope=\$\{scope\}/);
  assert.match(auth, /hqJsonRequestHeaders\("license-refresh"\)/);
  assert.match(auth, /hqJsonRequestHeaders\("auth-login"\)/);
  assert.match(auth, /\[license\] refresh failed request_id=\$\{requestId\}/);
  assert.match(auth, /\[auth\] login failed request_id=\$\{requestId\}/);
});
