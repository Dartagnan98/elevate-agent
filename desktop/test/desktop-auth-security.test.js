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

function successfulPayload(entitlements = [], { refreshToken, expiresAt } = {}) {
  const now = Math.floor(Date.now() / 1000);
  const expiry = expiresAt === undefined ? now + 3600 : expiresAt;
  const issuedAt = expiry - 3600;
  const accessToken = token(expiry);
  const signedRefreshToken = refreshToken || crypto.randomBytes(32).toString("base64url");
  const payload = {
    access_token: accessToken,
    refresh_token: signedRefreshToken,
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
    const expired = successfulPayload([], {
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
