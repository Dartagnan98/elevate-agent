"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const test = require("node:test");

const {
  hashRuntimeCodeTree,
  isMachOMagic,
} = require("../scripts/runtime-code-hash");

function fixtureRoot(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-runtime-code-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function sha256File(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function requireRun(command, args) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  assert.equal(result.status, 0, `${command} ${args.join(" ")}\n${result.stderr || result.stdout}`);
  return result;
}

test("Mach-O magic detection covers thin and fat byte orders", () => {
  for (const hex of ["feedface", "cefaedfe", "feedfacf", "cffaedfe", "cafebabe", "bebafeca", "cafebabf", "bfbafeca"]) {
    assert.equal(isMachOMagic(Buffer.from(hex, "hex")), true, hex);
  }
  assert.equal(isMachOMagic(Buffer.from("7f454c46", "hex")), false);
  assert.equal(isMachOMagic(Buffer.alloc(3)), false);
});

test("raw files, tree metadata, and runtime exclusions are hashed deterministically", (t) => {
  const root = fixtureRoot(t);
  fs.mkdirSync(path.join(root, "nested"));
  fs.mkdirSync(path.join(root, "__pycache__"));
  fs.writeFileSync(path.join(root, "nested", "payload.txt"), "approved");
  fs.writeFileSync(path.join(root, "ignored.pyc"), "ignored");
  fs.writeFileSync(path.join(root, "__pycache__", "ignored.txt"), "ignored");
  fs.symlinkSync("nested/payload.txt", path.join(root, "payload-link"));
  const first = hashRuntimeCodeTree(root);
  const second = hashRuntimeCodeTree(root);
  assert.deepEqual(second, first);
  assert.equal(first.file_count, 1);
  assert.equal(first.macho_file_count, 0);
  fs.writeFileSync(path.join(root, "nested", "payload.txt"), "altered!");
  assert.notEqual(hashRuntimeCodeTree(root).sha256, first.sha256);
});

test("normalization failures are closed and temporary copies are removed", (t) => {
  const root = fixtureRoot(t);
  const tempRoot = path.join(root, "temp");
  const runtime = path.join(root, "runtime");
  fs.mkdirSync(runtime);
  fs.writeFileSync(path.join(runtime, "fake-macho"), Buffer.concat([
    Buffer.from("feedfacf", "hex"),
    Buffer.from("not really a Mach-O"),
  ]));
  const original = sha256File(path.join(runtime, "fake-macho"));
  assert.throws(
    () => hashRuntimeCodeTree(runtime, {
      tempRoot,
      commandRunner: () => ({ status: 2, stderr: "unexpected codesign failure" }),
    }),
    /removing the existing signature.*unexpected codesign failure/,
  );
  assert.equal(sha256File(path.join(runtime, "fake-macho")), original);
  assert.deepEqual(fs.readdirSync(tempRoot), []);
});

test("only the explicit unsigned response is tolerated before deterministic signing", (t) => {
  const root = fixtureRoot(t);
  const runtime = path.join(root, "runtime");
  fs.mkdirSync(runtime);
  fs.writeFileSync(path.join(runtime, "fake-macho"), Buffer.concat([
    Buffer.from("feedfacf", "hex"), Buffer.from("fixture"),
  ]));
  const calls = [];
  const result = hashRuntimeCodeTree(runtime, {
    tempRoot: path.join(root, "temp"),
    commandRunner: (_command, args) => {
      calls.push(args.slice());
      const tempFile = args.at(-1);
      if (args[0] === "--remove-signature") {
        return { status: 1, stderr: `${tempFile}: code object is not signed at all` };
      }
      fs.writeFileSync(tempFile, Buffer.concat([Buffer.from("feedfacf", "hex"), Buffer.from("normalized")]));
      return { status: 0 };
    },
  });
  assert.equal(result.macho_file_count, 1);
  assert.equal(calls.length, 2);
  assert.ok(calls[1].includes("--timestamp=none"));

  assert.throws(
    () => hashRuntimeCodeTree(runtime, {
      tempRoot: path.join(root, "rejected-temp"),
      commandRunner: () => ({
        status: 1,
        stderr: "unexpected failure: code object is not signed at all\nadditional diagnostic",
      }),
    }),
    /unexpected failure.*additional diagnostic/s,
  );
});

test("real Mach-O binaries with different signatures normalize equally and code changes do not", (t) => {
  if (process.platform !== "darwin") return t.skip("macOS only");
  const root = fixtureRoot(t);
  const source = path.join(root, "fixture.c");
  const changedSource = path.join(root, "changed.c");
  const first = path.join(root, "first");
  const second = path.join(root, "second");
  const changed = path.join(root, "changed");
  for (const directory of [first, second, changed]) fs.mkdirSync(directory);
  fs.writeFileSync(source, "int main(void) { return 0; }\n");
  fs.writeFileSync(changedSource, "int main(void) { return 7; }\n");
  requireRun("xcrun", ["clang", source, "-o", path.join(first, "fixture")]);
  fs.copyFileSync(path.join(first, "fixture"), path.join(second, "fixture"));
  requireRun("xcrun", ["clang", changedSource, "-o", path.join(changed, "fixture")]);
  requireRun("codesign", ["--force", "--sign", "-", "--timestamp=none", "--identifier", "fixture.one", path.join(first, "fixture")]);
  requireRun("codesign", ["--force", "--sign", "-", "--timestamp=none", "--options", "runtime", "--identifier", "fixture.two", path.join(second, "fixture")]);
  requireRun("codesign", ["--force", "--sign", "-", "--timestamp=none", "--identifier", "fixture.changed", path.join(changed, "fixture")]);
  assert.notEqual(sha256File(path.join(first, "fixture")), sha256File(path.join(second, "fixture")));
  const firstHash = hashRuntimeCodeTree(first);
  const secondHash = hashRuntimeCodeTree(second);
  const changedHash = hashRuntimeCodeTree(changed);
  assert.equal(firstHash.sha256, secondHash.sha256);
  assert.equal(firstHash.macho_file_count, 1);
  assert.notEqual(changedHash.sha256, firstHash.sha256);
});
