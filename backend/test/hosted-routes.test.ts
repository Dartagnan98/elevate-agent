import assert from "node:assert/strict";
import crypto from "node:crypto";
import { describe, it } from "node:test";
import {
  assertNoRawDiagnosticsText,
  createFakeDb,
  failNextSupabasePatch,
  issueAccessToken,
  jsonRequest,
  loadRoute,
  makeUser,
  refreshHash,
  responseJson,
  seedLicense,
  useFakeDb,
} from "./route-harness";

describe("hosted route handlers", () => {
  it("health route is directly callable", async () => {
    const route = await loadRoute<{ GET: () => Promise<Response> }>("health");

    const response = await route.GET();
    const body = await responseJson(response);

    assert.equal(response.status, 200);
    assert.deepEqual(body, { ok: true, service: "elevate-backend" });
  });

  it("login returns the desktop token envelope for an active user", async () => {
    const db = useFakeDb();
    db.users.push(await makeUser());
    const route = await loadRoute<{ POST: (req: Request) => Promise<Response> }>("auth/login");

    const response = await route.POST(
      jsonRequest("/api/auth/login", {
        email: "agent@example.com",
        password: "secret",
        device_label: "MacBook",
      }),
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

    const okResponse = await route.POST(
      jsonRequest("/api/license/refresh", { refresh_token: "old-refresh" }),
    );
    const okBody = await responseJson(okResponse);

    assert.equal(okResponse.status, 200);
    assert.equal(typeof okBody.access_token, "string");
    assert.equal(typeof okBody.refresh_token, "string");
    assert.equal(okBody.tier, "pro");
    assert.deepEqual(okBody.entitlements, ["real_estate_sales"]);
    assert.notEqual(activeLicense.refresh_token_hash, refreshHash("old-refresh"));
    assert.equal(activeLicense.revoked, false);

    const inactiveResponse = await route.POST(
      jsonRequest("/api/license/refresh", { refresh_token: "inactive-refresh" }),
    );
    const inactiveBody = await responseJson(inactiveResponse);

    assert.equal(inactiveResponse.status, 402);
    assert.deepEqual(inactiveBody, { error: "subscription inactive" });
    assert.equal(inactiveLicense.revoked, true);
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

    const pollResponse = await poll.POST(
      jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
    );
    const pollBody = await responseJson(pollResponse);

    assert.equal(pollResponse.status, 200);
    assert.equal(pollBody.status, "approved");
    assert.equal(typeof pollBody.access_token, "string");
    assert.equal(typeof pollBody.refresh_token, "string");
    assert.equal(pollBody.license_id, "license-1");
    assert.equal(db.device_grants[0].status, "claimed");
    assert.equal(db.device_grants[0].refresh_token_plain, null);

    const secondPoll = await poll.POST(
      jsonRequest("/api/device/poll", { device_code: startBody.device_code }),
    );
    const secondBody = await responseJson(secondPoll);

    assert.equal(secondPoll.status, 410);
    assert.deepEqual(secondBody, { error: "already_claimed", status: "claimed" });
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

    const denyResponse = await deny.POST(
      jsonRequest(
        "/api/device/deny",
        { user_code: startBody.user_code },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );

    assert.equal(denyResponse.status, 200);
    assert.equal(db.device_grants[0].status, "denied");
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

      const rejected = await verifyRoute.POST(
        jsonRequest("/api/auth/login-code/verify", {
          email: "login-code@example.com",
          code: "000000",
        }),
      );
      const rejectedBody = await responseJson(rejected);

      assert.equal(rejected.status, 401);
      assert.deepEqual(rejectedBody, { error: "invalid code", attempts_remaining: 4 });
      assert.equal(db.login_codes[0].attempts, 1);

      const accepted = await verifyRoute.POST(
        jsonRequest("/api/auth/login-code/verify", {
          email: "login-code@example.com",
          code,
          device_label: "Admin Web",
        }),
      );
      const acceptedBody = await responseJson(accepted);

      assert.equal(accepted.status, 200);
      assert.equal(typeof acceptedBody.access_token, "string");
      assert.equal(typeof acceptedBody.refresh_token, "string");
      assert.equal(acceptedBody.license_id, "license-1");
      assert.equal(acceptedBody.tier, "pro");
      assert.deepEqual(acceptedBody.entitlements, ["real_estate_sales"]);
      assert.equal(db.licenses[0].device_label, "Admin Web");
      assert.equal(typeof db.login_codes[0].consumed_at, "string");
    } finally {
      if (previousNodeEnv === undefined) {
        Reflect.deleteProperty(process.env, "NODE_ENV");
      } else {
        Reflect.set(process.env, "NODE_ENV", previousNodeEnv);
      }
    }
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
