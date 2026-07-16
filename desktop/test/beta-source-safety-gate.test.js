"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const {
  BETA_SOURCE_SAFETY_KIND,
  BETA_SOURCE_SAFETY_SCHEMA_VERSION,
  REQUIRED_SUITE_IDS,
  currentNodeAtLeast,
  pythonDescriptor,
  sanitizedEnvironment,
  suiteManifest,
  suiteManifestId,
  validateBetaSourceSafetyEvidence,
} = require("../scripts/beta-source-safety-gate");

function passingEvidence() {
  const manifest = suiteManifest();
  const python = pythonDescriptor();
  return {
    schema_version: BETA_SOURCE_SAFETY_SCHEMA_VERSION,
    kind: BETA_SOURCE_SAFETY_KIND,
    channel: "beta",
    started_at: "2026-07-15T12:00:00.000Z",
    completed_at: "2026-07-15T12:05:00.000Z",
    node: process.version,
    python: python.path,
    python_version: python.version,
    manifest,
    manifest_id: suiteManifestId(manifest),
    git: {
      commit: "a".repeat(40),
      branch: "beta",
      clean: true,
      status_sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    },
    checkout_stable: true,
    passed: true,
    suites: REQUIRED_SUITE_IDS.map((id) => ({
      id,
      passed: true,
      status: 0,
      duration_ms: 1,
      output_sha256: "a".repeat(64),
    })),
  };
}

test("Beta source gate manifest covers every bounded release safety lane", () => {
  const manifest = suiteManifest();
  assert.deepEqual(manifest.map((suite) => suite.id), [...REQUIRED_SUITE_IDS]);
  assert.equal(suiteManifestId(manifest), suiteManifestId(structuredClone(manifest)));

  const serialized = JSON.stringify(manifest);
  for (const id of [
    "python-session-safety",
    "python-tool-policy-core",
    "python-tool-policy-runtime",
    "python-document-coordination",
    "desktop-release-tests",
  ]) {
    assert.deepEqual(
      manifest.find((suite) => suite.id === id)?.environment,
      { ELEVATE_EXACT_BETA: "0", ELEVATE_RELEASE_CHANNEL: "stable" },
    );
  }
  for (const required of [
    "test_turn_fence.py",
    "test_tui_gateway_server.py",
    "test_session_stop_adversarial.py",
    "test_registry_shadow_execution.py",
    "test_terminal_approval_effect_receipts.py",
    "test_tool_executor_beta_containment.py",
    "test_beta_execution_disabled.py",
    "test_run_agent.py",
    "test_admin_dispatch_endpoints.py",
    "test_beta_province_pack.py",
    "ChatPage.activityDigest.test.ts",
    "forms-provider-option-b.test.ts",
    "turnController.stop.test.ts",
    "web-production-build",
    "terminal-ui-session",
    "beta-source-safety-gate.test.js",
  ]) {
    assert.match(serialized, new RegExp(required.replaceAll(".", "\\.")));
  }
});

test("Beta source gate pins child npm scripts to the active Node toolchain", () => {
  const env = sanitizedEnvironment();
  assert.equal(env.PATH.split(path.delimiter)[0], path.dirname(process.execPath));
  assert.equal(env.ELEVATE_RELEASE_CHANNEL, "beta");
  assert.equal(env.PYTHONDONTWRITEBYTECODE, "1");
});

test("Beta source evidence is exact, complete, clean, and fail closed", (t) => {
  if (!currentNodeAtLeast(22, 12)) {
    t.skip("release evidence validation requires the declared Node 22.12+ toolchain");
    return;
  }
  const evidence = passingEvidence();
  assert.equal(
    validateBetaSourceSafetyEvidence(evidence, { expectedGit: evidence.git }),
    evidence,
  );

  const cases = [
    [{ ...evidence, passed: false }, /did not pass/],
    [{ ...evidence, checkout_stable: false }, /checkout changed/],
    [{ ...evidence, manifest_id: "0".repeat(64) }, /manifest drift/],
    [{ ...evidence, manifest: evidence.manifest.slice(1) }, /manifest does not match/],
    [{ ...evidence, git: { ...evidence.git, clean: false } }, /clean checkout/],
    [{ ...evidence, suites: evidence.suites.slice(1) }, /incomplete or reordered/],
    [{
      ...evidence,
      suites: evidence.suites.map((suite, index) => (
        index === 0 ? { ...suite, passed: false, status: 1 } : suite
      )),
    }, /failed suite/],
  ];
  for (const [value, pattern] of cases) {
    assert.throws(() => validateBetaSourceSafetyEvidence(value), pattern);
  }
});
