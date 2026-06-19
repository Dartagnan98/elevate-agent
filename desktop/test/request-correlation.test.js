const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const mainPath = path.resolve(__dirname, "../src/main.js");

function readMain() {
  return fs.readFileSync(mainPath, "utf8");
}

test("desktop HQ auth requests include request-id headers and safe log breadcrumbs", () => {
  const main = readMain();

  assert.match(main, /const crypto = require\("crypto"\)/);
  assert.match(main, /function hqJsonRequestHeaders\(scope\)/);
  assert.match(main, /`desktop-\$\{scope\}-\$\{crypto\.randomUUID\(\)\}`/);
  assert.match(main, /"X-Request-Id": requestId/);
  assert.match(main, /\[desktop:request\] request_id=\$\{requestId\} scope=\$\{scope\}/);
  assert.match(main, /hqJsonRequestHeaders\("license-refresh"\)/);
  assert.match(main, /hqJsonRequestHeaders\("auth-login"\)/);
  assert.match(main, /\[license\] refresh failed request_id=\$\{requestId\}/);
  assert.match(main, /\[auth\] login failed request_id=\$\{requestId\}/);
});
