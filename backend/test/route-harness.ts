import assert from "node:assert/strict";
import crypto from "node:crypto";
import { pathToFileURL } from "node:url";
import bcrypt from "bcryptjs";

const testEntitlementKeyPair = crypto.generateKeyPairSync("ed25519");
const testEntitlementKeyPairB = crypto.generateKeyPairSync("ed25519");
const TEST_ENTITLEMENT_PRIVATE_KEY_PKCS8_DER_B64 = testEntitlementKeyPair.privateKey
  .export({ format: "der", type: "pkcs8" })
  .toString("base64");
const TEST_ENTITLEMENT_PUBLIC_KEY_SPKI_DER_B64 = testEntitlementKeyPair.publicKey
  .export({ format: "der", type: "spki" })
  .toString("base64");
const TEST_ENTITLEMENT_PRIVATE_KEY_B_PKCS8_DER_B64 = testEntitlementKeyPairB.privateKey
  .export({ format: "der", type: "pkcs8" })
  .toString("base64");
const TEST_ENTITLEMENT_PUBLIC_KEY_B_SPKI_DER_B64 = testEntitlementKeyPairB.publicKey
  .export({ format: "der", type: "spki" })
  .toString("base64");

export const TEST_ENTITLEMENT_KEY_A = "ent-2026-07-a";
export const TEST_ENTITLEMENT_KEY_B = "ent-2026-07-b";
const TEST_ENTITLEMENT_PUBLIC_KEYS = {
  [TEST_ENTITLEMENT_KEY_A]: TEST_ENTITLEMENT_PUBLIC_KEY_SPKI_DER_B64,
  [TEST_ENTITLEMENT_KEY_B]: TEST_ENTITLEMENT_PUBLIC_KEY_B_SPKI_DER_B64,
} as const;

process.env.JWT_SECRET ||= "test-secret-for-hosted-route-handler-harness";
process.env.SUPABASE_URL ||= "https://example.supabase.test";
process.env.SUPABASE_SERVICE_ROLE_KEY ||= "test-service-role-key";
process.env.ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEY_B64 ||=
  TEST_ENTITLEMENT_PRIVATE_KEY_PKCS8_DER_B64;

export async function withTestEntitlementSigningRing<T>(
  activeKeyId: typeof TEST_ENTITLEMENT_KEY_A | typeof TEST_ENTITLEMENT_KEY_B,
  run: () => Promise<T>,
): Promise<T> {
  const activeEnvironment = "ELEVATE_ENTITLEMENT_SIGNING_ACTIVE_KID";
  const ringEnvironment = "ELEVATE_ENTITLEMENT_SIGNING_PRIVATE_KEYS_B64_JSON";
  const previousActive = process.env[activeEnvironment];
  const previousRing = process.env[ringEnvironment];
  process.env[activeEnvironment] = activeKeyId;
  process.env[ringEnvironment] = JSON.stringify({
    [TEST_ENTITLEMENT_KEY_A]: TEST_ENTITLEMENT_PRIVATE_KEY_PKCS8_DER_B64,
    [TEST_ENTITLEMENT_KEY_B]: TEST_ENTITLEMENT_PRIVATE_KEY_B_PKCS8_DER_B64,
  });
  try {
    return await run();
  } finally {
    if (previousActive === undefined) Reflect.deleteProperty(process.env, activeEnvironment);
    else process.env[activeEnvironment] = previousActive;
    if (previousRing === undefined) Reflect.deleteProperty(process.env, ringEnvironment);
    else process.env[ringEnvironment] = previousRing;
  }
}

type UserStatus = "active" | "trialing" | "inactive" | "canceled" | "past_due";
type Tier = "pro" | "builder";

type UserRow = {
  id: string;
  email: string;
  password_hash: string;
  stripe_customer: string | null;
  tier: Tier;
  status: UserStatus;
  current_period_end: string | null;
  entitlements: string[];
  blocked_entitlements: string[];
  role: "owner" | "admin" | "user";
  is_developer: boolean;
  first_name: string | null;
  last_name: string | null;
  created_at: string;
  updated_at: string;
};

type LicenseRow = {
  id: string;
  user_id: string;
  device_label: string | null;
  refresh_token_hash: string;
  previous_refresh_token_hash: string | null;
  previous_refresh_attempt_hash: string | null;
  refresh_family_expires_at: string;
  revoked: boolean;
  last_used_at: string | null;
  created_at: string;
};

type DeviceGrantRow = {
  id: string;
  user_code: string;
  device_code_hash: string;
  user_id: string | null;
  license_id: string | null;
  status: "pending" | "approved" | "denied" | "expired" | "claimed";
  device_label: string | null;
  ip_addr: string | null;
  user_agent: string | null;
  created_at: string;
  expires_at: string;
  approved_at: string | null;
  claimed_at: string | null;
  last_polled_at: string | null;
  refresh_token_plain?: string | null;
};

type LoginCodeRow = {
  id: string;
  user_id: string;
  code_hash: string;
  created_at: string;
  expires_at: string;
  consumed_at: string | null;
  attempts: number;
  ip_addr: string | null;
  user_agent: string | null;
};

type PasswordResetTokenRow = {
  id: string;
  user_id: string;
  token_hash: string;
  created_at: string;
  expires_at: string;
  consumed_at: string | null;
  ip_addr: string | null;
  user_agent: string | null;
};

type OrgRow = {
  id: string;
  slug: string;
  name: string;
  stripe_customer: string | null;
  tier: Tier;
  status: UserStatus;
  current_period_end: string | null;
  entitlements: string[];
  seat_limit: number;
  created_at: string;
  updated_at: string;
};

type MembershipRow = {
  id: string;
  org_id: string;
  user_id: string;
  role: "owner" | "admin" | "member";
  created_at: string;
  organization: OrgRow;
};

type InvitationRow = {
  id: string;
  org_id: string;
  email: string;
  role: "owner" | "admin" | "member";
  token_hash: string;
  invited_by: string | null;
  status: "pending" | "accepted" | "revoked" | "expired";
  expires_at: string;
  accepted_at: string | null;
  accepted_user_id: string | null;
  created_at: string;
};

type CatalogRow = {
  name: string;
  version: number;
  tier_required: Tier;
  manifest: Record<string, unknown>;
  body?: string;
  enabled: boolean;
  updated_at: string;
  created_at: string;
};

type FakeDb = {
  users: UserRow[];
  licenses: LicenseRow[];
  organizations: OrgRow[];
  memberships: MembershipRow[];
  invitations: InvitationRow[];
  skills: CatalogRow[];
  automations: Array<CatalogRow & {
    surface: string;
    kind: "heartbeat" | "automation";
    schedule: string;
    skill: string;
    prompt: string;
    deliver: string;
    spec: Record<string, unknown>;
  }>;
  device_grants: DeviceGrantRow[];
  login_codes: LoginCodeRow[];
  password_reset_tokens: PasswordResetTokenRow[];
  skill_invocations: unknown[];
  audit_log: unknown[];
  session_diagnostic_events: Record<string, unknown>[];
  calls: Array<{ table: string; method: string; body: unknown }>;
};

const baseUrl = "https://example.supabase.test";
let activeDb: FakeDb = createFakeDb();
let nextUserId = 1;
let nextLicenseId = 1;
let nextGrantId = 1;
let nextLoginCodeId = 1;
let nextPasswordResetTokenId = 1;
let nextPatchFailure: { table: string; status: number; message: string } | null = null;
let nextInsertFailure: { table: string; status: number; message: string } | null = null;
let nextSelectFailure: { table: string; status: number; message: string } | null = null;
let nextPatchBarrier: {
  table: string;
  parties: number;
  arrived: number;
  promise: Promise<void>;
  release: () => void;
} | null = null;
let nextRpcBarrier: {
  name: string;
  parties: number;
  arrived: number;
  promise: Promise<void>;
  release: () => void;
} | null = null;
let nextDeviceGrantDecisionBarrier: {
  parties: number;
  arrived: number;
  promise: Promise<void>;
  release: () => void;
} | null = null;
export type AtomicDeviceApprovalFailureStage =
  | "after_license_insert"
  | "after_grant_update"
  | "after_audit_insert";
let nextAtomicDeviceApprovalFailure: AtomicDeviceApprovalFailureStage | null = null;
let nextLoginCodeOperationBarrier: {
  parties: number;
  arrived: number;
  promise: Promise<void>;
  release: () => void;
} | null = null;
let nextMembershipOperationBarrier: {
  parties: number;
  arrived: number;
  promise: Promise<void>;
  release: () => void;
} | null = null;
export type AtomicLoginCodeFailureStage =
  | "issue_after_invalidate"
  | "issue_after_insert"
  | "issue_after_audit"
  | "attempt_after_increment"
  | "redeem_after_consume"
  | "redeem_after_license_insert";
let nextAtomicLoginCodeFailure: AtomicLoginCodeFailureStage | null = null;
export type AtomicMembershipFailureStage =
  | "invitation_after_user_insert"
  | "invitation_after_membership_insert"
  | "invitation_after_invitation_update"
  | "invitation_after_license_insert"
  | "org_owner_after_org_insert"
  | "org_owner_after_membership_insert";
let nextAtomicMembershipFailure: AtomicMembershipFailureStage | null = null;
export type AtomicRefreshV2FailureStage = "after_rotation";
let nextAtomicRefreshV2Failure: AtomicRefreshV2FailureStage | null = null;

export function createFakeDb(overrides: Partial<FakeDb> = {}): FakeDb {
  return {
    users: [],
    licenses: [],
    organizations: [],
    memberships: [],
    invitations: [],
    skills: [],
    automations: [],
    device_grants: [],
    login_codes: [],
    password_reset_tokens: [],
    skill_invocations: [],
    audit_log: [],
    session_diagnostic_events: [],
    calls: [],
    ...overrides,
  };
}

export function useFakeDb(db = createFakeDb()): FakeDb {
  activeDb = db;
  nextUserId = db.users.length + 1;
  nextLicenseId = db.licenses.length + 1;
  nextGrantId = db.device_grants.length + 1;
  nextLoginCodeId = db.login_codes.length + 1;
  nextPasswordResetTokenId = db.password_reset_tokens.length + 1;
  nextPatchFailure = null;
  nextInsertFailure = null;
  nextSelectFailure = null;
  nextPatchBarrier = null;
  nextRpcBarrier = null;
  nextDeviceGrantDecisionBarrier = null;
  nextAtomicDeviceApprovalFailure = null;
  nextLoginCodeOperationBarrier = null;
  nextAtomicLoginCodeFailure = null;
  nextMembershipOperationBarrier = null;
  nextAtomicMembershipFailure = null;
  nextAtomicRefreshV2Failure = null;
  return activeDb;
}

export function barrierNextSupabasePatches(table: string, parties = 2): void {
  let release = () => {};
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  nextPatchBarrier = { table, parties, arrived: 0, promise, release };
}

export function barrierNextSupabaseRpcs(name: string, parties = 2): void {
  let release = () => {};
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  nextRpcBarrier = { name, parties, arrived: 0, promise, release };
}

export function barrierNextDeviceGrantDecisions(parties = 2): void {
  let release = () => {};
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  nextDeviceGrantDecisionBarrier = { parties, arrived: 0, promise, release };
}

export function failNextAtomicDeviceApproval(
  stage: AtomicDeviceApprovalFailureStage,
): void {
  nextAtomicDeviceApprovalFailure = stage;
}

export function barrierNextLoginCodeOperations(parties = 2): void {
  let release = () => {};
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  nextLoginCodeOperationBarrier = { parties, arrived: 0, promise, release };
}

export function failNextAtomicLoginCode(stage: AtomicLoginCodeFailureStage): void {
  nextAtomicLoginCodeFailure = stage;
}

export function barrierNextMembershipOperations(parties = 2): void {
  let release = () => {};
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  nextMembershipOperationBarrier = { parties, arrived: 0, promise, release };
}

export function failNextAtomicMembership(stage: AtomicMembershipFailureStage): void {
  nextAtomicMembershipFailure = stage;
}

export function failNextAtomicRefreshV2(stage: AtomicRefreshV2FailureStage): void {
  nextAtomicRefreshV2Failure = stage;
}

export function failNextSupabasePatch(
  table: string,
  status = 500,
  message = "supabase patch failed",
): void {
  nextPatchFailure = { table, status, message };
}

export function failNextSupabaseInsert(
  table: string,
  status = 500,
  message = "supabase insert failed",
): void {
  nextInsertFailure = { table, status, message };
}

export function failNextSupabaseSelect(
  table: string,
  status = 500,
  message = "supabase select failed",
): void {
  nextSelectFailure = { table, status, message };
}

export async function makeUser(
  values: Partial<UserRow> & { email?: string; password?: string; status?: UserStatus } = {},
): Promise<UserRow> {
  const now = new Date().toISOString();
  return {
    id: values.id || "user-1",
    email: (values.email || "agent@example.com").toLowerCase(),
    password_hash: values.password_hash || (await bcrypt.hash(values.password || "secret", 4)),
    stripe_customer: values.stripe_customer ?? null,
    tier: values.tier || "pro",
    status: values.status || "active",
    current_period_end: values.current_period_end ?? null,
    entitlements: values.entitlements || ["real_estate_sales"],
    blocked_entitlements: values.blocked_entitlements || [],
    role: values.role || "user",
    is_developer: values.is_developer ?? false,
    first_name: values.first_name ?? null,
    last_name: values.last_name ?? null,
    created_at: values.created_at || now,
    updated_at: values.updated_at || now,
  };
}

export function refreshHash(token: string): string {
  return crypto.createHash("sha256").update(token).digest("hex");
}

function refreshFamilyExpiry(createdAt: string): string {
  return new Date(Date.parse(createdAt) + 90 * 24 * 60 * 60 * 1000).toISOString();
}

export async function issueAccessToken(user: UserRow, license: LicenseRow): Promise<string> {
  const { signAccessToken } = await import("../src/lib/jwt");
  return signAccessToken({
    sub: user.id,
    email: user.email,
    tier: user.tier,
    license_id: license.id,
  });
}

export async function loadRoute<T extends Record<string, unknown>>(relativePath: string): Promise<T> {
  const url = pathToFileURL(new URL(`../src/app/api/${relativePath}/route.ts`, import.meta.url).pathname);
  const mod = await import(url.href);
  return (mod.default || mod) as T;
}

export function jsonRequest(
  path: string,
  body: unknown = {},
  init: RequestInit = {},
): Request {
  return new Request(`https://app.test${path}`, {
    method: init.method || "POST",
    headers: {
      "content-type": "application/json",
      ...(init.headers || {}),
    },
    body: init.method === "GET" ? undefined : JSON.stringify(body),
  });
}

export async function responseJson(response: Response): Promise<Record<string, unknown>> {
  return (await response.json()) as Record<string, unknown>;
}

export function assertEntitlementEnvelope(
  body: Record<string, unknown>,
  expected: {
    sub: string;
    license_id: string;
    email: string;
    tier: Tier;
    entitlements: string[];
    kid?: typeof TEST_ENTITLEMENT_KEY_A | typeof TEST_ENTITLEMENT_KEY_B;
  },
): void {
  assert.equal(typeof body.access_token, "string");
  assert.equal(typeof body.refresh_token, "string");
  assert.equal(typeof body.entitlement_assertion, "string");
  assert.equal(body.expires_in, 3600);

  const segments = String(body.entitlement_assertion).split(".");
  assert.equal(segments.length, 3);
  const header = JSON.parse(Buffer.from(segments[0], "base64url").toString("utf8")) as Record<
    string,
    unknown
  >;
  const payload = JSON.parse(Buffer.from(segments[1], "base64url").toString("utf8")) as Record<
    string,
    unknown
  >;
  const expectedKeyId = expected.kid ?? TEST_ENTITLEMENT_KEY_A;
  assert.deepEqual(header, {
    alg: "EdDSA",
    typ: "elevate-entitlement+jwt",
    kid: expectedKeyId,
  });

  const publicKey = crypto.createPublicKey({
    key: Buffer.from(TEST_ENTITLEMENT_PUBLIC_KEYS[expectedKeyId], "base64"),
    format: "der",
    type: "spki",
  });
  assert.equal(
    crypto.verify(
      null,
      Buffer.from(`${segments[0]}.${segments[1]}`, "ascii"),
      publicKey,
      Buffer.from(segments[2], "base64url"),
    ),
    true,
  );

  const normalizedEmail = expected.email.trim().toLowerCase();
  const normalizedEntitlements = [...new Set(expected.entitlements.map((value) => value.trim()))].sort();
  assert.equal(payload.iss, "https://api.elevationrealestatehq.com");
  assert.equal(payload.aud, "elevate-realtor-beta");
  assert.equal(payload.schema, 1);
  assert.equal(payload.sub, expected.sub);
  assert.equal(payload.license_id, expected.license_id);
  assert.equal(payload.email, normalizedEmail);
  assert.equal(payload.tier, expected.tier);
  assert.deepEqual(payload.entitlements, normalizedEntitlements);
  assert.equal(payload.nbf, payload.iat);
  assert.equal(Number(payload.exp) - Number(payload.iat), 3600);
  assert.equal(typeof payload.jti, "string");
  assert.notEqual(payload.jti, "");
  assert.equal(
    payload.ath,
    crypto.createHash("sha256").update(String(body.access_token), "utf8").digest("base64url"),
  );
  assert.equal(
    payload.rth,
    crypto.createHash("sha256").update(String(body.refresh_token), "utf8").digest("base64url"),
  );

  assert.equal(body.license_id, payload.license_id);
  assert.equal(body.email, payload.email);
  assert.equal(body.tier, payload.tier);
  assert.deepEqual(body.entitlements, payload.entitlements);
}

function okJson(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function noContent(): Response {
  return new Response(null, { status: 204 });
}

function asArrayBody(body: unknown): Record<string, unknown>[] {
  if (Array.isArray(body)) return body as Record<string, unknown>[];
  return [body as Record<string, unknown>];
}

function insertRows(table: string, body: unknown): unknown {
  const rows = asArrayBody(body);
  if (table === "users") {
    const inserted = rows.map((row) => {
      const now = new Date().toISOString();
      const user: UserRow = {
        id: `user-${nextUserId++}`,
        email: String(row.email).toLowerCase(),
        password_hash: String(row.password_hash),
        stripe_customer: null,
        tier: (row.tier as Tier | undefined) ?? "pro",
        status: (row.status as UserStatus | undefined) ?? "active",
        current_period_end: null,
        entitlements: Array.isArray(row.entitlements) ? row.entitlements.map(String) : [],
        blocked_entitlements: [],
        role: (row.role as UserRow["role"] | undefined) ?? "user",
        is_developer: false,
        first_name: (row.first_name as string | null | undefined) ?? null,
        last_name: (row.last_name as string | null | undefined) ?? null,
        created_at: now,
        updated_at: now,
      };
      activeDb.users.push(user);
      return user;
    });
    return inserted[0];
  }
  if (table === "licenses") {
    const inserted = rows.map((row) => {
      const createdAt = new Date().toISOString();
      const license: LicenseRow = {
        id: `license-${nextLicenseId++}`,
        user_id: String(row.user_id),
        refresh_token_hash: String(row.refresh_token_hash),
        previous_refresh_token_hash:
          (row.previous_refresh_token_hash as string | null | undefined) ?? null,
        previous_refresh_attempt_hash:
          (row.previous_refresh_attempt_hash as string | null | undefined) ?? null,
        refresh_family_expires_at:
          (row.refresh_family_expires_at as string | undefined) ??
          refreshFamilyExpiry(createdAt),
        device_label: (row.device_label as string | null) ?? null,
        revoked: false,
        last_used_at: null,
        created_at: createdAt,
      };
      activeDb.licenses.push(license);
      return license;
    });
    return inserted[0];
  }
  if (table === "memberships") {
    const inserted = rows.map((row) => {
      const orgId = String(row.org_id);
      const organization = activeDb.organizations.find((org) => org.id === orgId);
      if (!organization) throw new Error(`missing organization ${orgId}`);
      const membership: MembershipRow = {
        id: String(row.id || `membership-${activeDb.memberships.length + 1}`),
        org_id: orgId,
        user_id: String(row.user_id),
        role: (row.role as MembershipRow["role"] | undefined) ?? "member",
        created_at: new Date().toISOString(),
        organization,
      };
      activeDb.memberships.push(membership);
      return membership;
    });
    return inserted[0];
  }
  if (table === "organizations") {
    const inserted = rows.map((row) => {
      const now = new Date().toISOString();
      const org: OrgRow = {
        id: String(row.id || `org-${activeDb.organizations.length + 1}`),
        slug: String(row.slug),
        name: String(row.name),
        stripe_customer: (row.stripe_customer as string | null | undefined) ?? null,
        tier: (row.tier as Tier | undefined) ?? "pro",
        status: (row.status as UserStatus | undefined) ?? "active",
        current_period_end: (row.current_period_end as string | null | undefined) ?? null,
        entitlements: Array.isArray(row.entitlements) ? row.entitlements.map(String) : [],
        seat_limit: Number(row.seat_limit ?? 1),
        created_at: (row.created_at as string | undefined) || now,
        updated_at: (row.updated_at as string | undefined) || now,
      };
      activeDb.organizations.push(org);
      return org;
    });
    return inserted[0];
  }
  if (table === "device_grants") {
    const inserted = rows.map((row) => {
      const grant: DeviceGrantRow = {
        id: `grant-${nextGrantId++}`,
        user_code: String(row.user_code),
        device_code_hash: String(row.device_code_hash),
        user_id: null,
        license_id: null,
        status: "pending",
        device_label: (row.device_label as string | null) ?? null,
        ip_addr: (row.ip_addr as string | null) ?? null,
        user_agent: (row.user_agent as string | null) ?? null,
        created_at: new Date().toISOString(),
        expires_at: String(row.expires_at),
        approved_at: null,
        claimed_at: null,
        last_polled_at: null,
        refresh_token_plain: null,
      };
      activeDb.device_grants.push(grant);
      return grant;
    });
    return inserted[0];
  }
  if (table === "audit_log") {
    activeDb.audit_log.push(...rows);
    return rows;
  }
  if (table === "skill_invocations") {
    activeDb.skill_invocations.push(...rows);
    return rows;
  }
  if (table === "login_codes") {
    const inserted = rows.map((row) => {
      const now = new Date().toISOString();
      const loginCode: LoginCodeRow = {
        id: `login-code-${nextLoginCodeId++}`,
        user_id: String(row.user_id),
        code_hash: String(row.code_hash),
        created_at: (row.created_at as string | undefined) || now,
        expires_at: String(row.expires_at),
        consumed_at: (row.consumed_at as string | null | undefined) ?? null,
        attempts: Number(row.attempts ?? 0),
        ip_addr: (row.ip_addr as string | null) ?? null,
        user_agent: (row.user_agent as string | null) ?? null,
      };
      activeDb.login_codes.push(loginCode);
      return loginCode;
    });
    return inserted[0];
  }
  if (table === "password_reset_tokens") {
    const inserted = rows.map((row) => {
      const now = new Date().toISOString();
      const resetToken: PasswordResetTokenRow = {
        id: `password-reset-${nextPasswordResetTokenId++}`,
        user_id: String(row.user_id),
        token_hash: String(row.token_hash),
        created_at: (row.created_at as string | undefined) || now,
        expires_at: String(row.expires_at),
        consumed_at: (row.consumed_at as string | null | undefined) ?? null,
        ip_addr: (row.ip_addr as string | null | undefined) ?? null,
        user_agent: (row.user_agent as string | null | undefined) ?? null,
      };
      activeDb.password_reset_tokens.push(resetToken);
      return resetToken;
    });
    return inserted[0];
  }
  throw new Error(`unexpected insert into ${table}`);
}

function updateRows(
  table: string,
  filters: URLSearchParams,
  body: Record<string, unknown>,
): unknown[] {
  const id = readEq(filters, "id");
  const notId = readNeq(filters, "id");
  const userId = readEq(filters, "user_id");
  const matchesId = (rowId: string) => (!id || rowId === id) && (!notId || rowId !== notId);
  const updated: unknown[] = [];
  if (table === "users") {
    for (const user of activeDb.users) {
      if (matchesId(user.id)) {
        Object.assign(user, body);
        updated.push(user);
      }
    }
    return updated;
  }
  if (table === "licenses") {
    const refreshTokenHash = readEq(filters, "refresh_token_hash");
    const revoked = readEq(filters, "revoked");
    const familyExpiresAfter = readGreaterThan(filters, "refresh_family_expires_at");
    for (const license of activeDb.licenses) {
      if (
        matchesId(license.id) &&
        (!userId || license.user_id === userId) &&
        (!refreshTokenHash || license.refresh_token_hash === refreshTokenHash) &&
        (!revoked || license.revoked === (revoked === "true")) &&
        (!familyExpiresAfter || license.refresh_family_expires_at > familyExpiresAfter)
      ) {
        Object.assign(license, body);
        updated.push(license);
      }
    }
    return updated;
  }
  if (table === "organizations") {
    for (const org of activeDb.organizations) {
      if (matchesId(org.id)) {
        Object.assign(org, body);
        updated.push(org);
      }
    }
    return updated;
  }
  if (table === "memberships") {
    const orgId = readEq(filters, "org_id");
    for (const membership of activeDb.memberships) {
      if ((!orgId || membership.org_id === orgId) && (!userId || membership.user_id === userId)) {
        Object.assign(membership, body);
        updated.push(membership);
      }
    }
    return updated;
  }
  if (table === "device_grants") {
    const status = readEq(filters, "status");
    const statuses = readIn(filters, "status");
    const expiresBefore = readLessThan(filters, "expires_at");
    const expiresAfter = readGreaterThan(filters, "expires_at");
    for (const grant of activeDb.device_grants) {
      if (
        matchesId(grant.id) &&
        (!status || grant.status === status) &&
        (!statuses || statuses.includes(grant.status)) &&
        (!expiresBefore || grant.expires_at < expiresBefore) &&
        (!expiresAfter || grant.expires_at > expiresAfter)
      ) {
        Object.assign(grant, body);
        updated.push(grant);
      }
    }
    return updated;
  }
  if (table === "login_codes") {
    for (const loginCode of activeDb.login_codes) {
      if (matchesId(loginCode.id)) {
        Object.assign(loginCode, body);
        updated.push(loginCode);
      }
    }
    return updated;
  }
  if (table === "password_reset_tokens") {
    for (const resetToken of activeDb.password_reset_tokens) {
      if (matchesId(resetToken.id)) {
        Object.assign(resetToken, body);
        updated.push(resetToken);
      }
    }
    return updated;
  }
  if (table === "invitations") {
    for (const invitation of activeDb.invitations) {
      if (matchesId(invitation.id)) {
        Object.assign(invitation, body);
        updated.push(invitation);
      }
    }
    return updated;
  }
  throw new Error(`unexpected update on ${table}`);
}

function deleteRows(table: string, filters: URLSearchParams): unknown[] {
  const id = readEq(filters, "id");
  const orgId = readEq(filters, "org_id");
  const userId = readEq(filters, "user_id");
  const removed: unknown[] = [];

  if (table === "organizations") {
    activeDb.organizations = activeDb.organizations.filter((org) => {
      if (id && org.id === id) {
        removed.push(org);
        return false;
      }
      return true;
    });
    return removed;
  }

  if (table === "memberships") {
    activeDb.memberships = activeDb.memberships.filter((membership) => {
      if ((!orgId || membership.org_id === orgId) && (!userId || membership.user_id === userId)) {
        removed.push(membership);
        return false;
      }
      return true;
    });
    return removed;
  }

  throw new Error(`unexpected delete from ${table}`);
}

function readEq(params: URLSearchParams, key: string): string | null {
  const raw = params.get(key);
  return raw?.startsWith("eq.") ? raw.slice(3) : null;
}

function readNeq(params: URLSearchParams, key: string): string | null {
  const raw = params.get(key);
  return raw?.startsWith("neq.") ? raw.slice(4) : null;
}

function readIn(params: URLSearchParams, key: string): string[] | null {
  const raw = params.get(key);
  if (!raw?.startsWith("in.")) return null;
  return raw.slice(3).replace(/^\(|\)$/g, "").split(",");
}

function readIsNull(params: URLSearchParams, key: string): boolean {
  return params.get(key) === "is.null";
}

function readGreaterThan(params: URLSearchParams, key: string): string | null {
  const raw = params.get(key);
  return raw?.startsWith("gt.") ? raw.slice(3) : null;
}

function readLessThan(params: URLSearchParams, key: string): string | null {
  const raw = params.get(key);
  return raw?.startsWith("lt.") ? raw.slice(3) : null;
}

function selectRows(table: string, params: URLSearchParams, wantsSingle: boolean): unknown {
  if (table === "users") {
    let rows = activeDb.users;
    const email = readEq(params, "email");
    const id = readEq(params, "id");
    const stripeCustomer = readEq(params, "stripe_customer");
    const statuses = readIn(params, "status");
    if (email) rows = rows.filter((row) => row.email === email.toLowerCase());
    if (id) rows = rows.filter((row) => row.id === id);
    if (stripeCustomer) rows = rows.filter((row) => row.stripe_customer === stripeCustomer);
    if (statuses) rows = rows.filter((row) => statuses.includes(row.status));
    return maybeSingle(wantsSingle, rows);
  }
  if (table === "licenses") {
    let rows = activeDb.licenses;
    const id = readEq(params, "id");
    const userId = readEq(params, "user_id");
    const hash = readEq(params, "refresh_token_hash");
    const revoked = readEq(params, "revoked");
    if (id) rows = rows.filter((row) => row.id === id);
    if (userId) rows = rows.filter((row) => row.user_id === userId);
    if (hash) rows = rows.filter((row) => row.refresh_token_hash === hash);
    if (revoked) rows = rows.filter((row) => row.revoked === (revoked === "true"));
    return maybeSingle(wantsSingle, rows);
  }
  if (table === "memberships") {
    let rows = activeDb.memberships;
    const userId = readEq(params, "user_id");
    const orgId = readEq(params, "org_id");
    if (userId) rows = rows.filter((row) => row.user_id === userId);
    if (orgId) rows = rows.filter((row) => row.org_id === orgId);
    return maybeSingle(wantsSingle, rows);
  }
  if (table === "invitations") {
    let rows = activeDb.invitations;
    const id = readEq(params, "id");
    const orgId = readEq(params, "org_id");
    const status = readEq(params, "status");
    const tokenHash = readEq(params, "token_hash");
    if (id) rows = rows.filter((row) => row.id === id);
    if (orgId) rows = rows.filter((row) => row.org_id === orgId);
    if (status) rows = rows.filter((row) => row.status === status);
    if (tokenHash) rows = rows.filter((row) => row.token_hash === tokenHash);
    return maybeSingle(wantsSingle, rows);
  }
  if (table === "organizations") {
    let rows = activeDb.organizations;
    const id = readEq(params, "id");
    const slug = readEq(params, "slug");
    if (id) rows = rows.filter((row) => row.id === id);
    if (slug) rows = rows.filter((row) => row.slug === slug);
    return maybeSingle(wantsSingle, rows);
  }
  if (table === "skills") {
    let rows = activeDb.skills;
    const name = readEq(params, "name");
    const enabled = readEq(params, "enabled");
    if (name) rows = rows.filter((row) => row.name === name);
    if (enabled) rows = rows.filter((row) => row.enabled === (enabled === "true"));
    return maybeSingle(wantsSingle, rows);
  }
  if (table === "automations") {
    let rows = activeDb.automations;
    const enabled = readEq(params, "enabled");
    if (enabled) rows = rows.filter((row) => row.enabled === (enabled === "true"));
    return maybeSingle(wantsSingle, rows);
  }
  if (table === "device_grants") {
    let rows = activeDb.device_grants;
    const id = readEq(params, "id");
    const userCode = readEq(params, "user_code");
    const deviceHash = readEq(params, "device_code_hash");
    if (id) rows = rows.filter((row) => row.id === id);
    if (userCode) rows = rows.filter((row) => row.user_code === userCode.toUpperCase());
    if (deviceHash) rows = rows.filter((row) => row.device_code_hash === deviceHash);
    return maybeSingle(wantsSingle, rows);
  }
  if (table === "login_codes") {
    let rows = activeDb.login_codes;
    const id = readEq(params, "id");
    const userId = readEq(params, "user_id");
    const expiresAfter = readGreaterThan(params, "expires_at");
    if (id) rows = rows.filter((row) => row.id === id);
    if (userId) rows = rows.filter((row) => row.user_id === userId);
    if (readIsNull(params, "consumed_at")) {
      rows = rows.filter((row) => row.consumed_at === null);
    }
    if (expiresAfter) {
      rows = rows.filter((row) => row.expires_at > expiresAfter);
    }
    if ((params.get("order") || "").startsWith("created_at.desc")) {
      rows = [...rows].sort((a, b) => b.created_at.localeCompare(a.created_at));
    }
    return maybeSingle(wantsSingle, rows);
  }
  if (table === "password_reset_tokens") {
    let rows = activeDb.password_reset_tokens;
    const id = readEq(params, "id");
    const tokenHash = readEq(params, "token_hash");
    if (id) rows = rows.filter((row) => row.id === id);
    if (tokenHash) rows = rows.filter((row) => row.token_hash === tokenHash);
    return maybeSingle(wantsSingle, rows);
  }
  throw new Error(`unexpected select from ${table}`);
}

function maybeSingle(wantsSingle: boolean, rows: unknown[]): unknown {
  return wantsSingle ? rows[0] || null : rows;
}

function upsertDiagnostics(body: unknown): void {
  for (const row of asArrayBody(body)) {
    const eventId = row.event_id;
    if (activeDb.session_diagnostic_events.some((existing) => existing.event_id === eventId)) {
      continue;
    }
    activeDb.session_diagnostic_events.push(row);
  }
}

function atomicLicenseRefreshV2(body: unknown): Response {
  const input = (body || {}) as Record<string, unknown>;
  const currentHash = String(input.p_current_refresh_token_hash || "");
  const nextHash = String(input.p_next_refresh_token_hash || "");
  const attemptHash = String(input.p_refresh_attempt_hash || "");
  if (
    !/^[0-9a-f]{64}$/.test(currentHash) ||
    !/^[0-9a-f]{64}$/.test(nextHash) ||
    !/^[0-9a-f]{64}$/.test(attemptHash) ||
    currentHash === nextHash
  ) {
    return okJson({ message: "invalid refresh v2 token material" }, 400);
  }

  const license =
    activeDb.licenses.find((candidate) => candidate.refresh_token_hash === currentHash) ??
    activeDb.licenses.find(
      (candidate) => candidate.previous_refresh_token_hash === currentHash,
    );
  if (!license || license.revoked) return okJson({ result: "invalid" });

  const familyExpiry = Date.parse(license.refresh_family_expires_at);
  if (!Number.isFinite(familyExpiry) || familyExpiry <= Date.now()) {
    license.revoked = true;
    return okJson({ result: "expired" });
  }

  const isFirstExecution = license.refresh_token_hash === currentHash;
  if (isFirstExecution) {
    if (
      license.previous_refresh_token_hash === nextHash ||
      activeDb.licenses.some(
        (candidate) =>
          candidate !== license &&
          (candidate.refresh_token_hash === nextHash ||
            candidate.previous_refresh_token_hash === nextHash),
      )
    ) {
      license.revoked = true;
      return okJson({ result: "conflict" });
    }
  } else if (
    license.refresh_token_hash !== nextHash ||
    license.previous_refresh_attempt_hash !== attemptHash
  ) {
    license.revoked = true;
    return okJson({ result: "conflict" });
  }

  const user = activeDb.users.find((candidate) => candidate.id === license.user_id);
  if (!user || !["active", "trialing"].includes(user.status)) {
    license.revoked = true;
    return okJson({ result: "inactive" });
  }

  const now = new Date().toISOString();
  if (isFirstExecution) {
    if (nextAtomicRefreshV2Failure === "after_rotation") {
      nextAtomicRefreshV2Failure = null;
      return okJson({ message: "injected refresh v2 failure after rotation" }, 500);
    }
    Object.assign(license, {
      refresh_token_hash: nextHash,
      previous_refresh_token_hash: currentHash,
      previous_refresh_attempt_hash: attemptHash,
      last_used_at: now,
    });
  } else {
    license.last_used_at = now;
  }

  return okJson({
    result: isFirstExecution ? "rotated" : "replay",
    license_id: license.id,
    user_id: user.id,
    email: user.email,
  });
}

function atomicDeviceApproval(body: unknown): Response {
  const input = (body || {}) as Record<string, unknown>;
  const grantId = String(input.p_grant_id || "");
  const userId = String(input.p_user_id || "");
  const refreshHashValue = String(input.p_refresh_token_hash || "");
  const refreshPlain = String(input.p_refresh_token_plain || "");

  if (!/^[0-9a-f]{64}$/.test(refreshHashValue) || !/^[A-Za-z0-9_-]{43}$/.test(refreshPlain)) {
    return okJson({ message: "invalid device refresh token material" }, 400);
  }

  const user = activeDb.users.find(
    (candidate) =>
      candidate.id === userId && ["active", "trialing"].includes(candidate.status),
  );
  if (!user) return okJson({ message: "device approver is not active" }, 500);

  const now = Date.now();
  const stale = activeDb.device_grants.filter(
    (candidate) =>
      ["pending", "approved"].includes(candidate.status) &&
      Number.isFinite(Date.parse(candidate.expires_at)) &&
      Date.parse(candidate.expires_at) <= now,
  );
  const applyStaleSweep = () => {
    for (const candidate of stale) {
      candidate.status = "expired";
      candidate.refresh_token_plain = null;
    }
  };

  const grant = activeDb.device_grants.find((candidate) => candidate.id === grantId);
  if (!grant) {
    applyStaleSweep();
    return okJson({ result: "not_found" });
  }

  const effectiveStatus = stale.includes(grant) ? "expired" : grant.status;
  if (effectiveStatus === "expired") {
    applyStaleSweep();
    return okJson({ result: "expired", grant_status: "expired" });
  }
  if (effectiveStatus !== "pending") {
    applyStaleSweep();
    return okJson({ result: "conflict", grant_status: effectiveStatus });
  }

  if (grant.user_id || grant.license_id || grant.refresh_token_plain) {
    applyStaleSweep();
    grant.status = "expired";
    grant.refresh_token_plain = null;
    return okJson({ result: "invalid", grant_status: "expired" });
  }

  const license: LicenseRow = {
    id: `license-${nextLicenseId}`,
    user_id: userId,
    refresh_token_hash: refreshHashValue,
    previous_refresh_token_hash: null,
    previous_refresh_attempt_hash: null,
    refresh_family_expires_at: refreshFamilyExpiry(new Date(now).toISOString()),
    device_label: grant.device_label ?? "linked-device",
    revoked: false,
    last_used_at: null,
    created_at: new Date(now).toISOString(),
  };
  if (nextAtomicDeviceApprovalFailure === "after_license_insert") {
    nextAtomicDeviceApprovalFailure = null;
    return okJson({ message: "injected atomic approval failure after license insert" }, 500);
  }

  const approvedAt = new Date(now).toISOString();
  if (nextAtomicDeviceApprovalFailure === "after_grant_update") {
    nextAtomicDeviceApprovalFailure = null;
    return okJson({ message: "injected atomic approval failure after grant update" }, 500);
  }

  const audit = {
    actor_user_id: userId,
    target_user_id: userId,
    action: "device.link.approved",
    payload: {
      grant_id: grant.id,
      user_code: grant.user_code,
      device_label: grant.device_label,
      license_id: license.id,
    },
  };
  if (nextAtomicDeviceApprovalFailure === "after_audit_insert") {
    nextAtomicDeviceApprovalFailure = null;
    return okJson({ message: "injected atomic approval failure after audit insert" }, 500);
  }

  // Commit the staged transaction only after every phase succeeded.
  applyStaleSweep();
  activeDb.licenses.push(license);
  nextLicenseId += 1;
  Object.assign(grant, {
    status: "approved",
    user_id: userId,
    license_id: license.id,
    approved_at: approvedAt,
    refresh_token_plain: refreshPlain,
  });
  activeDb.audit_log.push(audit);

  return okJson({ result: "approved", license_id: license.id });
}

type PlannedMembershipAllocation =
  | { result: "added" | "already_member"; membership: MembershipRow }
  | { result: "seat_limit" | "org_not_found" | "user_not_found" };

function membershipForRpc(membership: MembershipRow): Omit<MembershipRow, "organization"> {
  const { organization: _organization, ...row } = membership;
  return row;
}

function planMembershipAllocation(
  orgId: string,
  userId: string,
  role: MembershipRow["role"],
  view: {
    organizations?: OrgRow[];
    users?: UserRow[];
    memberships?: MembershipRow[];
  } = {},
): PlannedMembershipAllocation {
  const organizations = view.organizations ?? activeDb.organizations;
  const users = view.users ?? activeDb.users;
  const memberships = view.memberships ?? activeDb.memberships;
  const organization = organizations.find((candidate) => candidate.id === orgId);
  if (!organization) return { result: "org_not_found" };

  const existing = memberships.find(
    (candidate) => candidate.org_id === orgId && candidate.user_id === userId,
  );
  if (existing) return { result: "already_member", membership: existing };
  if (!users.some((candidate) => candidate.id === userId)) {
    return { result: "user_not_found" };
  }
  if (memberships.filter((candidate) => candidate.org_id === orgId).length >= organization.seat_limit) {
    return { result: "seat_limit" };
  }

  return {
    result: "added",
    membership: {
      id: `membership-${memberships.length + 1}`,
      org_id: orgId,
      user_id: userId,
      role,
      created_at: new Date().toISOString(),
      organization,
    },
  };
}

function atomicMembershipAdd(body: unknown): Response {
  const input = (body || {}) as Record<string, unknown>;
  const orgId = String(input.p_org_id || "");
  const userId = String(input.p_user_id || "");
  const role = String(input.p_role || "") as MembershipRow["role"];
  if (!orgId || !userId || !["owner", "admin", "member"].includes(role)) {
    return okJson({ message: "invalid membership allocation parameters" }, 400);
  }

  const planned = planMembershipAllocation(orgId, userId, role);
  if (planned.result === "added") activeDb.memberships.push(planned.membership);
  if (planned.result === "added" || planned.result === "already_member") {
    return okJson({ result: planned.result, membership: membershipForRpc(planned.membership) });
  }
  return okJson({ result: planned.result });
}

function consumeAtomicMembershipFailure(stage: AtomicMembershipFailureStage): boolean {
  if (nextAtomicMembershipFailure !== stage) return false;
  nextAtomicMembershipFailure = null;
  return true;
}

function atomicOrgWithOwnerCreate(body: unknown): Response {
  const input = (body || {}) as Record<string, unknown>;
  const orgId = String(input.p_org_id || "");
  const ownerUserId = String(input.p_owner_user_id || "");
  const slug = String(input.p_slug || "");
  const name = String(input.p_name || "");
  if (
    !orgId ||
    !ownerUserId ||
    !/^[a-z0-9-]{2,60}$/.test(slug) ||
    name.length < 2 ||
    name.length > 80
  ) {
    return okJson({ message: "invalid organization creation parameters" }, 400);
  }
  if (!activeDb.users.some((candidate) => candidate.id === ownerUserId)) {
    return okJson({ result: "owner_not_found" });
  }
  if (
    activeDb.organizations.some(
      (candidate) => candidate.id === orgId || candidate.slug === slug,
    )
  ) {
    return okJson({ message: "duplicate organization" }, 409);
  }

  const now = new Date().toISOString();
  const organization: OrgRow = {
    id: orgId,
    slug,
    name,
    stripe_customer: null,
    tier: "pro",
    status: "active",
    current_period_end: null,
    entitlements: [],
    seat_limit: 1,
    created_at: now,
    updated_at: now,
  };
  if (consumeAtomicMembershipFailure("org_owner_after_org_insert")) {
    return okJson({ message: "injected organization failure after org insert" }, 500);
  }

  const allocation = planMembershipAllocation(orgId, ownerUserId, "owner", {
    organizations: [...activeDb.organizations, organization],
  });
  if (allocation.result !== "added") {
    return okJson({ message: `initial owner allocation failed: ${allocation.result}` }, 500);
  }
  if (consumeAtomicMembershipFailure("org_owner_after_membership_insert")) {
    return okJson({ message: "injected organization failure after owner insert" }, 500);
  }

  activeDb.organizations.push(organization);
  activeDb.memberships.push(allocation.membership);
  return okJson({
    result: "created",
    organization,
    membership: membershipForRpc(allocation.membership),
  });
}

function atomicInvitationAccept(body: unknown): Response {
  const input = (body || {}) as Record<string, unknown>;
  const invitationId = String(input.p_invitation_id || "");
  const tokenHashValue = String(input.p_token_hash || "");
  const newUserId = String(input.p_new_user_id || "");
  const passwordHashValue =
    typeof input.p_new_user_password_hash === "string"
      ? input.p_new_user_password_hash
      : null;
  const licenseId = String(input.p_license_id || "");
  const refreshHashValue = String(input.p_refresh_token_hash || "");
  if (
    !invitationId ||
    !newUserId ||
    !licenseId ||
    !/^[0-9a-f]{64}$/.test(tokenHashValue) ||
    !/^[0-9a-f]{64}$/.test(refreshHashValue) ||
    (passwordHashValue !== null &&
      (passwordHashValue.length < 50 || passwordHashValue.length > 100))
  ) {
    return okJson({ message: "invalid invitation acceptance parameters" }, 400);
  }

  const invitation = activeDb.invitations.find(
    (candidate) => candidate.id === invitationId && candidate.token_hash === tokenHashValue,
  );
  if (!invitation) return okJson({ result: "invalid" });
  if (invitation.status !== "pending") return okJson({ result: invitation.status });
  if (Date.parse(invitation.expires_at) <= Date.now()) return okJson({ result: "expired" });

  const organization = activeDb.organizations.find(
    (candidate) => candidate.id === invitation.org_id,
  );
  if (!organization) return okJson({ result: "org_not_found" });

  let user = activeDb.users.find(
    (candidate) => candidate.email === invitation.email.toLowerCase(),
  );
  let stagedUser: UserRow | null = null;
  if (!user) {
    const memberCount = activeDb.memberships.filter(
      (candidate) => candidate.org_id === invitation.org_id,
    ).length;
    if (memberCount >= organization.seat_limit) return okJson({ result: "seat_limit" });
    if (!passwordHashValue) {
      return okJson({ result: "password_required", email: invitation.email });
    }
    if (activeDb.users.some((candidate) => candidate.id === newUserId)) {
      return okJson({ message: "duplicate invited user id" }, 409);
    }
    const now = new Date().toISOString();
    stagedUser = {
      id: newUserId,
      email: invitation.email.toLowerCase(),
      password_hash: passwordHashValue,
      stripe_customer: null,
      tier: "pro",
      status: "active",
      current_period_end: null,
      entitlements: [],
      blocked_entitlements: [],
      role: "user",
      is_developer: false,
      first_name: null,
      last_name: null,
      created_at: now,
      updated_at: now,
    };
    user = stagedUser;
    if (consumeAtomicMembershipFailure("invitation_after_user_insert")) {
      return okJson({ message: "injected invitation failure after user insert" }, 500);
    }
  }

  if (!["active", "trialing"].includes(user.status)) return okJson({ result: "inactive" });

  const allocation = planMembershipAllocation(invitation.org_id, user.id, invitation.role, {
    users: stagedUser ? [...activeDb.users, stagedUser] : activeDb.users,
  });
  if (allocation.result === "seat_limit") return okJson({ result: "seat_limit" });
  if (allocation.result !== "added" && allocation.result !== "already_member") {
    return okJson({ message: `invitation membership failed: ${allocation.result}` }, 500);
  }
  if (consumeAtomicMembershipFailure("invitation_after_membership_insert")) {
    return okJson({ message: "injected invitation failure after membership insert" }, 500);
  }

  const acceptedAt = new Date().toISOString();
  if (consumeAtomicMembershipFailure("invitation_after_invitation_update")) {
    return okJson({ message: "injected invitation failure after invitation update" }, 500);
  }

  if (
    activeDb.licenses.some(
      (candidate) =>
        candidate.id === licenseId || candidate.refresh_token_hash === refreshHashValue,
    )
  ) {
    return okJson({ message: "duplicate invitation license" }, 409);
  }
  const license: LicenseRow = {
    id: licenseId,
    user_id: user.id,
    refresh_token_hash: refreshHashValue,
    previous_refresh_token_hash: null,
    previous_refresh_attempt_hash: null,
    refresh_family_expires_at: refreshFamilyExpiry(acceptedAt),
    device_label: "invite-accept",
    revoked: false,
    last_used_at: null,
    created_at: acceptedAt,
  };
  if (consumeAtomicMembershipFailure("invitation_after_license_insert")) {
    return okJson({ message: "injected invitation failure after license insert" }, 500);
  }

  if (stagedUser) activeDb.users.push(stagedUser);
  if (allocation.result === "added") activeDb.memberships.push(allocation.membership);
  Object.assign(invitation, {
    status: "accepted",
    accepted_at: acceptedAt,
    accepted_user_id: user.id,
  });
  activeDb.licenses.push(license);

  return okJson({
    result: "accepted",
    license_id: license.id,
    user: {
      id: user.id,
      email: user.email,
      tier: user.tier,
      status: user.status,
    },
    membership_result: allocation.result,
    membership: membershipForRpc(allocation.membership),
    user_created: Boolean(stagedUser),
  });
}

function latestActiveLoginCode(userId: string, now = Date.now()): LoginCodeRow | null {
  return (
    activeDb.login_codes
      .filter(
        (candidate) =>
          candidate.user_id === userId &&
          candidate.consumed_at === null &&
          Date.parse(candidate.expires_at) > now,
      )
      .sort((left, right) => {
        const byCreated = right.created_at.localeCompare(left.created_at);
        return byCreated || right.id.localeCompare(left.id);
      })[0] ?? null
  );
}

function atomicLoginCodeIssue(body: unknown): Response {
  const input = (body || {}) as Record<string, unknown>;
  const userId = String(input.p_user_id || "");
  const codeHash = String(input.p_code_hash || "");
  const expiresAt = String(input.p_expires_at || "");
  const expiresAtMs = Date.parse(expiresAt);
  const now = Date.now();
  if (!/^[0-9a-f]{64}$/.test(codeHash) || !Number.isFinite(expiresAtMs) || expiresAtMs <= now) {
    return okJson({ message: "invalid atomic login-code issue parameters" }, 400);
  }
  const user = activeDb.users.find((candidate) => candidate.id === userId);
  if (!user) return okJson({ result: "not_found" });

  if (nextAtomicLoginCodeFailure === "issue_after_invalidate") {
    nextAtomicLoginCodeFailure = null;
    return okJson({ message: "injected login-code failure after invalidate" }, 500);
  }

  const createdAt = new Date(now).toISOString();
  const loginCode: LoginCodeRow = {
    id: `login-code-${nextLoginCodeId}`,
    user_id: userId,
    code_hash: codeHash,
    created_at: createdAt,
    expires_at: expiresAt,
    consumed_at: null,
    attempts: 0,
    ip_addr: (input.p_ip_addr as string | null | undefined) ?? null,
    user_agent: (input.p_user_agent as string | null | undefined) ?? null,
  };
  if (nextAtomicLoginCodeFailure === "issue_after_insert") {
    nextAtomicLoginCodeFailure = null;
    return okJson({ message: "injected login-code failure after insert" }, 500);
  }

  const audit = {
    actor_user_id: userId,
    target_user_id: userId,
    action: "auth.login_code_requested",
    payload: { ip: loginCode.ip_addr, ua: loginCode.user_agent },
  };
  if (nextAtomicLoginCodeFailure === "issue_after_audit") {
    nextAtomicLoginCodeFailure = null;
    return okJson({ message: "injected login-code failure after audit" }, 500);
  }

  // Commit the staged transaction only after all phases succeed.
  for (const candidate of activeDb.login_codes) {
    if (candidate.user_id === userId && candidate.consumed_at === null) {
      candidate.consumed_at = createdAt;
    }
  }
  activeDb.login_codes.push(loginCode);
  activeDb.audit_log.push(audit);
  nextLoginCodeId += 1;
  return okJson({ result: "issued", login_code_id: loginCode.id });
}

function atomicLoginCodeAttempt(body: unknown): Response {
  const input = (body || {}) as Record<string, unknown>;
  const userId = String(input.p_user_id || "");
  const loginCodeId = String(input.p_login_code_id || "");
  const attemptedHash = String(input.p_attempted_code_hash || "");
  const maxAttempts = Number(input.p_max_attempts);
  if (
    !/^[0-9a-f]{64}$/.test(attemptedHash) ||
    !Number.isInteger(maxAttempts) ||
    maxAttempts < 1 ||
    maxAttempts > 100
  ) {
    return okJson({ message: "invalid atomic login-code attempt parameters" }, 400);
  }
  if (!activeDb.users.some((candidate) => candidate.id === userId)) {
    return okJson({ result: "invalid" });
  }
  const loginCode = latestActiveLoginCode(userId);
  if (!loginCode || loginCode.id !== loginCodeId) return okJson({ result: "invalid" });
  if (loginCode.attempts >= maxAttempts) {
    return okJson({ result: "locked", attempts: loginCode.attempts });
  }
  if (loginCode.code_hash === attemptedHash) {
    return okJson({ result: "match", attempts: loginCode.attempts });
  }
  const nextAttempts = loginCode.attempts + 1;
  if (nextAtomicLoginCodeFailure === "attempt_after_increment") {
    nextAtomicLoginCodeFailure = null;
    return okJson({ message: "injected login-code failure after attempt increment" }, 500);
  }
  loginCode.attempts = nextAttempts;
  return okJson({
    result: loginCode.attempts >= maxAttempts ? "locked" : "invalid",
    attempts: loginCode.attempts,
  });
}

function atomicLoginCodeRedeem(body: unknown): Response {
  const input = (body || {}) as Record<string, unknown>;
  const userId = String(input.p_user_id || "");
  const loginCodeId = String(input.p_login_code_id || "");
  const codeHash = String(input.p_code_hash || "");
  const licenseId = String(input.p_license_id || "");
  const refreshHashValue = String(input.p_refresh_token_hash || "");
  const maxAttempts = Number(input.p_max_attempts);
  if (
    !/^[0-9a-f]{64}$/.test(codeHash) ||
    !/^[0-9a-f]{64}$/.test(refreshHashValue) ||
    !licenseId ||
    !Number.isInteger(maxAttempts) ||
    maxAttempts < 1 ||
    maxAttempts > 100
  ) {
    return okJson({ message: "invalid atomic login-code redeem parameters" }, 400);
  }
  const user = activeDb.users.find((candidate) => candidate.id === userId);
  if (!user) return okJson({ result: "invalid" });
  if (!["active", "trialing"].includes(user.status)) return okJson({ result: "inactive" });

  const loginCode = latestActiveLoginCode(userId);
  if (!loginCode || loginCode.id !== loginCodeId || loginCode.code_hash !== codeHash) {
    return okJson({ result: "invalid" });
  }
  if (loginCode.attempts >= maxAttempts) return okJson({ result: "locked" });

  if (nextAtomicLoginCodeFailure === "redeem_after_consume") {
    nextAtomicLoginCodeFailure = null;
    return okJson({ message: "injected login-code failure after consume" }, 500);
  }

  const licenseCreatedAt = new Date().toISOString();
  const license: LicenseRow = {
    id: licenseId,
    user_id: userId,
    refresh_token_hash: refreshHashValue,
    previous_refresh_token_hash: null,
    previous_refresh_attempt_hash: null,
    refresh_family_expires_at: refreshFamilyExpiry(licenseCreatedAt),
    device_label: (input.p_device_label as string | null | undefined) || null,
    revoked: false,
    last_used_at: null,
    created_at: licenseCreatedAt,
  };
  if (
    activeDb.licenses.some(
      (candidate) =>
        candidate.id === license.id || candidate.refresh_token_hash === license.refresh_token_hash,
    )
  ) {
    return okJson({ message: "duplicate login-code license" }, 409);
  }
  if (nextAtomicLoginCodeFailure === "redeem_after_license_insert") {
    nextAtomicLoginCodeFailure = null;
    return okJson({ message: "injected login-code failure after license insert" }, 500);
  }

  loginCode.consumed_at = new Date().toISOString();
  activeDb.licenses.push(license);
  return okJson({ result: "redeemed", license_id: license.id });
}

function headerValue(headers: HeadersInit | undefined, name: string): string {
  if (!headers) return "";
  if (headers instanceof Headers) return headers.get(name) || "";
  if (Array.isArray(headers)) {
    const entry = headers.find(([key]) => key.toLowerCase() === name.toLowerCase());
    return entry?.[1] || "";
  }
  const record = headers as Record<string, string>;
  return String(record[name] || record[name.toLowerCase()] || "");
}

async function waitForDeviceGrantDecisionBarrier(): Promise<void> {
  if (!nextDeviceGrantDecisionBarrier) return;
  const barrier = nextDeviceGrantDecisionBarrier;
  barrier.arrived += 1;
  if (barrier.arrived === barrier.parties) {
    nextDeviceGrantDecisionBarrier = null;
    barrier.release();
    return;
  }
  await barrier.promise;
}

async function waitForLoginCodeOperationBarrier(): Promise<void> {
  if (!nextLoginCodeOperationBarrier) return;
  const barrier = nextLoginCodeOperationBarrier;
  barrier.arrived += 1;
  if (barrier.arrived === barrier.parties) {
    nextLoginCodeOperationBarrier = null;
    barrier.release();
    return;
  }
  await barrier.promise;
}

async function waitForMembershipOperationBarrier(): Promise<void> {
  if (!nextMembershipOperationBarrier) return;
  const barrier = nextMembershipOperationBarrier;
  barrier.arrived += 1;
  if (barrier.arrived === barrier.parties) {
    nextMembershipOperationBarrier = null;
    barrier.release();
    return;
  }
  await barrier.promise;
}

async function waitForNamedRpcBarrier(name: string): Promise<void> {
  if (nextRpcBarrier?.name !== name) return;
  const barrier = nextRpcBarrier;
  barrier.arrived += 1;
  if (barrier.arrived === barrier.parties) {
    nextRpcBarrier = null;
    barrier.release();
    return;
  }
  await barrier.promise;
}

async function fakeSupabaseFetch(input: string | URL | Request, init: RequestInit = {}): Promise<Response> {
  const request = input instanceof Request ? input : null;
  const url = new URL(request ? request.url : String(input));
  const method = (request?.method || init.method || "GET").toUpperCase();
  const accept = request?.headers.get("accept") || headerValue(init.headers, "accept");
  const wantsSingle = accept.includes("application/vnd.pgrst.object+json");
  const bodyText = request ? await request.text() : String(init.body || "");
  const body = bodyText ? JSON.parse(bodyText) : null;
  const parts = url.pathname.split("/").filter(Boolean);
  const table = parts.at(-1) || "";

  if (url.pathname.includes("/rpc/check_rate_limit")) {
    return okJson({ allowed: true, remaining: 100, retry_after: 0 });
  }

  if (url.pathname.includes("/rpc/rotate_license_refresh_v2")) {
    activeDb.calls.push({ table: "rotate_license_refresh_v2", method, body });
    await waitForNamedRpcBarrier("rotate_license_refresh_v2");
    return atomicLicenseRefreshV2(body);
  }

  if (url.pathname.includes("/rpc/approve_device_grant_atomic")) {
    activeDb.calls.push({ table: "approve_device_grant_atomic", method, body });
    await waitForDeviceGrantDecisionBarrier();
    await waitForNamedRpcBarrier("approve_device_grant_atomic");
    return atomicDeviceApproval(body);
  }

  if (url.pathname.includes("/rpc/add_org_membership_atomic")) {
    activeDb.calls.push({ table: "add_org_membership_atomic", method, body });
    await waitForMembershipOperationBarrier();
    await waitForNamedRpcBarrier("add_org_membership_atomic");
    return atomicMembershipAdd(body);
  }

  if (url.pathname.includes("/rpc/create_org_with_owner_atomic")) {
    activeDb.calls.push({ table: "create_org_with_owner_atomic", method, body });
    await waitForMembershipOperationBarrier();
    await waitForNamedRpcBarrier("create_org_with_owner_atomic");
    return atomicOrgWithOwnerCreate(body);
  }

  if (url.pathname.includes("/rpc/accept_invitation_atomic")) {
    activeDb.calls.push({ table: "accept_invitation_atomic", method, body });
    await waitForMembershipOperationBarrier();
    await waitForNamedRpcBarrier("accept_invitation_atomic");
    return atomicInvitationAccept(body);
  }

  if (url.pathname.includes("/rpc/issue_login_code_atomic")) {
    activeDb.calls.push({ table: "issue_login_code_atomic", method, body });
    await waitForLoginCodeOperationBarrier();
    await waitForNamedRpcBarrier("issue_login_code_atomic");
    return atomicLoginCodeIssue(body);
  }

  if (url.pathname.includes("/rpc/record_login_code_attempt_atomic")) {
    activeDb.calls.push({ table: "record_login_code_attempt_atomic", method, body });
    await waitForLoginCodeOperationBarrier();
    await waitForNamedRpcBarrier("record_login_code_attempt_atomic");
    return atomicLoginCodeAttempt(body);
  }

  if (url.pathname.includes("/rpc/redeem_login_code_atomic")) {
    activeDb.calls.push({ table: "redeem_login_code_atomic", method, body });
    await waitForLoginCodeOperationBarrier();
    await waitForNamedRpcBarrier("redeem_login_code_atomic");
    return atomicLoginCodeRedeem(body);
  }

  activeDb.calls.push({ table, method, body });

  if (method === "GET") {
    if (nextSelectFailure?.table === table) {
      const failure = nextSelectFailure;
      nextSelectFailure = null;
      return okJson({ message: failure.message }, failure.status);
    }
    return okJson(selectRows(table, url.searchParams, wantsSingle));
  }
  if (method === "POST") {
    if (table === "session_diagnostic_events") {
      upsertDiagnostics(body);
      return noContent();
    }
    if (nextInsertFailure?.table === table) {
      const failure = nextInsertFailure;
      nextInsertFailure = null;
      return okJson({ message: failure.message }, failure.status);
    }
    return okJson(insertRows(table, body), 201);
  }
  if (method === "PATCH") {
    if (
      table === "device_grants" &&
      (body as Record<string, unknown> | null)?.status === "denied"
    ) {
      await waitForDeviceGrantDecisionBarrier();
    }
    if (nextPatchBarrier?.table === table) {
      const barrier = nextPatchBarrier;
      barrier.arrived += 1;
      if (barrier.arrived === barrier.parties) {
        nextPatchBarrier = null;
        barrier.release();
      } else {
        await barrier.promise;
      }
    }
    if (nextPatchFailure?.table === table) {
      const failure = nextPatchFailure;
      nextPatchFailure = null;
      return okJson({ message: failure.message }, failure.status);
    }
    const rows = updateRows(table, url.searchParams, body as Record<string, unknown>);
    if (url.searchParams.has("select")) return okJson(rows);
    return noContent();
  }
  if (method === "DELETE") {
    const rows = deleteRows(table, url.searchParams);
    if (url.searchParams.has("select")) return okJson(rows);
    return noContent();
  }

  throw new Error(`unexpected Supabase request ${method} ${url}`);
}

globalThis.fetch = fakeSupabaseFetch as typeof fetch;

if (!globalThis.WebSocket) {
  globalThis.WebSocket = class {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;
    readyState = 3;
    close() {}
    send() {}
    addEventListener() {}
    removeEventListener() {}
  } as unknown as typeof WebSocket;
}

export function seedLicense(values: Partial<LicenseRow> & { user_id: string }): LicenseRow {
  const createdAt = values.created_at || new Date().toISOString();
  const license: LicenseRow = {
    id: values.id || `license-${nextLicenseId++}`,
    user_id: values.user_id,
    device_label: values.device_label ?? null,
    refresh_token_hash: values.refresh_token_hash || refreshHash("refresh-token"),
    previous_refresh_token_hash: values.previous_refresh_token_hash ?? null,
    previous_refresh_attempt_hash: values.previous_refresh_attempt_hash ?? null,
    refresh_family_expires_at:
      values.refresh_family_expires_at || refreshFamilyExpiry(createdAt),
    revoked: values.revoked ?? false,
    last_used_at: values.last_used_at ?? null,
    created_at: createdAt,
  };
  activeDb.licenses.push(license);
  return license;
}

export function assertNoRawDiagnosticsText(db: FakeDb): void {
  const text = JSON.stringify(db.session_diagnostic_events);
  assert.equal(text.includes("raw prompt"), false);
  assert.equal(text.includes("secret body"), false);
}
