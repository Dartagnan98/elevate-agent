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
const {
  ENTITLEMENT_ASSERTION,
  tokenHash,
} = require("../src/entitlement-assertion");

const log = { info() {}, warn() {} };
const entitlementKeys = crypto.generateKeyPairSync("ed25519");
const entitlementKeyset = {
  [ENTITLEMENT_ASSERTION.keyId]: entitlementKeys.publicKey,
};

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

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
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
  const now = Math.floor(Date.now() / 1000);
  const accessToken = token(now + 3600);
  const refreshToken = `refresh-${crypto.randomUUID()}`;
  const payload = {
    access_token: accessToken,
    refresh_token: refreshToken,
    email: "agent@example.test",
    license_id: "license-1",
    tier: "pro",
    entitlements: [...new Set(entitlements)].sort(),
  };
  const header = Buffer.from(JSON.stringify({
    alg: ENTITLEMENT_ASSERTION.algorithm,
    typ: ENTITLEMENT_ASSERTION.type,
    kid: ENTITLEMENT_ASSERTION.keyId,
  })).toString("base64url");
  const claims = Buffer.from(JSON.stringify({
    iss: ENTITLEMENT_ASSERTION.issuer,
    aud: ENTITLEMENT_ASSERTION.audience,
    schema: ENTITLEMENT_ASSERTION.schema,
    sub: "user-1",
    license_id: payload.license_id,
    email: payload.email,
    tier: payload.tier,
    entitlements: payload.entitlements,
    iat: now,
    nbf: now,
    exp: now + 3600,
    jti: crypto.randomUUID(),
    ath: tokenHash(accessToken),
    rth: tokenHash(refreshToken),
  })).toString("base64url");
  const input = `${header}.${claims}`;
  payload.entitlement_assertion = `${input}.${crypto
    .sign(null, Buffer.from(input, "ascii"), entitlementKeys.privateKey)
    .toString("base64url")}`;
  payload.expires_at = now + 3600;
  return payload;
}

test("exact Beta desktop login and refresh ignore attacker backend and verify atomic snapshot", async () => {
  const state = profile();
  const calls = [];
  const initialPayload = successfulPayload([
    "real_estate_admin",
    "real_estate_sales",
  ]);
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
      entitlementKeyset,
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
      "real_estate_admin",
      "real_estate_sales",
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
        entitlementKeyset,
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

test("exact Beta desktop rejects incomplete success without replacing its prior session", async () => {
  const state = profile();
  try {
    const prior = successfulPayload(["real_estate_sales"]);
    fs.writeFileSync(state.licensePath, JSON.stringify(prior), { mode: 0o600 });
    const auth = createDesktopAuth({
      log,
      hqBaseUrl: "https://attacker.example.test",
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
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
    assert.equal(result.code, "beta_entitlement_assertion_invalid");
    assert.deepEqual(auth.readLicense(), {
      ...prior,
      expires_at: JSON.parse(
        Buffer.from(prior.entitlement_assertion.split(".")[1], "base64url").toString("utf8"),
      ).exp,
    });
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
      entitlementKeyset,
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
      JSON.stringify(successfulPayload(["real_estate_sales"])),
      { mode: 0o600 },
    );
    const auth = createDesktopAuth({
      log,
      hqBaseUrl: "https://attacker.example.test",
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
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

test("exact Beta desktop rejects unsigned and locally forged entitlement snapshots", () => {
  const state = profile();
  try {
    const auth = createDesktopAuth({
      log,
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
      profileRoot: state.root,
      licensePath: state.licensePath,
    });
    const unsigned = successfulPayload(["real_estate_sales"]);
    delete unsigned.entitlement_assertion;
    fs.writeFileSync(state.licensePath, JSON.stringify(unsigned), { mode: 0o600 });
    assert.equal(auth.readLicense(), null);

    const forged = successfulPayload(["real_estate_sales"]);
    forged.entitlements = ["real_estate_admin", "real_estate_sales"];
    forged.expires_at += 86400;
    fs.writeFileSync(state.licensePath, JSON.stringify(forged), { mode: 0o600 });
    assert.equal(auth.readLicense(), null);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop rejects signed-response duplicate drift before success", async () => {
  const state = profile();
  try {
    const payload = successfulPayload(["real_estate_sales"]);
    payload.email = "attacker@example.test";
    const auth = createDesktopAuth({
      log,
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async () => response(payload),
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });

    assert.equal(result.ok, false);
    assert.equal(result.activation_complete, false);
    assert.equal(result.code, "beta_entitlement_assertion_mismatch");
    assert.equal(auth.readLicense(), null);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop single-flights concurrent refreshes", async () => {
  const state = profile();
  const pending = deferred();
  let calls = 0;
  try {
    const initial = successfulPayload(["real_estate_sales"]);
    fs.writeFileSync(state.licensePath, JSON.stringify(initial), { mode: 0o600 });
    const auth = createDesktopAuth({
      log,
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async () => {
        calls += 1;
        return pending.promise;
      },
    });
    const current = auth.readLicense();

    const first = auth.refreshLicense(current);
    const second = auth.refreshLicense(current);
    assert.equal(first, second);
    assert.equal(calls, 1);

    pending.resolve(response(successfulPayload([])));
    const [one, two] = await Promise.all([first, second]);
    assert.deepEqual(one, two);
    assert.deepEqual(one.entitlements, []);
    assert.equal(calls, 1);
  } finally {
    state.cleanup();
  }
});

test("stale Beta refresh rejection cannot clear a newer valid snapshot", async () => {
  const state = profile();
  const pending = deferred();
  try {
    const initial = successfulPayload(["real_estate_sales"]);
    fs.writeFileSync(state.licensePath, JSON.stringify(initial), { mode: 0o600 });
    const auth = createDesktopAuth({
      log,
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async () => pending.promise,
    });

    const refresh = auth.refreshLicense(auth.readLicense());
    const newer = auth.writeLicense(successfulPayload(["real_estate_admin"]));
    pending.resolve(response({}, 401));

    const result = await refresh;
    assert.equal(result.refresh_token, newer.refresh_token);
    assert.deepEqual(result.entitlements, ["real_estate_admin"]);
    assert.deepEqual(auth.readLicense(), newer);
  } finally {
    state.cleanup();
  }
});

test("stale Beta refresh cannot resurrect a snapshot cleared by another process", async () => {
  const state = profile();
  const pending = deferred();
  try {
    const initial = successfulPayload(["real_estate_sales"]);
    fs.writeFileSync(state.licensePath, JSON.stringify(initial), { mode: 0o600 });
    const auth = createDesktopAuth({
      log,
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async () => pending.promise,
    });

    const refresh = auth.refreshLicense(auth.readLicense());
    fs.unlinkSync(state.licensePath);
    pending.resolve(response(successfulPayload(["real_estate_admin"])));

    assert.equal(await refresh, null);
    assert.equal(fs.existsSync(state.licensePath), false);
  } finally {
    state.cleanup();
  }
});

test("newer explicit Beta login supersedes an older background refresh", async () => {
  const state = profile();
  const refreshResponse = deferred();
  const loginResponse = deferred();
  try {
    const initial = successfulPayload(["real_estate_sales"]);
    const refreshed = successfulPayload(["real_estate_marketing"]);
    const signedIn = successfulPayload(["real_estate_admin"]);
    fs.writeFileSync(state.licensePath, JSON.stringify(initial), { mode: 0o600 });
    const auth = createDesktopAuth({
      log,
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async (url) => (
        url.endsWith("/api/license/refresh")
          ? refreshResponse.promise
          : loginResponse.promise
      ),
    });

    const refresh = auth.refreshLicense(auth.readLicense());
    const login = auth.performLogin({
      email: "agent@example.test",
      password: "new-password",
    });
    refreshResponse.resolve(response(refreshed));

    const discardedRefresh = await refresh;
    assert.equal(discardedRefresh.refresh_token, initial.refresh_token);
    assert.equal(auth.readLicense().refresh_token, initial.refresh_token);

    loginResponse.resolve(response(signedIn));
    const loginResult = await login;
    assert.equal(loginResult.ok, true);
    assert.equal(auth.readLicense().refresh_token, signedIn.refresh_token);
    assert.deepEqual(auth.readLicense().entitlements, ["real_estate_admin"]);
  } finally {
    state.cleanup();
  }
});

test("delayed valid Beta login cannot overwrite a newer account session", async () => {
  const state = profile();
  const firstResponse = deferred();
  const newer = successfulPayload(["real_estate_admin"]);
  let calls = 0;
  try {
    const auth = createDesktopAuth({
      log,
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async () => {
        calls += 1;
        return calls === 1 ? firstResponse.promise : response(newer);
      },
    });

    const stale = auth.performLogin({
      email: "old@example.test",
      password: "old-password",
    });
    const latest = await auth.performLogin({
      email: "agent@example.test",
      password: "new-password",
    });
    assert.equal(latest.ok, true);

    firstResponse.resolve(response(successfulPayload(["real_estate_sales"])));
    const staleResult = await stale;

    assert.equal(staleResult.ok, false);
    assert.equal(staleResult.code, "beta_auth_superseded");
    assert.deepEqual(auth.readLicense(), latest.license);
    assert.equal(auth.readLicense().refresh_token, newer.refresh_token);
  } finally {
    state.cleanup();
  }
});

test("delayed malformed Beta login cannot clear a newer account session", async () => {
  const state = profile();
  const firstResponse = deferred();
  const newer = successfulPayload(["real_estate_admin"]);
  let calls = 0;
  try {
    const auth = createDesktopAuth({
      log,
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async () => {
        calls += 1;
        return calls === 1 ? firstResponse.promise : response(newer);
      },
    });

    const stale = auth.performLogin({
      email: "old@example.test",
      password: "old-password",
    });
    const latest = await auth.performLogin({
      email: "agent@example.test",
      password: "new-password",
    });
    assert.equal(latest.ok, true);

    firstResponse.resolve(response({
      ...successfulPayload(["real_estate_sales"]),
      email: "forged@example.test",
    }));
    const staleResult = await stale;

    assert.equal(staleResult.ok, false);
    assert.deepEqual(auth.readLicense(), latest.license);
    assert.equal(auth.readLicense().refresh_token, newer.refresh_token);
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
