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
const { createRefreshPendingStore } = require("../src/refresh-pending");

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

async function waitFor(predicate, timeoutMs = 1_000) {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error("timed out waiting for test state");
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
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

function successfulPayload(
  entitlements = [],
  {
    refreshToken,
    expiresAt,
    email = "agent@example.test",
    licenseId = "license-1",
  } = {},
) {
  const now = Math.floor(Date.now() / 1000);
  const expiry = expiresAt === undefined ? now + 3600 : expiresAt;
  const issuedAt = expiry - 3600;
  const accessToken = token(expiry);
  const signedRefreshToken = refreshToken || crypto.randomBytes(32).toString("base64url");
  const payload = {
    access_token: accessToken,
    refresh_token: signedRefreshToken,
    email: String(email).trim().toLowerCase(),
    license_id: licenseId,
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
    iat: issuedAt,
    nbf: issuedAt,
    exp: expiry,
    jti: crypto.randomUUID(),
    ath: tokenHash(accessToken),
    rth: tokenHash(signedRefreshToken),
  })).toString("base64url");
  const input = `${header}.${claims}`;
  payload.entitlement_assertion = `${input}.${crypto
    .sign(null, Buffer.from(input, "ascii"), entitlementKeys.privateKey)
    .toString("base64url")}`;
  payload.expires_at = expiry;
  return payload;
}

test("exact Beta desktop login and refresh ignore attacker backend and verify atomic snapshot", async () => {
  const state = profile();
  const calls = [];
  const initialPayload = successfulPayload([
    "real_estate_admin",
    "real_estate_sales",
  ]);
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
        const body = JSON.parse(options.body);
        return response(
          url.endsWith("/api/license/refresh")
            ? successfulPayload([], { refreshToken: body.next_refresh_token })
            : initialPayload,
        );
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
    assert.deepEqual(Object.keys(calls[1].body).sort(), [
      "next_refresh_token",
      "refresh_attempt_id",
      "refresh_token",
    ]);
    assert.equal(calls[1].body.refresh_token, initialPayload.refresh_token);
    assert.equal(refreshed.refresh_token, calls[1].body.next_refresh_token);
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
  let successor = null;
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
      fetchImpl: async (_url, options) => {
        calls += 1;
        successor = JSON.parse(options.body).next_refresh_token;
        return pending.promise;
      },
    });
    const current = auth.readLicense();

    const first = auth.refreshLicense(current);
    const second = auth.refreshLicense(current);
    assert.equal(first, second);
    await waitFor(() => calls === 1);
    assert.equal(calls, 1);

    pending.resolve(response(successfulPayload([], { refreshToken: successor })));
    const [one, two] = await Promise.all([first, second]);
    assert.deepEqual(one, two);
    assert.deepEqual(one.entitlements, []);
    assert.equal(calls, 1);
  } finally {
    state.cleanup();
  }
});

test("a login mutation waits behind refresh and is never erased by its 401", async () => {
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
    await waitFor(() => fs.existsSync(path.join(state.root, ".license-refresh-pending.json")));
    let mutationFinished = false;
    const mutation = auth.writeLicense(successfulPayload(["real_estate_admin"]))
      .then((value) => {
        mutationFinished = true;
        return value;
      });
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.equal(mutationFinished, false);
    pending.resolve(response({}, 401));

    await assert.rejects(refresh, (error) => error.code === "beta_license_revoked");
    const newer = await mutation;
    assert.deepEqual(auth.readLicense(), newer);
  } finally {
    state.cleanup();
  }
});

test("public Beta writer uses snapshot CAS and clears superseded retry state", async () => {
  const state = profile();
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
    });
    const expected = auth.readLicense();
    const pendingStore = createRefreshPendingStore({ root: state.root });
    await pendingStore.withLock(async () => {
      pendingStore.create({
        licenseId: expected.license_id,
        currentRefreshToken: expected.refresh_token,
      });
    });
    const newer = successfulPayload(["real_estate_admin"]);

    const persisted = await auth.writeLicense(newer, { expected });

    assert.deepEqual(auth.readLicense(), persisted);
    assert.equal(fs.existsSync(pendingStore.markerPath), false);
    await assert.rejects(
      auth.writeLicense(expected),
      (error) => error.code === "beta_auth_superseded",
    );
    assert.deepEqual(auth.readLicense(), persisted);
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
    const markerPath = path.join(state.root, ".license-refresh-pending.json");
    await waitFor(() => fs.existsSync(markerPath));
    fs.unlinkSync(state.licensePath);
    const marker = JSON.parse(fs.readFileSync(markerPath, "utf8"));
    const rejected = assert.rejects(
      refresh,
      (error) => error.code === "beta_license_snapshot_invalid",
    );
    pending.resolve(response(successfulPayload(
      ["real_estate_admin"],
      { refreshToken: marker.successor_refresh_token },
    )));

    await rejected;
    assert.equal(fs.existsSync(state.licensePath), false);
    assert.equal(fs.existsSync(markerPath), true);
  } finally {
    state.cleanup();
  }
});

test("explicit Beta login waits for an older refresh and then supersedes it", async () => {
  const state = profile();
  const refreshResponse = deferred();
  const loginResponse = deferred();
  try {
    const initial = successfulPayload(["real_estate_sales"]);
    const signedIn = successfulPayload(["real_estate_admin"]);
    let refreshSuccessor = null;
    fs.writeFileSync(state.licensePath, JSON.stringify(initial), { mode: 0o600 });
    const auth = createDesktopAuth({
      log,
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async (url, options) => {
        if (url.endsWith("/api/license/refresh")) {
          refreshSuccessor = JSON.parse(options.body).next_refresh_token;
          return refreshResponse.promise;
        }
        return loginResponse.promise;
      },
    });

    const refresh = auth.refreshLicense(auth.readLicense());
    const login = auth.performLogin({
      email: "agent@example.test",
      password: "new-password",
    });
    await waitFor(() => refreshSuccessor !== null);
    const refreshed = successfulPayload(
      ["real_estate_marketing"],
      { refreshToken: refreshSuccessor },
    );
    refreshResponse.resolve(response(refreshed));

    const completedRefresh = await refresh;
    assert.equal(completedRefresh.refresh_token, refreshed.refresh_token);
    assert.equal(auth.readLicense().refresh_token, refreshed.refresh_token);

    loginResponse.resolve(response(signedIn));
    const loginResult = await login;
    assert.equal(loginResult.ok, true);
    assert.equal(auth.readLicense().refresh_token, signedIn.refresh_token);
    assert.deepEqual(auth.readLicense().entitlements, ["real_estate_admin"]);
  } finally {
    state.cleanup();
  }
});

test("hung Beta sign-in is bounded and releases background refresh", async () => {
  const state = profile();
  let calls = 0;
  let successor = null;
  try {
    const initial = successfulPayload(["real_estate_sales"]);
    const refreshed = successfulPayload(["real_estate_admin"]);
    fs.writeFileSync(state.licensePath, JSON.stringify(initial), { mode: 0o600 });
    const auth = createDesktopAuth({
      log,
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
      profileRoot: state.root,
      licensePath: state.licensePath,
      authRequestTimeoutMs: 10,
      fetchImpl: async (url, options) => {
        calls += 1;
        if (calls > 1) {
          const body = JSON.parse(options.body);
          successor = body.next_refresh_token;
          return response(successfulPayload(
            refreshed.entitlements,
            { refreshToken: body.next_refresh_token },
          ));
        }
        return new Promise((_resolve, reject) => {
          options.signal.addEventListener(
            "abort",
            () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })),
            { once: true },
          );
        });
      },
    });

    const login = await auth.performLogin({
      email: "agent@example.test",
      password: "password",
    });
    assert.equal(login.ok, false);
    assert.equal(login.code, "beta_auth_upstream_unavailable");

    const next = await auth.refreshLicense(auth.readLicense());
    assert.equal(next.refresh_token, successor);
    assert.deepEqual(next.entitlements, ["real_estate_admin"]);
    assert.equal(calls, 2);
  } finally {
    state.cleanup();
  }
});

test("hung Beta refresh is bounded and a later retry can recover", async () => {
  const state = profile();
  let calls = 0;
  let successor = null;
  try {
    const initial = successfulPayload(["real_estate_sales"]);
    const refreshed = successfulPayload(["real_estate_admin"]);
    fs.writeFileSync(state.licensePath, JSON.stringify(initial), { mode: 0o600 });
    const auth = createDesktopAuth({
      log,
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
      profileRoot: state.root,
      licensePath: state.licensePath,
      authRequestTimeoutMs: 10,
      fetchImpl: async (_url, options) => {
        calls += 1;
        if (calls > 1) {
          const body = JSON.parse(options.body);
          successor = body.next_refresh_token;
          return response(successfulPayload(
            refreshed.entitlements,
            { refreshToken: body.next_refresh_token },
          ));
        }
        return new Promise((_resolve, reject) => {
          options.signal.addEventListener(
            "abort",
            () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })),
            { once: true },
          );
        });
      },
    });

    await assert.rejects(
      auth.refreshLicense(auth.readLicense()),
      (error) => error.code === "beta_auth_upstream_unavailable",
    );
    assert.equal(auth.readLicense().refresh_token, initial.refresh_token);

    const next = await auth.refreshLicense(auth.readLicense());
    assert.equal(next.refresh_token, successor);
    assert.deepEqual(next.entitlements, ["real_estate_admin"]);
    assert.equal(calls, 2);
  } finally {
    state.cleanup();
  }
});

test("expired signed B replays the exact durable A/B/I triplet", async () => {
  const state = profile();
  try {
    const pendingStore = createRefreshPendingStore({ root: state.root });
    let pending;
    await pendingStore.withLock(async () => {
      pending = pendingStore.create({
        licenseId: "license-1",
        currentRefreshToken: Buffer.alloc(32, 0x41).toString("base64url"),
        createdAt: Math.floor(Date.now() / 1000) - 7200,
      });
    });
    const expired = successfulPayload(["real_estate_admin"], {
      refreshToken: pending.successor_refresh_token,
      expiresAt: Math.floor(Date.now() / 1000) - 120,
    });
    fs.writeFileSync(state.licensePath, JSON.stringify(expired), { mode: 0o600 });
    const calls = [];
    const auth = createDesktopAuth({
      log,
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async (_url, options) => {
        const body = JSON.parse(options.body);
        calls.push(body);
        return response(successfulPayload(
          ["real_estate_admin"],
          { refreshToken: body.next_refresh_token },
        ));
      },
    });

    const fresh = await auth.refreshLicense(auth.readLicense());

    assert.deepEqual(calls, [{
      refresh_token: pending.current_refresh_token,
      next_refresh_token: pending.successor_refresh_token,
      refresh_attempt_id: pending.attempt_id,
    }]);
    assert.equal(fresh.refresh_token, pending.successor_refresh_token);
    assert.deepEqual(fresh.entitlements, ["real_estate_admin"]);
    assert.equal(fs.existsSync(pendingStore.markerPath), false);
  } finally {
    state.cleanup();
  }
});

test("signed successor mismatch retains A/B/I and exact retry recovers", async () => {
  const state = profile();
  const bodies = [];
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
      fetchImpl: async (_url, options) => {
        const body = JSON.parse(options.body);
        bodies.push(body);
        return response(successfulPayload(
          ["real_estate_admin"],
          {
            refreshToken: bodies.length === 1
              ? Buffer.alloc(32, 0x43).toString("base64url")
              : body.next_refresh_token,
          },
        ));
      },
    });
    const markerPath = path.join(state.root, ".license-refresh-pending.json");

    await assert.rejects(
      auth.refreshLicense(auth.readLicense()),
      (error) => error.code === "beta_refresh_successor_mismatch",
    );
    assert.equal(auth.readLicense().refresh_token, initial.refresh_token);
    assert.equal(fs.existsSync(markerPath), true);

    const recovered = await auth.refreshLicense(auth.readLicense());

    assert.deepEqual(bodies[0], bodies[1]);
    assert.equal(recovered.refresh_token, bodies[0].next_refresh_token);
    assert.deepEqual(recovered.entitlements, ["real_estate_admin"]);
    assert.equal(fs.existsSync(markerPath), false);
  } finally {
    state.cleanup();
  }
});

for (const stateKind of ["successor", "newer"]) {
  test(`signed ${stateKind} state cleans marker without network`, async () => {
    const state = profile();
    try {
      const pendingStore = createRefreshPendingStore({ root: state.root });
      let pending;
      await pendingStore.withLock(async () => {
        pending = pendingStore.create({
          licenseId: "license-1",
          currentRefreshToken: Buffer.alloc(32, 0x41).toString("base64url"),
        });
      });
      const current = successfulPayload([], {
        refreshToken: stateKind === "successor"
          ? pending.successor_refresh_token
          : Buffer.alloc(32, 0x43).toString("base64url"),
      });
      fs.writeFileSync(state.licensePath, JSON.stringify(current), { mode: 0o600 });
      const auth = createDesktopAuth({
        log,
        home: state.sandbox,
        isBeta: true,
        entitlementKeyset,
        profileRoot: state.root,
        licensePath: state.licensePath,
        fetchImpl: async () => {
          throw new Error("signed local state should resolve before network");
        },
      });

      const resolved = await auth.refreshLicense(auth.readLicense());

      assert.equal(resolved.refresh_token, current.refresh_token);
      assert.equal(fs.existsSync(pendingStore.markerPath), false);
    } finally {
      state.cleanup();
    }
  });
}

test("ambiguous Beta 4xx retains marker and never falls back to v1", async () => {
  const state = profile();
  const calls = [];
  try {
    const initial = successfulPayload([]);
    fs.writeFileSync(state.licensePath, JSON.stringify(initial), { mode: 0o600 });
    const auth = createDesktopAuth({
      log,
      home: state.sandbox,
      isBeta: true,
      entitlementKeyset,
      profileRoot: state.root,
      licensePath: state.licensePath,
      fetchImpl: async (_url, options) => {
        calls.push(JSON.parse(options.body));
        return response({}, 400);
      },
    });
    const markerPath = path.join(state.root, ".license-refresh-pending.json");

    await assert.rejects(
      auth.refreshLicense(auth.readLicense()),
      (error) => error.code === "beta_refresh_protocol_rejected",
    );

    assert.equal(calls.length, 1);
    assert.deepEqual(Object.keys(calls[0]).sort(), [
      "next_refresh_token",
      "refresh_attempt_id",
      "refresh_token",
    ]);
    assert.equal(auth.readLicense().refresh_token, initial.refresh_token);
    assert.equal(fs.existsSync(markerPath), true);
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

test("Stable write and clear preserve their synchronous return contract", () => {
  const sandbox = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), "elevate-stable-auth-"));
  const licensePath = path.join(sandbox, "license.json");
  try {
    const auth = createDesktopAuth({
      log,
      hqBaseUrl: "https://stable.example.test",
      isBeta: false,
      profileRoot: sandbox,
      licensePath,
      entitlementKeyset,
    });
    const license = {
      access_token: token(),
      refresh_token: "stable-refresh",
      license_id: "stable-license",
      tier: "pro",
      email: "stable@example.test",
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      entitlements: [],
    };

    const written = auth.writeLicense(license);
    assert.equal(written, license);
    assert.equal(typeof written?.then, "undefined");
    const cleared = auth.clearLicense();
    assert.equal(typeof cleared?.then, "undefined");
    assert.equal(fs.existsSync(licensePath), false);
  } finally {
    fs.rmSync(sandbox, { recursive: true, force: true });
  }
});

test("Stable refresh keeps the legacy v1 request shape", async () => {
  const sandbox = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), "elevate-stable-refresh-"));
  const licensePath = path.join(sandbox, "license.json");
  const calls = [];
  try {
    const auth = createDesktopAuth({
      log,
      hqBaseUrl: "https://stable.example.test",
      isBeta: false,
      profileRoot: sandbox,
      licensePath,
      entitlementKeyset,
      fetchImpl: async (_url, options) => {
        calls.push(JSON.parse(options.body));
        return response({
          access_token: token(),
          refresh_token: "stable-next",
        });
      },
    });
    const current = {
      access_token: token(),
      refresh_token: "stable-current",
      license_id: "stable-license",
      tier: "pro",
      email: "stable@example.test",
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      entitlements: [],
    };
    auth.writeLicense(current);

    const refreshed = await auth.refreshLicense(current);

    assert.deepEqual(calls, [{ refresh_token: "stable-current" }]);
    assert.equal(refreshed.refresh_token, "stable-next");
  } finally {
    fs.rmSync(sandbox, { recursive: true, force: true });
  }
});

const DEVICE_D = Buffer.alloc(32, "D").toString("base64url");
const DEVICE_B = Buffer.alloc(32, "B").toString("base64url");
const DEVICE_C = Buffer.alloc(32, "C").toString("base64url");
const DEVICE_I = Buffer.alloc(32, "I").toString("base64url");

async function writeDevicePending(root) {
  const store = createRefreshPendingStore({ root });
  let pending;
  await store.withLock(async () => {
    pending = store.writeDevice({
      deviceCode: DEVICE_D,
      initialRefreshToken: DEVICE_B,
      recoveryRefreshToken: DEVICE_C,
      recoveryAttemptId: DEVICE_I,
    });
  });
  return { pending, store };
}

function writeOverlappingRefreshMarker(root) {
  const marker = {
    schema: 1,
    operation: "refresh",
    license_id: "license-1",
    current_refresh_token: Buffer.alloc(32, "A").toString("base64url"),
    successor_refresh_token: Buffer.alloc(32, "E").toString("base64url"),
    attempt_id: Buffer.alloc(32, "F").toString("base64url"),
    created_at: Math.floor(Date.now() / 1000),
  };
  const markerPath = path.join(root, ".license-refresh-pending.json");
  fs.writeFileSync(markerPath, `${JSON.stringify(marker)}\n`, { mode: 0o600 });
  return { marker, markerPath };
}

function betaAuth(state, options = {}) {
  return createDesktopAuth({
    log,
    home: state.sandbox,
    isBeta: true,
    entitlementKeyset,
    profileRoot: state.root,
    licensePath: state.licensePath,
    ...options,
  });
}

test("exact Beta desktop retains resumable pre-license Device state", async () => {
  const state = profile();
  try {
    const { pending, store } = await writeDevicePending(state.root);
    const auth = betaAuth(state);

    const outcome = await auth.reconcileDevicePending();

    assert.equal(outcome.status, "pending");
    assert.equal(outcome.license, null);
    assert.deepEqual(outcome.pending, pending);
    assert.deepEqual(store.readDevice(), pending);
    assert.equal(fs.existsSync(state.licensePath), false);
  } finally {
    state.cleanup();
  }
});

for (const refreshToken of [DEVICE_B, DEVICE_C]) {
  test(`exact Beta desktop removes Device state only after verified ${refreshToken === DEVICE_B ? "B" : "C"} mirror`, async () => {
    const state = profile();
    const events = [];
    try {
      const { store } = await writeDevicePending(state.root);
      const license = successfulPayload([], { refreshToken });
      fs.writeFileSync(state.licensePath, JSON.stringify(license), { mode: 0o600 });
      const devicePath = path.join(state.root, ".license-device-pending.json");
      const fsImpl = Object.create(fs);
      fsImpl.unlinkSync = (target) => {
        if (path.resolve(target) === path.resolve(devicePath)) {
          const persisted = JSON.parse(fs.readFileSync(state.licensePath, "utf8"));
          assert.deepEqual(persisted, license);
          events.push("verified-before-device-clear");
        }
        return fs.unlinkSync(target);
      };
      const auth = betaAuth(state, { fsImpl });

      const outcome = await auth.reconcileDevicePending();

      assert.equal(outcome.status, "already_persisted");
      assert.deepEqual(outcome.license, license);
      assert.deepEqual(events, ["verified-before-device-clear"]);
      assert.equal(store.readDevice(), null);
    } finally {
      state.cleanup();
    }
  });
}

test("exact Beta desktop expired explicit auth supersedes stale Device state", async () => {
  const state = profile();
  try {
    const { store } = await writeDevicePending(state.root);
    const expired = successfulPayload([], {
      refreshToken: Buffer.alloc(32, "A").toString("base64url"),
      expiresAt: Math.floor(Date.now() / 1000) - 30,
    });
    fs.writeFileSync(state.licensePath, JSON.stringify(expired), { mode: 0o600 });
    const auth = betaAuth(state);

    const outcome = await auth.reconcileDevicePending();

    assert.equal(outcome.status, "beta_auth_superseded");
    assert.deepEqual(outcome.license, expired);
    assert.equal(store.readDevice(), null);
    assert.deepEqual(JSON.parse(fs.readFileSync(state.licensePath, "utf8")), expired);
  } finally {
    state.cleanup();
  }
});

for (const corrupt of ["marker", "license"]) {
  test(`exact Beta desktop Device reconciliation retains corrupt ${corrupt} state`, async () => {
    const state = profile();
    try {
      await writeDevicePending(state.root);
      const markerPath = path.join(state.root, ".license-device-pending.json");
      if (corrupt === "marker") {
        fs.writeFileSync(markerPath, "{}\n", { mode: 0o600 });
      } else {
        fs.writeFileSync(state.licensePath, "{}\n", { mode: 0o600 });
      }
      const beforeMarker = fs.readFileSync(markerPath);
      const beforeLicense = fs.existsSync(state.licensePath)
        ? fs.readFileSync(state.licensePath)
        : null;
      const auth = betaAuth(state);

      await assert.rejects(
        auth.reconcileDevicePending(),
        (error) => error && String(error.code || "").startsWith("beta_"),
      );

      assert.deepEqual(fs.readFileSync(markerPath), beforeMarker);
      assert.deepEqual(
        fs.existsSync(state.licensePath) ? fs.readFileSync(state.licensePath) : null,
        beforeLicense,
      );
    } finally {
      state.cleanup();
    }
  });
}

test("exact Beta desktop rejects dual credential markers without mutation", async () => {
  const state = profile();
  try {
    await writeDevicePending(state.root);
    const { markerPath } = writeOverlappingRefreshMarker(state.root);
    const devicePath = path.join(state.root, ".license-device-pending.json");
    const before = [fs.readFileSync(devicePath), fs.readFileSync(markerPath)];
    const auth = betaAuth(state);

    await assert.rejects(
      auth.reconcileDevicePending(),
      (error) => error && error.code === "beta_device_state_conflict",
    );

    assert.deepEqual([fs.readFileSync(devicePath), fs.readFileSync(markerPath)], before);
    assert.equal(fs.existsSync(state.licensePath), false);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop explicit login clears Device only after signed readback", async () => {
  const state = profile();
  const events = [];
  try {
    const { store } = await writeDevicePending(state.root);
    const payload = successfulPayload([], {
      refreshToken: Buffer.alloc(32, "A").toString("base64url"),
    });
    const devicePath = path.join(state.root, ".license-device-pending.json");
    const fsImpl = Object.create(fs);
    fsImpl.unlinkSync = (target) => {
      if (path.resolve(target) === path.resolve(devicePath)) {
        assert.deepEqual(JSON.parse(fs.readFileSync(state.licensePath, "utf8")), payload);
        events.push("signed-readback-before-device-clear");
      }
      return fs.unlinkSync(target);
    };
    const auth = betaAuth(state, {
      fsImpl,
      fetchImpl: async () => response(payload),
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });

    assert.equal(result.ok, true);
    assert.equal(result.activation_complete, true);
    assert.deepEqual(auth.readLicense(), payload);
    assert.deepEqual(events, ["signed-readback-before-device-clear"]);
    assert.equal(store.readDevice(), null);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop failed login retains Device recovery state", async () => {
  const state = profile();
  try {
    const { pending, store } = await writeDevicePending(state.root);
    const auth = betaAuth(state, {
      fetchImpl: async () => response({}, 401),
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "wrong-password",
    });

    assert.equal(result.ok, false);
    assert.equal(result.activation_complete, false);
    assert.equal(result.code, "invalid_credentials");
    assert.deepEqual(store.readDevice(), pending);
    assert.equal(fs.existsSync(state.licensePath), false);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop logout clears license refresh then exact Device", async () => {
  const state = profile();
  const events = [];
  try {
    await writeDevicePending(state.root);
    const { markerPath } = writeOverlappingRefreshMarker(state.root);
    const devicePath = path.join(state.root, ".license-device-pending.json");
    fs.writeFileSync(
      state.licensePath,
      JSON.stringify(successfulPayload([], {
        refreshToken: Buffer.alloc(32, "A").toString("base64url"),
      })),
      { mode: 0o600 },
    );
    const fsImpl = Object.create(fs);
    fsImpl.unlinkSync = (target) => {
      const resolved = path.resolve(target);
      if (resolved === path.resolve(state.licensePath)) {
        events.push("license");
      } else if (resolved === path.resolve(markerPath)) {
        assert.equal(fs.existsSync(state.licensePath), false);
        events.push("refresh");
      } else if (resolved === path.resolve(devicePath)) {
        assert.equal(fs.existsSync(markerPath), false);
        events.push("device");
      }
      return fs.unlinkSync(target);
    };
    const auth = betaAuth(state, { fsImpl });

    assert.equal(await auth.clearLicense(), true);
    assert.deepEqual(events, ["license", "refresh", "device"]);
    assert.equal(fs.existsSync(state.licensePath), false);
    assert.equal(fs.existsSync(markerPath), false);
    assert.equal(fs.existsSync(devicePath), false);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop Device CAS never clears a replacement marker", async () => {
  const state = profile();
  try {
    const { store } = await writeDevicePending(state.root);
    const license = successfulPayload([], { refreshToken: DEVICE_B });
    fs.writeFileSync(state.licensePath, JSON.stringify(license), { mode: 0o600 });
    const devicePath = path.join(state.root, ".license-device-pending.json");
    const replacement = {
      schema: 1,
      operation: "device",
      device_code: Buffer.alloc(32, "E").toString("base64url"),
      initial_refresh_token: Buffer.alloc(32, "F").toString("base64url"),
      recovery_refresh_token: Buffer.alloc(32, "G").toString("base64url"),
      recovery_attempt_id: Buffer.alloc(32, "H").toString("base64url"),
      created_at: Math.floor(Date.now() / 1000) + 1,
    };
    const fsImpl = Object.create(fs);
    let deviceOpens = 0;
    fsImpl.openSync = (target, ...args) => {
      if (path.resolve(target) === path.resolve(devicePath)) {
        deviceOpens += 1;
        if (deviceOpens === 2) {
          const temp = `${devicePath}.replacement`;
          fs.writeFileSync(temp, `${JSON.stringify(replacement)}\n`, { mode: 0o600 });
          fs.renameSync(temp, devicePath);
        }
      }
      return fs.openSync(target, ...args);
    };
    const auth = betaAuth(state, { fsImpl });

    await assert.rejects(
      auth.reconcileDevicePending(),
      (error) => error && error.code === "beta_auth_superseded",
    );

    assert.deepEqual(store.readDevice(), replacement);
    assert.deepEqual(auth.readLicense(), license);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop readiness keeps superseding explicit auth signed in", async () => {
  const state = profile();
  try {
    const { store } = await writeDevicePending(state.root);
    const license = successfulPayload([], {
      refreshToken: Buffer.alloc(32, "A").toString("base64url"),
    });
    fs.writeFileSync(state.licensePath, JSON.stringify(license), { mode: 0o600 });
    const auth = betaAuth(state);

    assert.deepEqual(await auth.ensureValidLicense(), license);
    assert.equal(store.readDevice(), null);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop late persistence failure preserves newer signed winner", async () => {
  const state = profile();
  try {
    const responsePayload = successfulPayload([], {
      refreshToken: Buffer.alloc(32, "A").toString("base64url"),
    });
    const winner = successfulPayload(["real_estate_admin"], {
      refreshToken: Buffer.alloc(32, "Z").toString("base64url"),
    });
    const fsImpl = Object.create(fs);
    let replaceWinner = true;
    fsImpl.renameSync = (source, target) => {
      fs.renameSync(source, target);
      if (replaceWinner && path.resolve(target) === path.resolve(state.licensePath)) {
        replaceWinner = false;
        fs.writeFileSync(target, JSON.stringify(winner), { mode: 0o600 });
      }
    };
    const auth = betaAuth(state, {
      fsImpl,
      fetchImpl: async () => response(responsePayload),
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });

    assert.equal(result.ok, false);
    assert.equal(result.code, "beta_license_persistence_mismatch");
    assert.deepEqual(auth.readLicense(), winner);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop explicit auth CAS failure rolls back only its snapshot", async () => {
  const state = profile();
  try {
    const { store } = await writeDevicePending(state.root);
    const payload = successfulPayload([], {
      refreshToken: Buffer.alloc(32, "A").toString("base64url"),
    });
    const devicePath = path.join(state.root, ".license-device-pending.json");
    const replacement = {
      schema: 1,
      operation: "device",
      device_code: Buffer.alloc(32, "J").toString("base64url"),
      initial_refresh_token: Buffer.alloc(32, "K").toString("base64url"),
      recovery_refresh_token: Buffer.alloc(32, "L").toString("base64url"),
      recovery_attempt_id: Buffer.alloc(32, "M").toString("base64url"),
      created_at: Math.floor(Date.now() / 1000) + 1,
    };
    const fsImpl = Object.create(fs);
    let deviceOpens = 0;
    fsImpl.openSync = (target, ...args) => {
      if (path.resolve(target) === path.resolve(devicePath)) {
        deviceOpens += 1;
        if (deviceOpens === 2) {
          const temp = `${devicePath}.replacement`;
          fs.writeFileSync(temp, `${JSON.stringify(replacement)}\n`, { mode: 0o600 });
          fs.renameSync(temp, devicePath);
        }
      }
      return fs.openSync(target, ...args);
    };
    const auth = betaAuth(state, {
      fsImpl,
      fetchImpl: async () => response(payload),
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });

    assert.equal(result.ok, false);
    assert.equal(result.activation_complete, false);
    assert.equal(result.code, "beta_auth_superseded");
    assert.equal(fs.existsSync(state.licensePath), false);
    assert.deepEqual(store.readDevice(), replacement);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop expired paid supersession clears Device then refreshes", async () => {
  const state = profile();
  const calls = [];
  try {
    const { store } = await writeDevicePending(state.root);
    const expired = successfulPayload(["real_estate_admin"], {
      refreshToken: Buffer.alloc(32, "A").toString("base64url"),
      expiresAt: Math.floor(Date.now() / 1000) - 30,
    });
    fs.writeFileSync(state.licensePath, JSON.stringify(expired), { mode: 0o600 });
    const auth = betaAuth(state, {
      fetchImpl: async (url, options) => {
        calls.push(url);
        const body = JSON.parse(options.body);
        return response(successfulPayload(["real_estate_admin"], {
          refreshToken: body.next_refresh_token,
        }));
      },
    });

    const fresh = await auth.ensureValidLicense();

    assert.deepEqual(calls, [`${SIGNED_HQ_BASE_URL}/api/license/refresh`]);
    assert.deepEqual(fresh.entitlements, ["real_estate_admin"]);
    assert.ok(Number(fresh.expires_at) * 1000 > Date.now());
    assert.equal(store.readDevice(), null);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop pre-rename auth failure invalidates paid predecessor", async () => {
  const state = profile();
  try {
    const prior = successfulPayload(["real_estate_admin"], {
      refreshToken: Buffer.alloc(32, "A").toString("base64url"),
    });
    const next = successfulPayload([], {
      refreshToken: Buffer.alloc(32, "B").toString("base64url"),
    });
    fs.writeFileSync(state.licensePath, JSON.stringify(prior), { mode: 0o600 });
    const fsImpl = Object.create(fs);
    fsImpl.renameSync = (source, target) => {
      if (path.resolve(target) === path.resolve(state.licensePath)) {
        throw new Error("injected pre-rename EIO");
      }
      return fs.renameSync(source, target);
    };
    const auth = betaAuth(state, {
      fsImpl,
      fetchImpl: async () => response(next),
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });

    assert.equal(result.ok, false);
    assert.equal(result.code, "beta_license_persistence_failed");
    assert.equal(fs.existsSync(state.licensePath), false);
    assert.equal(auth.readLicense(), null);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop full-snapshot CAS catches same-token cross-process winner", async () => {
  const state = profile();
  try {
    const sharedRefresh = Buffer.alloc(32, "A").toString("base64url");
    const prior = successfulPayload(["real_estate_admin"], {
      refreshToken: sharedRefresh,
    });
    const winner = successfulPayload(["real_estate_sales"], {
      refreshToken: sharedRefresh,
    });
    const stale = successfulPayload([], {
      refreshToken: Buffer.alloc(32, "B").toString("base64url"),
    });
    fs.writeFileSync(state.licensePath, JSON.stringify(prior), { mode: 0o600 });
    const auth = betaAuth(state, {
      fetchImpl: async () => {
        fs.writeFileSync(state.licensePath, JSON.stringify(winner), { mode: 0o600 });
        return response(stale);
      },
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });

    assert.equal(result.ok, false);
    assert.equal(result.code, "beta_auth_superseded");
    assert.deepEqual(auth.readLicense(), winner);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop precondition mismatch preserves response-identical winner", async () => {
  const state = profile();
  try {
    const sharedRefresh = Buffer.alloc(32, "A").toString("base64url");
    const prior = successfulPayload(["real_estate_admin"], {
      refreshToken: sharedRefresh,
    });
    const winner = successfulPayload(["real_estate_sales"], {
      refreshToken: sharedRefresh,
    });
    fs.writeFileSync(state.licensePath, JSON.stringify(prior), { mode: 0o600 });
    const auth = betaAuth(state, {
      fetchImpl: async () => {
        fs.writeFileSync(state.licensePath, JSON.stringify(winner), { mode: 0o600 });
        return response(winner);
      },
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });

    assert.equal(result.ok, false);
    assert.equal(result.code, "beta_auth_superseded");
    assert.deepEqual(auth.readLicense(), winner);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop prewrite marker failure preserves response-identical winner", async () => {
  const state = profile();
  try {
    const prior = successfulPayload(["real_estate_admin"], {
      refreshToken: Buffer.alloc(32, "A").toString("base64url"),
    });
    const winner = successfulPayload(["real_estate_sales"], {
      refreshToken: Buffer.alloc(32, "B").toString("base64url"),
    });
    fs.writeFileSync(state.licensePath, JSON.stringify(prior), { mode: 0o600 });
    const devicePath = path.join(state.root, ".license-device-pending.json");
    fs.writeFileSync(devicePath, "{}\n", { mode: 0o600 });
    const fsImpl = Object.create(fs);
    let armed = false;
    fsImpl.openSync = (target, ...args) => {
      if (armed && path.resolve(String(target)) === path.resolve(devicePath)) {
        armed = false;
        fs.writeFileSync(state.licensePath, JSON.stringify(winner), { mode: 0o600 });
      }
      return fs.openSync(target, ...args);
    };
    const auth = betaAuth(state, {
      fsImpl,
      fetchImpl: async () => {
        armed = true;
        return response(winner);
      },
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });

    assert.equal(result.ok, false);
    assert.equal(result.code, "beta_device_state_corrupt");
    assert.deepEqual(auth.readLicense(), winner);
    assert.deepEqual(fs.readFileSync(devicePath), Buffer.from("{}\n"));
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop repairs unchanged private corrupt license", async () => {
  const state = profile();
  try {
    fs.writeFileSync(state.licensePath, '{"partial":', { mode: 0o600 });
    const payload = successfulPayload(["real_estate_admin"], {
      refreshToken: Buffer.alloc(32, "B").toString("base64url"),
    });
    const auth = betaAuth(state, {
      fetchImpl: async () => response(payload),
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });

    assert.equal(result.ok, true);
    assert.deepEqual(result.license, payload);
    assert.deepEqual(auth.readLicense(), payload);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop invalid predecessor failure preserves signed third winner", async () => {
  const state = profile();
  try {
    fs.writeFileSync(state.licensePath, '{"partial":', { mode: 0o600 });
    const attempted = successfulPayload([], {
      refreshToken: Buffer.alloc(32, "B").toString("base64url"),
    });
    const winner = successfulPayload(["real_estate_sales"], {
      refreshToken: Buffer.alloc(32, "C").toString("base64url"),
    });
    const fsImpl = Object.create(fs);
    fsImpl.renameSync = (source, target) => {
      if (path.resolve(target) === path.resolve(state.licensePath)) {
        fs.writeFileSync(target, JSON.stringify(winner), { mode: 0o600 });
        throw new Error("injected valid third winner");
      }
      return fs.renameSync(source, target);
    };
    const auth = betaAuth(state, {
      fsImpl,
      fetchImpl: async () => response(attempted),
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });

    assert.equal(result.ok, false);
    assert.equal(result.code, "beta_license_persistence_failed");
    assert.deepEqual(auth.readLicense(), winner);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop rejects signed response for another requested email", async () => {
  const state = profile();
  try {
    const prior = successfulPayload(["real_estate_admin"], {
      refreshToken: Buffer.alloc(32, "A").toString("base64url"),
    });
    fs.writeFileSync(state.licensePath, JSON.stringify(prior), { mode: 0o600 });
    const { pending, store } = await writeDevicePending(state.root);
    const markerPath = path.join(state.root, ".license-device-pending.json");
    const markerBytes = fs.readFileSync(markerPath);
    const victim = successfulPayload([], {
      refreshToken: Buffer.alloc(32, "B").toString("base64url"),
      email: "victim@example.test",
    });
    const auth = betaAuth(state, {
      fetchImpl: async () => response(victim),
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });

    assert.equal(result.ok, false);
    assert.equal(result.code, "beta_entitlement_response_mismatch");
    assert.deepEqual(auth.readLicense(), prior);
    assert.deepEqual(store.readDevice(), pending);
    assert.deepEqual(fs.readFileSync(markerPath), markerBytes);
  } finally {
    state.cleanup();
  }
});

for (const corruptMarker of ["refresh", "device"]) {
  test(`exact Beta desktop logout clears license and other marker with corrupt ${corruptMarker}`, async () => {
    const state = profile();
    try {
      await writeDevicePending(state.root);
      const { markerPath: refreshPath } = writeOverlappingRefreshMarker(state.root);
      const devicePath = path.join(state.root, ".license-device-pending.json");
      const corruptPath = corruptMarker === "refresh" ? refreshPath : devicePath;
      const otherPath = corruptMarker === "refresh" ? devicePath : refreshPath;
      fs.writeFileSync(corruptPath, "{}\n", { mode: 0o600 });
      const corruptBytes = fs.readFileSync(corruptPath);
      fs.writeFileSync(
        state.licensePath,
        JSON.stringify(successfulPayload(["real_estate_admin"])),
        { mode: 0o600 },
      );
      const auth = betaAuth(state);

      await assert.rejects(
        auth.clearLicense(),
        (error) => error && String(error.code || "").startsWith("beta_"),
      );

      assert.equal(fs.existsSync(state.licensePath), false);
      assert.equal(auth.readLicense(), null);
      assert.deepEqual(fs.readFileSync(corruptPath), corruptBytes);
      assert.equal(fs.existsSync(otherPath), false);
    } finally {
      state.cleanup();
    }
  });
}

for (const markerFault of ["corrupt_device", "dual_valid"]) {
  test(`exact Beta desktop signed auth ${markerFault} invalidates captured paid snapshot`, async () => {
    const state = profile();
    try {
      const prior = successfulPayload(["real_estate_admin"], {
        refreshToken: Buffer.alloc(32, "A").toString("base64url"),
      });
      fs.writeFileSync(state.licensePath, JSON.stringify(prior), { mode: 0o600 });
      await writeDevicePending(state.root);
      const devicePath = path.join(state.root, ".license-device-pending.json");
      const markerPaths = [devicePath];
      if (markerFault === "corrupt_device") {
        fs.writeFileSync(devicePath, "{}\n", { mode: 0o600 });
      } else {
        const { markerPath } = writeOverlappingRefreshMarker(state.root);
        markerPaths.push(markerPath);
      }
      const before = markerPaths.map((target) => fs.readFileSync(target));
      const revoked = successfulPayload([], {
        refreshToken: Buffer.alloc(32, "B").toString("base64url"),
      });
      const auth = betaAuth(state, {
        fetchImpl: async () => response(revoked),
      });

      const result = await auth.performLogin({
        email: "agent@example.test",
        password: "secret-password",
      });

      assert.equal(result.ok, false);
      assert.equal(
        result.code,
        markerFault === "dual_valid"
          ? "beta_device_state_conflict"
          : "beta_device_state_corrupt",
      );
      assert.equal(fs.existsSync(state.licensePath), false);
      assert.equal(auth.readLicense(), null);
      assert.deepEqual(
        markerPaths.map((target) => fs.readFileSync(target)),
        before,
      );
    } finally {
      state.cleanup();
    }
  });
}

test("exact Beta desktop never reads or surfaces login and refresh response bodies", async () => {
  const state = profile();
  const canary = "HQ-SECRET-BODY-CANARY";
  const messages = [];
  let bodyReads = 0;
  try {
    const captureLog = {
      info(message) { messages.push(String(message)); },
      warn(message) { messages.push(String(message)); },
    };
    const secretFailure = {
      ok: false,
      status: 503,
      async json() { return {}; },
      async text() {
        bodyReads += 1;
        return canary;
      },
    };
    const auth = betaAuth(state, {
      log: captureLog,
      fetchImpl: async () => secretFailure,
    });

    const login = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });
    assert.equal(login.ok, false);
    assert.equal(login.code, "auth_upstream_failed");

    const current = successfulPayload([], {
      refreshToken: Buffer.alloc(32, "A").toString("base64url"),
    });
    fs.writeFileSync(state.licensePath, JSON.stringify(current), { mode: 0o600 });
    await assert.rejects(
      auth.refreshLicense(auth.readLicense()),
      (error) => error && error.code === "beta_auth_upstream_failed",
    );

    assert.equal(bodyReads, 0);
    assert.equal(JSON.stringify(login).includes(canary), false);
    assert.equal(messages.join("\n").includes(canary), false);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop lock loss before auth write mutates no license or marker", async () => {
  const state = profile();
  try {
    const prior = successfulPayload(["real_estate_admin"], {
      refreshToken: Buffer.alloc(32, "A").toString("base64url"),
    });
    fs.writeFileSync(state.licensePath, JSON.stringify(prior), { mode: 0o600 });
    await writeDevicePending(state.root);
    const devicePath = path.join(state.root, ".license-device-pending.json");
    const markerBytes = fs.readFileSync(devicePath);
    const licenseBytes = fs.readFileSync(state.licensePath);
    const lockPath = path.join(state.root, ".license-refresh.lock");
    const fsImpl = Object.create(fs);
    let lockChecks = 0;
    fsImpl.lstatSync = (target, ...args) => {
      if (path.resolve(String(target)) === path.resolve(lockPath)) {
        lockChecks += 1;
        if (lockChecks === 3) {
          fs.unlinkSync(lockPath);
          fs.writeFileSync(lockPath, "", { mode: 0o600 });
        }
      }
      return fs.lstatSync(target, ...args);
    };
    const next = successfulPayload([], {
      refreshToken: Buffer.alloc(32, "B").toString("base64url"),
    });
    const auth = betaAuth(state, {
      fsImpl,
      fetchImpl: async () => response(next),
    });

    const result = await auth.performLogin({
      email: "agent@example.test",
      password: "secret-password",
    });

    assert.equal(result.ok, false);
    assert.equal(result.code, "beta_refresh_state_unsafe");
    assert.deepEqual(fs.readFileSync(state.licensePath), licenseBytes);
    assert.deepEqual(fs.readFileSync(devicePath), markerBytes);
  } finally {
    state.cleanup();
  }
});

test("exact Beta desktop lock loss before logout clear mutates no state", async () => {
  const state = profile();
  try {
    const prior = successfulPayload(["real_estate_admin"], {
      refreshToken: Buffer.alloc(32, "A").toString("base64url"),
    });
    fs.writeFileSync(state.licensePath, JSON.stringify(prior), { mode: 0o600 });
    await writeDevicePending(state.root);
    const devicePath = path.join(state.root, ".license-device-pending.json");
    const markerBytes = fs.readFileSync(devicePath);
    const licenseBytes = fs.readFileSync(state.licensePath);
    const lockPath = path.join(state.root, ".license-refresh.lock");
    const fsImpl = Object.create(fs);
    let lockChecks = 0;
    fsImpl.lstatSync = (target, ...args) => {
      if (path.resolve(String(target)) === path.resolve(lockPath)) {
        lockChecks += 1;
        if (lockChecks === 2) {
          fs.unlinkSync(lockPath);
          fs.writeFileSync(lockPath, "", { mode: 0o600 });
        }
      }
      return fs.lstatSync(target, ...args);
    };
    const auth = betaAuth(state, { fsImpl });

    await assert.rejects(
      auth.clearLicense(),
      (error) => error && error.code === "beta_refresh_state_unsafe",
    );

    assert.deepEqual(fs.readFileSync(state.licensePath), licenseBytes);
    assert.deepEqual(fs.readFileSync(devicePath), markerBytes);
  } finally {
    state.cleanup();
  }
});
