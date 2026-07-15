import assert from "node:assert/strict";
import crypto from "node:crypto";
import { describe, it } from "node:test";
import bcrypt from "bcryptjs";

import {
  afterNextSupabaseRpc,
  assertEntitlementEnvelope,
  barrierNextSupabaseRpcs,
  beforeNextInitialIssuanceInsert,
  failNextAtomicInitialIssuance,
  failNextSupabaseSelect,
  gateNextSupabaseRpc,
  jsonRequest,
  loadRoute,
  makeUser,
  refreshHash,
  responseJson,
  seedLicense,
  TEST_ENTITLEMENT_KEY_A,
  TEST_ENTITLEMENT_KEY_B,
  useFakeDb,
  withTestEntitlementSigningRing,
} from "./route-harness";

type PostRoute = { POST: (req: Request) => Promise<Response> };

const INITIAL_B = Buffer.alloc(32, 0x62).toString("base64url");
const RECOVERY_C = Buffer.alloc(32, 0x63).toString("base64url");
const RECOVERY_I = Buffer.alloc(32, 0x69).toString("base64url");
const OTHER_B = Buffer.alloc(32, 0x64).toString("base64url");

function loginBody(
  email = "agent@example.com",
  password = "secret",
  initialRefreshToken = INITIAL_B,
): Record<string, string> {
  return {
    email,
    password,
    device_label: "Beta Mac",
    initial_refresh_token: initialRefreshToken,
  };
}

function signupBody(
  initialRefreshToken = INITIAL_B,
  password = "password123",
): Record<string, string> {
  return {
    email: "new.agent@example.com",
    password,
    first_name: "New",
    last_name: "Agent",
    device_label: "Beta Mac",
    initial_refresh_token: initialRefreshToken,
  };
}

function refreshRecoveryBody(): Record<string, string> {
  return {
    refresh_token: INITIAL_B,
    next_refresh_token: RECOVERY_C,
    refresh_attempt_id: RECOVERY_I,
  };
}

function assertCredentialFree(body: Record<string, unknown>): void {
  assert.equal("access_token" in body, false);
  assert.equal("refresh_token" in body, false);
  assert.equal("entitlement_assertion" in body, false);
}

describe("initial issuance v2 hosted routes", () => {
  it("issues and exactly replays login around the caller-proposed hash-only B", async () => {
    const db = useFakeDb();
    db.users.push(await makeUser());
    const route = await loadRoute<PostRoute>("auth/login");

    const first = await withTestEntitlementSigningRing(TEST_ENTITLEMENT_KEY_B, () =>
      route.POST(jsonRequest("/api/auth/login", loginBody())),
    );
    const firstBody = await responseJson(first);
    const replay = await withTestEntitlementSigningRing(TEST_ENTITLEMENT_KEY_B, () =>
      route.POST(jsonRequest("/api/auth/login", loginBody())),
    );
    const replayBody = await responseJson(replay);

    assert.equal(first.status, 200);
    assert.equal(replay.status, 200);
    assert.equal(firstBody.refresh_token, INITIAL_B);
    assert.equal(replayBody.refresh_token, INITIAL_B);
    assert.equal(firstBody.license_id, replayBody.license_id);
    assert.equal(db.licenses.length, 1);
    assert.equal(db.licenses[0].refresh_token_hash, refreshHash(INITIAL_B));
    assert.equal(db.licenses[0].initial_issuance_kind, null);
    assertEntitlementEnvelope(replayBody, {
      sub: db.users[0].id,
      license_id: db.licenses[0].id,
      email: db.users[0].email,
      tier: "pro",
      entitlements: ["real_estate_sales"],
      kid: TEST_ENTITLEMENT_KEY_B,
    });

    const persistedAndRpcText = JSON.stringify(db);
    assert.equal(persistedAndRpcText.includes(INITIAL_B), false);
    assert.equal(persistedAndRpcText.includes("\"password\":\"secret\""), false);
    const calls = db.calls.filter(
      (call) => call.table === "issue_existing_user_license_v2",
    );
    assert.equal(calls.length, 2);
    assert.deepEqual(
      Object.keys(calls[0].body as Record<string, unknown>).sort(),
      [
        "p_device_label",
        "p_expected_password_hash",
        "p_refresh_token_hash",
        "p_user_id",
      ],
    );
  });

  it("rejects malformed B before either login or signup can mutate", async () => {
    const malformed = Buffer.alloc(31, 0x62).toString("base64url");
    const loginDb = useFakeDb();
    loginDb.users.push(await makeUser());
    const login = await loadRoute<PostRoute>("auth/login");
    const loginResponse = await login.POST(
      jsonRequest("/api/auth/login", loginBody("agent@example.com", "secret", malformed)),
    );
    assert.equal(loginResponse.status, 400);
    assert.equal(loginDb.licenses.length, 0);
    assert.equal(
      loginDb.calls.some((call) => call.table === "issue_existing_user_license_v2"),
      false,
    );

    const signupDb = useFakeDb();
    const signup = await loadRoute<PostRoute>("auth/signup");
    const signupResponse = await signup.POST(
      jsonRequest("/api/auth/signup", signupBody(malformed)),
    );
    assert.equal(signupResponse.status, 400);
    assert.equal(signupDb.users.length, 0);
    assert.equal(signupDb.licenses.length, 0);
  });

  it("preflights the complete signer ring before either v2 mutation", async () => {
    const activeName = "ELEVATE_ENTITLEMENT_SIGNING_ACTIVE_KID";
    const ringName = "ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEYS_B64_JSON";
    const previousActive = process.env[activeName];
    const previousRing = process.env[ringName];
    const previousConsoleError = console.error;
    process.env[activeName] = TEST_ENTITLEMENT_KEY_A;
    Reflect.deleteProperty(process.env, ringName);
    console.error = () => {};
    try {
      const loginDb = useFakeDb();
      loginDb.users.push(await makeUser());
      const login = await loadRoute<PostRoute>("auth/login");
      const loginResponse = await login.POST(
        jsonRequest("/api/auth/login", loginBody()),
      );
      const loginResponseBody = await responseJson(loginResponse);
      assert.equal(loginResponse.status, 503);
      assertCredentialFree(loginResponseBody);
      assert.equal(loginDb.licenses.length, 0);
      assert.equal(
        loginDb.calls.some((call) => call.table === "issue_existing_user_license_v2"),
        false,
      );

      const signupDb = useFakeDb();
      const signup = await loadRoute<PostRoute>("auth/signup");
      const signupResponse = await signup.POST(
        jsonRequest("/api/auth/signup", signupBody()),
      );
      const signupResponseBody = await responseJson(signupResponse);
      assert.equal(signupResponse.status, 503);
      assertCredentialFree(signupResponseBody);
      assert.equal(signupDb.users.length, 0);
      assert.equal(signupDb.licenses.length, 0);
      assert.equal(
        signupDb.calls.some((call) => call.table === "signup_with_license_v2"),
        false,
      );
    } finally {
      console.error = previousConsoleError;
      if (previousActive === undefined) Reflect.deleteProperty(process.env, activeName);
      else process.env[activeName] = previousActive;
      if (previousRing === undefined) Reflect.deleteProperty(process.env, ringName);
      else process.env[ringName] = previousRing;
    }
  });

  it("fails closed when the password hash changes after route verification", async () => {
    const db = useFakeDb();
    const user = await makeUser();
    db.users.push(user);
    const route = await loadRoute<PostRoute>("auth/login");
    const gate = gateNextSupabaseRpc("issue_existing_user_license_v2");

    const pending = route.POST(jsonRequest("/api/auth/login", loginBody()));
    await gate.reached;
    user.password_hash = await bcrypt.hash("changed-secret", 4);
    gate.release();
    const response = await pending;
    const body = await responseJson(response);

    assert.equal(response.status, 401);
    assert.deepEqual(body, { error: "invalid credentials" });
    assertCredentialFree(body);
    assert.equal(db.licenses.length, 0);
  });

  it("converges concurrent same-B login and rejects a different-account collision", async () => {
    const db = useFakeDb();
    db.users.push(await makeUser());
    const route = await loadRoute<PostRoute>("auth/login");
    barrierNextSupabaseRpcs("issue_existing_user_license_v2", 2);
    const sameUser = await Promise.all([
      route.POST(jsonRequest("/api/auth/login", loginBody())),
      route.POST(jsonRequest("/api/auth/login", loginBody())),
    ]);
    const sameBodies = await Promise.all(sameUser.map(responseJson));
    assert.deepEqual(sameUser.map((response) => response.status), [200, 200]);
    assert.equal(sameBodies[0].license_id, sameBodies[1].license_id);
    assert.equal(db.licenses.length, 1);

    const collisionDb = useFakeDb();
    collisionDb.users.push(
      await makeUser({ id: "user-a", email: "a@example.com", password: "secret-a" }),
      await makeUser({ id: "user-b", email: "b@example.com", password: "secret-b" }),
    );
    barrierNextSupabaseRpcs("issue_existing_user_license_v2", 2);
    const collisions = await Promise.all([
      route.POST(
        jsonRequest("/api/auth/login", loginBody("a@example.com", "secret-a")),
      ),
      route.POST(
        jsonRequest("/api/auth/login", loginBody("b@example.com", "secret-b")),
      ),
    ]);
    const collisionBodies = await Promise.all(collisions.map(responseJson));
    assert.deepEqual(
      collisions.map((response) => response.status).sort(),
      [200, 409],
    );
    assert.equal(collisionDb.licenses.length, 1);
    assertCredentialFree(collisionBodies[collisions.findIndex((response) => response.status === 409)]);

    const betweenDb = useFakeDb();
    const primary = await makeUser({
      id: "between-primary",
      email: "agent@example.com",
      password: "secret",
    });
    const other = await makeUser({
      id: "between-other",
      email: "other@example.com",
      password: "other-secret",
    });
    betweenDb.users.push(primary, other);
    beforeNextInitialIssuanceInsert(() => {
      seedLicense({
        id: "other-surface-license",
        user_id: other.id,
        refresh_token_hash: refreshHash(INITIAL_B),
      });
    });
    const between = await route.POST(jsonRequest("/api/auth/login", loginBody()));
    const betweenBody = await responseJson(between);
    assert.equal(between.status, 409);
    assertCredentialFree(betweenBody);
    assert.equal(betweenDb.licenses.length, 1);
    assert.equal(betweenDb.licenses[0].user_id, other.id);
  });

  it("never reopens a revoked, expired, or rotated predecessor B", async () => {
    const route = await loadRoute<PostRoute>("auth/login");
    for (const state of ["revoked", "expired", "predecessor"] as const) {
      const db = useFakeDb();
      const user = await makeUser();
      db.users.push(user);
      const original = seedLicense({
        user_id: user.id,
        refresh_token_hash:
          state === "predecessor" ? refreshHash(RECOVERY_C) : refreshHash(INITIAL_B),
        previous_refresh_token_hash:
          state === "predecessor" ? refreshHash(INITIAL_B) : null,
        revoked: state === "revoked",
        refresh_family_expires_at:
          state === "expired"
            ? new Date(Date.now() - 1_000).toISOString()
            : new Date(Date.now() + 60_000).toISOString(),
      });

      const response = await route.POST(jsonRequest("/api/auth/login", loginBody()));
      const body = await responseJson(response);
      assert.equal(response.status, 409, state);
      assertCredentialFree(body);
      assert.equal(db.licenses.length, 1);
      assert.equal(db.licenses[0], original, state);
    }
  });

  it("atomically creates signup and permits only its exact replay-only proof", async () => {
    const db = useFakeDb();
    const route = await loadRoute<PostRoute>("auth/signup");
    const first = await withTestEntitlementSigningRing(TEST_ENTITLEMENT_KEY_B, () =>
      route.POST(jsonRequest("/api/auth/signup", signupBody())),
    );
    const firstBody = await responseJson(first);
    const replay = await withTestEntitlementSigningRing(TEST_ENTITLEMENT_KEY_B, () =>
      route.POST(jsonRequest("/api/auth/signup", signupBody())),
    );
    const replayBody = await responseJson(replay);

    assert.equal(first.status, 200);
    assert.equal(replay.status, 200);
    assert.equal(firstBody.created, true);
    assert.equal(replayBody.created, true);
    assert.equal(firstBody.refresh_token, INITIAL_B);
    assert.equal(replayBody.refresh_token, INITIAL_B);
    assert.equal(firstBody.license_id, replayBody.license_id);
    assert.equal(db.users.length, 1);
    assert.equal(db.licenses.length, 1);
    assert.equal(db.licenses[0].initial_issuance_kind, "signup");
    assert.equal(JSON.stringify(db).includes(INITIAL_B), false);

    const wrongPassword = await route.POST(
      jsonRequest("/api/auth/signup", signupBody(INITIAL_B, "wrong-password")),
    );
    const wrongBody = await responseJson(wrongPassword);
    assert.equal(wrongPassword.status, 409);
    assertCredentialFree(wrongBody);
    assert.equal(db.users.length, 1);
    assert.equal(db.licenses.length, 1);
  });

  it("never lets signup replay create a license or reuse a non-signup source", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "new.agent@example.com", password: "password123" });
    db.users.push(user);
    const route = await loadRoute<PostRoute>("auth/signup");

    const absent = await route.POST(jsonRequest("/api/auth/signup", signupBody()));
    const absentBody = await responseJson(absent);
    assert.equal(absent.status, 409);
    assertCredentialFree(absentBody);
    assert.equal(db.licenses.length, 0);

    seedLicense({
      user_id: user.id,
      refresh_token_hash: refreshHash(INITIAL_B),
      initial_issuance_kind: null,
    });
    const wrongSource = await route.POST(jsonRequest("/api/auth/signup", signupBody()));
    const wrongSourceBody = await responseJson(wrongSource);
    assert.equal(wrongSource.status, 409);
    assertCredentialFree(wrongSourceBody);
    assert.equal(db.licenses.length, 1);
  });

  it("never treats a rotated signup successor C as a fresh initial replay", async () => {
    const db = useFakeDb();
    const signup = await loadRoute<PostRoute>("auth/signup");
    const refresh = await loadRoute<PostRoute>("license/refresh");

    const created = await signup.POST(jsonRequest("/api/auth/signup", signupBody()));
    assert.equal(created.status, 200);
    const rotated = await refresh.POST(
      jsonRequest("/api/license/refresh", refreshRecoveryBody()),
    );
    assert.equal(rotated.status, 200);
    assert.equal(db.users.length, 1);
    assert.equal(db.licenses.length, 1);
    assert.equal(db.licenses[0].refresh_token_hash, refreshHash(RECOVERY_C));
    assert.equal(db.licenses[0].previous_refresh_token_hash, refreshHash(INITIAL_B));
    const beforeRetry = structuredClone(db.licenses[0]);

    const retry = await signup.POST(
      jsonRequest("/api/auth/signup", signupBody(RECOVERY_C)),
    );
    const retryBody = await responseJson(retry);
    assert.equal(retry.status, 409);
    assertCredentialFree(retryBody);
    assert.equal(db.users.length, 1);
    assert.equal(db.licenses.length, 1);
    assert.deepEqual(db.licenses[0], beforeRetry);
  });

  it("converges concurrent same-B signup and rejects a different-B email race", async () => {
    const route = await loadRoute<PostRoute>("auth/signup");
    const db = useFakeDb();
    barrierNextSupabaseRpcs("signup_with_license_v2", 2);
    const same = await Promise.all([
      route.POST(jsonRequest("/api/auth/signup", signupBody())),
      route.POST(jsonRequest("/api/auth/signup", signupBody())),
    ]);
    const sameBodies = await Promise.all(same.map(responseJson));
    assert.deepEqual(same.map((response) => response.status), [200, 200]);
    assert.equal(sameBodies[0].license_id, sameBodies[1].license_id);
    assert.equal(db.users.length, 1);
    assert.equal(db.licenses.length, 1);

    const conflictDb = useFakeDb();
    barrierNextSupabaseRpcs("signup_with_license_v2", 2);
    const different = await Promise.all([
      route.POST(jsonRequest("/api/auth/signup", signupBody(INITIAL_B))),
      route.POST(jsonRequest("/api/auth/signup", signupBody(OTHER_B))),
    ]);
    const differentBodies = await Promise.all(different.map(responseJson));
    assert.deepEqual(
      different.map((response) => response.status).sort(),
      [200, 409],
    );
    assert.equal(conflictDb.users.length, 1);
    assert.equal(conflictDb.licenses.length, 1);
    assertCredentialFree(differentBodies[different.findIndex((response) => response.status === 409)]);
  });

  it("rolls back every staged login/signup transaction failure", async () => {
    const loginDb = useFakeDb();
    loginDb.users.push(await makeUser());
    const login = await loadRoute<PostRoute>("auth/login");
    failNextAtomicInitialIssuance("login_after_license_insert");
    const loginResponse = await login.POST(jsonRequest("/api/auth/login", loginBody()));
    assert.equal(loginResponse.status, 503);
    assert.equal(loginDb.licenses.length, 0);

    const signup = await loadRoute<PostRoute>("auth/signup");
    for (const stage of [
      "signup_after_user_insert",
      "signup_after_license_insert",
    ] as const) {
      const signupDb = useFakeDb();
      failNextAtomicInitialIssuance(stage);
      const signupResponse = await signup.POST(
        jsonRequest("/api/auth/signup", signupBody()),
      );
      const signupResponseBody = await responseJson(signupResponse);
      assert.equal(signupResponse.status, 503, stage);
      assertCredentialFree(signupResponseBody);
      assert.equal(signupDb.users.length, 0, stage);
      assert.equal(signupDb.licenses.length, 0, stage);
    }
  });

  it("recovers post-RPC login and signup failures through Refresh v2 B to C", async () => {
    const loginDb = useFakeDb();
    const loginUser = await makeUser();
    loginDb.users.push(loginUser);
    const login = await loadRoute<PostRoute>("auth/login");
    const refresh = await loadRoute<PostRoute>("license/refresh");
    afterNextSupabaseRpc("issue_existing_user_license_v2", () =>
      failNextSupabaseSelect("users"),
    );
    const lostLogin = await login.POST(jsonRequest("/api/auth/login", loginBody()));
    const lostLoginBody = await responseJson(lostLogin);
    assert.equal(lostLogin.status, 503);
    assertCredentialFree(lostLoginBody);
    assert.equal(loginDb.licenses.length, 1);
    assert.equal(loginDb.licenses[0].refresh_token_hash, refreshHash(INITIAL_B));

    const recoveredLogin = await withTestEntitlementSigningRing(
      TEST_ENTITLEMENT_KEY_B,
      () =>
        refresh.POST(
          jsonRequest("/api/license/refresh", refreshRecoveryBody()),
        ),
    );
    const recoveredLoginBody = await responseJson(recoveredLogin);
    assert.equal(recoveredLogin.status, 200);
    assert.equal(recoveredLoginBody.refresh_token, RECOVERY_C);
    assert.equal(recoveredLoginBody.license_id, loginDb.licenses[0].id);
    assert.equal(loginDb.licenses.length, 1);
    assert.equal(loginDb.licenses[0].refresh_token_hash, refreshHash(RECOVERY_C));
    assert.equal(loginDb.licenses[0].previous_refresh_token_hash, refreshHash(INITIAL_B));

    const signupDb = useFakeDb();
    const signup = await loadRoute<PostRoute>("auth/signup");
    afterNextSupabaseRpc("signup_with_license_v2", () =>
      failNextSupabaseSelect("users"),
    );
    const lostSignup = await signup.POST(jsonRequest("/api/auth/signup", signupBody()));
    const lostSignupBody = await responseJson(lostSignup);
    assert.equal(lostSignup.status, 503);
    assertCredentialFree(lostSignupBody);
    assert.equal(signupDb.users.length, 1);
    assert.equal(signupDb.licenses.length, 1);
    assert.equal(signupDb.licenses[0].initial_issuance_kind, "signup");

    const recoveredSignup = await withTestEntitlementSigningRing(
      TEST_ENTITLEMENT_KEY_B,
      () =>
        refresh.POST(
          jsonRequest("/api/license/refresh", refreshRecoveryBody()),
        ),
    );
    const recoveredSignupBody = await responseJson(recoveredSignup);
    assert.equal(recoveredSignup.status, 200);
    assert.equal(recoveredSignupBody.refresh_token, RECOVERY_C);
    assert.equal(recoveredSignupBody.license_id, signupDb.licenses[0].id);
    assert.equal(signupDb.licenses.length, 1);
    assert.equal(signupDb.licenses[0].refresh_token_hash, refreshHash(RECOVERY_C));
  });

  it("preserves Stable v1 request behavior when no proposed B is present", async () => {
    const db = useFakeDb();
    db.users.push(await makeUser());
    const login = await loadRoute<PostRoute>("auth/login");
    const response = await login.POST(
      jsonRequest("/api/auth/login", {
        email: "agent@example.com",
        password: "secret",
      }),
    );
    const body = await responseJson(response);
    assert.equal(response.status, 200);
    assert.equal(typeof body.refresh_token, "string");
    assert.equal(db.licenses.length, 1);
    assert.equal(
      db.calls.some((call) => call.table === "issue_existing_user_license_v2"),
      false,
    );
    assert.equal(
      db.licenses[0].refresh_token_hash,
      crypto.createHash("sha256").update(String(body.refresh_token)).digest("hex"),
    );
  });
});
