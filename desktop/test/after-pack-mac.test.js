const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const test = require("node:test");

const afterPackMac = require("../scripts/after-pack-mac").default;

test("after-pack hook clears extended attributes before Apple signing", async (t) => {
  if (process.platform !== "darwin") return t.skip("macOS only");

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
