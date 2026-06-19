import assert from "node:assert/strict";
import crypto from "node:crypto";
import { pathToFileURL } from "node:url";
import bcrypt from "bcryptjs";

process.env.JWT_SECRET ||= "test-secret-for-hosted-route-handler-harness";
process.env.SUPABASE_URL ||= "https://example.supabase.test";
process.env.SUPABASE_SERVICE_ROLE_KEY ||= "test-service-role-key";

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
  return activeDb;
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
      const license: LicenseRow = {
        id: `license-${nextLicenseId++}`,
        user_id: String(row.user_id),
        refresh_token_hash: String(row.refresh_token_hash),
        device_label: (row.device_label as string | null) ?? null,
        revoked: false,
        last_used_at: null,
        created_at: new Date().toISOString(),
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
    for (const license of activeDb.licenses) {
      if (matchesId(license.id) && (!userId || license.user_id === userId)) {
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
    for (const grant of activeDb.device_grants) {
      if (matchesId(grant.id)) {
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

  activeDb.calls.push({ table, method, body });

  if (method === "GET") return okJson(selectRows(table, url.searchParams, wantsSingle));
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
  const license: LicenseRow = {
    id: values.id || `license-${nextLicenseId++}`,
    user_id: values.user_id,
    device_label: values.device_label ?? null,
    refresh_token_hash: values.refresh_token_hash || refreshHash("refresh-token"),
    revoked: values.revoked ?? false,
    last_used_at: values.last_used_at ?? null,
    created_at: values.created_at || new Date().toISOString(),
  };
  activeDb.licenses.push(license);
  return license;
}

export function assertNoRawDiagnosticsText(db: FakeDb): void {
  const text = JSON.stringify(db.session_diagnostic_events);
  assert.equal(text.includes("raw prompt"), false);
  assert.equal(text.includes("secret body"), false);
}
