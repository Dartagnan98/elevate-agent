const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  SIGNED_HQ_BASE_URL,
  createDesktopAuth,
} = require("../src/desktop-auth");

const log = { info() {}, warn() {} };

function token(exp = Math.floor(Date.now() / 1000) + 3600) {
  const payload = Buffer.from(JSON.stringify({ exp })).toString("base64url");
  return `header.${payload}.signature`;
}

function response(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return payload;
    },
    async text() {
      return status === 200 ? "" : "upstream failure";
    },
  };
}

function profile() {
  const sandbox = fs.mkdtempSync(
    path.join(fs.realpathSync(os.tmpdir()), "elevate-desktop-auth-"),
  );
  const root = path.join(sandbox, ".elevate-beta");
  fs.mkdirSync(root, { mode: 0o700 });
  return {
    sandbox,
    root,
    licensePath: path.join(root, "license.json"),
    cleanup() {
      fs.chmodSync(root, 0o700);
      fs.rmSync(sandbox, { recursive: true, force: true });
    },
  };
}

function successfulPayload(entitlements = []) {
  return {
    access_token: token(),
    refresh_token: `refresh-${crypto.randomUUID()}`,
    license_id: "license-1",
    tier: "pro",
    entitlements,
  };
}

test("exact Beta desktop login and refresh ignore attacker backend and verify atomic snapshot", async () => {
  const state = profile();
  const calls = [];
  const initialPayload = successfulPayload();
  delete initialPayload.entitlements;
  initialPayload.packs = {
    realEstateSales: true,
    real_estate_admin: true,
    realEstateMarketing: false,
  };
  const payloads = [
    initialPayload,
    successfulPayload([]),
  ];
  try {
    const auth = createDesktopAuth({
      log,
      hqBaseUrl: "https://attacker.example.test",
      home: state.sandbox,
      isBeta: true,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async (url, options) => {
        calls.push({
          url,
          body: JSON.parse(options.body),
          redirect: options.redirect,
        });
        return response(payloads.shift());
      },
    });

    const login = await auth.performLogin({
      email: "Agent@Example.test",
      password: "secret-password",
    });
    assert.equal(login.ok, true);
    assert.equal(login.activation_complete, true);
    assert.deepEqual(login.license.entitlements, [
      "real_estate_sales",
      "real_estate_admin",
    ]);
    assert.equal(fs.statSync(state.licensePath).mode & 0o777, 0o600);
    assert.equal(fs.statSync(state.licensePath).nlink, 1);
    assert.deepEqual(auth.readLicense(), login.license);

    const refreshed = await auth.refreshLicense(login.license);
    assert.deepEqual(refreshed.entitlements, []);
    assert.deepEqual(auth.readLicense().entitlements, []);
    assert.deepEqual(
      calls.map((call) => call.url),
      [
        `${SIGNED_HQ_BASE_URL}/api/auth/login`,
        `${SIGNED_HQ_BASE_URL}/api/license/refresh`,
      ],
    );
    assert.ok(calls.every((call) => !call.url.includes("attacker.example.test")));
    assert.ok(calls.every((call) => call.redirect === "error"));
  } finally {
    state.cleanup();
  }
});

for (const storeKind of [
  "managed",
  "license-symlink",
  "broken-license-symlink",
  "profile-symlink",
  "hardlink",
  "public-file",
  "shared-root",
  "unwritable",
  "wrong-root",
]) {
  test(`exact Beta desktop rejects ${storeKind} profile before auth network`, async () => {
    const state = profile();
    const outside = path.join(state.sandbox, "outside-license.json");
    fs.writeFileSync(outside, "{}");
    try {
      if (storeKind === "managed") {
        fs.writeFileSync(path.join(state.root, ".managed"), "managed\n");
      } else if (storeKind === "license-symlink") {
        fs.symlinkSync(outside, state.licensePath);
      } else if (storeKind === "broken-license-symlink") {
        fs.symlinkSync(
          path.join(state.sandbox, "missing-license.json"),
          state.licensePath,
        );
      } else if (storeKind === "profile-symlink") {
        const outsideRoot = path.join(state.sandbox, "redirected-profile");
        fs.mkdirSync(outsideRoot);
        fs.rmdirSync(state.root);
        fs.symlinkSync(outsideRoot, state.root);
      } else if (storeKind === "hardlink") {
        fs.linkSync(outside, state.licensePath);
      } else if (storeKind === "public-file") {
        fs.writeFileSync(state.licensePath, "{}", { mode: 0o644 });
      } else if (storeKind === "shared-root") {
        fs.chmodSync(state.root, 0o770);
      } else if (storeKind === "unwritable") {
        fs.chmodSync(state.root, 0o500);
      }
      let networked = false;
      const auth = createDesktopAuth({
        log,
        hqBaseUrl: "https://attacker.example.test",
        home: storeKind === "wrong-root"
          ? path.join(state.sandbox, "different-home")
          : state.sandbox,
        isBeta: true,
        profileRoot: state.root,
        licensePath: state.licensePath,
        fetchImpl: async () => {
          networked = true;
          return response(successfulPayload());
        },
      });

      const result = await auth.performLogin({
        email: "agent@example.test",
        password: "secret-password",
      });

      assert.equal(result.ok, false);
      assert.equal(result.activation_complete, false);
      assert.match(result.code, /^beta_license_store_/);
      assert.equal(networked, false);
    } finally {
      state.cleanup();
    }
  });
}

test("exact Beta desktop rejects incomplete success response without persistence", async () => {
  const state = profile();
  try {
    fs.writeFileSync(
      state.licensePath,
      JSON.stringify({
        ...successfulPayload(["real_estate_sales"]),
        email: "agent@example.test",
        expires_at: Math.floor(Date.now() / 1000) + 3600,
      }),
      { mode: 0o600 },
    );
    const auth = createDesktopAuth({
      log,
      hqBaseUrl: "https://attacker.example.test",
      home: state.sandbox,
      isBeta: true,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async () => response({
        access_token: token(),
        refresh_token: "refresh",
        license_id: "license-1",
        tier: "pro",
      }),
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });

    assert.equal(result.ok, false);
    assert.equal(result.code, "beta_entitlement_snapshot_missing");
    assert.equal(fs.existsSync(state.licensePath), false);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop persistence mismatch invalidates stale grants and never reports success", async () => {
  const state = profile();
  try {
    let corruptNextRename = false;
    const fsImpl = Object.create(fs);
    fsImpl.renameSync = (source, target) => {
      fs.renameSync(source, target);
      if (corruptNextRename) {
        corruptNextRename = false;
        fs.writeFileSync(target, "{}");
      }
    };
    const first = createDesktopAuth({
      log,
      hqBaseUrl: SIGNED_HQ_BASE_URL,
      home: state.sandbox,
      isBeta: true,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async () => response(successfulPayload(["real_estate_sales"])),
      fsImpl,
    });
    const original = await first.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });
    assert.equal(original.ok, true);
    corruptNextRename = true;

    const result = await first.performLogin({
      email: "agent@example.test",
      password: "new-password",
    });

    assert.equal(result.ok, false);
    assert.equal(result.activation_complete, false);
    assert.match(result.code, /^beta_/);
    assert.equal(fs.existsSync(state.licensePath), false);
    assert.equal(first.readLicense(), null);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop revocation clears stale grants and throws typed", async () => {
  const state = profile();
  try {
    fs.writeFileSync(
      state.licensePath,
      JSON.stringify({
        ...successfulPayload(["real_estate_sales"]),
        email: "agent@example.test",
        expires_at: Math.floor(Date.now() / 1000) + 3600,
      }),
      { mode: 0o600 },
    );
    const auth = createDesktopAuth({
      log,
      hqBaseUrl: "https://attacker.example.test",
      home: state.sandbox,
      isBeta: true,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async () => response({}, 402),
    });

    await assert.rejects(
      auth.refreshLicense(auth.readLicense()),
      (err) => err && err.code === "beta_license_revoked",
    );
    assert.equal(fs.existsSync(state.licensePath), false);
    assert.equal(auth.readLicense(), null);
  } finally {
    state.cleanup();
  }
});

test("desktop main pins exact Beta HQ identity instead of mutable environment", () => {
  const source = fs.readFileSync(path.resolve(__dirname, "../src/main.js"), "utf8");
  assert.match(
    source,
    /RELEASE_PROFILE\.isBeta\s*\? SIGNED_HQ_BASE_URL\s*:\s*process\.env\.ELEVATE_BACKEND_URL \|\| SIGNED_HQ_BASE_URL/,
  );
});
