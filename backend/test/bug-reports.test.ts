import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  createFakeDb,
  issueAccessToken,
  jsonRequest,
  loadRoute,
  makeUser,
  responseJson,
  seedLicense,
  useFakeDb,
} from "./route-harness";

type BugReportsRoute = {
  POST: (req: Request) => Promise<Response>;
  GET: (req: Request) => Promise<Response>;
};

function bugReportsRoute(): Promise<BugReportsRoute> {
  return loadRoute<BugReportsRoute>("bug-reports");
}

describe("bug-reports route handlers", () => {
  it("POST requires the client bearer token the desktop already holds", async () => {
    useFakeDb(createFakeDb());
    const route = await bugReportsRoute();

    const response = await route.POST(
      jsonRequest("/api/bug-reports", { note: "no auth here" }),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 401);
    assert.deepEqual(body, { error: "missing bearer token" });
  });

  it("POST stores a row keyed to the token identity and returns { id, ok: true }", async () => {
    const db = useFakeDb(createFakeDb());
    const user = await makeUser({ email: "reporter@example.com" });
    db.users.push(user);
    const license = seedLicense({ id: "bug-license", user_id: user.id });
    const bearer = await issueAccessToken(user, license);
    const route = await bugReportsRoute();

    const response = await route.POST(
      jsonRequest(
        "/api/bug-reports",
        {
          note: "  Board fails to load on the Today tab  ",
          screenshot: "data:image/png;base64,AAAA",
          page: "/leads",
          pageTitle: "Leads",
          dealId: "deal-42",
          dealTitle: "4287 Ash Crescent",
          userAgent: "ElevateDesktop/1.2.81",
          viewport: "1440x900",
          reporter: "spoofed-name-from-body",
          appVersion: "1.2.81",
          consoleErrors: ["TypeError: x is undefined", "warn: slow render"],
        },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 200);
    assert.equal(body.ok, true);
    assert.equal(typeof body.id, "string");

    assert.equal(db.bug_reports.length, 1);
    const stored = db.bug_reports[0];
    assert.equal(stored.id, body.id);
    // Reporter identity is derived from the verified token, never the body.
    assert.equal(stored.user_id, user.id);
    assert.equal(stored.license_id, license.id);
    assert.equal(stored.reporter_email, "reporter@example.com");
    assert.equal(stored.app_version, "1.2.81");
    assert.equal(stored.note, "Board fails to load on the Today tab");
    assert.equal(stored.status, "open");
    assert.equal(stored.screenshot, "data:image/png;base64,AAAA");
    assert.equal(stored.context.page, "/leads");
    assert.equal(stored.context.dealId, "deal-42");
    assert.equal(stored.context.reporterLabel, "spoofed-name-from-body");
    assert.deepEqual(stored.context.consoleErrors, [
      "TypeError: x is undefined",
      "warn: slow render",
    ]);
  });

  it("POST rejects an empty note with 400, not 500", async () => {
    const db = useFakeDb(createFakeDb());
    const user = await makeUser();
    db.users.push(user);
    const license = seedLicense({ id: "empty-note-license", user_id: user.id });
    const bearer = await issueAccessToken(user, license);
    const route = await bugReportsRoute();

    const response = await route.POST(
      jsonRequest(
        "/api/bug-reports",
        { note: "   " },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 400);
    assert.deepEqual(body, { error: "a description is required" });
    assert.equal(db.bug_reports.length, 0);
  });

  it("POST tolerates a note-only payload (no 500 on missing optional fields)", async () => {
    const db = useFakeDb(createFakeDb());
    const user = await makeUser();
    db.users.push(user);
    const license = seedLicense({ id: "note-only-license", user_id: user.id });
    const bearer = await issueAccessToken(user, license);
    const route = await bugReportsRoute();

    const response = await route.POST(
      jsonRequest(
        "/api/bug-reports",
        { note: "just a note" },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 200);
    assert.equal(body.ok, true);
    assert.equal(db.bug_reports.length, 1);
    assert.equal(db.bug_reports[0].screenshot, null);
    assert.equal(db.bug_reports[0].app_version, null);
  });

  it("GET is gated behind HQ admin auth, not the client entitlement", async () => {
    const db = useFakeDb(createFakeDb());
    const member = await makeUser({ role: "user" });
    db.users.push(member);
    const license = seedLicense({ id: "member-license", user_id: member.id });
    const bearer = await issueAccessToken(member, license);
    const route = await bugReportsRoute();

    const missingBearer = await route.GET(
      jsonRequest("/api/bug-reports", {}, { method: "GET" }),
    );
    assert.equal(missingBearer.status, 401);

    const nonAdmin = await route.GET(
      jsonRequest(
        "/api/bug-reports",
        {},
        { method: "GET", headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    const nonAdminBody = await responseJson(nonAdmin);
    assert.equal(nonAdmin.status, 403);
    assert.deepEqual(nonAdminBody, { error: "admin role required" });
  });

  it("GET returns an admin the reports newest-first", async () => {
    const db = useFakeDb(createFakeDb());
    const admin = await makeUser({
      id: "admin-user",
      email: "admin@example.com",
      role: "admin",
    });
    db.users.push(admin);
    const adminLicense = seedLicense({ id: "admin-license", user_id: admin.id });
    const bearer = await issueAccessToken(admin, adminLicense);

    db.bug_reports.push(
      {
        id: "bug-report-old",
        created_at: "2026-01-01T00:00:00.000Z",
        user_id: admin.id,
        license_id: adminLicense.id,
        reporter_email: "reporter@example.com",
        app_version: "1.2.80",
        note: "older bug",
        context: {},
        screenshot: null,
        status: "open",
        resolved_at: null,
      },
      {
        id: "bug-report-new",
        created_at: "2026-02-01T00:00:00.000Z",
        user_id: admin.id,
        license_id: adminLicense.id,
        reporter_email: "reporter@example.com",
        app_version: "1.2.81",
        note: "newer bug",
        context: {},
        screenshot: null,
        status: "open",
        resolved_at: null,
      },
    );

    const route = await bugReportsRoute();
    const response = await route.GET(
      jsonRequest(
        "/api/bug-reports",
        {},
        { method: "GET", headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    const body = await responseJson(response);

    assert.equal(response.status, 200);
    const reports = body.reports as Array<Record<string, unknown>>;
    assert.equal(reports.length, 2);
    assert.equal(reports[0].note, "newer bug");
    assert.equal(reports[1].note, "older bug");
  });
});
