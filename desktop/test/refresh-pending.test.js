const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  LOCK_NAME,
  MARKER_NAME,
  RefreshPendingError,
  canonicalToken32,
  createRefreshPendingStore,
} = require("../src/refresh-pending");

const FIXTURE = path.resolve(
  __dirname,
  "../../cli/tests/fixtures/beta-refresh-pending-v1.json",
);
const A = "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE";

function root() {
  const value = fs.mkdtempSync(
    path.join(fs.realpathSync(os.tmpdir()), "elevate-refresh-pending-"),
  );
  fs.chmodSync(value, 0o700);
  return value;
}

test("Desktop reads the shared schema and writes private canonical state", async () => {
  const profile = root();
  try {
    const markerPath = path.join(profile, MARKER_NAME);
    fs.copyFileSync(FIXTURE, markerPath);
    fs.chmodSync(markerPath, 0o600);
    const store = createRefreshPendingStore({ root: profile });
    assert.deepEqual(store.read(), JSON.parse(fs.readFileSync(FIXTURE, "utf8")));
    fs.unlinkSync(markerPath);

    await store.withLock(async (guard) => {
      guard.assertHeld();
      const pending = store.create({
        licenseId: "license-fixture",
        currentRefreshToken: A,
        createdAt: 1784080000,
      });
      assert.equal(canonicalToken32(pending.successor_refresh_token), true);
      assert.equal(canonicalToken32(pending.attempt_id), true);
      assert.equal(fs.statSync(markerPath).mode & 0o777, 0o600);
      assert.equal(fs.statSync(markerPath).nlink, 1);
      store.remove();
    });
    assert.equal(fs.readFileSync(path.join(profile, LOCK_NAME)).length, 0);
    assert.equal(fs.statSync(path.join(profile, LOCK_NAME)).mode & 0o777, 0o600);
    assert.equal(fs.existsSync(markerPath), false);
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

test("Desktop inherited-fd lock excludes Python flock on the same inode", async (t) => {
  if (process.platform !== "darwin") {
    t.skip("Desktop lockf contract is a macOS runtime boundary");
    return;
  }
  const profile = root();
  try {
    const store = createRefreshPendingStore({ root: profile });
    await store.withLock(async (guard) => {
      guard.assertHeld();
      const script = [
        "import fcntl, os, sys",
        "fd = os.open(sys.argv[1], os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))",
        "try:",
        "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)",
        "except BlockingIOError:",
        "    raise SystemExit(23)",
        "raise SystemExit(0)",
      ].join("\n");
      const result = childProcess.spawnSync("python3", ["-c", script, store.lockPath]);
      assert.equal(result.status, 23);
    });
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

test("Python flock excludes Desktop lockf with documented EX_TEMPFAIL", async (t) => {
  if (process.platform !== "darwin") {
    t.skip("Desktop lockf contract is a macOS runtime boundary");
    return;
  }
  const profile = root();
  let holder = null;
  let lockFd = null;
  try {
    const lockPath = path.join(profile, LOCK_NAME);
    fs.writeFileSync(lockPath, "", { mode: 0o600 });
    const script = [
      "import fcntl, os, sys",
      "fd = os.open(sys.argv[1], os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))",
      "fcntl.flock(fd, fcntl.LOCK_EX)",
      "opened = os.fstat(fd)",
      "print(f'{opened.st_dev}:{opened.st_ino}', flush=True)",
      "sys.stdin.buffer.read()",
    ].join("\n");
    holder = childProcess.spawn("python3", ["-c", script, lockPath], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    const heldInode = await new Promise((resolve, reject) => {
      let output = "";
      holder.stdout.on("data", (chunk) => {
        output += chunk.toString("utf8");
        const newline = output.indexOf("\n");
        if (newline !== -1) resolve(output.slice(0, newline));
      });
      holder.once("error", reject);
      holder.once("exit", (code) => {
        reject(new Error(`Python lock holder exited before readiness: ${code}`));
      });
    });

    lockFd = fs.openSync(
      lockPath,
      fs.constants.O_RDWR | (fs.constants.O_NOFOLLOW || 0),
    );
    const opened = fs.fstatSync(lockFd);
    assert.equal(`${opened.dev}:${opened.ino}`, heldInode);
    const attempt = childProcess.spawnSync(
      "/usr/bin/lockf",
      ["-k", "-t", "0", "/dev/fd/3", "/bin/true"],
      { stdio: ["ignore", "pipe", "pipe", lockFd] },
    );
    assert.equal(attempt.status, 75);
  } finally {
    if (lockFd !== null) fs.closeSync(lockFd);
    if (holder && holder.exitCode === null && holder.signalCode === null) {
      holder.stdin.end();
      await new Promise((resolve) => {
        const timer = setTimeout(() => {
          holder.kill("SIGTERM");
          resolve();
        }, 2_000);
        holder.once("exit", () => {
          clearTimeout(timer);
          resolve();
        });
      });
    }
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

for (const artifact of ["lock", "marker"]) {
  for (const attack of ["symlink", "hardlink", "public"]) {
    test(`Desktop rejects ${attack} ${artifact} artifact`, async () => {
      const profile = root();
      const target = path.join(profile, artifact === "lock" ? LOCK_NAME : MARKER_NAME);
      const outside = path.join(path.dirname(profile), `${path.basename(profile)}-outside`);
      try {
        fs.writeFileSync(
          outside,
          artifact === "lock" ? "" : fs.readFileSync(FIXTURE),
          { mode: 0o600 },
        );
        if (attack === "symlink") fs.symlinkSync(outside, target);
        if (attack === "hardlink") fs.linkSync(outside, target);
        if (attack === "public") {
          fs.copyFileSync(outside, target);
          fs.chmodSync(target, 0o644);
        }
        const store = createRefreshPendingStore({ root: profile, lockTimeoutMs: 100 });
        await assert.rejects(
          artifact === "lock" ? store.withLock(async () => {}) : async () => store.read(),
          (error) => error instanceof RefreshPendingError,
        );
      } finally {
        fs.rmSync(profile, { recursive: true, force: true });
        fs.rmSync(outside, { force: true });
      }
    });
  }
}

test("Desktop rejects duplicate keys and invalid UTF-8 without deleting marker", () => {
  for (const payload of [
    Buffer.from('{"schema":1,"schema":1,"operation":"refresh"}'),
    Buffer.from([0x7b, 0x22, 0x78, 0x22, 0x3a, 0x22, 0xff, 0x22, 0x7d]),
  ]) {
    const profile = root();
    try {
      const marker = path.join(profile, MARKER_NAME);
      fs.writeFileSync(marker, payload, { mode: 0o600 });
      const store = createRefreshPendingStore({ root: profile });
      assert.throws(() => store.read(), RefreshPendingError);
      assert.equal(fs.existsSync(marker), true);
    } finally {
      fs.rmSync(profile, { recursive: true, force: true });
    }
  }
});

test("Desktop remove revalidates the open marker inode before unlink", () => {
  const profile = root();
  const marker = path.join(profile, MARKER_NAME);
  const backup = path.join(profile, "authenticated-marker");
  const outside = path.join(path.dirname(profile), `${path.basename(profile)}-outside-swap`);
  try {
    fs.copyFileSync(FIXTURE, marker);
    fs.chmodSync(marker, 0o600);
    fs.writeFileSync(outside, "outside-must-survive", { mode: 0o600 });
    const swappingFs = Object.create(fs);
    let markerChecks = 0;
    swappingFs.lstatSync = (target) => {
      if (target === marker) {
        markerChecks += 1;
        if (markerChecks === 2) {
          fs.renameSync(marker, backup);
          fs.symlinkSync(outside, marker);
        }
      }
      return fs.lstatSync(target);
    };
    const store = createRefreshPendingStore({ root: profile, fsImpl: swappingFs });

    assert.throws(
      () => store.remove(),
      (error) =>
        error instanceof RefreshPendingError &&
        error.code === "beta_refresh_state_unsafe",
    );

    assert.equal(markerChecks, 2);
    assert.equal(fs.lstatSync(marker).isSymbolicLink(), true);
    assert.deepEqual(fs.readFileSync(backup), fs.readFileSync(FIXTURE));
    assert.equal(fs.readFileSync(outside, "utf8"), "outside-must-survive");
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
    fs.rmSync(outside, { force: true });
  }
});

test("Desktop duplicate scanner ignores escaped key-like text in a value", () => {
  const profile = root();
  try {
    const value = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));
    value.license_id = 'value with \\"schema\\": text';
    const marker = path.join(profile, MARKER_NAME);
    fs.writeFileSync(marker, JSON.stringify(value), { mode: 0o600 });
    const store = createRefreshPendingStore({ root: profile });
    assert.equal(store.read().license_id, value.license_id);
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

test("Desktop rejects invalid createdAt before publishing", async () => {
  for (const createdAt of [-1, 1.5, Number.NaN, Number.MAX_SAFE_INTEGER + 1]) {
    const profile = root();
    try {
      const store = createRefreshPendingStore({ root: profile });
      await store.withLock(async () => {
        assert.throws(
          () => store.create({
            licenseId: "license-fixture",
            currentRefreshToken: A,
            createdAt,
          }),
          RefreshPendingError,
        );
      });
      assert.equal(fs.existsSync(store.markerPath), false);
    } finally {
      fs.rmSync(profile, { recursive: true, force: true });
    }
  }
});

test("Desktop rejects lock and marker owned by a different uid", async () => {
  const profile = root();
  try {
    fs.writeFileSync(path.join(profile, LOCK_NAME), "", { mode: 0o600 });
    fs.copyFileSync(FIXTURE, path.join(profile, MARKER_NAME));
    fs.chmodSync(path.join(profile, MARKER_NAME), 0o600);
    const processImpl = { getuid: () => process.getuid() + 1 };
    const store = createRefreshPendingStore({ root: profile, processImpl });
    await assert.rejects(store.withLock(async () => {}), RefreshPendingError);
    assert.throws(() => store.read(), RefreshPendingError);
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

test("Desktop marker publish and removal fsync file and directory", async () => {
  const profile = root();
  const fsynced = [];
  const auditedFs = Object.create(fs);
  auditedFs.fsyncSync = (fd) => {
    fsynced.push(fs.fstatSync(fd).isDirectory() ? "directory" : "file");
    fs.fsyncSync(fd);
  };
  try {
    const store = createRefreshPendingStore({ root: profile, fsImpl: auditedFs });
    await store.withLock(async () => {
      store.create({ licenseId: "license-fixture", currentRefreshToken: A });
      store.remove();
    });
    assert.equal(fsynced.includes("file"), true);
    assert.equal(fsynced.filter((kind) => kind === "directory").length >= 3, true);
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});
