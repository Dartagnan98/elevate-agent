const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const test = require("node:test");

const { default: afterPackMac, releaseArchitecture } = require("../scripts/after-pack-mac");

test("after-pack maps electron-builder numeric architecture enums", () => {
  assert.equal(releaseArchitecture(1), "x64");
  assert.equal(releaseArchitecture(3), "arm64");
  assert.equal(releaseArchitecture("x64"), "x64");
});

test("after-pack hook clears extended attributes before Apple signing", async (t) => {
  if (process.platform !== "darwin") return t.skip("macOS only");

  const previousSourceReceiptId = process.env.ELEVATE_SOURCE_RECEIPT_ID;
  delete process.env.ELEVATE_SOURCE_RECEIPT_ID;
  t.after(() => {
    if (previousSourceReceiptId === undefined) delete process.env.ELEVATE_SOURCE_RECEIPT_ID;
    else process.env.ELEVATE_SOURCE_RECEIPT_ID = previousSourceReceiptId;
  });

  const root = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-after-pack-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const fixture = path.join(root, "fixture");
  fs.writeFileSync(fixture, "signed payload");

  const write = spawnSync("/usr/bin/xattr", ["-w", "com.elevate.test", "present", fixture]);
  assert.equal(write.status, 0);

  await afterPackMac({ electronPlatformName: "darwin", appOutDir: root });

  const read = spawnSync("/usr/bin/xattr", ["-p", "com.elevate.test", fixture]);
  assert.notEqual(read.status, 0);
});
