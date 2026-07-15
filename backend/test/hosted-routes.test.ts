import assert from "node:assert/strict";
import crypto from "node:crypto";
import { describe, it } from "node:test";
import bcrypt from "bcryptjs";
import Stripe from "stripe";
import {
  afterNextSupabaseRpc,
  assertEntitlementEnvelope,
  assertNoRawDiagnosticsText,
  barrierNextDeviceGrantDecisions,
  barrierNextLoginCodeOperations,
  barrierNextMembershipOperations,
  barrierNextSupabasePatches,
  barrierNextSupabaseRpcs,
  createFakeDb,
  failNextAtomicDeviceApproval,
  failNextAtomicDeviceV2,
  failNextAtomicLoginCode,
  failNextAtomicMembership,
  failNextAtomicRefreshV2,
  failNextDeviceGrantInsertConflict,
  failNextSupabaseInsert,
  failNextSupabasePatch,
  failNextSupabaseSelect,
  gateNextSupabaseRpc,
  issueAccessToken,
  jsonRequest,
  loadRoute,
  makeUser,
  refreshHash,
  responseJson,
  seedLicense,
  TEST_ENTITLEMENT_KEY_B,
  useFakeDb,
  withTestEntitlementSigningRing,
} from "./route-harness";
import { ENTITLEMENT_ASSERTION_KEYSET_SHA256 } from "../src/lib/entitlement-assertion";

function patchStripeResource<T>(
  select: (stripe: Stripe) => Record<string, T>,
  method: string,
  impl: T,
): () => void {
  const stripe = new Stripe("sk_test_route_harness", {
    apiVersion: "2025-03-31.basil" as Stripe.LatestApiVersion,
  });
  const proto = Object.getPrototypeOf(select(stripe)) as Record<string, T>;
  const original = proto[method];
  proto[method] = impl;
  return () => {
    proto[method] = original;
  };
}

type PostRoute = { POST: (req: Request) => Promise<Response> };

const REFRESH_V2_B = Buffer.alloc(32, 0x42).toString("base64url");
const REFRESH_V2_C = Buffer.alloc(32, 0x43).toString("base64url");
const REFRESH_V2_D = Buffer.alloc(32, 0x44).toString("base64url");
const REFRESH_V2_I = Buffer.alloc(32, 0x49).toString("base64url");
const REFRESH_V2_J = Buffer.alloc(32, 0x4a).toString("base64url");

function refreshV2Body(
  current: string,
  successor = REFRESH_V2_B,
  attempt = REFRESH_V2_I,
): Record<string, string> {
  return {
    refresh_token: current,
    next_refresh_token: successor,
    refresh_attempt_id: attempt,
  };
}

function deviceV2StartBody(
  refreshToken = REFRESH_V2_B,
  deviceLabel = "Device v2 CLI",
): Record<string, string> {
  return {
    device_label: deviceLabel,
    proposed_refresh_token_hash: refreshHash(refreshToken),
  };
}

function deviceV2PollBody(
  startBody: Record<string, unknown>,
  refreshToken = REFRESH_V2_B,
): Record<string, string> {
  return {
    device_code: String(startBody.device_code),
    refresh_token: refreshToken,
  };
}

function assertCredentialFree(body: Record<string, unknown>): void {
  assert.equal("access_token" in body, false);
  assert.equal("refresh_token" in body, false);
  assert.equal("entitlement_assertion" in body, false);
}

const ENTITLEMENT_SIGNING_ENV_NAMES = [
  "ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64",
  "ELEVATE_ENTITLEMENT_SIGNING_ACTIVE_KID",
  "ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEYS_B64_JSON",
] as const;

async function withEntitlementSigningEnvironment<T>(
  values: Partial<Record<(typeof ENTITLEMENT_SIGNING_ENV_NAMES)[number], string | undefined>>,
  run: () => Promise<T>,
): Promise<T> {
  const previous = Object.fromEntries(
    ENTITLEMENT_SIGNING_ENV_NAMES.map((name) => [name, process.env[name]]),
  ) as Record<(typeof ENTITLEMENT_SIGNING_ENV_NAMES)[number], string | undefined>;
  for (const name of ENTITLEMENT_SIGNING_ENV_NAMES) {
    if (!Object.prototype.hasOwnProperty.call(values, name)) continue;
    const value = values[name];
    if (value === undefined) Reflect.deleteProperty(process.env, name);
    else process.env[name] = value;
  }
  try {
    return await run();
  } finally {
    for (const name of ENTITLEMENT_SIGNING_ENV_NAMES) {
      if (previous[name] === undefined) Reflect.deleteProperty(process.env, name);
      else process.env[name] = previous[name];
    }
  }
}

async function requestDevLoginCode(
  route: PostRoute,
  email: string,
  ip = "127.0.0.1",
): Promise<string> {
  const response = await route.POST(
    jsonRequest(
      "/api/auth/login-code/request",
      { email },
      { headers: { "x-forwarded-for": ip, "user-agent": "login-code-test" } },
    ),
  );
  const body = await responseJson(response);
  assert.equal(response.status, 200);
  const code = String((body.dev_only as { code?: string } | undefined)?.code || "");
  assert.match(code, /^\d{6}$/);
  return code;
}

async function approveDeviceV2Flow(input: {
  db: ReturnType<typeof useFakeDb>;
  user: Awaited<ReturnType<typeof makeUser>>;
  bearer: string;
  refreshToken?: string;
  deviceLabel?: string;
}) {
  const refreshToken = input.refreshToken ?? REFRESH_V2_B;
  const start = await loadRoute<PostRoute>("device/start");
  const approve = await loadRoute<PostRoute>("device/approve");
  const startResponse = await start.POST(
    jsonRequest(
      "/api/device/start",
      deviceV2StartBody(refreshToken, input.deviceLabel),
    ),
  );
  const startBody = await responseJson(startResponse);
  assert.equal(startResponse.status, 200);
  assert.equal(startBody.protocol_version, 2);

  const grant = input.db.device_grants.at(-1);
  assert.ok(grant);
  const approveResponse = await approve.POST(
    jsonRequest(
      "/api/device/approve",
      { user_code: startBody.user_code },
      { headers: { authorization: `Bearer ${input.bearer}` } },
    ),
  );
  assert.equal(approveResponse.status, 200);
  assert.deepEqual(await responseJson(approveResponse), { ok: true });
  assert.equal(grant.status, "approved");
  assert.equal(grant.refresh_token_plain, null);
  assert.equal(grant.proposed_refresh_token_hash, refreshHash(refreshToken));
  assert.equal(typeof grant.license_id, "string");
  const license = input.db.licenses.find(
    (candidate) => candidate.id === grant.license_id,
  );
  assert.ok(license);
  assert.equal(license.user_id, input.user.id);
  assert.equal(license.refresh_token_hash, refreshHash(refreshToken));
  return { startBody, grant, license };
}

function seedTestOrg(
  db: ReturnType<typeof useFakeDb>,
  input: { id: string; seatLimit: number; entitlements?: string[] },
) {
  const now = new Date().toISOString();
  const org = {
    id: input.id,
    slug: input.id,
    name: input.id,
    stripe_customer: null,
    tier: "pro" as const,
    status: "active" as const,
    current_period_end: null,
    entitlements: input.entitlements ?? [],
    seat_limit: input.seatLimit,
    created_at: now,
    updated_at: now,
  };
  db.organizations.push(org);
  return org;
}

function seedTestMembership(
  db: ReturnType<typeof useFakeDb>,
  org: ReturnType<typeof seedTestOrg>,
  userId: string,
  role: "owner" | "admin" | "member" = "member",
) {
  const membership = {
    id: `seed-membership-${org.id}-${userId}`,
    org_id: org.id,
    user_id: userId,
    role,
    created_at: new Date().toISOString(),
    organization: org,
  };
  db.memberships.push(membership);
  return membership;
}

function seedTestInvitation(
  db: ReturnType<typeof useFakeDb>,
  input: {
    id: string;
    orgId: string;
    email: string;
    token: string;
    role?: "owner" | "admin" | "member";
    invitedBy?: string | null;
  },
) {
  const invitation = {
    id: input.id,
    org_id: input.orgId,
    email: input.email.toLowerCase(),
    role: input.role ?? ("member" as const),
    token_hash: crypto.createHash("sha256").update(input.token).digest("hex"),
    invited_by: input.invitedBy ?? null,
    status: "pending" as const,
    expires_at: new Date(Date.now() + 60_000).toISOString(),
    accepted_at: null,
    accepted_user_id: null,
    created_at: new Date().toISOString(),
  };
  db.invitations.push(invitation);
  return invitation;
}

describe("hosted route handlers", () => {
  it("health route is directly callable", async () => {
    const route = await loadRoute<{ GET: () => Promise<Response> }>("health");

    const response = await route.GET();
    const body = await responseJson(response);

    assert.equal(response.status, 200);
    assert.deepEqual(body, {
      ok: true,
      service: "elevate-backend",
      backend_build_id: "development",
      entitlement_signer_ready: true,
      entitlement_signing_active_kid: "ent-2026-07-a",
      entitlement_public_keyset_sha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
      database_schema_ready: true,
      database_schema_contract: "elevate-hq-schema-readiness-v1",
      database_schema_version: "0020",
      initial_issuance_v2_ready: true,
    });

    await withTestEntitlementSigningRing(TEST_ENTITLEMENT_KEY_B, async () => {
      const ringResponse = await route.GET();
      assert.equal(ringResponse.status, 200);
      assert.deepEqual(await responseJson(ringResponse), {
        ok: true,
        service: "elevate-backend",
        backend_build_id: "development",
        entitlement_signer_ready: true,
        entitlement_signing_active_kid: TEST_ENTITLEMENT_KEY_B,
        entitlement_public_keyset_sha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
        database_schema_ready: true,
        database_schema_contract: "elevate-hq-schema-readiness-v1",
        database_schema_version: "0020",
        initial_issuance_v2_ready: true,
      });
    });
  });

  it("health is secret-safe and 503 for missing, partial, or malformed signer config", async () => {
    const route = await loadRoute<{ GET: () => Promise<Response> }>("health");
    const legacySecret = process.env.ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64;
    assert.equal(typeof legacySecret, "string");

    for (const scenario of [
      {
        values: {
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64: undefined,
          ELEVATE_ENTITLEMENT_SIGNING_ACTIVE_KID: undefined,
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEYS_B64_JSON: undefined,
        },
        activeKid: "ent-2026-07-a",
      },
      {
        values: {
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64: legacySecret,
          ELEVATE_ENTITLEMENT_SIGNING_ACTIVE_KID: "ent-2026-07-a",
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEYS_B64_JSON: undefined,
        },
        activeKid: "ent-2026-07-a",
      },
      {
        values: {
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64: legacySecret,
          ELEVATE_ENTITLEMENT_SIGNING_ACTIVE_KID: TEST_ENTITLEMENT_KEY_B,
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEYS_B64_JSON: "not-json",
        },
        activeKid: TEST_ENTITLEMENT_KEY_B,
      },
      {
        values: {
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64: legacySecret,
          ELEVATE_ENTITLEMENT_SIGNING_ACTIVE_KID:
            "unknown-value-that-must-not-be-reflected",
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEYS_B64_JSON: "{}",
        },
        activeKid: null,
      },
    ] as const) {
      await withEntitlementSigningEnvironment(scenario.values, async () => {
        const response = await route.GET();
        const body = await responseJson(response);
        assert.equal(response.status, 503);
        assert.deepEqual(body, {
          ok: false,
          service: "elevate-backend",
          backend_build_id: "development",
          entitlement_signer_ready: false,
          entitlement_signing_active_kid: scenario.activeKid,
          entitlement_public_keyset_sha256: ENTITLEMENT_ASSERTION_KEYSET_SHA256,
          database_schema_ready: true,
          database_schema_contract: "elevate-hq-schema-readiness-v1",
          database_schema_version: "0020",
          initial_issuance_v2_ready: true,
        });
        assert.equal(JSON.stringify(body).includes(String(legacySecret)), false);
      });
    }
  });

  it("health is 503 when the read-only 0011-0020 schema probe cannot run", async () => {
    const route = await loadRoute<{ GET: () => Promise<Response> }>("health");
    const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
    Reflect.deleteProperty(process.env, "SUPABASE_SERVICE_ROLE_KEY");
    try {
      const response = await route.GET();
      const body = await responseJson(response);
      assert.equal(response.status, 503);
      assert.equal(body.ok, false);
      assert.equal(body.entitlement_signer_ready, true);
      assert.equal(body.database_schema_ready, false);
      assert.equal(
        body.database_schema_contract,
        "elevate-hq-schema-readiness-v1",
      );
      assert.equal(body.database_schema_version, "0020");
      assert.equal(body.initial_issuance_v2_ready, false);
    } finally {
      if (serviceRoleKey !== undefined) {
        process.env.SUPABASE_SERVICE_ROLE_KEY = serviceRoleKey;
      }
    }
  });

  it("login returns the desktop token envelope for an active user", async () => {
    const db = useFakeDb();
    db.users.push(await makeUser());
    const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("auth/login");

    const response = await withTestEntitlementSigningRing(
      TEST_ENTITLEMENT_KEY_B,
      () =>
        route.POST(
          jsonRequest("/api/auth/login", {
            email: "agent@example.com",
            password: "secret",
            device_label: "MacBook",
          }),
        ),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 200);
    assert.equal(typeof body.access_token, "string");
    assert.equal(typeof body.refresh_token, "string");
    assert.equal(body.license_id, "license-1");
    assert.equal(body.tier, "pro");
    assert.deepEqual(body.entitlements, ["real_estate_sales"]);
    assert.deepEqual(body.orgs, []);
    assert.equal(body.expires_in, 3600);
    assert.equal(db.licenses[0].device_label, "MacBook");
    assertEntitlementEnvelope(body, {
      sub: "user-1",
      license_id: "license-1",
      email: "agent@example.com",
      tier: "pro",
      entitlements: ["real_estate_sales"],
      kid: TEST_ENTITLEMENT_KEY_B,
    });
  });

  it("login maps an inactive subscription to 402", async () => {
    const db = useFakeDb();
    db.users.push(await makeUser({ status: "inactive" }));
    const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("auth/login");

    const response = await route.POST(
      jsonRequest("/api/auth/login", {
        email: "agent@example.com",
        password: "secret",
      }),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 402);
    assert.deepEqual(body, { error: "no active subscription" });
    assert.equal(db.licenses.length, 0);
  });

  it("signup, forgot, and reset issue tokens then revoke sessions", async () => {
    const previousNodeEnv = process.env.NODE_ENV;
    const previousMailjetKey = process.env.MAILJET_API_KEY;
    const previousMailjetSecret = process.env.MAILJET_API_SECRET;
    const previousMailFrom = process.env.MAIL_FROM;
    Reflect.set(process.env, "NODE_ENV", "test");
    Reflect.deleteProperty(process.env, "MAILJET_API_KEY");
    Reflect.deleteProperty(process.env, "MAILJET_API_SECRET");
    Reflect.deleteProperty(process.env, "MAIL_FROM");
    try {
      const db = useFakeDb();
      const signup = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("auth/signup");
      const forgot = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("auth/forgot");
      const reset = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("auth/reset");

      const signupResponse = await withTestEntitlementSigningRing(
        TEST_ENTITLEMENT_KEY_B,
        () =>
          signup.POST(
            jsonRequest("/api/auth/signup", {
              email: "New.Agent@Example.COM",
              password: "old-secret",
              device_label: "New Mac",
            }),
          ),
      );
      const signupBody = await responseJson(signupResponse);

      assert.equal(signupResponse.status, 200);
      assert.equal(signupBody.created, true);
      assert.equal(typeof signupBody.access_token, "string");
      assert.equal(typeof signupBody.refresh_token, "string");
      assert.equal(signupBody.license_id, "license-1");
      assert.deepEqual(signupBody.entitlements, []);
      assert.equal(db.users.length, 1);
      assert.equal(db.users[0].email, "new.agent@example.com");
      assert.deepEqual(db.users[0].entitlements, []);
      assert.equal(db.licenses.length, 1);
      assert.equal(db.licenses[0].revoked, false);
      assertEntitlementEnvelope(signupBody, {
        sub: "user-1",
        license_id: "license-1",
        email: "new.agent@example.com",
        tier: "pro",
        entitlements: [],
        kid: TEST_ENTITLEMENT_KEY_B,
      });

      const originalHash = db.users[0].password_hash;
      const forgotResponse = await forgot.POST(
        jsonRequest(
          "/api/auth/forgot",
          { email: "new.agent@example.com", app: true },
          { headers: { "x-forwarded-for": "127.0.0.2", "user-agent": "desktop-app" } },
        ),
      );
      const forgotBody = await responseJson(forgotResponse);
      const devOnly = forgotBody.dev_only as { token?: string; reset_url?: string } | undefined;

      assert.equal(forgotResponse.status, 200);
      assert.equal(forgotBody.ok, true);
      assert.equal(db.password_reset_tokens.length, 1);
      assert.equal(db.password_reset_tokens[0].user_id, db.users[0].id);
      assert.equal(
        db.password_reset_tokens[0].token_hash,
        crypto.createHash("sha256").update(String(devOnly?.token)).digest("hex"),
      );
      assert.match(String(devOnly?.reset_url), /app=1$/);
      assert.equal(
        (db.audit_log as Array<{ action?: string }>).at(-1)?.action,
        "password.reset_requested",
      );

      const resetResponse = await reset.POST(
        jsonRequest("/api/auth/reset", {
          token: devOnly?.token,
          new_password: "new-secret",
        }),
      );
      const resetBody = await responseJson(resetResponse);

      assert.equal(resetResponse.status, 200);
      assert.deepEqual(resetBody, { ok: true, email: "new.agent@example.com" });
      assert.equal(db.licenses[0].revoked, true);
      assert.equal(typeof db.password_reset_tokens[0].consumed_at, "string");
      assert.notEqual(db.users[0].password_hash, originalHash);
      assert.equal(await bcrypt.compare("new-secret", db.users[0].password_hash), true);
      assert.equal(
        (db.audit_log as Array<{ action?: string }>).at(-1)?.action,
        "password.reset_completed",
      );
    } finally {
      if (previousNodeEnv === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
      else Reflect.set(process.env, "NODE_ENV", previousNodeEnv);
      if (previousMailjetKey === undefined) Reflect.deleteProperty(process.env, "MAILJET_API_KEY");
      else Reflect.set(process.env, "MAILJET_API_KEY", previousMailjetKey);
      if (previousMailjetSecret === undefined) Reflect.deleteProperty(process.env, "MAILJET_API_SECRET");
      else Reflect.set(process.env, "MAILJET_API_SECRET", previousMailjetSecret);
      if (previousMailFrom === undefined) Reflect.deleteProperty(process.env, "MAIL_FROM");
      else Reflect.set(process.env, "MAIL_FROM", previousMailFrom);
    }
  });

  it("forgot fails visibly in production when reset email cannot be delivered", async () => {
    const previousNodeEnv = process.env.NODE_ENV;
    const previousMailjetKey = process.env.MAILJET_API_KEY;
    const previousMailjetSecret = process.env.MAILJET_API_SECRET;
    const previousMailFrom = process.env.MAIL_FROM;
    Reflect.set(process.env, "NODE_ENV", "production");
    Reflect.deleteProperty(process.env, "MAILJET_API_KEY");
    Reflect.deleteProperty(process.env, "MAILJET_API_SECRET");
    Reflect.deleteProperty(process.env, "MAIL_FROM");
    try {
      const db = useFakeDb();
      db.users.push(await makeUser({ email: "agent@example.com" }));
      const forgot = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("auth/forgot");

      const response = await forgot.POST(
        jsonRequest("/api/auth/forgot", { email: "agent@example.com" }),
      );
      const body = await responseJson(response);

      assert.equal(response.status, 503);
      assert.deepEqual(body, { error: "password reset email unavailable" });
      assert.equal(db.password_reset_tokens.length, 0);
    } finally {
      if (previousNodeEnv === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
      else Reflect.set(process.env, "NODE_ENV", previousNodeEnv);
      if (previousMailjetKey === undefined) Reflect.deleteProperty(process.env, "MAILJET_API_KEY");
      else Reflect.set(process.env, "MAILJET_API_KEY", previousMailjetKey);
      if (previousMailjetSecret === undefined) Reflect.deleteProperty(process.env, "MAILJET_API_SECRET");
      else Reflect.set(process.env, "MAILJET_API_SECRET", previousMailjetSecret);
      if (previousMailFrom === undefined) Reflect.deleteProperty(process.env, "MAIL_FROM");
      else Reflect.set(process.env, "MAIL_FROM", previousMailFrom);
    }
  });

  it("reset leaves token retryable when the password write fails", async () => {
    const db = useFakeDb();
    const user = await makeUser();
    db.users.push(user);
    const license = seedLicense({ id: "reset-license", user_id: user.id });
    const token = "retryable-reset-token";
    db.password_reset_tokens.push({
      id: "reset-token-1",
      user_id: user.id,
      token_hash: crypto.createHash("sha256").update(token).digest("hex"),
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      consumed_at: null,
      ip_addr: null,
      user_agent: null,
    });
    const reset = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("auth/reset");

    failNextSupabasePatch("users");
    await assert.rejects(
      () =>
        reset.POST(
          jsonRequest("/api/auth/reset", {
            token,
            new_password: "new-secret",
          }),
        ),
      (error: unknown) =>
        typeof error === "object" &&
        error !== null &&
        "message" in error &&
        error.message === "supabase patch failed",
    );

    assert.equal(license.revoked, true);
    assert.equal(db.password_reset_tokens[0].consumed_at, null);
    assert.equal(db.users[0].password_hash, user.password_hash);
  });

  it("license refresh rotates active tokens and revokes inactive licenses", async () => {
    const db = useFakeDb();
    const active = await makeUser({ id: "active-user", email: "active@example.com" });
    const inactive = await makeUser({
      id: "inactive-user",
      email: "inactive@example.com",
      status: "inactive",
    });
    db.users.push(active, inactive);
    const activeLicense = seedLicense({
      id: "active-license",
      user_id: active.id,
      refresh_token_hash: refreshHash("old-refresh"),
    });
    const inactiveLicense = seedLicense({
      id: "inactive-license",
      user_id: inactive.id,
      refresh_token_hash: refreshHash("inactive-refresh"),
    });
    const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("license/refresh");

    const okResponse = await withTestEntitlementSigningRing(
      TEST_ENTITLEMENT_KEY_B,
      () =>
        route.POST(
          jsonRequest("/api/license/refresh", { refresh_token: "old-refresh" }),
        ),
    );
    const okBody = await responseJson(okResponse);

    assert.equal(okResponse.status, 200);
    assert.equal(typeof okBody.access_token, "string");
    assert.equal(typeof okBody.refresh_token, "string");
    assert.equal(okBody.tier, "pro");
    assert.deepEqual(okBody.entitlements, ["real_estate_sales"]);
    assert.notEqual(activeLicense.refresh_token_hash, refreshHash("old-refresh"));
    assert.equal(activeLicense.previous_refresh_token_hash, refreshHash("old-refresh"));
    assert.equal(activeLicense.previous_refresh_attempt_hash, null);
    assert.equal(activeLicense.revoked, false);
    assertEntitlementEnvelope(okBody, {
      sub: active.id,
      license_id: activeLicense.id,
      email: active.email,
      tier: "pro",
      entitlements: ["real_estate_sales"],
      kid: TEST_ENTITLEMENT_KEY_B,
    });

    const inactiveResponse = await route.POST(
      jsonRequest("/api/license/refresh", { refresh_token: "inactive-refresh" }),
    );
    const inactiveBody = await responseJson(inactiveResponse);

    assert.equal(inactiveResponse.status, 402);
    assert.deepEqual(inactiveBody, { error: "subscription inactive" });
    assert.equal(inactiveLicense.revoked, true);
  });

  it("license refresh has one winner when the same token is used concurrently", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "refresh-race-user", email: "race@example.com" });
    db.users.push(user);
    const oldHash = refreshHash("shared-refresh");
    const license = seedLicense({
      id: "refresh-race-license",
      user_id: user.id,
      refresh_token_hash: oldHash,
    });
    const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "license/refresh",
    );

    barrierNextSupabasePatches("licenses");
    const responses = await Promise.all([
      route.POST(jsonRequest("/api/license/refresh", { refresh_token: "shared-refresh" })),
      route.POST(jsonRequest("/api/license/refresh", { refresh_token: "shared-refresh" })),
    ]);
    const results = await Promise.all(
      responses.map(async (response) => ({ response, body: await responseJson(response) })),
    );
    const winners = results.filter(({ response }) => response.status === 200);
    const losers = results.filter(({ response }) => response.status === 401);

    assert.equal(winners.length, 1);
    assert.equal(losers.length, 1);
    assert.equal(license.refresh_token_hash, refreshHash(String(winners[0].body.refresh_token)));
    assert.notEqual(license.refresh_token_hash, oldHash);
    assert.deepEqual(losers[0].body, { error: "invalid or revoked refresh token" });
    assert.equal("access_token" in losers[0].body, false);
    assert.equal("refresh_token" in losers[0].body, false);
    assert.equal("entitlement_assertion" in losers[0].body, false);
  });

  it("legacy license refresh obeys the persisted absolute family deadline", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "expired-refresh-user" });
    db.users.push(user);
    const license = seedLicense({
      id: "expired-refresh-license",
      user_id: user.id,
      refresh_token_hash: refreshHash("expired-refresh"),
      created_at: new Date().toISOString(),
      refresh_family_expires_at: new Date(Date.now() - 1000).toISOString(),
    });
    const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "license/refresh",
    );

    const response = await route.POST(
      jsonRequest("/api/license/refresh", { refresh_token: "expired-refresh" }),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 401);
    assert.deepEqual(body, { error: "invalid or revoked refresh token" });
    assert.equal("access_token" in body, false);
    assert.equal("refresh_token" in body, false);
    assert.equal("entitlement_assertion" in body, false);
    assert.equal(license.revoked, true);
    assert.equal(license.refresh_token_hash, refreshHash("expired-refresh"));
  });

  it("refresh v2 requires paired canonical 32-byte base64url values", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "refresh-v2-contract-user" });
    db.users.push(user);
    const current = "refresh-v2-contract-current";
    const license = seedLicense({
      id: "refresh-v2-contract-license",
      user_id: user.id,
      refresh_token_hash: refreshHash(current),
    });
    const route = await loadRoute<PostRoute>("license/refresh");

    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    const canonicalFinalIndex = alphabet.indexOf(REFRESH_V2_B.at(-1) || "");
    assert.equal(canonicalFinalIndex % 4, 0);
    const badPaddingBits = `${REFRESH_V2_B.slice(0, -1)}${alphabet[canonicalFinalIndex + 1]}`;
    assert.equal(
      Buffer.from(badPaddingBits, "base64url").equals(
        Buffer.from(REFRESH_V2_B, "base64url"),
      ),
      true,
    );

    const responses = await Promise.all([
      route.POST(
        jsonRequest("/api/license/refresh", {
          refresh_token: current,
          next_refresh_token: REFRESH_V2_B,
        }),
      ),
      route.POST(
        jsonRequest(
          "/api/license/refresh",
          refreshV2Body(current, badPaddingBits, REFRESH_V2_I),
        ),
      ),
      route.POST(
        jsonRequest(
          "/api/license/refresh",
          refreshV2Body(current, REFRESH_V2_B, badPaddingBits),
        ),
      ),
    ]);

    for (const response of responses) {
      assert.equal(response.status, 400);
      assert.deepEqual(await responseJson(response), { error: "bad request" });
    }
    assert.equal(
      db.calls.filter((call) => call.table === "rotate_license_refresh_v2").length,
      0,
    );
    assert.equal(license.refresh_token_hash, refreshHash(current));
    assert.equal(license.previous_refresh_token_hash, null);
    assert.equal(license.last_used_at, null);
  });

  it("refresh v2 rotates once and recovers a discarded response by exact retry", async () => {
    const db = useFakeDb();
    const user = await makeUser({
      id: "refresh-v2-recovery-user",
      email: "refresh-v2-recovery@example.com",
    });
    db.users.push(user);
    const current = "refresh-v2-recovery-current";
    const license = seedLicense({
      id: "refresh-v2-recovery-license",
      user_id: user.id,
      refresh_token_hash: refreshHash(current),
    });
    const familyExpiry = license.refresh_family_expires_at;
    const route = await loadRoute<PostRoute>("license/refresh");

    const firstResponse = await withTestEntitlementSigningRing(
      TEST_ENTITLEMENT_KEY_B,
      () => route.POST(jsonRequest("/api/license/refresh", refreshV2Body(current))),
    );
    const firstBody = await responseJson(firstResponse);
    assert.equal(firstResponse.status, 200);
    assert.equal(firstBody.refresh_token, REFRESH_V2_B);
    assertEntitlementEnvelope(firstBody, {
      sub: user.id,
      license_id: license.id,
      email: user.email,
      tier: "pro",
      entitlements: ["real_estate_sales"],
      kid: TEST_ENTITLEMENT_KEY_B,
    });
    assert.equal(license.refresh_token_hash, refreshHash(REFRESH_V2_B));
    assert.equal(license.previous_refresh_token_hash, refreshHash(current));
    assert.equal(license.previous_refresh_attempt_hash, refreshHash(REFRESH_V2_I));
    assert.equal(license.refresh_family_expires_at, familyExpiry);

    // Treat the first successful response as lost and send the durable A/B/I
    // marker again. The refresh bearer is identical; access/assertion is new.
    const retryResponse = await withTestEntitlementSigningRing(
      TEST_ENTITLEMENT_KEY_B,
      () => route.POST(jsonRequest("/api/license/refresh", refreshV2Body(current))),
    );
    const retryBody = await responseJson(retryResponse);
    assert.equal(retryResponse.status, 200);
    assert.equal(retryBody.refresh_token, REFRESH_V2_B);
    assertEntitlementEnvelope(retryBody, {
      sub: user.id,
      license_id: license.id,
      email: user.email,
      tier: "pro",
      entitlements: ["real_estate_sales"],
      kid: TEST_ENTITLEMENT_KEY_B,
    });
    assert.notEqual(retryBody.entitlement_assertion, firstBody.entitlement_assertion);
    assert.equal(license.refresh_token_hash, refreshHash(REFRESH_V2_B));
    assert.equal(license.previous_refresh_token_hash, refreshHash(current));
    assert.equal(license.previous_refresh_attempt_hash, refreshHash(REFRESH_V2_I));
    assert.equal(license.revoked, false);
  });

  it("refresh v2 serializes identical concurrent requests as rotation plus replay", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "refresh-v2-identical-user" });
    db.users.push(user);
    const current = "refresh-v2-identical-current";
    const license = seedLicense({
      id: "refresh-v2-identical-license",
      user_id: user.id,
      refresh_token_hash: refreshHash(current),
    });
    const route = await loadRoute<PostRoute>("license/refresh");

    barrierNextSupabaseRpcs("rotate_license_refresh_v2");
    const responses = await Promise.all([
      route.POST(jsonRequest("/api/license/refresh", refreshV2Body(current))),
      route.POST(jsonRequest("/api/license/refresh", refreshV2Body(current))),
    ]);
    const bodies = await Promise.all(responses.map(responseJson));

    assert.deepEqual(responses.map((response) => response.status), [200, 200]);
    assert.deepEqual(bodies.map((body) => body.refresh_token), [REFRESH_V2_B, REFRESH_V2_B]);
    assert.equal(license.refresh_token_hash, refreshHash(REFRESH_V2_B));
    assert.equal(license.previous_refresh_token_hash, refreshHash(current));
    assert.equal(license.previous_refresh_attempt_hash, refreshHash(REFRESH_V2_I));
    assert.equal(license.revoked, false);
  });

  it("refresh v2 makes a concurrent different B/I request credential-free and revokes", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "refresh-v2-different-race-user" });
    db.users.push(user);
    const current = "refresh-v2-different-race-current";
    const license = seedLicense({
      id: "refresh-v2-different-race-license",
      user_id: user.id,
      refresh_token_hash: refreshHash(current),
    });
    const route = await loadRoute<PostRoute>("license/refresh");

    barrierNextSupabaseRpcs("rotate_license_refresh_v2");
    const responses = await Promise.all([
      route.POST(jsonRequest("/api/license/refresh", refreshV2Body(current))),
      route.POST(
        jsonRequest(
          "/api/license/refresh",
          refreshV2Body(current, REFRESH_V2_D, REFRESH_V2_J),
        ),
      ),
    ]);
    const results = await Promise.all(
      responses.map(async (response) => ({ response, body: await responseJson(response) })),
    );
    const winner = results.find(({ response }) => response.status === 200);
    const conflict = results.find(({ response }) => response.status === 401);

    assert.ok(winner);
    assert.ok(conflict);
    assertCredentialFree(conflict.body);
    assert.equal(license.revoked, true);
    assert.ok(
      [refreshHash(REFRESH_V2_B), refreshHash(REFRESH_V2_D)].includes(
        license.refresh_token_hash,
      ),
    );
    assert.equal(license.previous_refresh_token_hash, refreshHash(current));
  });

  it("refresh v2 revokes predecessor reuse when either B or I differs", async () => {
    const route = await loadRoute<PostRoute>("license/refresh");
    for (const scenario of [
      { name: "successor", successor: REFRESH_V2_D, attempt: REFRESH_V2_I },
      { name: "attempt", successor: REFRESH_V2_B, attempt: REFRESH_V2_J },
    ]) {
      const db = useFakeDb();
      const user = await makeUser({ id: `refresh-v2-${scenario.name}-user` });
      db.users.push(user);
      const current = `refresh-v2-${scenario.name}-current`;
      const license = seedLicense({
        id: `refresh-v2-${scenario.name}-license`,
        user_id: user.id,
        refresh_token_hash: refreshHash(current),
      });

      const first = await route.POST(
        jsonRequest("/api/license/refresh", refreshV2Body(current)),
      );
      assert.equal(first.status, 200);

      const conflict = await route.POST(
        jsonRequest(
          "/api/license/refresh",
          refreshV2Body(current, scenario.successor, scenario.attempt),
        ),
      );
      const body = await responseJson(conflict);
      assert.equal(conflict.status, 401);
      assert.deepEqual(body, { error: "invalid or revoked refresh token" });
      assertCredentialFree(body);
      assert.equal(license.revoked, true);
    }
  });

  it("refresh v2 never lets an A retry roll a later B to C rotation back", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "refresh-v2-later-user" });
    db.users.push(user);
    const current = "refresh-v2-later-current";
    const license = seedLicense({
      id: "refresh-v2-later-license",
      user_id: user.id,
      refresh_token_hash: refreshHash(current),
    });
    const route = await loadRoute<PostRoute>("license/refresh");

    assert.equal(
      (
        await route.POST(jsonRequest("/api/license/refresh", refreshV2Body(current)))
      ).status,
      200,
    );
    assert.equal(
      (
        await route.POST(
          jsonRequest(
            "/api/license/refresh",
            refreshV2Body(REFRESH_V2_B, REFRESH_V2_C, REFRESH_V2_J),
          ),
        )
      ).status,
      200,
    );

    const staleRetry = await route.POST(
      jsonRequest("/api/license/refresh", refreshV2Body(current)),
    );
    const staleBody = await responseJson(staleRetry);
    assert.equal(staleRetry.status, 401);
    assertCredentialFree(staleBody);
    assert.equal(license.refresh_token_hash, refreshHash(REFRESH_V2_C));
    assert.equal(license.previous_refresh_token_hash, refreshHash(REFRESH_V2_B));
    assert.equal(license.previous_refresh_attempt_hash, refreshHash(REFRESH_V2_J));
    assert.equal(license.revoked, false);
  });

  it("refresh v2 enforces family expiry on first execution and exact replay", async () => {
    const route = await loadRoute<PostRoute>("license/refresh");

    const firstDb = useFakeDb();
    const firstUser = await makeUser({ id: "refresh-v2-expired-first-user" });
    firstDb.users.push(firstUser);
    const firstCurrent = "refresh-v2-expired-first-current";
    const firstLicense = seedLicense({
      id: "refresh-v2-expired-first-license",
      user_id: firstUser.id,
      refresh_token_hash: refreshHash(firstCurrent),
      refresh_family_expires_at: new Date(Date.now() - 1000).toISOString(),
    });
    const firstResponse = await route.POST(
      jsonRequest("/api/license/refresh", refreshV2Body(firstCurrent)),
    );
    const firstBody = await responseJson(firstResponse);
    assert.equal(firstResponse.status, 401);
    assertCredentialFree(firstBody);
    assert.equal(firstLicense.revoked, true);
    assert.equal(firstLicense.refresh_token_hash, refreshHash(firstCurrent));

    const replayDb = useFakeDb();
    const replayUser = await makeUser({ id: "refresh-v2-expired-replay-user" });
    replayDb.users.push(replayUser);
    const replayCurrent = "refresh-v2-expired-replay-current";
    const replayLicense = seedLicense({
      id: "refresh-v2-expired-replay-license",
      user_id: replayUser.id,
      refresh_token_hash: refreshHash(replayCurrent),
    });
    assert.equal(
      (
        await route.POST(
          jsonRequest("/api/license/refresh", refreshV2Body(replayCurrent)),
        )
      ).status,
      200,
    );
    replayLicense.refresh_family_expires_at = new Date(Date.now() - 1000).toISOString();
    const replayResponse = await route.POST(
      jsonRequest("/api/license/refresh", refreshV2Body(replayCurrent)),
    );
    const replayBody = await responseJson(replayResponse);
    assert.equal(replayResponse.status, 401);
    assertCredentialFree(replayBody);
    assert.equal(replayLicense.revoked, true);
    assert.equal(replayLicense.refresh_token_hash, refreshHash(REFRESH_V2_B));
  });

  it("refresh v2 rolls back an RPC failure and succeeds on the next first execution", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "refresh-v2-rollback-user" });
    db.users.push(user);
    const current = "refresh-v2-rollback-current";
    const originalHash = refreshHash(current);
    const license = seedLicense({
      id: "refresh-v2-rollback-license",
      user_id: user.id,
      refresh_token_hash: originalHash,
    });
    const route = await loadRoute<PostRoute>("license/refresh");

    failNextAtomicRefreshV2("after_rotation");
    const failed = await route.POST(
      jsonRequest("/api/license/refresh", refreshV2Body(current)),
    );
    const failedBody = await responseJson(failed);
    assert.equal(failed.status, 503);
    assert.deepEqual(failedBody, { error: "license refresh unavailable" });
    assertCredentialFree(failedBody);
    assert.equal(license.refresh_token_hash, originalHash);
    assert.equal(license.previous_refresh_token_hash, null);
    assert.equal(license.previous_refresh_attempt_hash, null);
    assert.equal(license.last_used_at, null);

    const retry = await route.POST(
      jsonRequest("/api/license/refresh", refreshV2Body(current)),
    );
    assert.equal(retry.status, 200);
    assert.equal((await responseJson(retry)).refresh_token, REFRESH_V2_B);
  });

  it("refresh v2 recovers after a post-RPC issuance failure", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "refresh-v2-post-rpc-user" });
    db.users.push(user);
    const current = "refresh-v2-post-rpc-current";
    const license = seedLicense({
      id: "refresh-v2-post-rpc-license",
      user_id: user.id,
      refresh_token_hash: refreshHash(current),
    });
    const route = await loadRoute<PostRoute>("license/refresh");

    failNextSupabaseSelect("users");
    const failed = await route.POST(
      jsonRequest("/api/license/refresh", refreshV2Body(current)),
    );
    const failedBody = await responseJson(failed);
    assert.equal(failed.status, 503);
    assert.deepEqual(failedBody, { error: "license issuance unavailable" });
    assertCredentialFree(failedBody);
    assert.equal(license.refresh_token_hash, refreshHash(REFRESH_V2_B));
    assert.equal(license.previous_refresh_token_hash, refreshHash(current));

    const retry = await route.POST(
      jsonRequest("/api/license/refresh", refreshV2Body(current)),
    );
    const retryBody = await responseJson(retry);
    assert.equal(retry.status, 200);
    assert.equal(retryBody.refresh_token, REFRESH_V2_B);
    assert.equal(license.revoked, false);
  });

  it("refresh v2 signer preflight performs zero database mutation or RPC", async () => {
    const previousKey = process.env.ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64;
    const previousConsoleError = console.error;
    console.error = () => {};
    try {
      process.env.ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64 = "malformed signing key";
      const db = useFakeDb();
      const user = await makeUser({ id: "refresh-v2-preflight-user" });
      db.users.push(user);
      const current = "refresh-v2-preflight-current";
      const license = seedLicense({
        id: "refresh-v2-preflight-license",
        user_id: user.id,
        refresh_token_hash: refreshHash(current),
      });
      const route = await loadRoute<PostRoute>("license/refresh");

      const response = await route.POST(
        jsonRequest("/api/license/refresh", refreshV2Body(current)),
      );
      const body = await responseJson(response);
      assert.equal(response.status, 503);
      assert.deepEqual(body, { error: "license issuance unavailable" });
      assertCredentialFree(body);
      assert.equal(
        db.calls.filter((call) => call.table === "rotate_license_refresh_v2").length,
        0,
      );
      assert.equal(license.refresh_token_hash, refreshHash(current));
      assert.equal(license.previous_refresh_token_hash, null);
      assert.equal(license.last_used_at, null);
    } finally {
      if (previousKey === undefined) {
        Reflect.deleteProperty(process.env, "ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64");
      } else {
        process.env.ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64 = previousKey;
      }
      console.error = previousConsoleError;
    }
  });

  it("refresh v2 refuses successors colliding with current or recovery hashes", async () => {
    const route = await loadRoute<PostRoute>("license/refresh");
    for (const collisionSlot of ["current", "previous"] as const) {
      const db = useFakeDb();
      const user = await makeUser({ id: `refresh-v2-collision-${collisionSlot}-user` });
      db.users.push(user);
      const current = `refresh-v2-collision-${collisionSlot}-source`;
      const source = seedLicense({
        id: `refresh-v2-collision-${collisionSlot}-source-license`,
        user_id: user.id,
        refresh_token_hash: refreshHash(current),
      });
      const other = seedLicense({
        id: `refresh-v2-collision-${collisionSlot}-other-license`,
        user_id: user.id,
        refresh_token_hash:
          collisionSlot === "current"
            ? refreshHash(REFRESH_V2_B)
            : refreshHash("refresh-v2-collision-other-current"),
        previous_refresh_token_hash:
          collisionSlot === "previous" ? refreshHash(REFRESH_V2_B) : null,
        previous_refresh_attempt_hash:
          collisionSlot === "previous" ? refreshHash(REFRESH_V2_J) : null,
      });

      const response = await route.POST(
        jsonRequest("/api/license/refresh", refreshV2Body(current)),
      );
      const body = await responseJson(response);
      assert.equal(response.status, 401);
      assert.deepEqual(body, { error: "invalid or revoked refresh token" });
      assertCredentialFree(body);
      assert.equal(source.revoked, true);
      assert.equal(source.refresh_token_hash, refreshHash(current));
      assert.equal(source.previous_refresh_token_hash, null);
      assert.equal(other.revoked, false);
    }
  });

  it("every issuance route fails with zero credential mutation for a partial ring", async () => {
    const legacyKey = process.env.ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64;
    assert.equal(typeof legacyKey, "string");
    const previousConsoleError = console.error;
    console.error = () => {};
    try {
      await withEntitlementSigningEnvironment(
        {
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64: legacyKey,
          ELEVATE_ENTITLEMENT_SIGNING_ACTIVE_KID: "ent-2026-07-a",
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEYS_B64_JSON: undefined,
        },
        async () => {
          const loginDb = useFakeDb();
          loginDb.users.push(await makeUser());
          const login = await loadRoute<PostRoute>("auth/login");
          const loginResponse = await login.POST(
            jsonRequest("/api/auth/login", {
              email: "agent@example.com",
              password: "secret",
            }),
          );
          const loginBody = await responseJson(loginResponse);
          assert.equal(loginResponse.status, 503);
          assert.deepEqual(loginBody, { error: "license issuance unavailable" });
          assertCredentialFree(loginBody);
          assert.equal(loginDb.licenses.length, 0);

          const signupDb = useFakeDb();
          const signup = await loadRoute<PostRoute>("auth/signup");
          const signupResponse = await signup.POST(
            jsonRequest("/api/auth/signup", {
              email: "signer-unavailable@example.com",
              password: "password-1",
            }),
          );
          const signupBody = await responseJson(signupResponse);
          assert.equal(signupResponse.status, 503);
          assert.deepEqual(signupBody, { error: "license issuance unavailable" });
          assertCredentialFree(signupBody);
          assert.equal(signupDb.users.length, 0);
          assert.equal(signupDb.licenses.length, 0);

          const refreshDb = useFakeDb();
          const active = await makeUser({ id: "refresh-order-user" });
          refreshDb.users.push(active);
          const originalHash = refreshHash("refresh-before-signing-error");
          const license = seedLicense({
            id: "refresh-order-license",
            user_id: active.id,
            refresh_token_hash: originalHash,
          });
          const refresh = await loadRoute<PostRoute>("license/refresh");
          const refreshResponse = await refresh.POST(
            jsonRequest("/api/license/refresh", {
              refresh_token: "refresh-before-signing-error",
            }),
          );
          const refreshBody = await responseJson(refreshResponse);
          assert.equal(refreshResponse.status, 503);
          assert.deepEqual(refreshBody, { error: "license issuance unavailable" });
          assertCredentialFree(refreshBody);
          assert.equal(license.refresh_token_hash, originalHash);
          assert.equal(license.last_used_at, null);

          const inviteDb = useFakeDb();
          const invitee = await makeUser({
            id: "invite-signing-order-user",
            email: "invite-signing-order@example.com",
          });
          inviteDb.users.push(invitee);
          const inviteOrg = seedTestOrg(inviteDb, {
            id: "invite-signing-order-org",
            seatLimit: 1,
          });
          const invitation = seedTestInvitation(inviteDb, {
            id: "invite-signing-order-invite",
            orgId: inviteOrg.id,
            email: invitee.email,
            token: "invite-signing-order-token",
          });
          const accept = await loadRoute<PostRoute>("invitations/accept");
          const inviteResponse = await accept.POST(
            jsonRequest("/api/invitations/accept", { token: "invite-signing-order-token" }),
          );
          const inviteBody = await responseJson(inviteResponse);
          assert.equal(inviteResponse.status, 503);
          assert.deepEqual(inviteBody, { error: "license issuance unavailable" });
          assertCredentialFree(inviteBody);
          assert.equal(invitation.status, "pending");
          assert.equal(inviteDb.memberships.length, 0);
          assert.equal(inviteDb.licenses.length, 0);

          const codeDb = useFakeDb();
          const codeUser = await makeUser({
            id: "code-signing-order-user",
            email: "code-signing-order@example.com",
          });
          codeDb.users.push(codeUser);
          const code = "123456";
          codeDb.login_codes.push({
            id: "code-signing-order-code",
            user_id: codeUser.id,
            code_hash: crypto.createHash("sha256").update(code).digest("hex"),
            created_at: new Date().toISOString(),
            expires_at: new Date(Date.now() + 60_000).toISOString(),
            consumed_at: null,
            attempts: 0,
            ip_addr: null,
            user_agent: null,
          });
          const verifyCode = await loadRoute<PostRoute>("auth/login-code/verify");
          const codeResponse = await verifyCode.POST(
            jsonRequest("/api/auth/login-code/verify", {
              email: codeUser.email,
              code,
            }),
          );
          const codeBody = await responseJson(codeResponse);
          assert.equal(codeResponse.status, 503);
          assert.deepEqual(codeBody, { error: "license issuance unavailable" });
          assertCredentialFree(codeBody);
          assert.equal(codeDb.login_codes[0].consumed_at, null);
          assert.equal(codeDb.login_codes[0].attempts, 0);
          assert.equal(codeDb.licenses.length, 0);

          const deviceDb = useFakeDb();
          const deviceUser = await makeUser({ id: "device-signing-order-user" });
          deviceDb.users.push(deviceUser);
          const browserLicense = seedLicense({
            id: "device-signing-order-browser",
            user_id: deviceUser.id,
          });
          const bearer = await issueAccessToken(deviceUser, browserLicense);
          const start = await loadRoute<PostRoute>("device/start");
          const approve = await loadRoute<PostRoute>("device/approve");
          const poll = await loadRoute<PostRoute>("device/poll");
          const startBody = await responseJson(
            await start.POST(
              jsonRequest("/api/device/start", { device_label: "Signer unavailable CLI" }),
            ),
          );
          assert.equal(
            (
              await approve.POST(
                jsonRequest(
                  "/api/device/approve",
                  { user_code: startBody.user_code },
                  { headers: { authorization: `Bearer ${bearer}` } },
                ),
              )
            ).status,
            200,
          );
          const grant = deviceDb.device_grants[0];
          const stashedRefresh = grant.refresh_token_plain;
          const deviceLicense = deviceDb.licenses.find(
            (candidate) => candidate.id !== browserLicense.id,
          );
          assert.ok(deviceLicense);
          const pollResponse = await poll.POST(
            jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
          );
          const pollBody = await responseJson(pollResponse);
          assert.equal(pollResponse.status, 503);
          assert.deepEqual(pollBody, { error: "license issuance unavailable" });
          assertCredentialFree(pollBody);
          assert.equal(grant.status, "approved");
          assert.equal(grant.refresh_token_plain, stashedRefresh);
          assert.equal(deviceLicense.revoked, false);
          assert.equal(deviceLicense.last_used_at, null);
        },
      );
    } finally {
      console.error = previousConsoleError;
    }
  });

  it("self-service license routes read and revoke only the caller's sessions", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "license-user", email: "license@example.com" });
    const other = await makeUser({ id: "other-user", email: "other@example.com" });
    db.users.push(user, other);
    const current = seedLicense({ id: "current-license", user_id: user.id });
    const laptop = seedLicense({ id: "laptop-license", user_id: user.id, device_label: "Laptop" });
    const revoked = seedLicense({ id: "revoked-license", user_id: user.id, revoked: true });
    const otherLicense = seedLicense({ id: "other-license", user_id: other.id });
    const bearer = await issueAccessToken(user, current);
    const headers = { authorization: `Bearer ${bearer}` };
    const list = await loadRoute<{ GET: (req: Request) => Promise<Response> }>("me/licenses");
    const revoke = await loadRoute<{
      DELETE: (req: Request, ctx: { params: Promise<{ id: string }> }) => Promise<Response>;
    }>("me/licenses/[id]");

    const listResponse = await list.GET(
      jsonRequest("/api/me/licenses", {}, { method: "GET", headers }),
    );
    const listBody = await responseJson(listResponse);

    assert.equal(listResponse.status, 200);
    assert.equal(listBody.current_license_id, current.id);
    assert.deepEqual(
      (listBody.licenses as Array<{ id: string }>).map((license) => license.id).sort(),
      [current.id, laptop.id],
    );

    const crossUser = await revoke.DELETE(
      jsonRequest("/api/me/licenses/other-license", {}, { method: "DELETE", headers }),
      { params: Promise.resolve({ id: otherLicense.id }) },
    );
    const crossUserBody = await responseJson(crossUser);

    assert.equal(crossUser.status, 404);
    assert.deepEqual(crossUserBody, { error: "not_found" });
    assert.equal(otherLicense.revoked, false);

    const own = await revoke.DELETE(
      jsonRequest("/api/me/licenses/laptop-license", {}, { method: "DELETE", headers }),
      { params: Promise.resolve({ id: laptop.id }) },
    );
    const ownBody = await responseJson(own);

    assert.equal(own.status, 200);
    assert.deepEqual(ownBody, { ok: true });
    assert.equal(current.revoked, false);
    assert.equal(laptop.revoked, true);
    assert.equal(revoked.revoked, true);
    assert.equal(otherLicense.revoked, false);
    assert.equal(
      (db.audit_log as Array<{ action?: string }>).at(-1)?.action,
      "license.self_revoked",
    );
  });

  it("sign out everywhere revokes sibling sessions but keeps the current one", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "session-user", email: "sessions@example.com" });
    const other = await makeUser({ id: "other-session-user", email: "other-session@example.com" });
    db.users.push(user, other);
    const current = seedLicense({ id: "keep-license", user_id: user.id });
    const stale = seedLicense({ id: "stale-license", user_id: user.id });
    const otherLicense = seedLicense({ id: "other-user-license", user_id: other.id });
    const bearer = await issueAccessToken(user, current);
    const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "me/sign-out-everywhere",
    );

    const response = await route.POST(
      jsonRequest(
        "/api/me/sign-out-everywhere",
        {},
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 200);
    assert.deepEqual(body, { ok: true });
    assert.equal(current.revoked, false);
    assert.equal(stale.revoked, true);
    assert.equal(otherLicense.revoked, false);
    assert.equal(
      (db.audit_log as Array<{ action?: string }>).at(-1)?.action,
      "license.sign_out_everywhere",
    );
  });

  it("account email changes still succeed when audit logging fails", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "email-change-user", email: "old-email@example.com" });
    db.users.push(user);
    const license = seedLicense({ id: "email-change-license", user_id: user.id });
    const bearer = await issueAccessToken(user, license);
    const route = await loadRoute<{ PATCH: (req: Request) => Promise<Response> }>("me/email");
    failNextSupabaseInsert("audit_log");

    const response = await route.PATCH(
      jsonRequest(
        "/api/me/email",
        { email: "New-Email@Example.COM", password: "secret" },
        { method: "PATCH", headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 200);
    assert.deepEqual(body, { ok: true, email: "new-email@example.com" });
    assert.equal(user.email, "new-email@example.com");
    assert.equal(db.audit_log.length, 0);
  });

  it("account password changes still succeed when audit logging fails", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "password-change-user", email: "password-change@example.com" });
    db.users.push(user);
    const license = seedLicense({ id: "password-change-license", user_id: user.id });
    const bearer = await issueAccessToken(user, license);
    const route = await loadRoute<{ PATCH: (req: Request) => Promise<Response> }>("me/password");
    failNextSupabaseInsert("audit_log");

    const response = await route.PATCH(
      jsonRequest(
        "/api/me/password",
        { current_password: "secret", new_password: "new-secret" },
        { method: "PATCH", headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 200);
    assert.deepEqual(body, { ok: true });
    assert.equal(await bcrypt.compare("new-secret", user.password_hash), true);
    assert.equal(db.audit_log.length, 0);
  });

  it("stripe subscription webhooks do not grant pro for unknown prices", async () => {
    const previousSecretKey = process.env.STRIPE_SECRET_KEY;
    const previousWebhookSecret = process.env.STRIPE_WEBHOOK_SECRET;
    const previousBuilderPrice = process.env.STRIPE_PRICE_BUILDER_MONTHLY;
    const previousProPrice = process.env.STRIPE_PRICE_PRO_MONTHLY;
    Reflect.set(process.env, "STRIPE_SECRET_KEY", "sk_test_route_harness");
    Reflect.set(process.env, "STRIPE_WEBHOOK_SECRET", "whsec_route_harness");
    Reflect.set(process.env, "STRIPE_PRICE_BUILDER_MONTHLY", "price_builder");
    Reflect.set(process.env, "STRIPE_PRICE_PRO_MONTHLY", "price_pro");
    try {
      const db = useFakeDb();
      const user = await makeUser({
        id: "billing-user",
        email: "billing@example.com",
        status: "inactive",
        tier: "builder",
        stripe_customer: "cus_unknown_price",
      });
      db.users.push(user);
      const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
        "stripe/webhook",
      );
      const payload = JSON.stringify({
        id: "evt_unknown_price",
        object: "event",
        type: "customer.subscription.updated",
        data: {
          object: {
            id: "sub_unknown_price",
            object: "subscription",
            customer: "cus_unknown_price",
            status: "active",
            current_period_end: 1_800_000_000,
            items: {
              object: "list",
              data: [{ price: { id: "price_not_configured" } }],
            },
          },
        },
      });
      const signature = Stripe.webhooks.generateTestHeaderString({
        payload,
        secret: "whsec_route_harness",
      });

      const response = await route.POST(
        new Request("https://app.test/api/stripe/webhook", {
          method: "POST",
          headers: { "stripe-signature": signature },
          body: payload,
        }),
      );
      const body = await responseJson(response);

      assert.equal(response.status, 200);
      assert.deepEqual(body, { received: true });
      assert.equal(db.users[0].tier, "builder");
      assert.equal(db.users[0].status, "inactive");
      assert.equal(db.users[0].current_period_end, null);
    } finally {
      if (previousSecretKey === undefined) Reflect.deleteProperty(process.env, "STRIPE_SECRET_KEY");
      else Reflect.set(process.env, "STRIPE_SECRET_KEY", previousSecretKey);
      if (previousWebhookSecret === undefined) Reflect.deleteProperty(process.env, "STRIPE_WEBHOOK_SECRET");
      else Reflect.set(process.env, "STRIPE_WEBHOOK_SECRET", previousWebhookSecret);
      if (previousBuilderPrice === undefined) Reflect.deleteProperty(process.env, "STRIPE_PRICE_BUILDER_MONTHLY");
      else Reflect.set(process.env, "STRIPE_PRICE_BUILDER_MONTHLY", previousBuilderPrice);
      if (previousProPrice === undefined) Reflect.deleteProperty(process.env, "STRIPE_PRICE_PRO_MONTHLY");
      else Reflect.set(process.env, "STRIPE_PRICE_PRO_MONTHLY", previousProPrice);
    }
  });

  it("stripe checkout returns JSON when customer creation fails", async () => {
    const previousSecretKey = process.env.STRIPE_SECRET_KEY;
    const previousProPrice = process.env.STRIPE_PRICE_PRO_MONTHLY;
    Reflect.set(process.env, "STRIPE_SECRET_KEY", "sk_test_route_harness");
    Reflect.set(process.env, "STRIPE_PRICE_PRO_MONTHLY", "price_pro");
    const restore = patchStripeResource(
      (stripe) => stripe.customers as unknown as Record<string, unknown>,
      "create",
      async () => {
        throw new Error("stripe customer outage");
      },
    );
    try {
      const db = useFakeDb();
      const user = await makeUser({ id: "checkout-user", email: "checkout@example.com" });
      db.users.push(user);
      const license = seedLicense({ id: "checkout-license", user_id: user.id });
      const bearer = await issueAccessToken(user, license);
      const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("stripe/checkout");

      const response = await route.POST(
        jsonRequest(
          "/api/stripe/checkout",
          { plan: "pro" },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      );
      const body = await responseJson(response);

      assert.equal(response.status, 503);
      assert.deepEqual(body, { error: "checkout unavailable" });
      assert.equal(db.users[0].stripe_customer, null);
      assert.equal(db.audit_log.length, 0);
    } finally {
      restore();
      if (previousSecretKey === undefined) Reflect.deleteProperty(process.env, "STRIPE_SECRET_KEY");
      else Reflect.set(process.env, "STRIPE_SECRET_KEY", previousSecretKey);
      if (previousProPrice === undefined) Reflect.deleteProperty(process.env, "STRIPE_PRICE_PRO_MONTHLY");
      else Reflect.set(process.env, "STRIPE_PRICE_PRO_MONTHLY", previousProPrice);
    }
  });

  it("stripe checkout returns JSON when session creation fails", async () => {
    const previousSecretKey = process.env.STRIPE_SECRET_KEY;
    const previousProPrice = process.env.STRIPE_PRICE_PRO_MONTHLY;
    Reflect.set(process.env, "STRIPE_SECRET_KEY", "sk_test_route_harness");
    Reflect.set(process.env, "STRIPE_PRICE_PRO_MONTHLY", "price_pro");
    const restore = patchStripeResource(
      (stripe) => stripe.checkout.sessions as unknown as Record<string, unknown>,
      "create",
      async () => {
        throw new Error("stripe checkout outage");
      },
    );
    try {
      const db = useFakeDb();
      const user = await makeUser({
        id: "checkout-session-user",
        email: "checkout-session@example.com",
        stripe_customer: "cus_checkout_session",
      });
      db.users.push(user);
      const license = seedLicense({ id: "checkout-session-license", user_id: user.id });
      const bearer = await issueAccessToken(user, license);
      const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("stripe/checkout");

      const response = await route.POST(
        jsonRequest(
          "/api/stripe/checkout",
          { plan: "pro" },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      );
      const body = await responseJson(response);

      assert.equal(response.status, 503);
      assert.deepEqual(body, { error: "checkout unavailable" });
      assert.equal(db.audit_log.length, 0);
    } finally {
      restore();
      if (previousSecretKey === undefined) Reflect.deleteProperty(process.env, "STRIPE_SECRET_KEY");
      else Reflect.set(process.env, "STRIPE_SECRET_KEY", previousSecretKey);
      if (previousProPrice === undefined) Reflect.deleteProperty(process.env, "STRIPE_PRICE_PRO_MONTHLY");
      else Reflect.set(process.env, "STRIPE_PRICE_PRO_MONTHLY", previousProPrice);
    }
  });

  it("stripe checkout still returns a session when audit logging fails", async () => {
    const previousSecretKey = process.env.STRIPE_SECRET_KEY;
    const previousProPrice = process.env.STRIPE_PRICE_PRO_MONTHLY;
    Reflect.set(process.env, "STRIPE_SECRET_KEY", "sk_test_route_harness");
    Reflect.set(process.env, "STRIPE_PRICE_PRO_MONTHLY", "price_pro");
    const restore = patchStripeResource(
      (stripe) => stripe.checkout.sessions as unknown as Record<string, unknown>,
      "create",
      async () => ({ id: "cs_ok", url: "https://checkout.stripe.test/session" }),
    );
    try {
      const db = useFakeDb();
      const user = await makeUser({
        id: "checkout-audit-user",
        email: "checkout-audit@example.com",
        stripe_customer: "cus_checkout_audit",
      });
      db.users.push(user);
      const license = seedLicense({ id: "checkout-audit-license", user_id: user.id });
      const bearer = await issueAccessToken(user, license);
      failNextSupabaseInsert("audit_log");
      const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("stripe/checkout");

      const response = await route.POST(
        jsonRequest(
          "/api/stripe/checkout",
          { plan: "pro" },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      );
      const body = await responseJson(response);

      assert.equal(response.status, 200);
      assert.deepEqual(body, { url: "https://checkout.stripe.test/session" });
      assert.equal(db.audit_log.length, 0);
    } finally {
      restore();
      if (previousSecretKey === undefined) Reflect.deleteProperty(process.env, "STRIPE_SECRET_KEY");
      else Reflect.set(process.env, "STRIPE_SECRET_KEY", previousSecretKey);
      if (previousProPrice === undefined) Reflect.deleteProperty(process.env, "STRIPE_PRICE_PRO_MONTHLY");
      else Reflect.set(process.env, "STRIPE_PRICE_PRO_MONTHLY", previousProPrice);
    }
  });

  it("stripe portal returns JSON when session creation fails", async () => {
    const previousSecretKey = process.env.STRIPE_SECRET_KEY;
    Reflect.set(process.env, "STRIPE_SECRET_KEY", "sk_test_route_harness");
    const restore = patchStripeResource(
      (stripe) => stripe.billingPortal.sessions as unknown as Record<string, unknown>,
      "create",
      async () => {
        throw new Error("stripe portal outage");
      },
    );
    try {
      const db = useFakeDb();
      const user = await makeUser({
        id: "portal-user",
        email: "portal@example.com",
        stripe_customer: "cus_portal",
      });
      db.users.push(user);
      const license = seedLicense({ id: "portal-license", user_id: user.id });
      const bearer = await issueAccessToken(user, license);
      const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("stripe/portal");

      const response = await route.POST(
        jsonRequest(
          "/api/stripe/portal",
          {},
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      );
      const body = await responseJson(response);

      assert.equal(response.status, 503);
      assert.deepEqual(body, { error: "billing portal unavailable" });
      assert.equal(db.audit_log.length, 0);
    } finally {
      restore();
      if (previousSecretKey === undefined) Reflect.deleteProperty(process.env, "STRIPE_SECRET_KEY");
      else Reflect.set(process.env, "STRIPE_SECRET_KEY", previousSecretKey);
    }
  });

  it("account read routes return effective org access and gated catalogs", async () => {
    const db = useFakeDb();
    const user = await makeUser({ entitlements: [] });
    db.users.push(user);
    const license = seedLicense({ id: "account-license", user_id: user.id });
    const bearer = await issueAccessToken(user, license);
    const now = new Date().toISOString();
    const org = {
      id: "org-1",
      slug: "elevate-team",
      name: "Elevate Team",
      stripe_customer: null,
      tier: "pro" as const,
      status: "active" as const,
      current_period_end: null,
      entitlements: ["real_estate_cma", "real_estate_admin"],
      seat_limit: 3,
      created_at: now,
      updated_at: now,
    };
    db.memberships.push({
      id: "membership-1",
      org_id: org.id,
      user_id: user.id,
      role: "owner",
      created_at: now,
      organization: org,
    });
    db.skills.push(
      {
        name: "cma-report",
        version: 1,
        tier_required: "pro",
        manifest: { required_entitlement: "real_estate_cma" },
        body: "skill body",
        enabled: true,
        created_at: now,
        updated_at: now,
      },
      {
        name: "builder-only",
        version: 1,
        tier_required: "builder",
        manifest: {},
        body: "hidden",
        enabled: true,
        created_at: now,
        updated_at: now,
      },
    );
    db.automations.push({
      name: "admin-digest",
      surface: "real_estate",
      kind: "automation",
      schedule: "daily",
      skill: "admin",
      prompt: "Summarize admin work",
      deliver: "dashboard",
      spec: { paused: true },
      version: 1,
      tier_required: "pro",
      manifest: { required_entitlement: "real_estate_admin" },
      enabled: true,
      created_at: now,
      updated_at: now,
    });

    const headers = { authorization: `Bearer ${bearer}` };
    const me = await loadRoute<{ GET: (req: Request) => Promise<Response> }>("me");
    const orgs = await loadRoute<{ GET: (req: Request) => Promise<Response> }>("orgs");
    const skills = await loadRoute<{ GET: (req: Request) => Promise<Response> }>("skills/list");
    const automations = await loadRoute<{ GET: (req: Request) => Promise<Response> }>(
      "automations/list",
    );

    const meBody = await responseJson(
      await me.GET(jsonRequest("/api/me", {}, { method: "GET", headers })),
    );
    const orgsBody = await responseJson(
      await orgs.GET(jsonRequest("/api/orgs", {}, { method: "GET", headers })),
    );
    const skillsBody = await responseJson(
      await skills.GET(jsonRequest("/api/skills/list", {}, { method: "GET", headers })),
    );
    const automationsBody = await responseJson(
      await automations.GET(jsonRequest("/api/automations/list", {}, { method: "GET", headers })),
    );

    assert.equal(meBody.account_type, "team_owner");
    assert.deepEqual(meBody.billing, {
      has_customer: false,
      has_subscription: false,
      current_period_end: null,
      personal_tier: "pro",
      personal_status: "active",
    });
    assert.deepEqual(meBody.entitlements, ["real_estate_cma", "real_estate_admin"]);
    assert.deepEqual(
      (orgsBody.orgs as Array<{ slug: string; role: string }>).map((orgRow) => [orgRow.slug, orgRow.role]),
      [["elevate-team", "owner"]],
    );
    assert.deepEqual(
      (skillsBody.skills as Array<{ name: string }>).map((skill) => skill.name),
      ["cma-report"],
    );
    assert.deepEqual(
      (automationsBody.automations as Array<{ name: string }>).map((automation) => automation.name),
      ["admin-digest"],
    );
  });

  it("catalog list routes return JSON when hosted catalog reads fail", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "catalog-user", email: "catalog@example.com" });
    db.users.push(user);
    const license = seedLicense({ id: "catalog-license", user_id: user.id });
    const bearer = await issueAccessToken(user, license);
    const headers = { authorization: `Bearer ${bearer}` };
    const skills = await loadRoute<{ GET: (req: Request) => Promise<Response> }>("skills/list");
    const automations = await loadRoute<{ GET: (req: Request) => Promise<Response> }>(
      "automations/list",
    );

    failNextSupabaseSelect("skills");
    const skillsResponse = await skills.GET(
      jsonRequest("/api/skills/list", {}, { method: "GET", headers }),
    );
    assert.equal(skillsResponse.status, 503);
    assert.deepEqual(await responseJson(skillsResponse), { error: "skills catalog unavailable" });

    failNextSupabaseSelect("automations");
    const automationsResponse = await automations.GET(
      jsonRequest("/api/automations/list", {}, { method: "GET", headers }),
    );
    assert.equal(automationsResponse.status, 503);
    assert.deepEqual(await responseJson(automationsResponse), {
      error: "automations catalog unavailable",
    });
  });

  it("account billing distinguishes a Stripe customer from a subscription", async () => {
    const db = useFakeDb();
    const user = await makeUser({
      id: "customer-only-user",
      email: "customer-only@example.com",
      stripe_customer: "cus_no_subscription",
      current_period_end: null,
    });
    db.users.push(user);
    const license = seedLicense({ id: "customer-only-license", user_id: user.id });
    const bearer = await issueAccessToken(user, license);
    const me = await loadRoute<{ GET: (req: Request) => Promise<Response> }>("me");

    const response = await me.GET(
      jsonRequest("/api/me", {}, { method: "GET", headers: { authorization: `Bearer ${bearer}` } }),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 200);
    assert.deepEqual(body.billing, {
      has_customer: true,
      has_subscription: false,
      current_period_end: null,
      personal_tier: "pro",
      personal_status: "active",
    });
  });

  it("hosted bearer licenses must belong to the token user", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "token-user", email: "token-user@example.com" });
    const other = await makeUser({ id: "license-owner", email: "license-owner@example.com" });
    db.users.push(user, other);
    const otherLicense = seedLicense({ id: "other-user-license", user_id: other.id });
    const bearer = await issueAccessToken(user, otherLicense);
    const me = await loadRoute<{ GET: (req: Request) => Promise<Response> }>("me");

    const response = await me.GET(
      jsonRequest("/api/me", {}, { method: "GET", headers: { authorization: `Bearer ${bearer}` } }),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 403);
    assert.deepEqual(body, { error: "license revoked" });
    assert.equal(otherLicense.last_used_at, null);
  });

  it("admin namespace rejects missing bearer and non-admin callers", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "plain-user", email: "plain@example.com" });
    db.users.push(user);
    const license = seedLicense({ id: "plain-license", user_id: user.id });
    const bearer = await issueAccessToken(user, license);
    const cases = [
      { route: "admin/audit", method: "GET", path: "/api/admin/audit" },
      { route: "admin/search", method: "GET", path: "/api/admin/search?q=agent" },
      { route: "admin/users", method: "GET", path: "/api/admin/users" },
      {
        route: "admin/users/[id]",
        method: "PATCH",
        path: "/api/admin/users/plain-user",
        body: { tier: "builder" },
        params: { id: "plain-user" },
      },
      {
        route: "admin/users/[id]/licenses",
        method: "GET",
        path: "/api/admin/users/plain-user/licenses",
        params: { id: "plain-user" },
      },
      {
        route: "admin/users/[id]/licenses/[licenseId]",
        method: "DELETE",
        path: "/api/admin/users/plain-user/licenses/plain-license",
        params: { id: "plain-user", licenseId: "plain-license" },
      },
      { route: "admin/orgs", method: "GET", path: "/api/admin/orgs" },
      {
        route: "admin/orgs",
        method: "POST",
        path: "/api/admin/orgs",
        body: { slug: "matrix", name: "Matrix" },
      },
      {
        route: "admin/orgs/[id]",
        method: "GET",
        path: "/api/admin/orgs/org-1",
        params: { id: "org-1" },
      },
      {
        route: "admin/orgs/[id]",
        method: "PATCH",
        path: "/api/admin/orgs/org-1",
        body: { name: "Matrix" },
        params: { id: "org-1" },
      },
      {
        route: "admin/orgs/[id]",
        method: "DELETE",
        path: "/api/admin/orgs/org-1",
        params: { id: "org-1" },
      },
      {
        route: "admin/orgs/[id]/members",
        method: "POST",
        path: "/api/admin/orgs/org-1/members",
        body: { email: "member@example.com", role: "member" },
        params: { id: "org-1" },
      },
      {
        route: "admin/orgs/[id]/members/[userId]",
        method: "PATCH",
        path: "/api/admin/orgs/org-1/members/plain-user",
        body: { role: "member" },
        params: { id: "org-1", userId: "plain-user" },
      },
      {
        route: "admin/orgs/[id]/members/[userId]",
        method: "DELETE",
        path: "/api/admin/orgs/org-1/members/plain-user",
        params: { id: "org-1", userId: "plain-user" },
      },
    ] as const;

    for (const c of cases) {
      const route = await loadRoute<Record<string, (req: Request, ctx?: unknown) => Promise<Response>>>(
        c.route,
      );
      const call = (headers: Record<string, string> = {}) =>
        route[c.method](
          jsonRequest(c.path, "body" in c ? c.body : {}, { method: c.method, headers }),
          "params" in c ? { params: Promise.resolve(c.params) } : undefined,
        );

      const missing = await call();
      assert.equal(missing.status, 401, `${c.method} ${c.route} missing bearer`);
      assert.deepEqual(await responseJson(missing), { error: "missing bearer token" });

      const nonAdmin = await call({ authorization: `Bearer ${bearer}` });
      assert.equal(nonAdmin.status, 403, `${c.method} ${c.route} non-admin`);
      assert.deepEqual(await responseJson(nonAdmin), { error: "admin role required" });
    }
  });

  it("org seat limits block direct member adds and stale invite accepts", async () => {
    const db = useFakeDb();
    const admin = await makeUser({ id: "seat-admin", email: "seat-admin@example.com", role: "admin" });
    const owner = await makeUser({ id: "seat-owner", email: "seat-owner@example.com" });
    const target = await makeUser({ id: "seat-target", email: "seat-target@example.com" });
    const invitee = await makeUser({ id: "seat-invitee", email: "seat-invitee@example.com" });
    db.users.push(admin, owner, target, invitee);
    const adminLicense = seedLicense({ id: "seat-admin-license", user_id: admin.id });
    const bearer = await issueAccessToken(admin, adminLicense);
    const headers = { authorization: `Bearer ${bearer}` };
    const now = new Date().toISOString();
    const org = {
      id: "full-org",
      slug: "full-org",
      name: "Full Org",
      stripe_customer: null,
      tier: "pro" as const,
      status: "active" as const,
      current_period_end: null,
      entitlements: [],
      seat_limit: 1,
      created_at: now,
      updated_at: now,
    };
    db.organizations.push(org);
    db.memberships.push({
      id: "full-org-owner",
      org_id: org.id,
      user_id: owner.id,
      role: "owner",
      created_at: now,
      organization: org,
    });

    const memberRoute = await loadRoute<{
      POST: (req: Request, ctx: { params: Promise<{ id: string }> }) => Promise<Response>;
    }>("admin/orgs/[id]/members");
    const addResponse = await memberRoute.POST(
      jsonRequest(
        "/api/admin/orgs/full-org/members",
        { email: target.email, role: "member" },
        { headers },
      ),
      { params: Promise.resolve({ id: org.id }) },
    );
    const addBody = await responseJson(addResponse);

    assert.equal(addResponse.status, 409);
    assert.deepEqual(addBody, { error: "seat limit reached" });
    assert.equal(db.memberships.some((membership) => membership.user_id === target.id), false);

    const token = "full-seat-invite";
    db.invitations.push({
      id: "full-seat-invite",
      org_id: org.id,
      email: invitee.email,
      role: "member",
      token_hash: crypto.createHash("sha256").update(token).digest("hex"),
      invited_by: admin.id,
      status: "pending",
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      accepted_at: null,
      accepted_user_id: null,
      created_at: now,
    });
    const acceptRoute = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "invitations/accept",
    );
    const acceptResponse = await acceptRoute.POST(
      jsonRequest("/api/invitations/accept", { token }),
    );
    const acceptBody = await responseJson(acceptResponse);

    assert.equal(acceptResponse.status, 409);
    assert.deepEqual(acceptBody, { error: "seat limit reached" });
    assert.equal(db.invitations[0].status, "pending");
    assert.equal(db.memberships.some((membership) => membership.user_id === invitee.id), false);
  });

  it("invitation accept returns a signed entitlement envelope", async () => {
    const db = useFakeDb();
    const invitee = await makeUser({
      id: "signed-invitee",
      email: "Signed.Invitee@Example.com",
      entitlements: ["real_estate_sales", "real_estate_admin", "real_estate_sales"],
    });
    db.users.push(invitee);
    const now = new Date().toISOString();
    db.organizations.push({
      id: "signed-invite-org",
      slug: "signed-invite-org",
      name: "Signed Invite Org",
      stripe_customer: null,
      tier: "pro",
      status: "active",
      current_period_end: null,
      entitlements: ["real_estate_cma"],
      seat_limit: 2,
      created_at: now,
      updated_at: now,
    });
    const token = "signed-invitation-token";
    db.invitations.push({
      id: "signed-invitation",
      org_id: "signed-invite-org",
      email: invitee.email,
      role: "member",
      token_hash: crypto.createHash("sha256").update(token).digest("hex"),
      invited_by: null,
      status: "pending",
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      accepted_at: null,
      accepted_user_id: null,
      created_at: now,
    });
    const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "invitations/accept",
    );

    const response = await withTestEntitlementSigningRing(
      TEST_ENTITLEMENT_KEY_B,
      () => route.POST(jsonRequest("/api/invitations/accept", { token })),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 200);
    assert.equal(body.accepted, true);
    assert.equal(db.invitations[0].status, "accepted");
    assert.equal(db.memberships[0].user_id, invitee.id);
    assert.match(String(body.license_id), /^[0-9a-f-]{36}$/);
    assert.equal(db.licenses[0].id, body.license_id);
    assertEntitlementEnvelope(body, {
      sub: invitee.id,
      license_id: String(body.license_id),
      email: invitee.email,
      tier: "pro",
      entitlements: ["real_estate_admin", "real_estate_cma", "real_estate_sales"],
      kid: TEST_ENTITLEMENT_KEY_B,
    });
  });

  it("inactive invite accepts do not consume the invite or add membership", async () => {
    const db = useFakeDb();
    const admin = await makeUser({ id: "inactive-invite-admin", email: "inactive-invite-admin@example.com", role: "admin" });
    const owner = await makeUser({ id: "inactive-invite-owner", email: "inactive-invite-owner@example.com" });
    const invitee = await makeUser({
      id: "inactive-invitee",
      email: "inactive-invitee@example.com",
      status: "inactive",
    });
    db.users.push(admin, owner, invitee);
    const now = new Date().toISOString();
    const org = {
      id: "inactive-invite-org",
      slug: "inactive-invite-org",
      name: "Inactive Invite Org",
      stripe_customer: null,
      tier: "pro" as const,
      status: "active" as const,
      current_period_end: null,
      entitlements: [],
      seat_limit: 3,
      created_at: now,
      updated_at: now,
    };
    db.organizations.push(org);
    db.memberships.push({
      id: "inactive-invite-owner-membership",
      org_id: org.id,
      user_id: owner.id,
      role: "owner",
      created_at: now,
      organization: org,
    });
    const token = "inactive-invite-token";
    const invitation = {
      id: "inactive-invite",
      org_id: org.id,
      email: invitee.email,
      role: "member" as const,
      token_hash: crypto.createHash("sha256").update(token).digest("hex"),
      invited_by: admin.id,
      status: "pending" as const,
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      accepted_at: null,
      accepted_user_id: null,
      created_at: now,
    };
    db.invitations.push(invitation);
    const acceptRoute = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "invitations/accept",
    );

    const response = await acceptRoute.POST(
      jsonRequest("/api/invitations/accept", { token }),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 402);
    assert.deepEqual(body, { error: "no active subscription" });
    assert.equal(invitation.status, "pending");
    assert.equal(invitation.accepted_at, null);
    assert.equal(invitation.accepted_user_id, null);
    assert.equal(db.memberships.some((membership) => membership.user_id === invitee.id), false);
    assert.equal(db.licenses.some((license) => license.user_id === invitee.id), false);
  });

  it("concurrent invitations competing for the final seat have one winner", async () => {
    const db = useFakeDb();
    const owner = await makeUser({ id: "invite-race-owner", email: "invite-race-owner@example.com" });
    const first = await makeUser({ id: "invite-race-first", email: "invite-race-first@example.com" });
    const second = await makeUser({ id: "invite-race-second", email: "invite-race-second@example.com" });
    db.users.push(owner, first, second);
    const org = seedTestOrg(db, { id: "invite-final-seat-org", seatLimit: 2 });
    seedTestMembership(db, org, owner.id, "owner");
    seedTestInvitation(db, {
      id: "invite-final-seat-first",
      orgId: org.id,
      email: first.email,
      token: "invite-final-seat-token-first",
    });
    seedTestInvitation(db, {
      id: "invite-final-seat-second",
      orgId: org.id,
      email: second.email,
      token: "invite-final-seat-token-second",
    });
    const route = await loadRoute<PostRoute>("invitations/accept");

    barrierNextMembershipOperations();
    const responses = await Promise.all([
      route.POST(
        jsonRequest("/api/invitations/accept", { token: "invite-final-seat-token-first" }),
      ),
      route.POST(
        jsonRequest("/api/invitations/accept", { token: "invite-final-seat-token-second" }),
      ),
    ]);
    const bodies = await Promise.all(responses.map(responseJson));

    assert.deepEqual(responses.map((response) => response.status).sort(), [200, 409]);
    assert.equal(db.memberships.length, 2);
    assert.equal(db.licenses.length, 1);
    assert.equal(db.invitations.filter((invitation) => invitation.status === "accepted").length, 1);
    assert.equal(db.invitations.filter((invitation) => invitation.status === "pending").length, 1);
    const loser = bodies[responses.findIndex((response) => response.status === 409)];
    assert.deepEqual(loser, { error: "seat limit reached" });
  });

  it("concurrent direct add and invitation accept share the final-seat lock", async () => {
    const db = useFakeDb();
    const admin = await makeUser({ id: "mixed-seat-admin", email: "mixed-seat-admin@example.com", role: "admin" });
    const owner = await makeUser({ id: "mixed-seat-owner", email: "mixed-seat-owner@example.com" });
    const direct = await makeUser({ id: "mixed-seat-direct", email: "mixed-seat-direct@example.com" });
    const invitee = await makeUser({ id: "mixed-seat-invitee", email: "mixed-seat-invitee@example.com" });
    db.users.push(admin, owner, direct, invitee);
    const adminLicense = seedLicense({ id: "mixed-seat-admin-license", user_id: admin.id });
    const bearer = await issueAccessToken(admin, adminLicense);
    const org = seedTestOrg(db, { id: "mixed-final-seat-org", seatLimit: 2 });
    seedTestMembership(db, org, owner.id, "owner");
    const invitation = seedTestInvitation(db, {
      id: "mixed-final-seat-invite",
      orgId: org.id,
      email: invitee.email,
      token: "mixed-final-seat-token",
      invitedBy: admin.id,
    });
    const memberRoute = await loadRoute<{
      POST: (req: Request, ctx: { params: Promise<{ id: string }> }) => Promise<Response>;
    }>("admin/orgs/[id]/members");
    const inviteRoute = await loadRoute<PostRoute>("invitations/accept");

    barrierNextMembershipOperations();
    const [directResponse, inviteResponse] = await Promise.all([
      memberRoute.POST(
        jsonRequest(
          `/api/admin/orgs/${org.id}/members`,
          { email: direct.email, role: "member" },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
        { params: Promise.resolve({ id: org.id }) },
      ),
      inviteRoute.POST(
        jsonRequest("/api/invitations/accept", { token: "mixed-final-seat-token" }),
      ),
    ]);

    assert.deepEqual([directResponse.status, inviteResponse.status].sort(), [200, 409]);
    assert.equal(db.memberships.length, 2);
    const newMembers = db.memberships.filter((membership) => membership.user_id !== owner.id);
    assert.equal(newMembers.length, 1);
    if (inviteResponse.status === 200) {
      assert.equal(invitation.status, "accepted");
      assert.equal(db.licenses.filter((license) => license.user_id === invitee.id).length, 1);
      assert.equal(newMembers[0].user_id, invitee.id);
    } else {
      assert.equal(invitation.status, "pending");
      assert.equal(db.licenses.filter((license) => license.user_id === invitee.id).length, 0);
      assert.equal(newMembers[0].user_id, direct.id);
    }
  });

  it("concurrent acceptance of the same invitation creates one license", async () => {
    const db = useFakeDb();
    const owner = await makeUser({ id: "same-invite-owner", email: "same-invite-owner@example.com" });
    const invitee = await makeUser({ id: "same-invite-user", email: "same-invite-user@example.com" });
    db.users.push(owner, invitee);
    const org = seedTestOrg(db, { id: "same-invite-org", seatLimit: 2 });
    seedTestMembership(db, org, owner.id, "owner");
    seedTestInvitation(db, {
      id: "same-invite",
      orgId: org.id,
      email: invitee.email,
      token: "same-invite-token",
    });
    const route = await loadRoute<PostRoute>("invitations/accept");

    barrierNextMembershipOperations();
    const responses = await Promise.all([
      route.POST(jsonRequest("/api/invitations/accept", { token: "same-invite-token" })),
      route.POST(jsonRequest("/api/invitations/accept", { token: "same-invite-token" })),
    ]);

    assert.deepEqual(responses.map((response) => response.status).sort(), [200, 410]);
    assert.equal(db.memberships.filter((membership) => membership.user_id === invitee.id).length, 1);
    assert.equal(db.licenses.filter((license) => license.user_id === invitee.id).length, 1);
  });

  it("an already-member invite accepts safely even when every seat is occupied", async () => {
    const db = useFakeDb();
    const invitee = await makeUser({ id: "already-member-invitee", email: "already-member@example.com" });
    db.users.push(invitee);
    const org = seedTestOrg(db, { id: "already-member-invite-org", seatLimit: 1 });
    const existing = seedTestMembership(db, org, invitee.id, "admin");
    const invitation = seedTestInvitation(db, {
      id: "already-member-invite",
      orgId: org.id,
      email: invitee.email,
      token: "already-member-token",
      role: "member",
    });
    const route = await loadRoute<PostRoute>("invitations/accept");

    const response = await route.POST(
      jsonRequest("/api/invitations/accept", { token: "already-member-token" }),
    );

    assert.equal(response.status, 200);
    assert.equal(db.memberships.length, 1);
    assert.equal(existing.role, "admin");
    assert.equal(invitation.status, "accepted");
    assert.equal(db.licenses.length, 1);
  });

  for (const failureStage of [
    "invitation_after_user_insert",
    "invitation_after_membership_insert",
    "invitation_after_invitation_update",
    "invitation_after_license_insert",
  ] as const) {
    it(`invitation acceptance rolls back every write when ${failureStage} fails`, async () => {
      const db = useFakeDb();
      const org = seedTestOrg(db, { id: `${failureStage}-org`, seatLimit: 1 });
      const email = `${failureStage.replaceAll("_", "-")}@example.com`;
      const token = `${failureStage}-token`;
      const invitation = seedTestInvitation(db, {
        id: `${failureStage}-invite`,
        orgId: org.id,
        email,
        token,
      });
      const route = await loadRoute<PostRoute>("invitations/accept");

      failNextAtomicMembership(failureStage);
      const failed = await route.POST(
        jsonRequest("/api/invitations/accept", { token, password: "password123" }),
      );
      assert.equal(failed.status, 503);
      assert.deepEqual(await responseJson(failed), { error: "license issuance unavailable" });
      assert.equal(db.users.some((candidate) => candidate.email === email), false);
      assert.equal(db.memberships.length, 0);
      assert.equal(db.licenses.length, 0);
      assert.equal(invitation.status, "pending");
      assert.equal(invitation.accepted_at, null);
      assert.equal(invitation.accepted_user_id, null);

      const retry = await route.POST(
        jsonRequest("/api/invitations/accept", { token, password: "password123" }),
      );
      assert.equal(retry.status, 200);
      assert.equal(db.users.filter((candidate) => candidate.email === email).length, 1);
      assert.equal(db.memberships.length, 1);
      assert.equal(db.licenses.length, 1);
      assert.equal(invitation.status, "accepted");
      assert.equal(await bcrypt.compare("password123", db.users[0].password_hash), true);
    });
  }

  for (const failureStage of [
    "org_owner_after_org_insert",
    "org_owner_after_membership_insert",
  ] as const) {
    it(`self org creation rolls back org and owner when ${failureStage} fails`, async () => {
      const db = useFakeDb();
      const owner = await makeUser({
        id: `${failureStage}-owner`,
        email: `${failureStage.replaceAll("_", "-")}@example.com`,
      });
      db.users.push(owner);
      const license = seedLicense({ id: `${failureStage}-license`, user_id: owner.id });
      const bearer = await issueAccessToken(owner, license);
      const route = await loadRoute<PostRoute>("orgs");
      const slug = `${failureStage.replaceAll("_", "-")}-slug`;

      failNextAtomicMembership(failureStage);
      const failed = await route.POST(
        jsonRequest(
          "/api/orgs",
          { name: "Atomic Owner Org", slug },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      );
      assert.equal(failed.status, 400);
      assert.equal(db.organizations.length, 0);
      assert.equal(db.memberships.length, 0);

      const retry = await route.POST(
        jsonRequest(
          "/api/orgs",
          { name: "Atomic Owner Org", slug },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      );
      assert.equal(retry.status, 200);
      assert.equal(db.organizations.length, 1);
      assert.equal(db.memberships.length, 1);
      assert.equal(db.memberships[0].role, "owner");
      assert.equal(db.memberships[0].user_id, owner.id);
    });
  }

  it("admin org member mutations preserve an owner", async () => {
    const db = useFakeDb();
    const admin = await makeUser({ id: "owner-guard-admin", email: "owner-guard-admin@example.com", role: "admin" });
    const owner = await makeUser({ id: "owner-guard-owner", email: "owner-guard-owner@example.com" });
    db.users.push(admin, owner);
    const adminLicense = seedLicense({ id: "owner-guard-admin-license", user_id: admin.id });
    const bearer = await issueAccessToken(admin, adminLicense);
    const headers = { authorization: `Bearer ${bearer}` };
    const now = new Date().toISOString();
    const org = {
      id: "owner-guard-org",
      slug: "owner-guard-org",
      name: "Owner Guard Org",
      stripe_customer: null,
      tier: "pro" as const,
      status: "active" as const,
      current_period_end: null,
      entitlements: [],
      seat_limit: 2,
      created_at: now,
      updated_at: now,
    };
    db.organizations.push(org);
    db.memberships.push({
      id: "owner-guard-membership",
      org_id: org.id,
      user_id: owner.id,
      role: "owner",
      created_at: now,
      organization: org,
    });
    const route = await loadRoute<{
      PATCH: (
        req: Request,
        ctx: { params: Promise<{ id: string; userId: string }> },
      ) => Promise<Response>;
      DELETE: (
        req: Request,
        ctx: { params: Promise<{ id: string; userId: string }> },
      ) => Promise<Response>;
    }>("admin/orgs/[id]/members/[userId]");

    const demoteResponse = await route.PATCH(
      jsonRequest(
        "/api/admin/orgs/owner-guard-org/members/owner-guard-owner",
        { role: "member" },
        { method: "PATCH", headers },
      ),
      { params: Promise.resolve({ id: org.id, userId: owner.id }) },
    );
    const deleteResponse = await route.DELETE(
      jsonRequest(
        "/api/admin/orgs/owner-guard-org/members/owner-guard-owner",
        {},
        { method: "DELETE", headers },
      ),
      { params: Promise.resolve({ id: org.id, userId: owner.id }) },
    );

    assert.equal(demoteResponse.status, 409);
    assert.deepEqual(await responseJson(demoteResponse), { error: "org must keep an owner" });
    assert.equal(deleteResponse.status, 409);
    assert.deepEqual(await responseJson(deleteResponse), { error: "org must keep an owner" });
    assert.equal(db.memberships[0].role, "owner");
    assert.equal(db.memberships.length, 1);
    assert.equal(db.audit_log.length, 0);
  });

  it("admin org seat limit cannot be lowered below occupied seats", async () => {
    const db = useFakeDb();
    const admin = await makeUser({ id: "seat-limit-admin", email: "seat-limit-admin@example.com", role: "admin" });
    const owner = await makeUser({ id: "seat-limit-owner", email: "seat-limit-owner@example.com" });
    const member = await makeUser({ id: "seat-limit-member", email: "seat-limit-member@example.com" });
    db.users.push(admin, owner, member);
    const adminLicense = seedLicense({ id: "seat-limit-admin-license", user_id: admin.id });
    const bearer = await issueAccessToken(admin, adminLicense);
    const now = new Date().toISOString();
    const org = {
      id: "seat-limit-org",
      slug: "seat-limit-org",
      name: "Seat Limit Org",
      stripe_customer: null,
      tier: "pro" as const,
      status: "active" as const,
      current_period_end: null,
      entitlements: [],
      seat_limit: 2,
      created_at: now,
      updated_at: now,
    };
    db.organizations.push(org);
    db.memberships.push(
      {
        id: "seat-limit-owner-membership",
        org_id: org.id,
        user_id: owner.id,
        role: "owner" as const,
        created_at: now,
        organization: org,
      },
      {
        id: "seat-limit-member-membership",
        org_id: org.id,
        user_id: member.id,
        role: "member" as const,
        created_at: now,
        organization: org,
      },
    );
    const route = await loadRoute<{
      PATCH: (req: Request, ctx: { params: Promise<{ id: string }> }) => Promise<Response>;
    }>("admin/orgs/[id]");

    const response = await route.PATCH(
      jsonRequest(
        "/api/admin/orgs/seat-limit-org",
        { seat_limit: 1 },
        { method: "PATCH", headers: { authorization: `Bearer ${bearer}` } },
      ),
      { params: Promise.resolve({ id: org.id }) },
    );

    assert.equal(response.status, 409);
    assert.deepEqual(await responseJson(response), { error: "seat limit below occupied seats" });
    assert.equal(org.seat_limit, 2);
    assert.equal(db.audit_log.length, 0);
  });

  it("admin org audit rows include org_id", async () => {
    const db = useFakeDb();
    const admin = await makeUser({ id: "org-audit-admin", email: "org-audit-admin@example.com", role: "admin" });
    db.users.push(admin);
    const adminLicense = seedLicense({ id: "org-audit-admin-license", user_id: admin.id });
    const bearer = await issueAccessToken(admin, adminLicense);
    const headers = { authorization: `Bearer ${bearer}` };
    const collectionRoute = await loadRoute<{
      POST: (req: Request) => Promise<Response>;
    }>("admin/orgs");
    const itemRoute = await loadRoute<{
      PATCH: (req: Request, ctx: { params: Promise<{ id: string }> }) => Promise<Response>;
      DELETE: (req: Request, ctx: { params: Promise<{ id: string }> }) => Promise<Response>;
    }>("admin/orgs/[id]");

    const createResponse = await collectionRoute.POST(
      jsonRequest(
        "/api/admin/orgs",
        { slug: "org-audit", name: "Org Audit", seat_limit: 1 },
        { headers },
      ),
    );
    const createBody = await responseJson(createResponse) as { org: { id: string } };
    const orgId = createBody.org.id;
    const updateResponse = await itemRoute.PATCH(
      jsonRequest(
        `/api/admin/orgs/${orgId}`,
        { name: "Org Audit Updated" },
        { method: "PATCH", headers },
      ),
      { params: Promise.resolve({ id: orgId }) },
    );
    const deleteResponse = await itemRoute.DELETE(
      jsonRequest(`/api/admin/orgs/${orgId}`, {}, { method: "DELETE", headers }),
      { params: Promise.resolve({ id: orgId }) },
    );

    assert.equal(createResponse.status, 200);
    assert.equal(updateResponse.status, 200);
    assert.equal(deleteResponse.status, 200);
    assert.deepEqual(
      (db.audit_log as Array<{ action: string; org_id: string | null }>).map((row) => [
        row.action,
        row.org_id,
      ]),
      [
        ["org_created", orgId],
        ["org_updated", orgId],
        ["org_deleted", orgId],
      ],
    );
  });

  it("admin license revoke mutates only the target user's license", async () => {
    const db = useFakeDb();
    const admin = await makeUser({ id: "license-admin", email: "license-admin@example.com", role: "admin" });
    const target = await makeUser({ id: "license-target", email: "license-target@example.com" });
    const other = await makeUser({ id: "license-other", email: "license-other@example.com" });
    db.users.push(admin, target, other);
    const adminLicense = seedLicense({ id: "license-admin-session", user_id: admin.id });
    const targetLicense = seedLicense({ id: "target-session", user_id: target.id });
    const otherLicense = seedLicense({ id: "other-session", user_id: other.id });
    const bearer = await issueAccessToken(admin, adminLicense);
    const headers = { authorization: `Bearer ${bearer}` };
    const listRoute = await loadRoute<{
      GET: (req: Request, ctx: { params: Promise<{ id: string }> }) => Promise<Response>;
    }>("admin/users/[id]/licenses");
    const revokeRoute = await loadRoute<{
      DELETE: (
        req: Request,
        ctx: { params: Promise<{ id: string; licenseId: string }> },
      ) => Promise<Response>;
    }>("admin/users/[id]/licenses/[licenseId]");

    const listBefore = await responseJson(
      await listRoute.GET(
        jsonRequest("/api/admin/users/license-target/licenses", {}, { method: "GET", headers }),
        { params: Promise.resolve({ id: target.id }) },
      ),
    );
    assert.deepEqual(
      (listBefore.licenses as Array<{ id: string }>).map((license) => license.id),
      [targetLicense.id],
    );

    const crossUser = await revokeRoute.DELETE(
      jsonRequest(
        "/api/admin/users/license-target/licenses/other-session",
        {},
        { method: "DELETE", headers },
      ),
      { params: Promise.resolve({ id: target.id, licenseId: otherLicense.id }) },
    );
    const crossUserBody = await responseJson(crossUser);

    assert.equal(crossUser.status, 404);
    assert.deepEqual(crossUserBody, { error: "license not found" });
    assert.equal(otherLicense.revoked, false);

    const revoked = await revokeRoute.DELETE(
      jsonRequest(
        "/api/admin/users/license-target/licenses/target-session",
        {},
        { method: "DELETE", headers },
      ),
      { params: Promise.resolve({ id: target.id, licenseId: targetLicense.id }) },
    );
    const revokedBody = await responseJson(revoked);

    assert.equal(revoked.status, 200);
    assert.deepEqual(revokedBody, { ok: true });
    assert.equal(targetLicense.revoked, true);
    assert.equal(otherLicense.revoked, false);
    assert.equal(
      (db.audit_log as Array<{ action?: string }>).at(-1)?.action,
      "license.admin_revoked",
    );
  });

  it("skills run returns the requested skill and records an invocation", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "skill-user", tier: "pro" });
    db.users.push(user);
    const license = seedLicense({ id: "skill-license", user_id: user.id });
    const bearer = await issueAccessToken(user, license);
    const now = new Date().toISOString();
    db.skills.push(
      {
        name: "wrong-skill",
        version: 1,
        tier_required: "pro",
        manifest: {},
        body: "wrong body",
        enabled: true,
        created_at: now,
        updated_at: now,
      },
      {
        name: "right-skill",
        version: 2,
        tier_required: "pro",
        manifest: {},
        body: "right body",
        enabled: true,
        created_at: now,
        updated_at: now,
      },
    );
    const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("skills/run");
    const args = { lead_id: "lead-1" };

    const response = await route.POST(
      jsonRequest(
        "/api/skills/run",
        { skill_name: "right-skill", args },
        {
          headers: {
            authorization: `Bearer ${bearer}`,
            "x-forwarded-for": "203.0.113.7",
            "user-agent": "hosted-route-test",
          },
        },
      ),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 200);
    assert.equal(body.name, "right-skill");
    assert.equal(body.version, 2);
    assert.equal(body.body, "right body");
    assert.equal(db.skill_invocations.length, 1);
    const [invocation] = db.skill_invocations as Array<Record<string, unknown>>;
    assert.equal(invocation.user_id, user.id);
    assert.equal(invocation.skill_name, "right-skill");
    assert.equal(
      invocation.args_hash,
      crypto.createHash("sha256").update(JSON.stringify(args)).digest("hex"),
    );
    assert.equal(invocation.ip_address, "203.0.113.7");
    assert.equal(invocation.user_agent, "hosted-route-test");
  });

  it("skills run returns JSON when invocation logging fails", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "skill-log-user", email: "skill-log@example.com" });
    db.users.push(user);
    const license = seedLicense({ id: "skill-log-license", user_id: user.id });
    const bearer = await issueAccessToken(user, license);
    const now = new Date().toISOString();
    db.skills.push({
      name: "logged-skill",
      version: 1,
      tier_required: "pro",
      manifest: {},
      body: "body",
      enabled: true,
      created_at: now,
      updated_at: now,
    });
    failNextSupabaseInsert("skill_invocations");
    const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("skills/run");

    const response = await route.POST(
      jsonRequest(
        "/api/skills/run",
        { skill_name: "logged-skill", args: { lead_id: "lead-2" } },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );

    assert.equal(response.status, 503);
    assert.deepEqual(await responseJson(response), { error: "skill invocation unavailable" });
    assert.equal(db.skill_invocations.length, 0);
  });

  it("admin mutations return 404 for missing records", async () => {
    const db = useFakeDb();
    const admin = await makeUser({ role: "admin" });
    db.users.push(admin);
    const license = seedLicense({ id: "admin-license", user_id: admin.id });
    const bearer = await issueAccessToken(admin, license);
    const headers = { authorization: `Bearer ${bearer}` };
    const userRoute = await loadRoute<{
      PATCH: (req: Request, ctx: { params: Promise<{ id: string }> }) => Promise<Response>;
    }>("admin/users/[id]");
    const orgRoute = await loadRoute<{
      PATCH: (req: Request, ctx: { params: Promise<{ id: string }> }) => Promise<Response>;
      DELETE: (req: Request, ctx: { params: Promise<{ id: string }> }) => Promise<Response>;
    }>("admin/orgs/[id]");
    const memberRoute = await loadRoute<{
      PATCH: (
        req: Request,
        ctx: { params: Promise<{ id: string; userId: string }> },
      ) => Promise<Response>;
      DELETE: (
        req: Request,
        ctx: { params: Promise<{ id: string; userId: string }> },
      ) => Promise<Response>;
    }>("admin/orgs/[id]/members/[userId]");

    const missingUser = await userRoute.PATCH(
      jsonRequest("/api/admin/users/missing", { tier: "builder" }, { method: "PATCH", headers }),
      { params: Promise.resolve({ id: "missing-user" }) },
    );
    const missingOrgPatch = await orgRoute.PATCH(
      jsonRequest("/api/admin/orgs/missing", { name: "Missing" }, { method: "PATCH", headers }),
      { params: Promise.resolve({ id: "missing-org" }) },
    );
    const missingOrgDelete = await orgRoute.DELETE(
      jsonRequest("/api/admin/orgs/missing", {}, { method: "DELETE", headers }),
      { params: Promise.resolve({ id: "missing-org" }) },
    );
    const missingMemberPatch = await memberRoute.PATCH(
      jsonRequest(
        "/api/admin/orgs/org-1/members/missing-user",
        { role: "member" },
        { method: "PATCH", headers },
      ),
      { params: Promise.resolve({ id: "org-1", userId: "missing-user" }) },
    );
    const missingMemberDelete = await memberRoute.DELETE(
      jsonRequest("/api/admin/orgs/org-1/members/missing-user", {}, { method: "DELETE", headers }),
      { params: Promise.resolve({ id: "org-1", userId: "missing-user" }) },
    );

    assert.equal(missingUser.status, 404);
    assert.equal(missingOrgPatch.status, 404);
    assert.equal(missingOrgDelete.status, 404);
    assert.equal(missingMemberPatch.status, 404);
    assert.equal(missingMemberDelete.status, 404);
    assert.equal(db.audit_log.length, 0);
  });

  it("device v2 start validates proposals and retries only user-code collisions", async () => {
    const db = useFakeDb();
    const start = await loadRoute<PostRoute>("device/start");

    for (const proposed_refresh_token_hash of [
      "not-a-sha256",
      refreshHash(REFRESH_V2_B).toUpperCase(),
    ]) {
      const response = await start.POST(
        jsonRequest("/api/device/start", { proposed_refresh_token_hash }),
      );
      assert.equal(response.status, 400);
      assertCredentialFree(await responseJson(response));
    }
    assert.equal(db.device_grants.length, 0);

    failNextDeviceGrantInsertConflict("user_code");
    const recovered = await start.POST(
      jsonRequest("/api/device/start", deviceV2StartBody()),
    );
    const recoveredBody = await responseJson(recovered);
    assert.equal(recovered.status, 200);
    assert.equal(recoveredBody.protocol_version, 2);
    assert.equal(db.device_grants.length, 1);
    assert.equal(
      db.calls.filter(
        (call) => call.table === "device_grants" && call.method === "POST",
      ).length,
      2,
    );
    assert.equal(JSON.stringify(db.calls).includes(REFRESH_V2_B), false);

    const duplicateProposal = await start.POST(
      jsonRequest("/api/device/start", deviceV2StartBody()),
    );
    assert.equal(duplicateProposal.status, 409);
    assert.deepEqual(await responseJson(duplicateProposal), {
      error: "refresh_token_proposal_conflict",
    });
    assert.equal(db.device_grants.length, 1);

    const insertsBeforeFailure = db.calls.filter(
      (call) => call.table === "device_grants" && call.method === "POST",
    ).length;
    failNextSupabaseInsert("device_grants");
    const unavailable = await start.POST(
      jsonRequest("/api/device/start", deviceV2StartBody(REFRESH_V2_C)),
    );
    assert.equal(unavailable.status, 503);
    assert.deepEqual(await responseJson(unavailable), {
      error: "device authorization unavailable",
    });
    assert.equal(
      db.calls.filter(
        (call) => call.table === "device_grants" && call.method === "POST",
      ).length,
      insertsBeforeFailure + 1,
    );
    assert.equal(db.device_grants.length, 1);
  });

  it("device v2 approval and exact poll retry use hashes only", async () => {
    const db = useFakeDb();
    const user = await makeUser({
      id: "device-v2-recovery-user",
      email: "device-v2-recovery@example.com",
    });
    db.users.push(user);
    const browserLicense = seedLicense({
      id: "device-v2-recovery-browser",
      user_id: user.id,
    });
    const bearer = await issueAccessToken(user, browserLicense);
    const start = await loadRoute<PostRoute>("device/start");
    const approve = await loadRoute<PostRoute>("device/approve");
    const poll = await loadRoute<PostRoute>("device/poll");

    const startResponse = await start.POST(
      jsonRequest("/api/device/start", deviceV2StartBody()),
    );
    const startBody = await responseJson(startResponse);
    assert.equal(startResponse.status, 200);
    assert.equal(startBody.protocol_version, 2);
    const grant = db.device_grants[0];
    assert.equal(grant.proposed_refresh_token_hash, refreshHash(REFRESH_V2_B));
    assert.equal(grant.refresh_token_plain, null);

    const pending = await poll.POST(
      jsonRequest("/api/device/poll", deviceV2PollBody(startBody)),
    );
    assert.equal(pending.status, 200);
    assert.deepEqual(await responseJson(pending), { status: "pending", interval: 5 });
    const pendingCall = db.calls.find(
      (call) => call.table === "poll_device_grant_pending_v2",
    );
    assert.ok(pendingCall);
    assert.deepEqual(Object.keys(pendingCall.body as Record<string, unknown>).sort(), [
      "p_device_code_hash",
      "p_refresh_token_hash",
    ]);
    assert.equal(JSON.stringify(pendingCall.body).includes(REFRESH_V2_B), false);

    const approval = await approve.POST(
      jsonRequest(
        "/api/device/approve",
        { user_code: startBody.user_code },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    assert.equal(approval.status, 200);
    const license = db.licenses.find((candidate) => candidate.id === grant.license_id);
    assert.ok(license);
    assert.equal(license.refresh_token_hash, refreshHash(REFRESH_V2_B));
    assert.equal(grant.refresh_token_plain, null);
    const approvalCall = db.calls.find(
      (call) => call.table === "approve_device_grant_atomic_v2",
    );
    assert.ok(approvalCall);
    assert.deepEqual(Object.keys(approvalCall.body as Record<string, unknown>).sort(), [
      "p_grant_id",
      "p_user_id",
    ]);

    const first = await withTestEntitlementSigningRing(
      TEST_ENTITLEMENT_KEY_B,
      () => poll.POST(jsonRequest("/api/device/poll", deviceV2PollBody(startBody))),
    );
    const firstBody = await responseJson(first);
    assert.equal(first.status, 200);
    assert.equal(firstBody.protocol_version, 2);
    assert.equal(firstBody.refresh_token, REFRESH_V2_B);
    assert.equal(grant.status, "claimed");
    assert.equal(grant.refresh_token_plain, null);
    assert.equal(typeof grant.claimed_at, "string");
    assert.equal(typeof grant.claim_retry_until, "string");
    assert.ok(Date.parse(String(grant.claim_retry_until)) > Date.now());
    assert.ok(
      Date.parse(String(grant.claim_retry_until)) - Date.parse(String(grant.claimed_at)) <=
        2 * 60 * 1000,
    );
    assertEntitlementEnvelope(firstBody, {
      sub: user.id,
      license_id: license.id,
      email: user.email,
      tier: "pro",
      entitlements: ["real_estate_sales"],
      kid: TEST_ENTITLEMENT_KEY_B,
    });

    const claimedAt = grant.claimed_at;
    const retryUntil = grant.claim_retry_until;
    grant.expires_at = new Date(Date.now() - 1000).toISOString();
    const replay = await withTestEntitlementSigningRing(
      TEST_ENTITLEMENT_KEY_B,
      () => poll.POST(jsonRequest("/api/device/poll", deviceV2PollBody(startBody))),
    );
    const replayBody = await responseJson(replay);
    assert.equal(replay.status, 200);
    assert.equal(replayBody.refresh_token, REFRESH_V2_B);
    assert.notEqual(replayBody.entitlement_assertion, firstBody.entitlement_assertion);
    assert.equal(grant.claimed_at, claimedAt);
    assert.equal(grant.claim_retry_until, retryUntil);

    const claimCalls = db.calls.filter(
      (call) => call.table === "claim_device_grant_atomic_v2",
    );
    assert.equal(claimCalls.length, 2);
    for (const call of claimCalls) {
      assert.deepEqual(Object.keys(call.body as Record<string, unknown>).sort(), [
        "p_device_code_hash",
        "p_refresh_token_hash",
      ]);
      assert.equal(JSON.stringify(call.body).includes(REFRESH_V2_B), false);
    }
    assert.equal(JSON.stringify(db.device_grants).includes(REFRESH_V2_B), false);

    grant.claim_retry_until = new Date(Date.now() - 1000).toISOString();
    const tooLate = await poll.POST(
      jsonRequest("/api/device/poll", deviceV2PollBody(startBody)),
    );
    const tooLateBody = await responseJson(tooLate);
    assert.equal(tooLate.status, 410);
    assert.deepEqual(tooLateBody, {
      error: "claim_retry_expired",
      status: "claimed",
    });
    assertCredentialFree(tooLateBody);
  });

  it("device v2 approve and deny decisions have one durable winner", async () => {
    const db = useFakeDb();
    const approvingUser = await makeUser({
      id: "device-v2-approve-race-user",
      email: "device-v2-approve-race@example.com",
    });
    const denyingUser = await makeUser({
      id: "device-v2-deny-race-user",
      email: "device-v2-deny-race@example.com",
    });
    db.users.push(approvingUser, denyingUser);
    const approvingBrowser = seedLicense({
      id: "device-v2-approve-race-browser",
      user_id: approvingUser.id,
    });
    const denyingBrowser = seedLicense({
      id: "device-v2-deny-race-browser",
      user_id: denyingUser.id,
    });
    const approvingBearer = await issueAccessToken(
      approvingUser,
      approvingBrowser,
    );
    const denyingBearer = await issueAccessToken(denyingUser, denyingBrowser);
    const start = await loadRoute<PostRoute>("device/start");
    const approve = await loadRoute<PostRoute>("device/approve");
    const deny = await loadRoute<PostRoute>("device/deny");
    const startBody = await responseJson(
      await start.POST(
        jsonRequest("/api/device/start", deviceV2StartBody()),
      ),
    );

    barrierNextDeviceGrantDecisions();
    const responses = await Promise.all([
      approve.POST(
        jsonRequest(
          "/api/device/approve",
          { user_code: startBody.user_code },
          { headers: { authorization: `Bearer ${approvingBearer}` } },
        ),
      ),
      deny.POST(
        jsonRequest(
          "/api/device/deny",
          { user_code: startBody.user_code },
          { headers: { authorization: `Bearer ${denyingBearer}` } },
        ),
      ),
    ]);
    const bodies = await Promise.all(responses.map(responseJson));

    assert.equal(responses.filter((response) => response.status === 200).length, 1);
    assert.equal(responses.filter((response) => response.status === 409).length, 1);
    for (const body of bodies) assertCredentialFree(body);

    const grant = db.device_grants[0];
    const deviceLicenses = db.licenses.filter(
      (license) =>
        license.id !== approvingBrowser.id && license.id !== denyingBrowser.id,
    );
    assert.equal(grant.refresh_token_plain, null);
    assert.equal(grant.claim_retry_until, null);
    if (grant.status === "approved") {
      assert.equal(responses[0].status, 200);
      assert.equal(responses[1].status, 409);
      assert.equal(grant.user_id, approvingUser.id);
      assert.equal(deviceLicenses.length, 1);
      assert.equal(deviceLicenses[0].user_id, approvingUser.id);
      assert.equal(
        deviceLicenses[0].refresh_token_hash,
        refreshHash(REFRESH_V2_B),
      );
      assert.equal(deviceLicenses[0].revoked, false);
    } else {
      assert.equal(grant.status, "denied");
      assert.equal(responses[0].status, 409);
      assert.equal(responses[1].status, 200);
      assert.equal(grant.user_id, denyingUser.id);
      assert.equal(grant.license_id, null);
      assert.equal(deviceLicenses.length, 0);
    }
    assert.equal(db.audit_log.length, 1);
  });

  it("device v2 serializes stale pending polls with concurrent approval", async () => {
    for (const expireAfterApproval of [false, true]) {
      const db = useFakeDb();
      const suffix = expireAfterApproval ? "expired" : "claimable";
      const user = await makeUser({
        id: `device-v2-stale-pending-${suffix}-user`,
      });
      db.users.push(user);
      const browser = seedLicense({
        id: `device-v2-stale-pending-${suffix}-browser`,
        user_id: user.id,
      });
      const bearer = await issueAccessToken(user, browser);
      const start = await loadRoute<PostRoute>("device/start");
      const approve = await loadRoute<PostRoute>("device/approve");
      const poll = await loadRoute<PostRoute>("device/poll");
      const startBody = await responseJson(
        await start.POST(
          jsonRequest(
            "/api/device/start",
            deviceV2StartBody(REFRESH_V2_B, `Stale pending ${suffix}`),
          ),
        ),
      );
      const grant = db.device_grants[0];
      const gate = gateNextSupabaseRpc("poll_device_grant_pending_v2");

      const pollResponse = await withTestEntitlementSigningRing(
        TEST_ENTITLEMENT_KEY_B,
        async () => {
          const pendingPoll = poll.POST(
            jsonRequest("/api/device/poll", deviceV2PollBody(startBody)),
          );
          await gate.reached;
          try {
            const approval = await approve.POST(
              jsonRequest(
                "/api/device/approve",
                { user_code: startBody.user_code },
                { headers: { authorization: `Bearer ${bearer}` } },
              ),
            );
            assert.equal(approval.status, 200);
            if (expireAfterApproval) {
              grant.expires_at = new Date(Date.now() - 1000).toISOString();
            }
          } finally {
            gate.release();
          }
          return pendingPoll;
        },
      );
      const pollBody = await responseJson(pollResponse);
      const license = db.licenses.find(
        (candidate) => candidate.id === grant.license_id,
      );
      assert.ok(license);
      assert.equal(grant.refresh_token_plain, null);

      if (expireAfterApproval) {
        assert.equal(pollResponse.status, 410);
        assert.deepEqual(pollBody, {
          error: "expired_token",
          status: "expired",
        });
        assertCredentialFree(pollBody);
        assert.equal(grant.status, "expired");
        assert.equal(license.revoked, true);
        assert.equal(
          db.calls.filter(
            (call) => call.table === "claim_device_grant_atomic_v2",
          ).length,
          0,
        );
      } else {
        assert.equal(pollResponse.status, 200);
        assert.equal(pollBody.refresh_token, REFRESH_V2_B);
        assert.equal(grant.status, "claimed");
        assert.equal(license.revoked, false);
      }
    }
  });

  it("device v2 pending polls do not require a configured signer", async () => {
    const db = useFakeDb();
    const start = await loadRoute<PostRoute>("device/start");
    const poll = await loadRoute<PostRoute>("device/poll");
    const startBody = await responseJson(
      await start.POST(jsonRequest("/api/device/start", deviceV2StartBody())),
    );
    const previousConsoleError = console.error;
    console.error = () => {};
    try {
      await withEntitlementSigningEnvironment(
        {
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64: "malformed signing key",
          ELEVATE_ENTITLEMENT_SIGNING_ACTIVE_KID: undefined,
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEYS_B64_JSON: undefined,
        },
        async () => {
          const response = await poll.POST(
            jsonRequest("/api/device/poll", deviceV2PollBody(startBody)),
          );
          assert.equal(response.status, 200);
          assert.deepEqual(await responseJson(response), {
            status: "pending",
            interval: 5,
          });
        },
      );
    } finally {
      console.error = previousConsoleError;
    }
    assert.equal(db.device_grants[0].status, "pending");
    assert.equal(
      db.calls.filter(
        (call) => call.table === "poll_device_grant_pending_v2",
      ).length,
      1,
    );
    assert.equal(
      db.calls.filter(
        (call) => call.table === "claim_device_grant_atomic_v2",
      ).length,
      0,
    );
  });

  it("device v2 rejects missing, malformed, wrong, and protocol-mismatched tokens", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "device-v2-invalid-user" });
    db.users.push(user);
    const browser = seedLicense({
      id: "device-v2-invalid-browser",
      user_id: user.id,
    });
    const bearer = await issueAccessToken(user, browser);
    const { startBody, grant, license } = await approveDeviceV2Flow({
      db,
      user,
      bearer,
    });
    const poll = await loadRoute<PostRoute>("device/poll");

    const missing = await poll.POST(
      jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
    );
    assert.equal(missing.status, 400);
    assertCredentialFree(await responseJson(missing));

    const malformed = await poll.POST(
      jsonRequest("/api/device/poll", {
        device_code: startBody.device_code,
        refresh_token: `${REFRESH_V2_B}=`,
      }),
    );
    assert.equal(malformed.status, 400);
    assertCredentialFree(await responseJson(malformed));

    const claimCallsBeforeWrong = db.calls.filter(
      (call) => call.table === "claim_device_grant_atomic_v2",
    ).length;
    const wrong = await poll.POST(
      jsonRequest("/api/device/poll", deviceV2PollBody(startBody, REFRESH_V2_D)),
    );
    const wrongBody = await responseJson(wrong);
    assert.equal(wrong.status, 401);
    assertCredentialFree(wrongBody);
    assert.equal(grant.status, "approved");
    assert.equal(license.revoked, false);
    assert.equal(
      db.calls.filter((call) => call.table === "claim_device_grant_atomic_v2").length,
      claimCallsBeforeWrong,
    );

    const legacyStart = await loadRoute<PostRoute>("device/start");
    const legacyBody = await responseJson(
      await legacyStart.POST(jsonRequest("/api/device/start", { device_label: "Legacy" })),
    );
    const mismatch = await poll.POST(
      jsonRequest("/api/device/poll", deviceV2PollBody(legacyBody)),
    );
    assert.equal(mismatch.status, 409);
    assert.deepEqual(await responseJson(mismatch), {
      error: "device_protocol_mismatch",
    });
  });

  for (const failureStage of [
    "approval_after_license_insert",
    "approval_after_grant_update",
    "approval_after_audit_insert",
  ] as const) {
    it(`device v2 approval rolls back every write when ${failureStage} fails`, async () => {
      const db = useFakeDb();
      const user = await makeUser({ id: `device-v2-${failureStage}-user` });
      db.users.push(user);
      const browser = seedLicense({
        id: `device-v2-${failureStage}-browser`,
        user_id: user.id,
      });
      const bearer = await issueAccessToken(user, browser);
      const start = await loadRoute<PostRoute>("device/start");
      const approve = await loadRoute<PostRoute>("device/approve");
      const startBody = await responseJson(
        await start.POST(jsonRequest("/api/device/start", deviceV2StartBody())),
      );
      const grant = db.device_grants[0];

      failNextAtomicDeviceV2(failureStage);
      const failed = await approve.POST(
        jsonRequest(
          "/api/device/approve",
          { user_code: startBody.user_code },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      );
      const failedBody = await responseJson(failed);
      assert.equal(failed.status, 500);
      assert.deepEqual(failedBody, { error: "approval_failed" });
      assertCredentialFree(failedBody);
      assert.equal(grant.status, "pending");
      assert.equal(grant.user_id, null);
      assert.equal(grant.license_id, null);
      assert.equal(grant.refresh_token_plain, null);
      assert.equal(grant.claim_retry_until, null);
      assert.equal(db.licenses.length, 1);
      assert.equal(db.audit_log.length, 0);

      const retry = await approve.POST(
        jsonRequest(
          "/api/device/approve",
          { user_code: startBody.user_code },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      );
      assert.equal(retry.status, 200);
      assert.equal(db.licenses.length, 2);
      assert.equal(grant.status, "approved");
      assert.equal(grant.refresh_token_plain, null);
    });
  }

  it("device v2 approval rejects current and recovery token collisions", async () => {
    const approve = await loadRoute<PostRoute>("device/approve");
    const start = await loadRoute<PostRoute>("device/start");
    for (const slot of ["current", "recovery"] as const) {
      const db = useFakeDb();
      const user = await makeUser({ id: `device-v2-${slot}-collision-user` });
      db.users.push(user);
      const browser = seedLicense({
        id: `device-v2-${slot}-collision-browser`,
        user_id: user.id,
      });
      const bearer = await issueAccessToken(user, browser);
      const startBody = await responseJson(
        await start.POST(jsonRequest("/api/device/start", deviceV2StartBody())),
      );
      const grant = db.device_grants[0];
      // Simulate a legacy/server-random residual committed after the proposal.
      // New client-controlled writers and v2 table inserts are serialized by
      // the shared capability lock, but approval must still fail closed for an
      // already-existing cross-table collision.
      seedLicense({
        id: `device-v2-${slot}-collision-license`,
        user_id: user.id,
        refresh_token_hash:
          slot === "current" ? refreshHash(REFRESH_V2_B) : refreshHash(REFRESH_V2_C),
        previous_refresh_token_hash:
          slot === "recovery" ? refreshHash(REFRESH_V2_B) : null,
      });

      const response = await approve.POST(
        jsonRequest(
          "/api/device/approve",
          { user_code: startBody.user_code },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      );
      const body = await responseJson(response);
      assert.equal(response.status, 409);
      assert.deepEqual(body, { error: "refresh_token_proposal_conflict" });
      assertCredentialFree(body);
      assert.equal(grant.status, "expired");
      assert.equal(grant.license_id, null);
      assert.equal(grant.refresh_token_plain, null);
      assert.equal(db.licenses.length, 2);
      assert.equal(db.audit_log.length, 0);
    }
  });

  it("device v2 concurrent identical polls claim once and replay equivalently", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "device-v2-identical-poll-user" });
    db.users.push(user);
    const browser = seedLicense({
      id: "device-v2-identical-poll-browser",
      user_id: user.id,
    });
    const bearer = await issueAccessToken(user, browser);
    const { startBody, grant, license } = await approveDeviceV2Flow({
      db,
      user,
      bearer,
    });
    const poll = await loadRoute<PostRoute>("device/poll");

    barrierNextSupabaseRpcs("claim_device_grant_atomic_v2");
    const responses = await Promise.all([
      poll.POST(jsonRequest("/api/device/poll", deviceV2PollBody(startBody))),
      poll.POST(jsonRequest("/api/device/poll", deviceV2PollBody(startBody))),
    ]);
    const bodies = await Promise.all(responses.map(responseJson));
    assert.deepEqual(responses.map((response) => response.status), [200, 200]);
    assert.deepEqual(
      bodies.map((body) => body.refresh_token),
      [REFRESH_V2_B, REFRESH_V2_B],
    );
    assert.equal(grant.status, "claimed");
    assert.equal(typeof grant.claimed_at, "string");
    assert.equal(typeof grant.claim_retry_until, "string");
    assert.equal(license.refresh_token_hash, refreshHash(REFRESH_V2_B));
    assert.equal(grant.refresh_token_plain, null);
    assert.equal(
      db.calls.filter((call) => call.table === "claim_device_grant_atomic_v2").length,
      2,
    );
  });

  it("device v2 concurrent conflicting poll returns credentials only for exact B", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "device-v2-conflicting-poll-user" });
    db.users.push(user);
    const browser = seedLicense({
      id: "device-v2-conflicting-poll-browser",
      user_id: user.id,
    });
    const bearer = await issueAccessToken(user, browser);
    const { startBody, grant, license } = await approveDeviceV2Flow({
      db,
      user,
      bearer,
    });
    const poll = await loadRoute<PostRoute>("device/poll");

    const responses = await Promise.all([
      poll.POST(jsonRequest("/api/device/poll", deviceV2PollBody(startBody))),
      poll.POST(
        jsonRequest("/api/device/poll", deviceV2PollBody(startBody, REFRESH_V2_D)),
      ),
    ]);
    const bodies = await Promise.all(responses.map(responseJson));
    const exactIndex = responses.findIndex((response) => response.status === 200);
    const wrongIndex = responses.findIndex((response) => response.status === 401);
    assert.notEqual(exactIndex, -1);
    assert.notEqual(wrongIndex, -1);
    assert.equal(bodies[exactIndex].refresh_token, REFRESH_V2_B);
    assertCredentialFree(bodies[wrongIndex]);
    assert.equal(grant.status, "claimed");
    assert.equal(license.revoked, false);
    assert.equal(license.refresh_token_hash, refreshHash(REFRESH_V2_B));
    assert.equal(
      db.calls.filter((call) => call.table === "claim_device_grant_atomic_v2").length,
      1,
    );
  });

  it("device v2 claim rollback leaves the first claim exactly retryable", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "device-v2-claim-rollback-user" });
    db.users.push(user);
    const browser = seedLicense({
      id: "device-v2-claim-rollback-browser",
      user_id: user.id,
    });
    const bearer = await issueAccessToken(user, browser);
    const { startBody, grant, license } = await approveDeviceV2Flow({
      db,
      user,
      bearer,
    });
    const poll = await loadRoute<PostRoute>("device/poll");

    failNextAtomicDeviceV2("claim_after_grant_update");
    const failed = await poll.POST(
      jsonRequest("/api/device/poll", deviceV2PollBody(startBody)),
    );
    const failedBody = await responseJson(failed);
    assert.equal(failed.status, 503);
    assert.deepEqual(failedBody, { error: "device claim unavailable" });
    assertCredentialFree(failedBody);
    assert.equal(grant.status, "approved");
    assert.equal(grant.claimed_at, null);
    assert.equal(grant.claim_retry_until, null);
    assert.equal(grant.refresh_token_plain, null);
    assert.equal(license.revoked, false);
    assert.equal(license.refresh_token_hash, refreshHash(REFRESH_V2_B));

    const retry = await poll.POST(
      jsonRequest("/api/device/poll", deviceV2PollBody(startBody)),
    );
    const retryBody = await responseJson(retry);
    assert.equal(retry.status, 200);
    assert.equal(retryBody.refresh_token, REFRESH_V2_B);
    assert.equal(grant.status, "claimed");
  });

  it("device v2 recovers after a post-RPC issuance failure", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "device-v2-post-rpc-user" });
    db.users.push(user);
    const browser = seedLicense({
      id: "device-v2-post-rpc-browser",
      user_id: user.id,
    });
    const bearer = await issueAccessToken(user, browser);
    const { startBody, grant, license } = await approveDeviceV2Flow({
      db,
      user,
      bearer,
    });
    const poll = await loadRoute<PostRoute>("device/poll");

    failNextSupabaseSelect("users");
    const failed = await poll.POST(
      jsonRequest("/api/device/poll", deviceV2PollBody(startBody)),
    );
    const failedBody = await responseJson(failed);
    assert.equal(failed.status, 503);
    assert.deepEqual(failedBody, { error: "license issuance unavailable" });
    assertCredentialFree(failedBody);
    assert.equal(grant.status, "claimed");
    assert.equal(typeof grant.claim_retry_until, "string");
    assert.equal(grant.refresh_token_plain, null);
    assert.equal(license.refresh_token_hash, refreshHash(REFRESH_V2_B));

    const retry = await poll.POST(
      jsonRequest("/api/device/poll", deviceV2PollBody(startBody)),
    );
    const retryBody = await responseJson(retry);
    assert.equal(retry.status, 200);
    assert.equal(retryBody.refresh_token, REFRESH_V2_B);
    assert.equal(license.revoked, false);
  });

  it("device v2 signer preflight performs zero claim mutation or RPC", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "device-v2-signer-preflight-user" });
    db.users.push(user);
    const browser = seedLicense({
      id: "device-v2-signer-preflight-browser",
      user_id: user.id,
    });
    const bearer = await issueAccessToken(user, browser);
    const { startBody, grant, license } = await approveDeviceV2Flow({
      db,
      user,
      bearer,
    });
    const poll = await loadRoute<PostRoute>("device/poll");
    const claimCallsBefore = db.calls.filter(
      (call) => call.table === "claim_device_grant_atomic_v2",
    ).length;
    const previousConsoleError = console.error;
    console.error = () => {};
    try {
      await withEntitlementSigningEnvironment(
        {
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64: "malformed signing key",
          ELEVATE_ENTITLEMENT_SIGNING_ACTIVE_KID: undefined,
          ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEYS_B64_JSON: undefined,
        },
        async () => {
          const response = await poll.POST(
            jsonRequest("/api/device/poll", deviceV2PollBody(startBody)),
          );
          const body = await responseJson(response);
          assert.equal(response.status, 503);
          assert.deepEqual(body, { error: "license issuance unavailable" });
          assertCredentialFree(body);
        },
      );
    } finally {
      console.error = previousConsoleError;
    }
    assert.equal(grant.status, "approved");
    assert.equal(grant.claimed_at, null);
    assert.equal(grant.claim_retry_until, null);
    assert.equal(license.revoked, false);
    assert.equal(
      db.calls.filter((call) => call.table === "claim_device_grant_atomic_v2").length,
      claimCallsBefore,
    );
  });

  it("device v2 replay stops after B rotates to C", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "device-v2-later-rotation-user" });
    db.users.push(user);
    const browser = seedLicense({
      id: "device-v2-later-rotation-browser",
      user_id: user.id,
    });
    const bearer = await issueAccessToken(user, browser);
    const { startBody, grant, license } = await approveDeviceV2Flow({
      db,
      user,
      bearer,
    });
    const poll = await loadRoute<PostRoute>("device/poll");
    const refresh = await loadRoute<PostRoute>("license/refresh");

    const first = await poll.POST(
      jsonRequest("/api/device/poll", deviceV2PollBody(startBody)),
    );
    assert.equal(first.status, 200);
    assert.equal(grant.status, "claimed");
    assert.ok(Date.parse(String(grant.claim_retry_until)) > Date.now());

    const rotated = await refresh.POST(
      jsonRequest(
        "/api/license/refresh",
        refreshV2Body(REFRESH_V2_B, REFRESH_V2_C, REFRESH_V2_I),
      ),
    );
    const rotatedBody = await responseJson(rotated);
    assert.equal(rotated.status, 200);
    assert.equal(rotatedBody.refresh_token, REFRESH_V2_C);
    assert.equal(license.refresh_token_hash, refreshHash(REFRESH_V2_C));
    assert.equal(license.previous_refresh_token_hash, refreshHash(REFRESH_V2_B));

    const stale = await poll.POST(
      jsonRequest("/api/device/poll", deviceV2PollBody(startBody)),
    );
    const staleBody = await responseJson(stale);
    assert.equal(stale.status, 401);
    assert.deepEqual(staleBody, { error: "invalid_grant" });
    assertCredentialFree(staleBody);
    assert.equal(license.refresh_token_hash, refreshHash(REFRESH_V2_C));
    assert.equal(license.revoked, false);
  });

  it("device v2 claim rejects expired, revoked, and inactive state credential-free", async () => {
    const poll = await loadRoute<PostRoute>("device/poll");

    for (const scenario of [
      { name: "grant_expired", expectedStatus: 410 },
      { name: "family_expired", expectedStatus: 410 },
      { name: "revoked", expectedStatus: 403 },
      { name: "inactive", expectedStatus: 402 },
    ] as const) {
      const db = useFakeDb();
      const user = await makeUser({ id: `device-v2-${scenario.name}-user` });
      db.users.push(user);
      const browser = seedLicense({
        id: `device-v2-${scenario.name}-browser`,
        user_id: user.id,
      });
      const bearer = await issueAccessToken(user, browser);
      const { startBody, grant, license } = await approveDeviceV2Flow({
        db,
        user,
        bearer,
        deviceLabel: scenario.name,
      });

      if (scenario.name === "grant_expired") {
        grant.expires_at = new Date(Date.now() - 1000).toISOString();
      } else if (scenario.name === "family_expired") {
        license.refresh_family_expires_at = new Date(Date.now() - 1000).toISOString();
      } else if (scenario.name === "revoked") {
        license.revoked = true;
      } else {
        user.status = "inactive";
      }

      const response = await poll.POST(
        jsonRequest("/api/device/poll", deviceV2PollBody(startBody)),
      );
      const body = await responseJson(response);
      assert.equal(response.status, scenario.expectedStatus);
      assertCredentialFree(body);
      assert.equal(grant.refresh_token_plain, null);
      if (scenario.name === "grant_expired" || scenario.name === "family_expired") {
        assert.equal(grant.status, "expired");
        assert.equal(license.revoked, true);
      }
      if (scenario.name === "inactive") {
        assert.equal(grant.status, "expired");
        assert.equal(license.revoked, true);
      }
      if (scenario.name === "revoked") {
        assert.equal(grant.status, "approved");
        assert.equal(license.revoked, true);
      }
    }
  });

  it("device v2 cleanup cannot be bypassed by approval between its two sweeps", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "device-v2-cleanup-race-user" });
    db.users.push(user);
    const browser = seedLicense({
      id: "device-v2-cleanup-race-browser",
      user_id: user.id,
    });
    const bearer = await issueAccessToken(user, browser);
    const start = await loadRoute<PostRoute>("device/start");
    const approve = await loadRoute<PostRoute>("device/approve");
    const startBody = await responseJson(
      await start.POST(jsonRequest("/api/device/start", deviceV2StartBody())),
    );
    const grant = db.device_grants[0];
    const { expireStaleDeviceGrants } = await import("../src/lib/store");

    afterNextSupabaseRpc("expire_stale_device_grants_v2", async () => {
      const approval = await approve.POST(
        jsonRequest(
          "/api/device/approve",
          { user_code: startBody.user_code },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      );
      assert.equal(approval.status, 200);
      grant.expires_at = new Date(Date.now() - 1000).toISOString();
    });
    await expireStaleDeviceGrants();

    const license = db.licenses.find(
      (candidate) => candidate.id === grant.license_id,
    );
    assert.ok(license);
    assert.equal(grant.status, "approved");
    assert.equal(grant.refresh_token_plain, null);
    assert.equal(license.revoked, false);

    await expireStaleDeviceGrants();
    assert.equal(grant.status, "expired");
    assert.equal(license.revoked, true);
  });

  it("device v2 start cleanup revokes approved grants that were never polled", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "device-v2-orphan-cleanup-user" });
    db.users.push(user);
    const browser = seedLicense({
      id: "device-v2-orphan-cleanup-browser",
      user_id: user.id,
    });
    const bearer = await issueAccessToken(user, browser);
    const { grant, license } = await approveDeviceV2Flow({
      db,
      user,
      bearer,
    });
    grant.expires_at = new Date(Date.now() - 1000).toISOString();
    assert.equal(grant.status, "approved");
    assert.equal(license.revoked, false);

    const start = await loadRoute<PostRoute>("device/start");
    const replacement = await start.POST(
      jsonRequest("/api/device/start", deviceV2StartBody(REFRESH_V2_C)),
    );
    assert.equal(replacement.status, 200);
    assert.equal(grant.status, "expired");
    assert.equal(grant.claim_retry_until, null);
    assert.equal(grant.refresh_token_plain, null);
    assert.equal(license.revoked, true);
    assert.equal(db.device_grants.length, 2);
    assert.equal(db.device_grants[1].status, "pending");
    assert.equal(
      db.calls.filter((call) => call.table === "expire_stale_device_grants_v2").length,
      2,
    );
  });

  it("device start, approve, and poll issue tokens once", async () => {
    const db = useFakeDb();
    const user = await makeUser();
    db.users.push(user);
    const browserLicense = seedLicense({ id: "browser-license", user_id: user.id });
    const bearer = await issueAccessToken(user, browserLicense);
    const start = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/start");
    const approve = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/approve");
    const poll = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/poll");

    const startResponse = await start.POST(
      jsonRequest(
        "/api/device/start",
        { device_label: "CLI" },
        { headers: { origin: "https://app.test", "user-agent": "test-cli" } },
      ),
    );
    const startBody = await responseJson(startResponse);

    assert.equal(startResponse.status, 200);
    assert.equal("protocol_version" in startBody, false);
    assert.equal(startBody.user_code, db.device_grants[0].user_code);
    assert.equal(startBody.verification_uri_complete, `https://app.test/link?code=${startBody.user_code}`);

    const approveResponse = await approve.POST(
      jsonRequest(
        "/api/device/approve",
        { user_code: startBody.user_code },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );

    assert.equal(approveResponse.status, 200);
    assert.equal(db.device_grants[0].status, "approved");
    assert.equal(db.device_grants[0].license_id, "license-1");
    assert.equal(typeof db.device_grants[0].refresh_token_plain, "string");

    const pollResponse = await withTestEntitlementSigningRing(
      TEST_ENTITLEMENT_KEY_B,
      () => poll.POST(jsonRequest("/api/device/poll", { device_code: startBody.device_code })),
    );
    const pollBody = await responseJson(pollResponse);

    assert.equal(pollResponse.status, 200);
    assert.equal(pollBody.status, "approved");
    assert.equal(typeof pollBody.access_token, "string");
    assert.equal(typeof pollBody.refresh_token, "string");
    assert.equal(pollBody.license_id, "license-1");
    assert.equal(db.device_grants[0].status, "claimed");
    assert.equal(db.device_grants[0].refresh_token_plain, null);
    assertEntitlementEnvelope(pollBody, {
      sub: user.id,
      license_id: "license-1",
      email: user.email,
      tier: "pro",
      entitlements: ["real_estate_sales"],
      kid: TEST_ENTITLEMENT_KEY_B,
    });

    const secondPoll = await poll.POST(
      jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
    );
    const secondBody = await responseJson(secondPoll);

    assert.equal(secondPoll.status, 410);
    assert.deepEqual(secondBody, { error: "already_claimed", status: "claimed" });
  });

  it("device approval has one account-bound winner under concurrent approvers", async () => {
    const db = useFakeDb();
    const firstUser = await makeUser({
      id: "first-device-approver",
      email: "first-approver@example.com",
    });
    const secondUser = await makeUser({
      id: "second-device-approver",
      email: "second-approver@example.com",
    });
    db.users.push(firstUser, secondUser);
    const firstBrowserLicense = seedLicense({
      id: "first-browser-license",
      user_id: firstUser.id,
    });
    const secondBrowserLicense = seedLicense({
      id: "second-browser-license",
      user_id: secondUser.id,
    });
    const firstBearer = await issueAccessToken(firstUser, firstBrowserLicense);
    const secondBearer = await issueAccessToken(secondUser, secondBrowserLicense);
    const start = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/start");
    const approve = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "device/approve",
    );
    const poll = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/poll");

    const startBody = await responseJson(
      await start.POST(jsonRequest("/api/device/start", { device_label: "Contested CLI" })),
    );

    barrierNextSupabaseRpcs("approve_device_grant_atomic");
    const responses = await Promise.all([
      approve.POST(
        jsonRequest(
          "/api/device/approve",
          { user_code: startBody.user_code },
          { headers: { authorization: `Bearer ${firstBearer}` } },
        ),
      ),
      approve.POST(
        jsonRequest(
          "/api/device/approve",
          { user_code: startBody.user_code },
          { headers: { authorization: `Bearer ${secondBearer}` } },
        ),
      ),
    ]);
    const bodies = await Promise.all(responses.map(responseJson));
    const winnerIndex = responses.findIndex((response) => response.status === 200);
    const loserIndex = responses.findIndex((response) => response.status === 409);

    assert.notEqual(winnerIndex, -1);
    assert.notEqual(loserIndex, -1);
    assert.notEqual(winnerIndex, loserIndex);
    assert.deepEqual(bodies[winnerIndex], { ok: true });
    assert.deepEqual(bodies[loserIndex], { error: "already approved" });
    assert.equal("access_token" in bodies[loserIndex], false);
    assert.equal("refresh_token" in bodies[loserIndex], false);
    assert.equal("entitlement_assertion" in bodies[loserIndex], false);

    const winningUser = winnerIndex === 0 ? firstUser : secondUser;
    const grant = db.device_grants[0];
    const deviceLicenses = db.licenses.filter(
      (license) =>
        license.id !== firstBrowserLicense.id && license.id !== secondBrowserLicense.id,
    );
    assert.equal(deviceLicenses.length, 1);
    assert.equal(grant.status, "approved");
    assert.equal(grant.user_id, winningUser.id);
    assert.equal(grant.license_id, deviceLicenses[0].id);
    assert.equal(deviceLicenses[0].user_id, winningUser.id);
    assert.equal(refreshHash(String(grant.refresh_token_plain)), deviceLicenses[0].refresh_token_hash);
    assert.equal(db.audit_log.length, 1);
    assert.equal(
      (db.audit_log[0] as { actor_user_id?: string }).actor_user_id,
      winningUser.id,
    );

    const pollResponse = await poll.POST(
      jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
    );
    const pollBody = await responseJson(pollResponse);
    assert.equal(pollResponse.status, 200);
    assertEntitlementEnvelope(pollBody, {
      sub: winningUser.id,
      license_id: deviceLicenses[0].id,
      email: winningUser.email,
      tier: "pro",
      entitlements: ["real_estate_sales"],
    });
    assert.equal(grant.refresh_token_plain, null);
  });

  it("device approve and deny decisions cannot overwrite each other", async () => {
    const db = useFakeDb();
    const approvingUser = await makeUser({
      id: "approve-race-user",
      email: "approve-race@example.com",
    });
    const denyingUser = await makeUser({
      id: "deny-race-user",
      email: "deny-race@example.com",
    });
    db.users.push(approvingUser, denyingUser);
    const approvingBrowser = seedLicense({
      id: "approve-race-browser",
      user_id: approvingUser.id,
    });
    const denyingBrowser = seedLicense({
      id: "deny-race-browser",
      user_id: denyingUser.id,
    });
    const approvingBearer = await issueAccessToken(approvingUser, approvingBrowser);
    const denyingBearer = await issueAccessToken(denyingUser, denyingBrowser);
    const start = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/start");
    const approve = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "device/approve",
    );
    const deny = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/deny");
    const poll = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/poll");
    const startBody = await responseJson(
      await start.POST(jsonRequest("/api/device/start", { device_label: "Decision race CLI" })),
    );

    barrierNextDeviceGrantDecisions();
    const responses = await Promise.all([
      approve.POST(
        jsonRequest(
          "/api/device/approve",
          { user_code: startBody.user_code },
          { headers: { authorization: `Bearer ${approvingBearer}` } },
        ),
      ),
      deny.POST(
        jsonRequest(
          "/api/device/deny",
          { user_code: startBody.user_code },
          { headers: { authorization: `Bearer ${denyingBearer}` } },
        ),
      ),
    ]);
    const bodies = await Promise.all(responses.map(responseJson));

    assert.equal(responses.filter((response) => response.status === 200).length, 1);
    assert.equal(responses.filter((response) => response.status === 409).length, 1);
    for (const [index, response] of responses.entries()) {
      if (response.status === 409) {
        assert.equal("access_token" in bodies[index], false);
        assert.equal("refresh_token" in bodies[index], false);
        assert.equal("entitlement_assertion" in bodies[index], false);
      }
    }

    const grant = db.device_grants[0];
    const decisionStatus = grant.status;
    const deviceLicenses = db.licenses.filter(
      (license) => license.id !== approvingBrowser.id && license.id !== denyingBrowser.id,
    );
    const pollResponse = await poll.POST(
      jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
    );
    const pollBody = await responseJson(pollResponse);

    if (decisionStatus === "approved") {
      assert.equal(responses[0].status, 200);
      assert.equal(responses[1].status, 409);
      assert.equal(grant.user_id, approvingUser.id);
      assert.equal(deviceLicenses.length, 1);
      assert.equal(deviceLicenses[0].user_id, approvingUser.id);
      assert.equal(pollResponse.status, 200);
      assertEntitlementEnvelope(pollBody, {
        sub: approvingUser.id,
        license_id: deviceLicenses[0].id,
        email: approvingUser.email,
        tier: "pro",
        entitlements: ["real_estate_sales"],
      });
    } else {
      assert.equal(grant.status, "denied");
      assert.equal(responses[0].status, 409);
      assert.equal(responses[1].status, 200);
      assert.equal(grant.user_id, denyingUser.id);
      assert.equal(grant.license_id, null);
      assert.equal(grant.refresh_token_plain, null);
      assert.equal(deviceLicenses.length, 0);
      assert.equal(pollResponse.status, 403);
      assert.deepEqual(pollBody, { error: "access_denied", status: "denied" });
    }
    assert.equal(db.audit_log.length, 1);
  });

  for (const failureStage of [
    "after_license_insert",
    "after_grant_update",
    "after_audit_insert",
  ] as const) {
    it(`device approval rolls back every write when ${failureStage} fails`, async () => {
      const db = useFakeDb();
      const user = await makeUser({
        id: `atomic-failure-${failureStage}`,
        email: `${failureStage.replaceAll("_", "-")}@example.com`,
      });
      db.users.push(user);
      const browserLicense = seedLicense({
        id: `browser-${failureStage}`,
        user_id: user.id,
      });
      const bearer = await issueAccessToken(user, browserLicense);
      const start = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/start");
      const approve = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
        "device/approve",
      );
      const poll = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/poll");

      const startBody = await responseJson(
        await start.POST(jsonRequest("/api/device/start", { device_label: "Transactional CLI" })),
      );
      failNextAtomicDeviceApproval(failureStage);
      const failedResponse = await approve.POST(
        jsonRequest(
          "/api/device/approve",
          { user_code: startBody.user_code },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      );
      const failedBody = await responseJson(failedResponse);
      const grant = db.device_grants[0];

      assert.equal(failedResponse.status, 500);
      assert.deepEqual(failedBody, { error: "approval_failed" });
      assert.equal("access_token" in failedBody, false);
      assert.equal("refresh_token" in failedBody, false);
      assert.equal("entitlement_assertion" in failedBody, false);
      assert.equal(grant.status, "pending");
      assert.equal(grant.user_id, null);
      assert.equal(grant.license_id, null);
      assert.equal(grant.refresh_token_plain, null);
      assert.deepEqual(db.licenses.map((license) => license.id), [browserLicense.id]);
      assert.equal(db.audit_log.length, 0);

      const stillPending = await poll.POST(
        jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
      );
      const pendingBody = await responseJson(stillPending);
      assert.equal(stillPending.status, 200);
      assert.deepEqual(pendingBody, { status: "pending", interval: 5 });

      const retry = await approve.POST(
        jsonRequest(
          "/api/device/approve",
          { user_code: startBody.user_code },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      );
      assert.equal(retry.status, 200);
      assert.equal(grant.status, "approved");
      assert.equal(db.licenses.length, 2);
      assert.equal(db.audit_log.length, 1);
    });
  }

  it("device approval expires stale plaintext without creating a license", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "expired-approval-user" });
    db.users.push(user);
    const browserLicense = seedLicense({
      id: "expired-approval-browser",
      user_id: user.id,
    });
    const bearer = await issueAccessToken(user, browserLicense);
    const start = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/start");
    const approve = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "device/approve",
    );
    const startBody = await responseJson(
      await start.POST(jsonRequest("/api/device/start", { device_label: "Expired approval" })),
    );
    const grant = db.device_grants[0];
    grant.expires_at = new Date(Date.now() - 1000).toISOString();
    grant.refresh_token_plain = "defensive-stale-plaintext";

    const response = await approve.POST(
      jsonRequest(
        "/api/device/approve",
        { user_code: startBody.user_code },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 410);
    assert.deepEqual(body, { error: "expired" });
    assert.equal(grant.status, "expired");
    assert.equal(grant.refresh_token_plain, null);
    assert.deepEqual(db.licenses.map((license) => license.id), [browserLicense.id]);
    assert.equal(db.audit_log.length, 0);
  });

  it("device poll has one winner when an approved grant is claimed concurrently", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "device-race-user", email: "device-race@example.com" });
    db.users.push(user);
    const browserLicense = seedLicense({ id: "device-race-browser", user_id: user.id });
    const bearer = await issueAccessToken(user, browserLicense);
    const start = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/start");
    const approve = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "device/approve",
    );
    const poll = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/poll");

    const startBody = await responseJson(
      await start.POST(jsonRequest("/api/device/start", { device_label: "Concurrent CLI" })),
    );
    const approveResponse = await approve.POST(
      jsonRequest(
        "/api/device/approve",
        { user_code: startBody.user_code },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    assert.equal(approveResponse.status, 200);

    barrierNextSupabasePatches("device_grants");
    const responses = await Promise.all([
      poll.POST(jsonRequest("/api/device/poll", { device_code: startBody.device_code })),
      poll.POST(jsonRequest("/api/device/poll", { device_code: startBody.device_code })),
    ]);
    const results = await Promise.all(
      responses.map(async (response) => ({ response, body: await responseJson(response) })),
    );
    const winners = results.filter(({ response }) => response.status === 200);
    const losers = results.filter(({ response }) => response.status === 410);

    assert.equal(winners.length, 1);
    assert.equal(losers.length, 1);
    assert.equal(db.device_grants[0].status, "claimed");
    assert.equal(db.device_grants[0].refresh_token_plain, null);
    assert.deepEqual(losers[0].body, { error: "already_claimed", status: "claimed" });
    assert.equal("access_token" in losers[0].body, false);
    assert.equal("refresh_token" in losers[0].body, false);
    assert.equal("entitlement_assertion" in losers[0].body, false);
  });

  it("device poll revalidates subscription state before issuing credentials", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "device-inactive-user" });
    db.users.push(user);
    const browserLicense = seedLicense({ id: "device-inactive-browser", user_id: user.id });
    const bearer = await issueAccessToken(user, browserLicense);
    const start = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/start");
    const approve = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "device/approve",
    );
    const poll = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/poll");

    const startBody = await responseJson(
      await start.POST(jsonRequest("/api/device/start", { device_label: "Inactive CLI" })),
    );
    const approveResponse = await approve.POST(
      jsonRequest(
        "/api/device/approve",
        { user_code: startBody.user_code },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    assert.equal(approveResponse.status, 200);

    const deviceLicense = db.licenses.find((candidate) => candidate.id !== browserLicense.id);
    assert.ok(deviceLicense);
    user.status = "inactive";

    const response = await poll.POST(
      jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 402);
    assert.deepEqual(body, { error: "subscription inactive" });
    assert.equal("access_token" in body, false);
    assert.equal("refresh_token" in body, false);
    assert.equal("entitlement_assertion" in body, false);
    assert.equal(deviceLicense.revoked, true);
    assert.equal(db.device_grants[0].status, "expired");
    assert.equal(db.device_grants[0].refresh_token_plain, null);
  });

  it("device poll binds the approved user, license, and stashed refresh token", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "bound-device-user" });
    const other = await makeUser({ id: "other-device-user", email: "other-device@example.com" });
    db.users.push(user, other);
    const browserLicense = seedLicense({ id: "bound-device-browser", user_id: user.id });
    const bearer = await issueAccessToken(user, browserLicense);
    const start = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/start");
    const approve = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "device/approve",
    );
    const poll = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/poll");

    const startBody = await responseJson(
      await start.POST(jsonRequest("/api/device/start", { device_label: "Bound CLI" })),
    );
    const approveResponse = await approve.POST(
      jsonRequest(
        "/api/device/approve",
        { user_code: startBody.user_code },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    assert.equal(approveResponse.status, 200);
    const grant = db.device_grants[0];
    const stashedRefresh = grant.refresh_token_plain;
    assert.equal(typeof stashedRefresh, "string");

    grant.refresh_token_plain = "refresh-from-another-approval";
    const mismatchedRefresh = await poll.POST(
      jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
    );
    const mismatchedRefreshBody = await responseJson(mismatchedRefresh);
    assert.equal(mismatchedRefresh.status, 500);
    assert.deepEqual(mismatchedRefreshBody, { error: "invalid_grant" });
    assert.equal("access_token" in mismatchedRefreshBody, false);
    assert.equal("refresh_token" in mismatchedRefreshBody, false);
    assert.equal(grant.status, "expired");
    assert.equal(grant.refresh_token_plain, null);

    grant.status = "approved";
    grant.refresh_token_plain = stashedRefresh;
    grant.user_id = other.id;
    const mismatchedUser = await poll.POST(
      jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
    );
    const mismatchedUserBody = await responseJson(mismatchedUser);
    assert.equal(mismatchedUser.status, 500);
    assert.deepEqual(mismatchedUserBody, { error: "invalid_grant" });
    assert.equal("access_token" in mismatchedUserBody, false);
    assert.equal("refresh_token" in mismatchedUserBody, false);
    assert.equal(grant.status, "expired");
    assert.equal(grant.refresh_token_plain, null);
  });

  it("device poll expires an approved grant and clears its plaintext refresh stash", async () => {
    const db = useFakeDb();
    const user = await makeUser({ id: "expired-device-user" });
    db.users.push(user);
    const browserLicense = seedLicense({ id: "expired-device-browser", user_id: user.id });
    const bearer = await issueAccessToken(user, browserLicense);
    const start = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/start");
    const approve = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "device/approve",
    );
    const poll = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/poll");

    const startBody = await responseJson(
      await start.POST(jsonRequest("/api/device/start", { device_label: "Expired CLI" })),
    );
    const approveResponse = await approve.POST(
      jsonRequest(
        "/api/device/approve",
        { user_code: startBody.user_code },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    assert.equal(approveResponse.status, 200);
    assert.equal(typeof db.device_grants[0].refresh_token_plain, "string");
    db.device_grants[0].expires_at = new Date(Date.now() - 1000).toISOString();

    const response = await poll.POST(
      jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 410);
    assert.deepEqual(body, { error: "expired_token", status: "expired" });
    assert.equal("access_token" in body, false);
    assert.equal("refresh_token" in body, false);
    assert.equal("entitlement_assertion" in body, false);
    assert.equal(db.device_grants[0].status, "expired");
    assert.equal(db.device_grants[0].refresh_token_plain, null);
  });

  it("device grant expiry cleanup clears only stale pending or approved stashes", async () => {
    const db = useFakeDb();
    const start = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/start");
    await start.POST(jsonRequest("/api/device/start", { device_label: "Stale CLI" }));
    await start.POST(jsonRequest("/api/device/start", { device_label: "Fresh CLI" }));
    assert.equal(db.device_grants.length, 2);

    db.device_grants[0].status = "approved";
    db.device_grants[0].expires_at = new Date(Date.now() - 1000).toISOString();
    db.device_grants[0].refresh_token_plain = "stale-plaintext-refresh";
    db.device_grants[1].status = "approved";
    db.device_grants[1].expires_at = new Date(Date.now() + 60_000).toISOString();
    db.device_grants[1].refresh_token_plain = "fresh-plaintext-refresh";

    const { expireStaleDeviceGrants } = await import("../src/lib/store");
    await expireStaleDeviceGrants();

    assert.equal(db.device_grants[0].status, "expired");
    assert.equal(db.device_grants[0].refresh_token_plain, null);
    assert.equal(db.device_grants[1].status, "approved");
    assert.equal(db.device_grants[1].refresh_token_plain, "fresh-plaintext-refresh");
  });

  it("starting a new device flow sweeps abandoned expired plaintext stashes", async () => {
    const db = useFakeDb();
    const start = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/start");
    await start.POST(jsonRequest("/api/device/start", { device_label: "Abandoned CLI" }));
    const abandoned = db.device_grants[0];
    abandoned.status = "approved";
    abandoned.expires_at = new Date(Date.now() - 1000).toISOString();
    abandoned.refresh_token_plain = "abandoned-plaintext-refresh";

    const response = await start.POST(
      jsonRequest("/api/device/start", { device_label: "Replacement CLI" }),
    );

    assert.equal(response.status, 200);
    assert.equal(abandoned.status, "expired");
    assert.equal(abandoned.refresh_token_plain, null);
    assert.equal(db.device_grants.length, 2);
    assert.equal(db.device_grants[1].status, "pending");
  });

  it("device poll does not return a one-shot refresh token when clearing it fails", async () => {
    const db = useFakeDb();
    const user = await makeUser();
    db.users.push(user);
    const browserLicense = seedLicense({ id: "browser-license", user_id: user.id });
    const bearer = await issueAccessToken(user, browserLicense);
    const start = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/start");
    const approve = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/approve");
    const poll = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/poll");

    const startResponse = await start.POST(
      jsonRequest("/api/device/start", { device_label: "CLI" }),
    );
    const startBody = await responseJson(startResponse);

    const approveResponse = await approve.POST(
      jsonRequest(
        "/api/device/approve",
        { user_code: startBody.user_code },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );

    assert.equal(approveResponse.status, 200);
    assert.equal(typeof db.device_grants[0].refresh_token_plain, "string");

    failNextSupabasePatch("device_grants");
    const pollResponse = await poll.POST(
      jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
    );
    const pollBody = await responseJson(pollResponse);

    assert.equal(pollResponse.status, 500);
    assert.deepEqual(pollBody, { error: "invalid_grant" });
    assert.equal(db.device_grants[0].status, "approved");
    assert.equal(typeof db.device_grants[0].refresh_token_plain, "string");
  });

  it("device lookup and deny report the browser approval leg", async () => {
    const db = useFakeDb();
    const user = await makeUser();
    db.users.push(user);
    const browserLicense = seedLicense({ id: "browser-license", user_id: user.id });
    const bearer = await issueAccessToken(user, browserLicense);
    const start = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/start");
    const lookup = await loadRoute<{ GET: (req: Request) => Promise<Response> }>("device/lookup");
    const deny = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/deny");
    const poll = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("device/poll");

    const startResponse = await start.POST(
      jsonRequest(
        "/api/device/start",
        { device_label: "CLI lookup" },
        { headers: { origin: "https://app.test", "user-agent": "lookup-cli" } },
      ),
    );
    const startBody = await responseJson(startResponse);

    const lookupResponse = await lookup.GET(
      jsonRequest(
        `/api/device/lookup?code=${startBody.user_code}`,
        {},
        { method: "GET", headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    const lookupBody = await responseJson(lookupResponse);

    assert.equal(lookupResponse.status, 200);
    assert.equal(lookupBody.status, "pending");
    assert.equal(lookupBody.device_label, "CLI lookup");
    assert.equal(lookupBody.user_agent, "lookup-cli");

    db.device_grants[0].refresh_token_plain = "defensive-stale-refresh";

    const denyResponse = await deny.POST(
      jsonRequest(
        "/api/device/deny",
        { user_code: startBody.user_code },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );

    assert.equal(denyResponse.status, 200);
    assert.equal(db.device_grants[0].status, "denied");
    assert.equal(db.device_grants[0].refresh_token_plain, null);
    assert.equal(db.audit_log.length, 1);

    const pollResponse = await poll.POST(
      jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
    );
    const pollBody = await responseJson(pollResponse);

    assert.equal(pollResponse.status, 403);
    assert.deepEqual(pollBody, { error: "access_denied", status: "denied" });
  });

  it("login-code request and verify issue the desktop token envelope", async () => {
    const previousNodeEnv = process.env.NODE_ENV;
    Reflect.set(process.env, "NODE_ENV", "test");
    try {
      const db = useFakeDb();
      const user = await makeUser({ email: "login-code@example.com" });
      db.users.push(user);
      const requestRoute = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
        "auth/login-code/request",
      );
      const verifyRoute = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
        "auth/login-code/verify",
      );

      const requested = await requestRoute.POST(
        jsonRequest(
          "/api/auth/login-code/request",
          { email: "login-code@example.com" },
          { headers: { "x-forwarded-for": "127.0.0.1", "user-agent": "admin-web" } },
        ),
      );
      const requestedBody = await responseJson(requested);
      const code = (requestedBody.dev_only as { code?: string } | undefined)?.code;

      assert.equal(requested.status, 200);
      assert.match(String(code), /^\d{6}$/);
      assert.equal(db.login_codes.length, 1);
      assert.equal(db.login_codes[0].user_id, user.id);
      assert.equal(
        db.login_codes[0].code_hash,
        crypto.createHash("sha256").update(String(code)).digest("hex"),
      );
      const wrongCode = code === "000000" ? "999999" : "000000";

      const rejected = await verifyRoute.POST(
        jsonRequest("/api/auth/login-code/verify", {
          email: "login-code@example.com",
          code: wrongCode,
        }),
      );
      const rejectedBody = await responseJson(rejected);

      assert.equal(rejected.status, 401);
      assert.deepEqual(rejectedBody, { error: "invalid code" });
      assert.equal(db.login_codes[0].attempts, 1);

      const accepted = await withTestEntitlementSigningRing(
        TEST_ENTITLEMENT_KEY_B,
        () =>
          verifyRoute.POST(
            jsonRequest("/api/auth/login-code/verify", {
              email: "login-code@example.com",
              code,
              device_label: "Admin Web",
            }),
          ),
      );
      const acceptedBody = await responseJson(accepted);

      assert.equal(accepted.status, 200);
      assert.equal(typeof acceptedBody.access_token, "string");
      assert.equal(typeof acceptedBody.refresh_token, "string");
      assert.match(String(acceptedBody.license_id), /^[0-9a-f-]{36}$/);
      assert.equal(acceptedBody.tier, "pro");
      assert.deepEqual(acceptedBody.entitlements, ["real_estate_sales"]);
      assert.equal(db.licenses[0].id, acceptedBody.license_id);
      assert.equal(db.licenses[0].device_label, "Admin Web");
      assert.equal(typeof db.login_codes[0].consumed_at, "string");
      assertEntitlementEnvelope(acceptedBody, {
        sub: user.id,
        license_id: String(acceptedBody.license_id),
        email: user.email,
        tier: "pro",
        entitlements: ["real_estate_sales"],
        kid: TEST_ENTITLEMENT_KEY_B,
      });
    } finally {
      if (previousNodeEnv === undefined) {
        Reflect.deleteProperty(process.env, "NODE_ENV");
      } else {
        Reflect.set(process.env, "NODE_ENV", previousNodeEnv);
      }
    }
  });

  it("new login-code issuance supersedes every older unconsumed code", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "supersede-code@example.com" });
    db.users.push(user);
    const requestRoute = await loadRoute<PostRoute>("auth/login-code/request");
    const verifyRoute = await loadRoute<PostRoute>("auth/login-code/verify");

    const firstCode = await requestDevLoginCode(requestRoute, user.email, "127.0.0.10");
    db.login_codes.push({
      ...db.login_codes[0],
      id: "legacy-unconsumed-login-code",
      code_hash: crypto.createHash("sha256").update("123456").digest("hex"),
      created_at: new Date(Date.now() - 60_000).toISOString(),
      consumed_at: null,
    });
    assert.equal(db.login_codes.filter((candidate) => candidate.consumed_at === null).length, 2);
    let newestCode = await requestDevLoginCode(requestRoute, user.email, "127.0.0.11");
    if (newestCode === firstCode) {
      newestCode = await requestDevLoginCode(requestRoute, user.email, "127.0.0.12");
    }

    const active = db.login_codes.filter((candidate) => candidate.consumed_at === null);
    assert.equal(active.length, 1);
    assert.equal(
      active[0].code_hash,
      crypto.createHash("sha256").update(newestCode).digest("hex"),
    );
    assert.equal(
      db.login_codes
        .filter((candidate) => candidate.id !== active[0].id)
        .every((candidate) => typeof candidate.consumed_at === "string"),
      true,
    );

    const oldResponse = await verifyRoute.POST(
      jsonRequest("/api/auth/login-code/verify", { email: user.email, code: firstCode }),
    );
    assert.equal(oldResponse.status, 401);
    assert.deepEqual(await responseJson(oldResponse), { error: "invalid code" });
    assert.equal(db.licenses.length, 0);

    const newestResponse = await verifyRoute.POST(
      jsonRequest("/api/auth/login-code/verify", { email: user.email, code: newestCode }),
    );
    assert.equal(newestResponse.status, 200);
    assert.equal(db.licenses.length, 1);
  });

  it("concurrent login-code requests leave exactly one newest active code", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "concurrent-issue@example.com" });
    db.users.push(user);
    const requestRoute = await loadRoute<PostRoute>("auth/login-code/request");

    barrierNextSupabaseRpcs("issue_login_code_atomic");
    const codes = await Promise.all([
      requestDevLoginCode(requestRoute, user.email, "127.0.0.20"),
      requestDevLoginCode(requestRoute, user.email, "127.0.0.21"),
    ]);

    assert.equal(db.login_codes.length, 2);
    assert.equal(db.login_codes.filter((candidate) => candidate.consumed_at === null).length, 1);
    assert.equal(db.login_codes.filter((candidate) => candidate.consumed_at !== null).length, 1);
    const active = db.login_codes.find((candidate) => candidate.consumed_at === null);
    assert.ok(active);
    assert.equal(
      codes.some(
        (code) => crypto.createHash("sha256").update(code).digest("hex") === active.code_hash,
      ),
      true,
    );
    assert.equal(db.audit_log.length, 2);
  });

  it("concurrent wrong login-code guesses count exactly and enforce the cap", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "wrong-race@example.com" });
    db.users.push(user);
    const requestRoute = await loadRoute<PostRoute>("auth/login-code/request");
    const verifyRoute = await loadRoute<PostRoute>("auth/login-code/verify");
    const correctCode = await requestDevLoginCode(requestRoute, user.email, "127.0.0.30");
    const wrongCode = correctCode === "000000" ? "999999" : "000000";

    barrierNextSupabaseRpcs("record_login_code_attempt_atomic", 5);
    const responses = await Promise.all(
      Array.from({ length: 5 }, () =>
        verifyRoute.POST(
          jsonRequest("/api/auth/login-code/verify", { email: user.email, code: wrongCode }),
        ),
      ),
    );
    for (const response of responses) {
      assert.equal(response.status, 401);
      assert.deepEqual(await responseJson(response), { error: "invalid code" });
    }

    assert.equal(db.login_codes[0].attempts, 5);
    const sixth = await verifyRoute.POST(
      jsonRequest("/api/auth/login-code/verify", { email: user.email, code: wrongCode }),
    );
    const correctAfterCap = await verifyRoute.POST(
      jsonRequest("/api/auth/login-code/verify", { email: user.email, code: correctCode }),
    );
    assert.equal(sixth.status, 401);
    assert.equal(correctAfterCap.status, 401);
    assert.deepEqual(await responseJson(sixth), { error: "invalid code" });
    assert.deepEqual(await responseJson(correctAfterCap), { error: "invalid code" });
    assert.equal(db.login_codes[0].attempts, 5);
    assert.equal(db.login_codes[0].consumed_at, null);
    assert.equal(db.licenses.length, 0);
  });

  it("concurrent correct login-code redeems create exactly one license", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "correct-race@example.com" });
    db.users.push(user);
    const requestRoute = await loadRoute<PostRoute>("auth/login-code/request");
    const verifyRoute = await loadRoute<PostRoute>("auth/login-code/verify");
    const code = await requestDevLoginCode(requestRoute, user.email, "127.0.0.40");

    barrierNextSupabaseRpcs("redeem_login_code_atomic");
    const responses = await Promise.all([
      verifyRoute.POST(jsonRequest("/api/auth/login-code/verify", { email: user.email, code })),
      verifyRoute.POST(jsonRequest("/api/auth/login-code/verify", { email: user.email, code })),
    ]);
    const results = await Promise.all(
      responses.map(async (response) => ({ response, body: await responseJson(response) })),
    );
    const winner = results.find(({ response }) => response.status === 200);
    const loser = results.find(({ response }) => response.status === 401);

    assert.ok(winner);
    assert.ok(loser);
    assert.deepEqual(loser.body, { error: "invalid code" });
    assert.equal("access_token" in loser.body, false);
    assert.equal("refresh_token" in loser.body, false);
    assert.equal("entitlement_assertion" in loser.body, false);
    assert.equal(db.licenses.length, 1);
    assert.equal(db.licenses[0].id, winner.body.license_id);
    assert.equal(typeof db.login_codes[0].consumed_at, "string");
  });

  it("concurrent correct and wrong login-code attempts preserve one winner", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "mixed-race@example.com" });
    db.users.push(user);
    const requestRoute = await loadRoute<PostRoute>("auth/login-code/request");
    const verifyRoute = await loadRoute<PostRoute>("auth/login-code/verify");
    const code = await requestDevLoginCode(requestRoute, user.email, "127.0.0.50");
    const wrongCode = code === "000000" ? "999999" : "000000";

    barrierNextLoginCodeOperations();
    const [correct, wrong] = await Promise.all([
      verifyRoute.POST(jsonRequest("/api/auth/login-code/verify", { email: user.email, code })),
      verifyRoute.POST(
        jsonRequest("/api/auth/login-code/verify", { email: user.email, code: wrongCode }),
      ),
    ]);

    assert.equal(correct.status, 200);
    assert.equal(wrong.status, 401);
    assert.deepEqual(await responseJson(wrong), { error: "invalid code" });
    assert.equal(db.licenses.length, 1);
    assert.equal(typeof db.login_codes[0].consumed_at, "string");
    assert.ok(db.login_codes[0].attempts === 0 || db.login_codes[0].attempts === 1);
  });

  it("new issuance racing an old correct code cannot redeem the replacement", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "new-old-race@example.com" });
    db.users.push(user);
    const requestRoute = await loadRoute<PostRoute>("auth/login-code/request");
    const verifyRoute = await loadRoute<PostRoute>("auth/login-code/verify");
    const oldCode = await requestDevLoginCode(requestRoute, user.email, "127.0.0.60");
    const oldCodeId = db.login_codes[0].id;

    barrierNextLoginCodeOperations();
    const [newRequest, oldRedeem] = await Promise.all([
      requestRoute.POST(
        jsonRequest(
          "/api/auth/login-code/request",
          { email: user.email },
          { headers: { "x-forwarded-for": "127.0.0.61" } },
        ),
      ),
      verifyRoute.POST(
        jsonRequest("/api/auth/login-code/verify", { email: user.email, code: oldCode }),
      ),
    ]);
    const newBody = await responseJson(newRequest);
    let newCode = String((newBody.dev_only as { code?: string } | undefined)?.code || "");

    assert.equal(newRequest.status, 200);
    assert.match(newCode, /^\d{6}$/);
    assert.ok(oldRedeem.status === 200 || oldRedeem.status === 401);

    // A random collision would make the old plaintext valid for the replacement
    // by coincidence. Reissue once so this assertion tests identity binding,
    // not six-digit-code luck.
    if (newCode === oldCode) {
      newCode = await requestDevLoginCode(requestRoute, user.email, "127.0.0.62");
    }
    assert.notEqual(newCode, oldCode);
    assert.equal(db.login_codes.filter((candidate) => candidate.consumed_at === null).length, 1);
    const active = db.login_codes.find((candidate) => candidate.consumed_at === null);
    assert.ok(active);
    assert.notEqual(active.id, oldCodeId);
    assert.equal(active.code_hash, crypto.createHash("sha256").update(newCode).digest("hex"));
    assert.equal(db.licenses.length, oldRedeem.status === 200 ? 1 : 0);

    const licensesAfterRace = db.licenses.length;
    const staleRetry = await verifyRoute.POST(
      jsonRequest("/api/auth/login-code/verify", { email: user.email, code: oldCode }),
    );
    assert.equal(staleRetry.status, 401);
    assert.deepEqual(await responseJson(staleRetry), { error: "invalid code" });
    assert.equal(db.licenses.length, licensesAfterRace);
  });

  for (const failureStage of [
    "issue_after_invalidate",
    "issue_after_insert",
    "issue_after_audit",
  ] as const) {
    it(`login-code issuance rolls back every write when ${failureStage} fails`, async () => {
      const db = useFakeDb();
      const user = await makeUser({
        email: `${failureStage.replaceAll("_", "-")}@example.com`,
      });
      db.users.push(user);
      const requestRoute = await loadRoute<PostRoute>("auth/login-code/request");
      await requestDevLoginCode(requestRoute, user.email, "127.0.0.70");
      const oldCode = db.login_codes[0];
      const baselineAudit = db.audit_log.length;

      failNextAtomicLoginCode(failureStage);
      const failed = await requestRoute.POST(
        jsonRequest(
          "/api/auth/login-code/request",
          { email: user.email },
          { headers: { "x-forwarded-for": "127.0.0.71" } },
        ),
      );

      assert.equal(failed.status, 200);
      assert.deepEqual(await responseJson(failed), { ok: true });
      assert.equal(db.login_codes.length, 1);
      assert.equal(oldCode.consumed_at, null);
      assert.equal(db.audit_log.length, baselineAudit);
    });
  }

  it("login-code attempt rollback preserves the counter after an update failure", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "attempt-rollback@example.com" });
    db.users.push(user);
    const requestRoute = await loadRoute<PostRoute>("auth/login-code/request");
    const verifyRoute = await loadRoute<PostRoute>("auth/login-code/verify");
    const code = await requestDevLoginCode(requestRoute, user.email, "127.0.0.75");
    const wrongCode = code === "000000" ? "000001" : "000000";

    failNextAtomicLoginCode("attempt_after_increment");
    const failed = await verifyRoute.POST(
      jsonRequest("/api/auth/login-code/verify", { email: user.email, code: wrongCode }),
    );
    assert.equal(failed.status, 401);
    assert.deepEqual(await responseJson(failed), { error: "invalid code" });
    assert.equal(db.login_codes[0].attempts, 0);

    const retry = await verifyRoute.POST(
      jsonRequest("/api/auth/login-code/verify", { email: user.email, code: wrongCode }),
    );
    assert.equal(retry.status, 401);
    assert.equal(db.login_codes[0].attempts, 1);
  });

  for (const failureStage of [
    "redeem_after_consume",
    "redeem_after_license_insert",
  ] as const) {
    it(`login-code redeem rolls back code and license when ${failureStage} fails`, async () => {
      const db = useFakeDb();
      const user = await makeUser({
        email: `${failureStage.replaceAll("_", "-")}@example.com`,
      });
      db.users.push(user);
      const requestRoute = await loadRoute<PostRoute>("auth/login-code/request");
      const verifyRoute = await loadRoute<PostRoute>("auth/login-code/verify");
      const code = await requestDevLoginCode(requestRoute, user.email, "127.0.0.80");

      failNextAtomicLoginCode(failureStage);
      const failed = await verifyRoute.POST(
        jsonRequest("/api/auth/login-code/verify", { email: user.email, code }),
      );
      assert.equal(failed.status, 503);
      assert.deepEqual(await responseJson(failed), { error: "license issuance unavailable" });
      assert.equal(db.login_codes[0].consumed_at, null);
      assert.equal(db.licenses.length, 0);

      const retry = await verifyRoute.POST(
        jsonRequest("/api/auth/login-code/verify", { email: user.email, code }),
      );
      assert.equal(retry.status, 200);
      assert.equal(typeof db.login_codes[0].consumed_at, "string");
      assert.equal(db.licenses.length, 1);
    });
  }

  it("atomic login-code redeem rechecks active subscription before mutation", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "rpc-inactive-code@example.com" });
    db.users.push(user);
    const requestRoute = await loadRoute<PostRoute>("auth/login-code/request");
    await requestDevLoginCode(requestRoute, user.email, "127.0.0.90");
    const loginCode = db.login_codes[0];
    user.status = "inactive";
    const { redeemLoginCode } = await import("../src/lib/store");

    const result = await redeemLoginCode({
      userId: user.id,
      loginCodeId: loginCode.id,
      codeHash: loginCode.code_hash,
      licenseId: crypto.randomUUID(),
      refreshTokenHash: refreshHash("inactive-refresh"),
      deviceLabel: "Inactive RPC",
      maxAttempts: 5,
    });

    assert.deepEqual(result, { result: "inactive" });
    assert.equal(loginCode.consumed_at, null);
    assert.equal(db.licenses.length, 0);
  });

  it("diagnostics requires bearer auth and stores sanitized idempotent rows", async () => {
    const db = useFakeDb(createFakeDb());
    const user = await makeUser();
    db.users.push(user);
    const license = seedLicense({ id: "diagnostics-license", user_id: user.id });
    const bearer = await issueAccessToken(user, license);
    const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "diagnostics/session-events",
    );

    const missingBearer = await route.POST(
      jsonRequest("/api/diagnostics/session-events", { events: [] }),
    );
    assert.equal(missingBearer.status, 401);

    const event = {
      event_id: "evt-1",
      event: "Diagnostics.Raw",
      ts: 1_700_000_000,
      seq: 7,
      severity: "warn",
      source: "desktop",
      component: "gateway",
      session_id: "session-1",
      payload: {
        message_count: 4,
        success: true,
        status: "failed for joe@example.com token=sk-1234567890abcdef password=hunter2 /Users/dartagnanpatricio/private/report.pdf",
        prompt: "raw prompt",
        body: "secret body",
        unknown: "dropped",
      },
      redaction: {
        strings_redacted: 2.8,
        bad: "drop me",
      },
    };

    const accepted = await route.POST(
      jsonRequest(
        "/api/diagnostics/session-events",
        { events: [event, event] },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    const acceptedBody = await responseJson(accepted);

    assert.equal(accepted.status, 200);
    assert.deepEqual(acceptedBody, { accepted: 2 });
    assert.equal(db.session_diagnostic_events.length, 1);
    assert.deepEqual(db.session_diagnostic_events[0].payload, {
      message_count: 4,
      success: true,
      status:
        "failed for [redacted-email] token=[redacted-secret] password=[redacted-secret] [path:report.pdf]",
    });
    assert.deepEqual(db.session_diagnostic_events[0].redaction, {
      strings_redacted: 2,
    });
    assert.equal(db.session_diagnostic_events[0].event, "diagnostics.raw");
    assertNoRawDiagnosticsText(db);
    const stored = JSON.stringify(db.session_diagnostic_events);
    assert.equal(stored.includes("joe@example.com"), false);
    assert.equal(stored.includes("hunter2"), false);
    assert.equal(stored.includes("sk-1234567890abcdef"), false);
    assert.equal(stored.includes("/Users/dartagnanpatricio"), false);
  });

  it("diagnostics maps revoked hosted bearer licenses to 403", async () => {
    const db = useFakeDb();
    const user = await makeUser();
    db.users.push(user);
    const license = seedLicense({
      id: "revoked-diagnostics-license",
      user_id: user.id,
      revoked: true,
    });
    const bearer = await issueAccessToken(user, license);
    const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>(
      "diagnostics/session-events",
    );

    const response = await route.POST(
      jsonRequest(
        "/api/diagnostics/session-events",
        { events: [] },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 403);
    assert.deepEqual(body, { error: "license revoked" });
  });
});
