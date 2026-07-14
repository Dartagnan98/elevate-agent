"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { backendCanServeApp, backendIsReady } = require("../src/backend-http");

const EXPECTED_BETA_RUNTIME = Object.freeze({
  releaseChannel: "beta",
  elevateHome: "/Users/tester/.elevate-beta",
  providerPolicyVersion: "realtor-beta-codex-v1",
  allowedModelsVersion: "2026-07-14-v1",
  allowedProvider: "openai-codex",
  allowedModels: [
    "gpt-5.5",
    "gpt-5.4-mini",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
  ],
});

function runtimeReceipt(overrides = {}) {
  return {
    releaseChannel: "beta",
    elevateHome: "/Users/tester/.elevate-beta",
    providerPolicyVersion: "realtor-beta-codex-v1",
    allowedModelsVersion: "2026-07-14-v1",
    allowedProvider: "openai-codex",
    configuredProvider: "openai-codex",
    configuredModel: "gpt-5.5",
    authReady: true,
    authReason: null,
    runtimeReady: true,
    blockedReason: null,
    ...overrides,
  };
}

function statusPayload(receipt = runtimeReceipt()) {
  return {
    version: "0.12.0",
    gateway_running: false,
    beta_runtime: receipt,
  };
}

function fakeHttp(payload, statusCode = 200) {
  const body = JSON.stringify(payload);
  return {
    get(_options, callback) {
      callback({
        statusCode,
        resume() {},
        setEncoding() {},
        on(event, listener) {
          if (event === "data") listener(body);
          if (event === "end") listener();
          return this;
        },
      });
      return {
        destroy() {},
        on() {
          return this;
        },
      };
    },
  };
}

async function ready(payload, expectedRuntime = EXPECTED_BETA_RUNTIME) {
  return backendIsReady({
    http: fakeHttp(payload),
    host: "127.0.0.1",
    port: 9139,
    expectedRuntime,
  });
}

async function compatible(payload, expectedRuntime = EXPECTED_BETA_RUNTIME) {
  return backendCanServeApp({
    http: fakeHttp(payload),
    host: "127.0.0.1",
    port: 9139,
    expectedRuntime,
  });
}

test("valid Beta runtime receipt is ready for desktop adoption", async () => {
  assert.equal(await ready(statusPayload()), true);
});

test("Beta readiness rejects a Stable or legacy backend", async () => {
  assert.equal(await ready({ version: "0.12.0", gateway_running: true }), false);
  assert.equal(
    await ready(statusPayload(runtimeReceipt({ releaseChannel: "latest" }))),
    false,
  );
});

test("Beta readiness rejects wrong home and stale policy versions", async () => {
  assert.equal(
    await ready(statusPayload(runtimeReceipt({ elevateHome: "/Users/tester/.elevate" }))),
    false,
  );
  assert.equal(
    await ready(statusPayload(runtimeReceipt({ providerPolicyVersion: "old-policy" }))),
    false,
  );
  assert.equal(
    await ready(statusPayload(runtimeReceipt({ allowedModelsVersion: "old-models" }))),
    false,
  );
});

test("Beta readiness rejects hostile providers and unready auth", async () => {
  assert.equal(
    await ready(statusPayload(runtimeReceipt({ configuredProvider: "anthropic" }))),
    false,
  );
  assert.equal(
    await ready(statusPayload(runtimeReceipt({ allowedProvider: "anthropic" }))),
    false,
  );
  assert.equal(
    await ready(statusPayload(runtimeReceipt({ configuredModel: "hostile-model" }))),
    false,
  );
  assert.equal(
    await ready(statusPayload(runtimeReceipt({
      authReady: false,
      authReason: "missing_auth_store",
      runtimeReady: false,
      blockedReason: "missing_auth_store",
    }))),
    false,
  );
});

test("correct Beta backend can serve onboarding before runtime is ready", async () => {
  const onboardingReceipt = runtimeReceipt({
    configuredProvider: "",
    configuredModel: "",
    authReady: false,
    authReason: "missing_auth_store",
    runtimeReady: false,
    blockedReason: "missing_beta_provider",
  });

  assert.equal(await ready(statusPayload(onboardingReceipt)), false);
  assert.equal(await compatible(statusPayload(onboardingReceipt)), true);
});

test("onboarding compatibility still rejects wrong channel, home, or policy", async () => {
  assert.equal(
    await compatible(statusPayload(runtimeReceipt({ releaseChannel: "latest" }))),
    false,
  );
  assert.equal(
    await compatible(statusPayload(runtimeReceipt({ elevateHome: "/Users/tester/.elevate" }))),
    false,
  );
  assert.equal(
    await compatible(statusPayload(runtimeReceipt({ providerPolicyVersion: "old-policy" }))),
    false,
  );
});

test("Stable keeps legacy readiness behavior without a Beta expectation", async () => {
  assert.equal(
    await ready(
      { version: "0.12.0", gateway_running: false },
      null,
    ),
    true,
  );
  assert.equal(
    await compatible(
      { version: "0.12.0", gateway_running: false },
      null,
    ),
    true,
  );
});
