import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatDeviceV3UserCode } from "../src/lib/store";
import {
  afterNextDeviceApprovalCapabilityRead,
  afterNextSupabaseRpc,
  barrierNextDeviceGrantRowOperations,
  barrierNextRefreshCapabilityOperations,
  barrierNextSupabaseRpcs,
  failNextAtomicDeviceStartV3,
  gateNextSupabaseRpc,
  gateNextDeviceApprovalUserLock,
  issueAccessToken,
  jsonRequest,
  loadRoute,
  makeUser,
  refreshHash,
  responseJson,
  seedLicense,
  useFakeDb,
} from "./route-harness";

type PostRoute = { POST: (req: Request) => Promise<Response> };

const DEVICE_D = Buffer.alloc(32, 0x44).toString("base64url");
const DEVICE_E = Buffer.alloc(32, 0x45).toString("base64url");
const REFRESH_B = Buffer.alloc(32, 0x42).toString("base64url");
const REFRESH_C = Buffer.alloc(32, 0x43).toString("base64url");
const REFRESH_A = Buffer.alloc(32, 0x41).toString("base64url");
const REFRESH_I = Buffer.alloc(32, 0x49).toString("base64url");

function startBody(
  deviceCode = DEVICE_D,
  refreshToken = REFRESH_B,
): Record<string, unknown> {
  return {
    protocol_version: 3,
    device_code: deviceCode,
    device_label: "Device v3 CLI",
    proposed_refresh_token_hash: refreshHash(refreshToken),
  };
}

function request(body = startBody(), origin = "https://attacker.invalid"): Request {
  return jsonRequest("/api/device/start", body, {
    headers: {
      origin,
      "x-forwarded-for": "198.51.100.20",
      "user-agent": "device-v3-test",
    },
  });
}

function assertStartCredentialFree(body: Record<string, unknown>): void {
  for (const field of [
    "device_code",
    "user_code",
    "access_token",
    "refresh_token",
    "entitlement_assertion",
  ]) {
    assert.equal(field in body, false, `unexpected ${field}`);
  }
}

function assertCredentialFree(body: Record<string, unknown>): void {
  for (const field of ["access_token", "refresh_token", "entitlement_assertion"]) {
    assert.equal(field in body, false, `unexpected ${field}`);
  }
}

function capabilityOwnerCount(
  db: ReturnType<typeof useFakeDb>,
  refreshToken: string,
): number {
  const hash = refreshHash(refreshToken);
  return (
    db.device_grants.filter(
      (candidate) => candidate.proposed_refresh_token_hash === hash,
    ).length +
    db.licenses.filter(
      (candidate) =>
        candidate.refresh_token_hash === hash ||
        candidate.previous_refresh_token_hash === hash,
    ).length
  );
}

describe("device start v3 route", () => {
  it("formats v3 user codes with the truly unambiguous alphabet", async () => {
    const observed = new Set<string>();
    for (let value = 0; value <= 255; value += 1) {
      const code = formatDeviceV3UserCode(
        Uint8Array.from({ length: 8 }, () => value),
      );
      assert.match(code, /^[A-HJ-KM-NP-Z2-9]{4}-[A-HJ-KM-NP-Z2-9]{4}$/);
      assert.doesNotMatch(code, /[01ILO]/);
      observed.add(code[0]);
    }
    assert.equal(observed.size, 31);
  });

  it("requires canonical D and B whenever exact numeric v3 is requested", async () => {
    const db = useFakeDb();
    const start = await loadRoute<PostRoute>("device/start");
    const noncanonical = `${DEVICE_D.slice(0, -1)}R`;
    assert.equal(Buffer.from(noncanonical, "base64url").length, 32);
    assert.notEqual(Buffer.from(noncanonical, "base64url").toString("base64url"), noncanonical);

    for (const body of [
      { ...startBody(), device_code: undefined },
      { ...startBody(), proposed_refresh_token_hash: undefined },
      { ...startBody(), device_code: noncanonical },
      {
        ...startBody(),
        proposed_refresh_token_hash: refreshHash(REFRESH_B).toUpperCase(),
      },
    ]) {
      const response = await start.POST(request(body));
      assert.equal(response.status, 400);
      assertStartCredentialFree(await responseJson(response));
    }
    assert.equal(db.device_grants.length, 0);
  });

  it("keeps absent, explicit v1/v2, and nonnumeric protocol values on legacy paths", async () => {
    const start = await loadRoute<PostRoute>("device/start");
    for (const scenario of [
      {
        body: { device_label: "Absent protocol" },
        expectedProtocol: undefined,
      },
      {
        body: {
          protocol_version: 1,
          device_code: "legacy-client-field-is-ignored",
          device_label: "Explicit v1",
        },
        expectedProtocol: undefined,
      },
      {
        body: {
          protocol_version: 2,
          device_code: DEVICE_D,
          device_label: "Explicit v2",
          proposed_refresh_token_hash: refreshHash(REFRESH_B),
        },
        expectedProtocol: 2,
      },
      {
        body: {
          protocol_version: "3",
          device_code: DEVICE_D,
          device_label: "String three stays legacy",
        },
        expectedProtocol: undefined,
      },
    ]) {
      const db = useFakeDb();
      const response = await start.POST(
        jsonRequest("/api/device/start", scenario.body, {
          headers: { origin: "https://legacy-client.test" },
        }),
      );
      const body = await responseJson(response);
      assert.equal(response.status, 200);
      assert.equal(body.protocol_version, scenario.expectedProtocol);
      assert.match(String(body.device_code), /^[A-Za-z0-9_-]{43}$/);
      assert.notEqual(body.device_code, scenario.body.device_code);
      assert.match(String(body.user_code), /^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$/);
      assert.equal(body.verification_uri, "https://legacy-client.test/link");
      assert.equal(body.expires_in, 600);
      assert.equal(db.device_grants.length, 1);
      assert.equal(
        db.calls.some(
          (call) => call.table === "start_device_grant_atomic_v3",
        ),
        false,
      );
      assert.equal(
        db.device_grants[0].proposed_refresh_token_hash,
        scenario.expectedProtocol === 2 ? refreshHash(REFRESH_B) : null,
      );
    }
  });

  it("recovers a discarded start response with one grant and no expiry extension", async () => {
    const db = useFakeDb();
    const start = await loadRoute<PostRoute>("device/start");
    const previousBaseUrl = process.env.PUBLIC_BASE_URL;
    process.env.PUBLIC_BASE_URL = "https://beta.elevate.test/";
    try {
      const first = await start.POST(request());
      const firstBody = await responseJson(first);
      assert.equal(first.status, 200);
      assert.equal(firstBody.protocol_version, 3);
      assert.equal(firstBody.device_code, DEVICE_D);
      assert.equal(firstBody.verification_uri, "https://beta.elevate.test/link");
      assert.equal(
        firstBody.verification_uri_complete,
        `https://beta.elevate.test/link?code=${firstBody.user_code}`,
      );

      const committedExpiry = db.device_grants[0].expires_at;
      const retry = await start.POST(request(startBody(), "https://different.invalid"));
      const retryBody = await responseJson(retry);
      assert.equal(retry.status, 200);
      assert.equal(retryBody.device_code, DEVICE_D);
      assert.equal(retryBody.user_code, firstBody.user_code);
      assert.equal(db.device_grants.length, 1);
      assert.equal(db.device_grants[0].expires_at, committedExpiry);
      assert.ok(Number(retryBody.expires_in) <= Number(firstBody.expires_in));

      const rpcCalls = db.calls.filter(
        (call) => call.table === "start_device_grant_atomic_v3",
      );
      assert.equal(rpcCalls.length, 2);
      for (const call of rpcCalls) {
        const serialized = JSON.stringify(call.body);
        assert.equal(serialized.includes(DEVICE_D), false);
        assert.equal(serialized.includes(REFRESH_B), false);
        assert.deepEqual(Object.keys(call.body as Record<string, unknown>).sort(), [
          "p_device_code_hash",
          "p_device_label",
          "p_expires_at",
          "p_ip_addr",
          "p_proposed_refresh_token_hash",
          "p_user_agent",
          "p_user_code",
        ]);
      }
    } finally {
      if (previousBaseUrl === undefined) delete process.env.PUBLIC_BASE_URL;
      else process.env.PUBLIC_BASE_URL = previousBaseUrl;
    }
  });

  it("sweeps an unrelated stale approved grant and revokes its orphan license", async () => {
    const db = useFakeDb();
    const start = await loadRoute<PostRoute>("device/start");
    const staleStart = await start.POST(
      jsonRequest("/api/device/start", {
        device_label: "Unrelated stale device",
        proposed_refresh_token_hash: refreshHash(REFRESH_C),
      }),
    );
    assert.equal(staleStart.status, 200);
    const staleGrant = db.device_grants[0];
    const staleUser = await makeUser({ email: "stale-device-v3@example.com" });
    db.users.push(staleUser);
    const orphan = seedLicense({
      user_id: staleUser.id,
      refresh_token_hash: refreshHash(REFRESH_C),
    });
    Object.assign(staleGrant, {
      status: "approved",
      user_id: staleUser.id,
      license_id: orphan.id,
      approved_at: new Date(Date.now() - 20 * 60 * 1000).toISOString(),
      expires_at: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
    });

    const fresh = await start.POST(request(startBody(DEVICE_D, REFRESH_B)));
    assert.equal(fresh.status, 200);
    assert.equal(staleGrant.status, "expired");
    assert.equal(orphan.revoked, true);
    assert.equal(db.device_grants.length, 2);
    assert.equal(db.device_grants[1].status, "pending");
    assert.equal(
      db.calls.filter((call) => call.table === "expire_stale_device_grants_v2")
        .length,
      2,
      "both v2 and v3 starts run the stale-grant sweep",
    );
  });

  it("recovers when the RPC committed but its response never reached the route", async () => {
    const db = useFakeDb();
    const start = await loadRoute<PostRoute>("device/start");
    afterNextSupabaseRpc("start_device_grant_atomic_v3", () => {
      throw new Error("discarded committed RPC response");
    });

    const lost = await start.POST(request());
    assert.equal(lost.status, 503);
    assertStartCredentialFree(await responseJson(lost));
    assert.equal(db.device_grants.length, 1);
    const committed = { ...db.device_grants[0] };

    const recovered = await start.POST(request());
    const recoveredBody = await responseJson(recovered);
    assert.equal(recovered.status, 200);
    assert.equal(recoveredBody.user_code, committed.user_code);
    assert.equal(db.device_grants.length, 1);
    assert.equal(db.device_grants[0].expires_at, committed.expires_at);
  });

  it("converges identical concurrency and gives conflicting requests one winner", async () => {
    for (const bodies of [
      [startBody(), startBody()],
      [startBody(DEVICE_D, REFRESH_B), startBody(DEVICE_D, REFRESH_C)],
      [startBody(DEVICE_D, REFRESH_B), startBody(DEVICE_E, REFRESH_B)],
    ]) {
      const db = useFakeDb();
      const start = await loadRoute<PostRoute>("device/start");
      barrierNextSupabaseRpcs("start_device_grant_atomic_v3", 2);
      const responses = await Promise.all(
        bodies.map((body) => start.POST(request(body))),
      );
      const payloads = await Promise.all(responses.map(responseJson));
      assert.equal(db.device_grants.length, 1);
      if (JSON.stringify(bodies[0]) === JSON.stringify(bodies[1])) {
        assert.deepEqual(responses.map((response) => response.status), [200, 200]);
        assert.equal(payloads[0].user_code, payloads[1].user_code);
        assert.equal(payloads[0].device_code, payloads[1].device_code);
      } else {
        assert.deepEqual(
          responses.map((response) => response.status).sort(),
          [200, 409],
        );
        const conflict = payloads[responses.findIndex((response) => response.status === 409)];
        assertStartCredentialFree(conflict);
      }
    }
  });

  it("gives Device Start or login exactly one simultaneous capability winner", async () => {
    const db = useFakeDb();
    db.users.push(await makeUser());
    const start = await loadRoute<PostRoute>("device/start");
    const login = await loadRoute<PostRoute>("auth/login");
    barrierNextRefreshCapabilityOperations(2);

    const [startResponse, loginResponse] = await Promise.all([
      start.POST(request()),
      login.POST(
        jsonRequest("/api/auth/login", {
          email: "agent@example.com",
          password: "secret",
          device_label: "Competing Beta Mac",
          initial_refresh_token: REFRESH_B,
        }),
      ),
    ]);
    const [startPayload, loginPayload] = await Promise.all([
      responseJson(startResponse),
      responseJson(loginResponse),
    ]);

    assert.deepEqual(
      [startResponse.status, loginResponse.status].sort((left, right) => left - right),
      [200, 409],
    );
    assert.equal(capabilityOwnerCount(db, REFRESH_B), 1);
    if (startResponse.status === 409) assertStartCredentialFree(startPayload);
    if (loginResponse.status === 409) assertCredentialFree(loginPayload);
  });

  it("gives Device Start or signup exactly one simultaneous capability winner", async () => {
    const db = useFakeDb();
    const start = await loadRoute<PostRoute>("device/start");
    const signup = await loadRoute<PostRoute>("auth/signup");
    barrierNextRefreshCapabilityOperations(2);

    const [startResponse, signupResponse] = await Promise.all([
      start.POST(request()),
      signup.POST(
        jsonRequest("/api/auth/signup", {
          email: "start-race-signup@example.com",
          password: "password123",
          first_name: "Race",
          last_name: "Signup",
          device_label: "Competing Beta Mac",
          initial_refresh_token: REFRESH_B,
        }),
      ),
    ]);
    const [startPayload, signupPayload] = await Promise.all([
      responseJson(startResponse),
      responseJson(signupResponse),
    ]);

    assert.deepEqual(
      [startResponse.status, signupResponse.status].sort((left, right) => left - right),
      [200, 409],
    );
    assert.equal(capabilityOwnerCount(db, REFRESH_B), 1);
    if (startResponse.status === 409) assertStartCredentialFree(startPayload);
    if (signupResponse.status === 409) assertCredentialFree(signupPayload);
  });

  it("gives Device Start or Refresh A to B exactly one simultaneous winner", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "start-race-refresh@example.com" });
    db.users.push(user);
    const source = seedLicense({
      user_id: user.id,
      refresh_token_hash: refreshHash(REFRESH_A),
    });
    const start = await loadRoute<PostRoute>("device/start");
    const refresh = await loadRoute<PostRoute>("license/refresh");
    barrierNextRefreshCapabilityOperations(2);

    const [startResponse, refreshResponse] = await Promise.all([
      start.POST(request()),
      refresh.POST(
        jsonRequest("/api/license/refresh", {
          refresh_token: REFRESH_A,
          next_refresh_token: REFRESH_B,
          refresh_attempt_id: REFRESH_I,
        }),
      ),
    ]);
    const [startPayload, refreshPayload] = await Promise.all([
      responseJson(startResponse),
      responseJson(refreshResponse),
    ]);

    assert.equal([startResponse.status, refreshResponse.status].filter((status) => status === 200).length, 1);
    assert.ok([401, 409].includes(startResponse.status === 200 ? refreshResponse.status : startResponse.status));
    assert.equal(capabilityOwnerCount(db, REFRESH_B), 1);
    if (startResponse.status === 409) assertStartCredentialFree(startPayload);
    if (refreshResponse.status === 401) {
      assertCredentialFree(refreshPayload);
      assert.equal(source.revoked, true);
    }
  });

  it("serializes Device Start against an existing Device approval", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "start-race-approval@example.com" });
    db.users.push(user);
    const browserLicense = seedLicense({
      user_id: user.id,
      refresh_token_hash: refreshHash(REFRESH_C),
    });
    const bearer = await issueAccessToken(user, browserLicense);
    const start = await loadRoute<PostRoute>("device/start");
    const approve = await loadRoute<PostRoute>("device/approve");
    const proposal = await start.POST(
      jsonRequest("/api/device/start", {
        device_label: "Existing Device proposal",
        proposed_refresh_token_hash: refreshHash(REFRESH_B),
      }),
    );
    const proposalPayload = await responseJson(proposal);
    assert.equal(proposal.status, 200);
    barrierNextRefreshCapabilityOperations(2);

    const [competingStart, approval] = await Promise.all([
      start.POST(request(startBody(DEVICE_E, REFRESH_B))),
      approve.POST(
        jsonRequest(
          "/api/device/approve",
          { user_code: proposalPayload.user_code },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      ),
    ]);

    assert.equal(competingStart.status, 409);
    assertStartCredentialFree(await responseJson(competingStart));
    assert.equal(approval.status, 200);
    assert.equal(capabilityOwnerCount(db, REFRESH_B), 2);
    assert.equal(
      db.device_grants.filter(
        (candidate) =>
          candidate.proposed_refresh_token_hash === refreshHash(REFRESH_B),
      ).length,
      1,
    );
    assert.equal(
      db.licenses.filter(
        (candidate) => candidate.refresh_token_hash === refreshHash(REFRESH_B),
      ).length,
      1,
    );
  });

  it("never approves a replacement proposal under the stale capability lock", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "approval-rebind@example.com" });
    db.users.push(user);
    const browserLicense = seedLicense({
      user_id: user.id,
      refresh_token_hash: refreshHash(REFRESH_A),
    });
    const bearer = await issueAccessToken(user, browserLicense);
    const start = await loadRoute<PostRoute>("device/start");
    const approve = await loadRoute<PostRoute>("device/approve");
    const proposal = await start.POST(
      jsonRequest("/api/device/start", {
        device_label: "Mutating proposal",
        proposed_refresh_token_hash: refreshHash(REFRESH_B),
      }),
    );
    const proposalPayload = await responseJson(proposal);
    const grant = db.device_grants[0];
    afterNextDeviceApprovalCapabilityRead(() => {
      grant.proposed_refresh_token_hash = refreshHash(REFRESH_C);
    });

    const staleApproval = await approve.POST(
      jsonRequest(
        "/api/device/approve",
        { user_code: proposalPayload.user_code },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    assert.equal(staleApproval.status, 409);
    assert.equal(grant.status, "pending");
    assert.equal(capabilityOwnerCount(db, REFRESH_B), 0);
    assert.equal(capabilityOwnerCount(db, REFRESH_C), 1);
    assert.equal(db.licenses.length, 1);

    const reboundApproval = await approve.POST(
      jsonRequest(
        "/api/device/approve",
        { user_code: proposalPayload.user_code },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    assert.equal(reboundApproval.status, 200);
    assert.equal(grant.status, "approved");
    assert.equal(capabilityOwnerCount(db, REFRESH_C), 2);
  });

  it("samples approval expiry after a blocking user-row wait", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "approval-expiry-wait@example.com" });
    db.users.push(user);
    const browserLicense = seedLicense({
      user_id: user.id,
      refresh_token_hash: refreshHash(REFRESH_A),
    });
    const bearer = await issueAccessToken(user, browserLicense);
    const start = await loadRoute<PostRoute>("device/start");
    const approve = await loadRoute<PostRoute>("device/approve");
    const proposal = await start.POST(
      jsonRequest("/api/device/start", {
        device_label: "Expires during user wait",
        proposed_refresh_token_hash: refreshHash(REFRESH_B),
      }),
    );
    const proposalPayload = await responseJson(proposal);
    const grant = db.device_grants[0];
    const userLock = gateNextDeviceApprovalUserLock();

    const approvalPromise = approve.POST(
      jsonRequest(
        "/api/device/approve",
        { user_code: proposalPayload.user_code },
        { headers: { authorization: `Bearer ${bearer}` } },
      ),
    );
    await userLock.reached;
    grant.expires_at = new Date(Date.now() - 1).toISOString();
    userLock.release();

    const approval = await approvalPromise;
    assert.equal(approval.status, 410);
    assert.deepEqual(await responseJson(approval), { error: "expired" });
    assert.equal(grant.status, "expired");
    assert.equal(grant.license_id, null);
    assert.equal(db.licenses.length, 1);
    assert.equal(capabilityOwnerCount(db, REFRESH_B), 1);
  });

  it("completes repeat approval versus claim without a reverse-lock cycle", async () => {
    const db = useFakeDb();
    const user = await makeUser({ email: "approval-claim-lock-order@example.com" });
    db.users.push(user);
    const browserLicense = seedLicense({
      user_id: user.id,
      refresh_token_hash: refreshHash(REFRESH_A),
    });
    const bearer = await issueAccessToken(user, browserLicense);
    const start = await loadRoute<PostRoute>("device/start");
    const approve = await loadRoute<PostRoute>("device/approve");
    const poll = await loadRoute<PostRoute>("device/poll");
    const proposal = await start.POST(
      jsonRequest("/api/device/start", {
        device_label: "Approval claim lock order",
        proposed_refresh_token_hash: refreshHash(REFRESH_B),
      }),
    );
    const proposalPayload = await responseJson(proposal);
    const approvalRequest = () =>
      approve.POST(
        jsonRequest(
          "/api/device/approve",
          { user_code: proposalPayload.user_code },
          { headers: { authorization: `Bearer ${bearer}` } },
        ),
      );
    assert.equal((await approvalRequest()).status, 200);
    const grant = db.device_grants[0];
    assert.equal(grant.status, "approved");

    barrierNextDeviceGrantRowOperations(2);
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      const [repeatApproval, claim] = await Promise.race([
        Promise.all([
          approvalRequest(),
          poll.POST(
            jsonRequest("/api/device/poll", {
              device_code: proposalPayload.device_code,
              refresh_token: REFRESH_B,
            }),
          ),
        ]),
        new Promise<never>((_resolve, reject) => {
          timeout = setTimeout(
            () => reject(new Error("approval/claim lock-order deadlock")),
            1_000,
          );
        }),
      ]);
      const [repeatPayload, claimPayload] = await Promise.all([
        responseJson(repeatApproval),
        responseJson(claim),
      ]);
      assert.equal(repeatApproval.status, 409);
      assertCredentialFree(repeatPayload);
      assert.equal(claim.status, 200);
      assert.equal(claimPayload.refresh_token, REFRESH_B);
    } finally {
      if (timeout) clearTimeout(timeout);
    }

    assert.equal(grant.status, "claimed");
    assert.equal(db.licenses.length, 2);
    assert.equal(
      db.licenses.filter(
        (candidate) => candidate.refresh_token_hash === refreshHash(REFRESH_B),
      ).length,
      1,
    );
  });

  it("rejects direct proposal mutation without taking a reverse-order B lock", async () => {
    const db = useFakeDb();
    const start = await loadRoute<PostRoute>("device/start");
    const proposal = await start.POST(
      jsonRequest("/api/device/start", {
        device_label: "Immutable proposal",
        proposed_refresh_token_hash: refreshHash(REFRESH_B),
      }),
    );
    assert.equal(proposal.status, 200);
    const grant = db.device_grants[0];

    const changed = await fetch(
      `https://example.supabase.test/rest/v1/device_grants?id=eq.${grant.id}`,
      {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          proposed_refresh_token_hash: refreshHash(REFRESH_C),
        }),
      },
    );
    assert.equal(changed.status, 400);
    assert.equal((await responseJson(changed)).code, "23514");
    assert.equal(grant.proposed_refresh_token_hash, refreshHash(REFRESH_B));

    const unchanged = await fetch(
      `https://example.supabase.test/rest/v1/device_grants?id=eq.${grant.id}`,
      {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          proposed_refresh_token_hash: refreshHash(REFRESH_B),
        }),
      },
    );
    assert.equal(unchanged.status, 204);
    assert.equal(grant.proposed_refresh_token_hash, refreshHash(REFRESH_B));
  });

  it("closes v3 races with v2/direct inserts and license lineage", async () => {
    const db = useFakeDb();
    const start = await loadRoute<PostRoute>("device/start");
    const gate = gateNextSupabaseRpc("start_device_grant_atomic_v3");
    const v3Promise = start.POST(request());
    await gate.reached;

    const v2 = await start.POST(
      jsonRequest("/api/device/start", {
        proposed_refresh_token_hash: refreshHash(REFRESH_B),
      }),
    );
    assert.equal(v2.status, 200);
    gate.release();
    const v3 = await v3Promise;
    assert.equal(v3.status, 409);
    assertStartCredentialFree(await responseJson(v3));
    assert.equal(db.device_grants.length, 1);

    useFakeDb();
    const user = await makeUser({ email: "lineage-device-v3@example.com" });
    seedLicense({ user_id: user.id, refresh_token_hash: refreshHash(REFRESH_B) });
    const lineage = await start.POST(request());
    assert.equal(lineage.status, 409);
    assertStartCredentialFree(await responseJson(lineage));

    for (const collisionSlot of ["current", "previous"] as const) {
      const retryDb = useFakeDb();
      const initial = await start.POST(request());
      assert.equal(initial.status, 200);
      const retryUser = await makeUser({
        email: `${collisionSlot}-after-start-v3@example.com`,
      });
      seedLicense({
        user_id: retryUser.id,
        refresh_token_hash:
          collisionSlot === "current" ? refreshHash(REFRESH_B) : refreshHash(REFRESH_C),
        previous_refresh_token_hash:
          collisionSlot === "previous" ? refreshHash(REFRESH_B) : null,
      });
      const blockedRetry = await start.POST(request());
      assert.equal(blockedRetry.status, 409);
      assertStartCredentialFree(await responseJson(blockedRetry));
      assert.equal(retryDb.device_grants.length, 1);
    }
  });

  it("retries user-code collision and rolls back an injected database failure", async () => {
    const db = useFakeDb();
    const start = await loadRoute<PostRoute>("device/start");
    failNextAtomicDeviceStartV3("user_code_conflict");
    const recovered = await start.POST(request());
    assert.equal(recovered.status, 200);
    assert.equal(db.device_grants.length, 1);
    assert.equal(
      db.calls.filter((call) => call.table === "start_device_grant_atomic_v3").length,
      2,
    );

    const rollbackDb = useFakeDb();
    failNextAtomicDeviceStartV3("after_insert");
    const failed = await start.POST(request(startBody(DEVICE_E, REFRESH_C)));
    assert.equal(failed.status, 503);
    assertStartCredentialFree(await responseJson(failed));
    assert.equal(rollbackDb.device_grants.length, 0);
  });

  it("returns typed credential-free recovery states without reopening a grant", async () => {
    const scenarios = ["approved", "claimed", "denied", "expired"] as const;
    for (const status of scenarios) {
      const db = useFakeDb();
      const start = await loadRoute<PostRoute>("device/start");
      const created = await start.POST(request());
      assert.equal(created.status, 200);
      const grant = db.device_grants[0];
      if (status === "approved" || status === "claimed") {
        const user = await makeUser({ email: `${status}-device-v3@example.com` });
        db.users.push(user);
        const license = seedLicense({
          user_id: user.id,
          refresh_token_hash: refreshHash(REFRESH_B),
        });
        Object.assign(grant, {
          status,
          user_id: user.id,
          license_id: license.id,
          approved_at: new Date().toISOString(),
          claimed_at: status === "claimed" ? new Date().toISOString() : null,
        });
      } else {
        grant.status = status;
      }

      const response = await start.POST(request());
      const body = await responseJson(response);
      assertStartCredentialFree(body);
      if (status === "approved" || status === "claimed") {
        assert.equal(response.status, 200);
        assert.deepEqual(body, {
          protocol_version: 3,
          status: "resume_poll",
          grant_status: status,
          interval: 5,
        });
      } else if (status === "denied") {
        assert.equal(response.status, 403);
        assert.deepEqual(body, { error: "authorization_denied" });
      } else {
        assert.equal(response.status, 410);
        assert.deepEqual(body, { error: "expired_token" });
      }
      assert.equal(db.device_grants.length, 1);
    }
  });

  it("expires an exact pending/approved retry without extending it", async () => {
    for (const status of ["pending", "approved"] as const) {
      const db = useFakeDb();
      const start = await loadRoute<PostRoute>("device/start");
      await start.POST(request());
      const grant = db.device_grants[0];
      let license: ReturnType<typeof seedLicense> | null = null;
      if (status === "approved") {
        const user = await makeUser({ email: "expired-approved-v3@example.com" });
        db.users.push(user);
        license = seedLicense({
          user_id: user.id,
          refresh_token_hash: refreshHash(REFRESH_B),
        });
        Object.assign(grant, {
          status: "approved",
          user_id: user.id,
          license_id: license.id,
        });
      }
      grant.expires_at = new Date(Date.now() - 1_000).toISOString();

      const response = await start.POST(request());
      assert.equal(response.status, 410);
      assert.deepEqual(await responseJson(response), { error: "expired_token" });
      assert.equal(grant.status, "expired");
      if (license) assert.equal(license.revoked, true);
    }
  });
});
