import assert from "node:assert/strict";
import crypto from "node:crypto";
import { describe, it } from "node:test";
import bcrypt from "bcryptjs";
import Stripe from "stripe";
import {
  assertNoRawDiagnosticsText,
  createFakeDb,
  failNextSupabaseInsert,
  failNextSupabasePatch,
  failNextSupabaseSelect,
  issueAccessToken,
  jsonRequest,
  loadRoute,
  makeUser,
  refreshHash,
  responseJson,
  seedLicense,
  useFakeDb,
} from "./route-harness";

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

      const signupResponse = await signup.POST(
        jsonRequest("/api/auth/signup", {
          email: "New.Agent@Example.COM",
          password: "old-secret",
          device_label: "New Mac",
        }),
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
