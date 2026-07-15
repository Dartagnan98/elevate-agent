const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  DEVICE_MARKER_NAME,
  LOCK_NAME,
  MARKER_NAME,
  RefreshPendingError,
  canonicalToken32,
  createRefreshPendingStore,
  initialAuthLicenseId,
  initialAuthPendingMatches,
  isInitialAuthPending,
  parseDevicePending,
} = require("../src/refresh-pending");

const FIXTURE = path.resolve(
  __dirname,
  "../../cli/tests/fixtures/beta-refresh-pending-v1.json",
);
const DEVICE_FIXTURE = path.resolve(
  __dirname,
  "../../cli/tests/fixtures/beta-device-pending-v1.json",
);
const A = "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE";
const DEVICE_VALUE = JSON.parse(fs.readFileSync(DEVICE_FIXTURE, "utf8"));
const DEVICE_TOKEN_KEYS = [
  "device_code",
  "initial_refresh_token",
  "recovery_refresh_token",
  "recovery_attempt_id",
];

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

function deviceWriteInput(value = DEVICE_VALUE) {
  return {
    deviceCode: value.device_code,
    initialRefreshToken: value.initial_refresh_token,
    recoveryRefreshToken: value.recovery_refresh_token,
    recoveryAttemptId: value.recovery_attempt_id,
    createdAt: value.created_at,
  };
}

function deeplyNestedDevicePayload() {
  const nested = `${"[".repeat(1100)}0${"]".repeat(1100)}`;
  const fixture = fs.readFileSync(DEVICE_FIXTURE, "utf8");
  return Buffer.from(fixture.replace(
    `"device_code":"${DEVICE_VALUE.device_code}"`,
    `"device_code":${nested}`,
  ));
}

test("Desktop Device marker has byte-exact shared fixture parity and exact CAS", async () => {
  const profile = root();
  try {
    const markerPath = path.join(profile, DEVICE_MARKER_NAME);
    fs.copyFileSync(DEVICE_FIXTURE, markerPath);
    fs.chmodSync(markerPath, 0o600);
    const store = createRefreshPendingStore({ root: profile });

    assert.deepEqual(parseDevicePending(fs.readFileSync(DEVICE_FIXTURE)), DEVICE_VALUE);
    assert.deepEqual(store.parseDevice(fs.readFileSync(DEVICE_FIXTURE)), DEVICE_VALUE);
    assert.deepEqual(store.readDevice(), DEVICE_VALUE);
    fs.unlinkSync(markerPath);

    await store.withLock(async (guard) => {
      guard.assertHeld();
      const pending = store.writeDevice(deviceWriteInput());
      assert.deepEqual(pending, DEVICE_VALUE);
      assert.deepEqual(fs.readFileSync(markerPath), fs.readFileSync(DEVICE_FIXTURE));
      assert.equal(fs.statSync(markerPath).mode & 0o777, 0o600);
      assert.equal(fs.statSync(markerPath).nlink, 1);

      assert.equal(store.removeDevice({
        ...pending,
        created_at: pending.created_at + 1,
      }), false);
      assert.deepEqual(fs.readFileSync(markerPath), fs.readFileSync(DEVICE_FIXTURE));
      assert.equal(store.removeDevice(pending), true);
      assert.equal(store.removeDevice(pending), false);
    });

    assert.equal(fs.existsSync(markerPath), false);
    assert.deepEqual(
      fs.readdirSync(profile).filter((name) => name.startsWith(".license-device-pending-")),
      [],
    );
    assert.equal(store.lockPath, path.join(profile, LOCK_NAME));
    assert.equal(fs.readFileSync(store.lockPath).length, 0);
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

test("Python and Desktop round-trip the same Device marker under the shared lock", async () => {
  const profile = root();
  const cliRoot = path.resolve(__dirname, "../../cli");
  const pythonEnv = { ...process.env, PYTHONPATH: cliRoot };
  const store = createRefreshPendingStore({ root: profile });
  try {
    await store.withLock(async () => store.writeDevice(deviceWriteInput()));
    const pythonRead = childProcess.spawnSync(
      "python3",
      [
        "-c",
        [
          "import sys",
          "from pathlib import Path",
          "from elevate_cli import refresh_pending as rp",
          "root = Path(sys.argv[1])",
          "with rp.refresh_lock(root):",
          "    pending = rp.read_device_pending(root)",
          "    sys.stdout.buffer.write(pending.to_bytes())",
        ].join("\n"),
        profile,
      ],
      { cwd: cliRoot, env: pythonEnv },
    );
    assert.equal(pythonRead.status, 0, pythonRead.stderr.toString("utf8"));
    assert.deepEqual(pythonRead.stdout, fs.readFileSync(DEVICE_FIXTURE));
    await store.withLock(async () => assert.equal(store.removeDevice(DEVICE_VALUE), true));

    const pythonWrite = childProcess.spawnSync(
      "python3",
      [
        "-c",
        [
          "import json, sys",
          "from pathlib import Path",
          "from elevate_cli import refresh_pending as rp",
          "root, fixture = Path(sys.argv[1]), Path(sys.argv[2])",
          "value = json.loads(fixture.read_text())",
          "with rp.refresh_lock(root):",
          "    rp.write_device_pending(root, device_code=value['device_code'],",
          "        initial_refresh_token=value['initial_refresh_token'],",
          "        recovery_refresh_token=value['recovery_refresh_token'],",
          "        recovery_attempt_id=value['recovery_attempt_id'],",
          "        created_at=value['created_at'])",
        ].join("\n"),
        profile,
        DEVICE_FIXTURE,
      ],
      { cwd: cliRoot, env: pythonEnv },
    );
    assert.equal(pythonWrite.status, 0, pythonWrite.stderr.toString("utf8"));
    await store.withLock(async () => {
      assert.deepEqual(store.readDevice(), DEVICE_VALUE);
      assert.equal(store.removeDevice(DEVICE_VALUE), true);
    });
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

test("Python and Desktop share kind-scoped initial-auth marker identity", async () => {
  const profile = root();
  const cliRoot = path.resolve(__dirname, "../../cli");
  const pythonEnv = { ...process.env, PYTHONPATH: cliRoot };
  const store = createRefreshPendingStore({ root: profile });
  const markerPath = path.join(profile, MARKER_NAME);
  try {
    let desktopLogin = null;
    await store.withLock(async (guard) => {
      guard.assertHeld();
      desktopLogin = store.createInitialAuth({
        email: " Agent@Example.Test ",
        authKind: "login",
        createdAt: 1784080000,
      });
    });
    assert.match(desktopLogin.license_id, /^initial-auth-v1:login:[0-9a-f]{64}$/);
    assert.equal(initialAuthPendingMatches(
      desktopLogin,
      "agent@example.test",
      { authKind: "login" },
    ), true);
    assert.equal(initialAuthPendingMatches(
      desktopLogin,
      "agent@example.test",
      { authKind: "signup" },
    ), false);

    const pythonRead = childProcess.spawnSync(
      "python3",
      [
        "-c",
        [
          "import sys",
          "from pathlib import Path",
          "from elevate_cli import refresh_pending as rp",
          "root = Path(sys.argv[1])",
          "with rp.refresh_lock(root):",
          "    pending = rp.read_pending(root)",
          "    assert rp.is_initial_auth_pending(pending)",
          "    assert rp.initial_auth_pending_matches(pending, 'AGENT@example.test', auth_kind='login')",
          "    assert not rp.initial_auth_pending_matches(pending, 'agent@example.test', auth_kind='signup')",
          "    sys.stdout.buffer.write(pending.to_bytes())",
        ].join("\n"),
        profile,
      ],
      { cwd: cliRoot, env: pythonEnv },
    );
    assert.equal(pythonRead.status, 0, pythonRead.stderr.toString("utf8"));
    assert.deepEqual(pythonRead.stdout, fs.readFileSync(markerPath));
    await store.withLock(async () => assert.equal(store.remove(), true));

    const pythonWrite = childProcess.spawnSync(
      "python3",
      [
        "-c",
        [
          "import sys",
          "from pathlib import Path",
          "from elevate_cli import refresh_pending as rp",
          "root = Path(sys.argv[1])",
          "with rp.refresh_lock(root):",
          "    rp.create_initial_auth_pending(root, email='Agent@Example.Test', auth_kind='signup', created_at=1784080001)",
        ].join("\n"),
        profile,
      ],
      { cwd: cliRoot, env: pythonEnv },
    );
    assert.equal(pythonWrite.status, 0, pythonWrite.stderr.toString("utf8"));
    await store.withLock(async (guard) => {
      guard.assertHeld();
      const pythonSignup = store.read();
      assert.equal(isInitialAuthPending(pythonSignup), true);
      assert.equal(
        pythonSignup.license_id,
        initialAuthLicenseId(" agent@example.test ", { authKind: "signup" }),
      );
      assert.equal(initialAuthPendingMatches(
        pythonSignup,
        "agent@example.test",
        { authKind: "signup" },
      ), true);
      assert.equal(initialAuthPendingMatches(
        pythonSignup,
        "agent@example.test",
        { authKind: "login" },
      ), false);
      assert.equal(store.remove(), true);
    });
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

for (const [field, invalid] of [
  ["schema", 2],
  ["schema", true],
  ["operation", "refresh"],
  ["created_at", true],
  ["created_at", -1],
  ["created_at", 1.5],
  ["created_at", Number.MAX_SAFE_INTEGER + 1],
]) {
  test(`Desktop Device parser rejects invalid ${field} value ${String(invalid)}`, () => {
    assert.throws(
      () => parseDevicePending(Buffer.from(JSON.stringify({
        ...DEVICE_VALUE,
        [field]: invalid,
      }))),
      (error) =>
        error instanceof RefreshPendingError &&
        error.code === "beta_device_state_corrupt",
    );
  });
}

for (const [field, original] of [["schema", "1"], ["created_at", "1784080000"]]) {
  test(`Desktop Device parser rejects non-integer JSON spelling for ${field}`, () => {
    const fixture = fs.readFileSync(DEVICE_FIXTURE, "utf8");
    const payload = fixture.replace(`"${field}":${original}`, `"${field}":${original}.0`);
    assert.throws(() => parseDevicePending(Buffer.from(payload)), RefreshPendingError);
  });
}

for (const [original, replacement] of [
  ['"schema":1', '"schema":1e0'],
  ['"schema":1', '"schema":01'],
  ['"created_at":1784080000', '"created_at":-0'],
  ['"created_at":1784080000', '"created_at":1784080000e0'],
  ['"created_at":1784080000', '"created_at":01784080000'],
]) {
  test(`Desktop Device parser rejects wire spelling ${replacement}`, () => {
    const fixture = fs.readFileSync(DEVICE_FIXTURE, "utf8");
    const payload = fixture.replace(original, replacement);
    assert.notEqual(payload, fixture);
    assert.throws(
      () => parseDevicePending(Buffer.from(payload)),
      (error) =>
        error instanceof RefreshPendingError &&
        error.code === "beta_device_state_corrupt",
    );
  });
}

test("Desktop refresh parser keeps legacy negative-zero behavior", () => {
  const profile = root();
  try {
    const fixture = fs.readFileSync(FIXTURE, "utf8");
    const payload = fixture.replace('"created_at":1784080000', '"created_at":-0');
    const markerPath = path.join(profile, MARKER_NAME);
    fs.writeFileSync(markerPath, payload, { mode: 0o600 });
    const store = createRefreshPendingStore({ root: profile });

    assert.equal(Object.is(store.read().created_at, -0), true);
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

test("Desktop deep Device bytes fail typed in parser and filesystem", () => {
  const payload = deeplyNestedDevicePayload();
  assert.equal(payload.length <= 16 * 1024, true);
  assert.throws(
    () => parseDevicePending(payload),
    (error) =>
      error instanceof RefreshPendingError &&
      error.code === "beta_device_state_corrupt",
  );

  const profile = root();
  try {
    const markerPath = path.join(profile, DEVICE_MARKER_NAME);
    fs.writeFileSync(markerPath, payload, { mode: 0o600 });
    const store = createRefreshPendingStore({ root: profile });
    assert.throws(
      () => store.readDevice(),
      (error) =>
        error instanceof RefreshPendingError &&
        error.code === "beta_device_state_corrupt",
    );
    assert.deepEqual(fs.readFileSync(markerPath), payload);
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

test("Desktop refresh deep nesting also fails typed corrupt", () => {
  const nested = `${"[".repeat(1100)}0${"]".repeat(1100)}`;
  const fixture = fs.readFileSync(FIXTURE, "utf8");
  const payload = fixture.replace(
    '"license_id":"license-fixture"',
    `"license_id":${nested}`,
  );
  const profile = root();
  try {
    const markerPath = path.join(profile, MARKER_NAME);
    fs.writeFileSync(markerPath, payload, { mode: 0o600 });
    const store = createRefreshPendingStore({ root: profile });
    assert.throws(
      () => store.read(),
      (error) =>
        error instanceof RefreshPendingError &&
        error.code === "beta_refresh_state_corrupt",
    );
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

for (const field of DEVICE_TOKEN_KEYS) {
  test(`Desktop Device parser rejects noncanonical ${field}`, () => {
    assert.throws(
      () => parseDevicePending(Buffer.from(JSON.stringify({
        ...DEVICE_VALUE,
        [field]: `${DEVICE_VALUE[field]}=`,
      }))),
      RefreshPendingError,
    );
  });
}

for (let left = 0; left < DEVICE_TOKEN_KEYS.length; left += 1) {
  for (let right = left + 1; right < DEVICE_TOKEN_KEYS.length; right += 1) {
    const leftKey = DEVICE_TOKEN_KEYS[left];
    const rightKey = DEVICE_TOKEN_KEYS[right];
    test(`Desktop Device parser rejects equal ${leftKey}/${rightKey}`, () => {
      assert.throws(
        () => parseDevicePending(Buffer.from(JSON.stringify({
          ...DEVICE_VALUE,
          [rightKey]: DEVICE_VALUE[leftKey],
        }))),
        RefreshPendingError,
      );
    });
  }
}

for (const field of Object.keys(DEVICE_VALUE)) {
  test(`Desktop Device parser rejects duplicate ${field}`, () => {
    const fixture = fs.readFileSync(DEVICE_FIXTURE, "utf8").trim();
    const duplicate = `${fixture.slice(0, -1)},${JSON.stringify(field)}:${
      JSON.stringify(DEVICE_VALUE[field])
    }}`;
    assert.throws(
      () => parseDevicePending(Buffer.from(duplicate)),
      RefreshPendingError,
    );
  });
}

for (const [label, payload] of [
  ["missing field", Buffer.from(JSON.stringify((() => {
    const value = { ...DEVICE_VALUE };
    delete value.device_code;
    return value;
  })()))],
  ["extra field", Buffer.from(JSON.stringify({ ...DEVICE_VALUE, future: true }))],
  ["array root", Buffer.from("[]")],
  ["invalid UTF-8", Buffer.from([0x7b, 0x22, 0x78, 0x22, 0x3a, 0x22, 0xff])],
  ["oversize payload", Buffer.alloc(16 * 1024 + 1, 0x20)],
]) {
  test(`Desktop Device parser rejects ${label}`, () => {
    assert.throws(
      () => parseDevicePending(payload),
      (error) =>
        error instanceof RefreshPendingError &&
        error.code === "beta_device_state_corrupt",
    );
  });
}

for (const attack of ["symlink", "hardlink", "public", "directory"]) {
  test(`Desktop Device marker rejects ${attack} filesystem attack`, () => {
    const profile = root();
    const target = path.join(profile, DEVICE_MARKER_NAME);
    const outside = path.join(path.dirname(profile), `${path.basename(profile)}-device-outside`);
    try {
      fs.copyFileSync(DEVICE_FIXTURE, outside);
      fs.chmodSync(outside, 0o600);
      if (attack === "symlink") fs.symlinkSync(outside, target);
      if (attack === "hardlink") fs.linkSync(outside, target);
      if (attack === "public") {
        fs.copyFileSync(outside, target);
        fs.chmodSync(target, 0o644);
      }
      if (attack === "directory") fs.mkdirSync(target, { mode: 0o700 });
      const store = createRefreshPendingStore({ root: profile });

      assert.throws(
        () => store.readDevice(),
        (error) =>
          error instanceof RefreshPendingError &&
          error.code === "beta_device_state_unsafe",
      );
      assert.equal(fs.existsSync(target), true);
    } finally {
      fs.rmSync(profile, { recursive: true, force: true });
      fs.rmSync(outside, { force: true });
    }
  });
}

for (const [markerName, reader, expectedCode] of [
  [MARKER_NAME, "read", "beta_refresh_state_unsafe"],
  [DEVICE_MARKER_NAME, "readDevice", "beta_device_state_unsafe"],
]) {
  test(`Desktop ${reader} rejects FIFO without blocking`, (t) => {
    if (process.platform === "win32") {
      t.skip("FIFO marker regression is POSIX-only");
      return;
    }
    const profile = root();
    const markerPath = path.join(profile, markerName);
    try {
      const created = childProcess.spawnSync("/usr/bin/mkfifo", [markerPath]);
      assert.equal(created.status, 0, created.stderr.toString("utf8"));
      fs.chmodSync(markerPath, 0o600);
      const modulePath = path.resolve(__dirname, "../src/refresh-pending.js");
      const script = [
        "const { createRefreshPendingStore } = require(process.env.TEST_MODULE);",
        "const store = createRefreshPendingStore({ root: process.env.TEST_ROOT });",
        "try {",
        "  store[process.env.TEST_READER]();",
        "} catch (error) {",
        "  process.stdout.write(String(error.code || 'untyped'));",
        "  process.exit(0);",
        "}",
        "process.exit(3);",
      ].join("\n");
      const result = childProcess.spawnSync(process.execPath, ["-e", script], {
        encoding: "utf8",
        timeout: 2_000,
        env: {
          ...process.env,
          TEST_MODULE: modulePath,
          TEST_READER: reader,
          TEST_ROOT: profile,
        },
      });

      assert.equal(result.error, undefined, result.error && result.error.message);
      assert.equal(result.status, 0, result.stderr);
      assert.equal(result.stdout, expectedCode);
      assert.equal(fs.lstatSync(markerPath).isFIFO(), true);
      fs.unlinkSync(markerPath);
      assert.equal(fs.existsSync(markerPath), false);
    } finally {
      fs.rmSync(profile, { recursive: true, force: true });
    }
  });
}

test("Desktop Device marker rejects wrong owner and retains marker", () => {
  const profile = root();
  try {
    const markerPath = path.join(profile, DEVICE_MARKER_NAME);
    fs.copyFileSync(DEVICE_FIXTURE, markerPath);
    fs.chmodSync(markerPath, 0o600);
    const store = createRefreshPendingStore({
      root: profile,
      processImpl: { getuid: () => process.getuid() + 1 },
    });
    assert.throws(
      () => store.readDevice(),
      (error) =>
        error instanceof RefreshPendingError &&
        error.code === "beta_device_state_unsafe",
    );
    assert.deepEqual(fs.readFileSync(markerPath), fs.readFileSync(DEVICE_FIXTURE));
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

test("Desktop Device marker rejects oversized file and retains it", () => {
  const profile = root();
  try {
    const markerPath = path.join(profile, DEVICE_MARKER_NAME);
    const bytes = Buffer.alloc(16 * 1024 + 1, 0x20);
    fs.writeFileSync(markerPath, bytes, { mode: 0o600 });
    const store = createRefreshPendingStore({ root: profile });
    assert.throws(
      () => store.readDevice(),
      (error) =>
        error instanceof RefreshPendingError &&
        error.code === "beta_device_state_corrupt",
    );
    assert.deepEqual(fs.readFileSync(markerPath), bytes);
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

test("Desktop Device CAS never removes duplicate-key or invalid-UTF-8 state", () => {
  const fixture = fs.readFileSync(DEVICE_FIXTURE, "utf8").trim();
  const payloads = [
    Buffer.from(`${fixture.slice(0, -1)},"schema":1}`),
    Buffer.from([0x7b, 0x22, 0x78, 0x22, 0x3a, 0x22, 0xff]),
  ];
  for (const payload of payloads) {
    const profile = root();
    try {
      const markerPath = path.join(profile, DEVICE_MARKER_NAME);
      fs.writeFileSync(markerPath, payload, { mode: 0o600 });
      const store = createRefreshPendingStore({ root: profile });
      assert.throws(
        () => store.removeDevice(DEVICE_VALUE),
        (error) =>
          error instanceof RefreshPendingError &&
          error.code === "beta_device_state_corrupt",
      );
      assert.deepEqual(fs.readFileSync(markerPath), payload);
    } finally {
      fs.rmSync(profile, { recursive: true, force: true });
    }
  }
});

test("Desktop refresh and Device marker writes conflict in both directions", async () => {
  const deviceProfile = root();
  const refreshProfile = root();
  try {
    const deviceStore = createRefreshPendingStore({ root: deviceProfile });
    await deviceStore.withLock(async () => {
      deviceStore.writeDevice(deviceWriteInput());
      assert.throws(
        () => deviceStore.create({ licenseId: "license-fixture", currentRefreshToken: A }),
        (error) =>
          error instanceof RefreshPendingError &&
          error.code === "beta_refresh_state_conflict",
      );
    });

    const refreshStore = createRefreshPendingStore({ root: refreshProfile });
    await refreshStore.withLock(async () => {
      refreshStore.create({ licenseId: "license-fixture", currentRefreshToken: A });
      assert.throws(
        () => refreshStore.writeDevice(deviceWriteInput()),
        (error) =>
          error instanceof RefreshPendingError &&
          error.code === "beta_device_state_conflict",
      );
    });
  } finally {
    fs.rmSync(deviceProfile, { recursive: true, force: true });
    fs.rmSync(refreshProfile, { recursive: true, force: true });
  }
});

test("Desktop Device marker completes partial writes", async () => {
  const profile = root();
  const shortFs = Object.create(fs);
  let writes = 0;
  shortFs.writeSync = (fd, bytes, offset, length) => {
    writes += 1;
    return fs.writeSync(fd, bytes, offset, Math.max(1, Math.floor(length / 2)));
  };
  try {
    const store = createRefreshPendingStore({ root: profile, fsImpl: shortFs });
    await store.withLock(async () => store.writeDevice(deviceWriteInput()));
    assert.equal(writes > 1, true);
    assert.deepEqual(
      fs.readFileSync(store.deviceMarkerPath),
      fs.readFileSync(DEVICE_FIXTURE),
    );
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

test("Desktop Device post-publish fsync failure retains exact marker", async () => {
  const profile = root();
  const lockPath = path.join(profile, LOCK_NAME);
  fs.writeFileSync(lockPath, "", { mode: 0o600 });
  const failingFs = Object.create(fs);
  failingFs.fsyncSync = (fd) => {
    if (fs.fstatSync(fd).isDirectory()) {
      throw new Error("injected directory fsync failure");
    }
    fs.fsyncSync(fd);
  };
  try {
    const store = createRefreshPendingStore({ root: profile, fsImpl: failingFs });
    await store.withLock(async () => {
      assert.throws(
        () => store.writeDevice(deviceWriteInput()),
        (error) =>
          error instanceof RefreshPendingError &&
          error.code === "beta_device_persistence_failed",
      );
    });
    assert.deepEqual(
      fs.readFileSync(store.deviceMarkerPath),
      fs.readFileSync(DEVICE_FIXTURE),
    );
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

test("Desktop Device readback failure retains exact marker", async () => {
  const profile = root();
  const failingFs = Object.create(fs);
  let markerReads = 0;
  failingFs.readFileSync = (target, ...args) => {
    if (typeof target === "number") {
      markerReads += 1;
      if (markerReads === 1) throw new Error("injected readback failure");
    }
    return fs.readFileSync(target, ...args);
  };
  try {
    const store = createRefreshPendingStore({ root: profile, fsImpl: failingFs });
    await store.withLock(async () => {
      assert.throws(
        () => store.writeDevice(deviceWriteInput()),
        (error) =>
          error instanceof RefreshPendingError &&
          error.code === "beta_device_state_unsafe",
      );
    });
    assert.deepEqual(
      fs.readFileSync(store.deviceMarkerPath),
      fs.readFileSync(DEVICE_FIXTURE),
    );
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
  }
});

test("Desktop Device CAS revalidates the open inode before unlink", () => {
  const profile = root();
  const marker = path.join(profile, DEVICE_MARKER_NAME);
  const backup = path.join(profile, "authenticated-device-marker");
  const outside = path.join(path.dirname(profile), `${path.basename(profile)}-device-swap`);
  try {
    fs.copyFileSync(DEVICE_FIXTURE, marker);
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
      () => store.removeDevice(DEVICE_VALUE),
      (error) =>
        error instanceof RefreshPendingError &&
        error.code === "beta_device_state_unsafe",
    );
    assert.equal(markerChecks, 2);
    assert.equal(fs.lstatSync(marker).isSymbolicLink(), true);
    assert.deepEqual(fs.readFileSync(backup), fs.readFileSync(DEVICE_FIXTURE));
    assert.equal(fs.readFileSync(outside, "utf8"), "outside-must-survive");
  } finally {
    fs.rmSync(profile, { recursive: true, force: true });
    fs.rmSync(outside, { force: true });
  }
});
