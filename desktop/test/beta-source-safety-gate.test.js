"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const test = require("node:test");

const {
  BETA_SOURCE_SAFETY_KIND,
  BETA_SOURCE_SAFETY_SCHEMA_VERSION,
  REQUIRED_FILES_BY_SUITE,
  REQUIRED_SUITE_IDS,
  analyzeSuiteExecution,
  buildSuiteSpecs,
  currentNodeAtLeast,
  npmCliPath,
  pythonDescriptor,
  requirePaths,
  runSuite,
  sanitizedEnvironment,
  suiteManifest,
  suiteManifestId,
  validateBetaSourceSafetyEvidence,
} = require("../scripts/beta-source-safety-gate");

function passingExecution(contract) {
  if (contract.kind === "command") return { kind: "command", commands_executed: 1 };
  const tests = contract.expected_tests || contract.minimum_tests || 1;
  const base = {
    kind: contract.kind,
    tests,
    passed: tests,
    failed: 0,
    skipped: 0,
    deselected: 0,
    collected_only: false,
  };
  if (contract.kind === "node-test") return { ...base, cancelled: 0, todo: 0 };
  if (contract.kind === "pytest") return { ...base, errors: 0, xfailed: 0, xpassed: 0 };
  return { ...base, todo: 0, test_files: 1, test_files_passed: 1 };
}

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
    suites: REQUIRED_SUITE_IDS.map((id, index) => ({
      id,
      passed: true,
      status: 0,
      signal: null,
      duration_ms: 1,
      execution: passingExecution(manifest[index].result_contract),
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
    "python-recovery-roll-forward",
    "desktop-release-tests",
  ]) {
    assert.deepEqual(
      manifest.find((suite) => suite.id === id)?.environment,
      { ELEVATE_EXACT_BETA: "0", ELEVATE_RELEASE_CHANNEL: "stable" },
    );
  }
  for (const suite of manifest) {
    assert.ok(suite.result_contract, `${suite.id} result contract`);
    if (suite.result_contract.kind !== "command") {
      assert.ok(suite.result_contract.minimum_tests > 0, `${suite.id} positive test count`);
      assert.equal(
        suite.result_contract.expected_tests,
        suite.result_contract.minimum_tests,
        `${suite.id} exact test count`,
      );
    }
  }
  assert.doesNotMatch(
    JSON.stringify(manifest.find((suite) => suite.id === "python-tool-policy-runtime").args),
    /"-k"|deselected/,
  );
  for (const required of [
    "test_turn_fence.py",
    "test_beta_oauth_containment.py",
    "test_beta_pty_provider_repair_bridge.py",
    "test_channel_telegram_routes.py",
    "test_gateway_launchd_reliability.py",
    "test_beta_status_receipt.py",
    "test_beta_unregistered_runtime_disabled.py",
    "test_tui_gateway_server.py",
    "test_beta_session_runtime_repair.py",
    "test_delegate_partial.py",
    "test_session_stop_adversarial.py",
    "test_registry_shadow_execution.py",
    "test_terminal_approval_effect_receipts.py",
    "test_agent_owned_registry_dispatch.py",
    "test_todo_registry_dispatch.py",
    "test_send_message_effects.py",
    "test_composio_tool.py",
    "test_manage_agent_tool.py",
    "test_leads_overview_tool.py",
    "test_working_state_tool.py",
    "test_hermes_tools_mcp_server.py",
    "test_tool_executor_beta_containment.py",
    "test_beta_execution_disabled.py",
    "test_beta_agent_setup_memory_policy.py",
    "test_beta_cli_provider_policy.py",
    "test_beta_config_write_policy.py",
    "test_beta_provider_policy.py",
    "test_admin_deal_effects.py",
    "test_lead_status_effects.py",
    "test_outreach_templates_effects.py",
    "test_discord_effects.py",
    "test_elevate_db_effects.py",
    "test_file_tools_effects.py",
    "test_file_materialize.py",
    "test_file_read_guards.py",
    "test_effect_policy.py",
    "test_memory_provider_registry_dispatch.py",
    "test_context_engine_registry_dispatch.py",
    "test_delegate_registry_dispatch.py",
    "test_memory_tool_registry_dispatch.py",
    "test_session_search_registry_dispatch.py",
    "test_plugin_registry_dispatch.py",
    "test_tool_effect_receipts_store.py",
    "test_effect_broker.py",
    "test_registry_effect_claims.py",
    "test_dispatch_companion_liveness.py",
    "test_terminal_transform_receipt_evidence.py",
    "test_beta_memory_flush_policy.py",
    "test_memory_write_metadata_wiring.py",
    "test_policy_inheritance.py",
    "test_delegate_policy_inheritance.py",
    "test_policy_inheritance_boundaries.py",
    "test_beta_enforcement_flip.py",
    "test_beta_unrouted_lane_containment.py",
    "test_beta_sender_containment.py",
    "test_run_agent.py",
    "test_admin_dispatch_endpoints.py",
    "test_beta_province_pack.py",
    "test_exact_candidate_realtor_beta_gate.py",
    "backend-tests",
    "deploy-health-verifier.test.ts",
    "entitlement-assertion.test.ts",
    "hosted-routes.test.ts",
    "deploy-script-static.sh",
    "backend-production-build",
    "beta-memory-policy.test.ts",
    "beta-provider-ui.test.ts",
    "oauth-readiness.test.ts",
    "ChatPage.activityDigest.test.ts",
    "forms-provider-option-b.test.ts",
    "turnController.stop.test.ts",
    "web-production-build",
    "terminal-ui-session",
    "backend-runner.test.js",
    "beta-source-safety-gate.test.js",
    "candidate-receipt.test.js",
    "gateway-self-heal.test.js",
    "recovery-containment.test.js",
    "recovery-packaging.test.js",
    "rollback-realtor-beta.test.js",
  ]) {
    assert.match(serialized, new RegExp(required.replaceAll(".", "\\.")));
  }
});

test("Beta source gate pins child npm scripts to the active Node toolchain", () => {
  const env = sanitizedEnvironment();
  const npmCli = npmCliPath();
  const npmVersion = spawnSync(process.execPath, [npmCli, "--version"], {
    encoding: "utf8",
    timeout: 30_000,
  });
  assert.equal(env.PATH.split(path.delimiter)[0], path.dirname(process.execPath));
  assert.equal(env.ELEVATE_RELEASE_CHANNEL, "beta");
  assert.equal(env.PYTHONDONTWRITEBYTECODE, "1");
  assert.equal(path.isAbsolute(npmCli), true);
  assert.equal(npmVersion.status, 0, npmVersion.stderr);
  for (const suite of buildSuiteSpecs().filter((spec) => (
    spec.id === "backend-production-build"
    || spec.id.startsWith("web-")
    || spec.id.startsWith("terminal-ui-")
  ))) {
    assert.equal(suite.command, process.execPath, suite.id);
    assert.equal(suite.args[0], npmCli, suite.id);
  }
  const backendTests = buildSuiteSpecs().find((spec) => spec.id === "backend-tests");
  assert.equal(backendTests.command, process.execPath);
  assert.deepEqual(backendTests.args.slice(0, 3), ["--import", "tsx", "--test"]);
  for (const required of REQUIRED_FILES_BY_SUITE["backend-tests"]) {
    assert.ok(backendTests.args.includes(path.resolve(__dirname, "../..", required)));
  }
});

test("source gate strips inherited runner injection and proves real Node/Python execution", (t) => {
  const poisoned = sanitizedEnvironment({
    environment: {
      ...process.env,
      NODE_OPTIONS: "--test-only --require=/tmp/injected.cjs",
      NODE_PATH: "/tmp/injected-modules",
      PYTEST_ADDOPTS: "--collect-only",
      PYTEST_PLUGINS: "injected_plugin",
      COVERAGE_PROCESS_START: "/tmp/coveragerc",
      NPM_CONFIG_IGNORE_SCRIPTS: "true",
      VITEST_MODE: "benchmark",
      PATH: "/tmp/poisoned-bin",
    },
  });
  for (const key of [
    "NODE_OPTIONS",
    "NODE_PATH",
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
    "COVERAGE_PROCESS_START",
    "NPM_CONFIG_IGNORE_SCRIPTS",
    "VITEST_MODE",
  ]) assert.equal(poisoned[key], undefined, key);
  assert.equal(poisoned.PATH.includes("poisoned-bin"), false);
  assert.equal(poisoned.PYTEST_DISABLE_PLUGIN_AUTOLOAD, "1");

  const root = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-source-gate-poison-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const nodeTest = path.join(root, "one.test.js");
  fs.writeFileSync(nodeTest, [
    'const test = require("node:test");',
    'test("actually runs", () => {});',
    "",
  ].join("\n"));
  const nodeResult = runSuite({
    id: "poisoned-node",
    cwd: root,
    command: process.execPath,
    args: ["--test", "--test-reporter=tap", nodeTest],
    timeoutMs: 30_000,
    resultContract: { kind: "node-test", expected_tests: 1, minimum_tests: 1 },
  }, poisoned);
  assert.equal(nodeResult.passed, true);
  assert.equal(nodeResult.execution.passed, 1);
  assert.equal(nodeResult.execution.skipped, 0);

  const pythonTest = path.join(root, "test_one.py");
  fs.writeFileSync(pythonTest, "def test_actually_runs():\n    assert True\n");
  const python = buildSuiteSpecs()[0].command;
  const pythonResult = runSuite({
    id: "poisoned-pytest",
    cwd: root,
    command: python,
    args: ["-B", "-m", "pytest", "-q", "-o", "addopts=", "--color=no", pythonTest],
    timeoutMs: 30_000,
    resultContract: { kind: "pytest", expected_tests: 1, minimum_tests: 1 },
  }, poisoned);
  assert.equal(pythonResult.passed, true);
  assert.equal(pythonResult.execution.passed, 1);
  assert.equal(pythonResult.execution.collected_only, false);
});

test("suite result contracts reject skipped, selected-out, and collect-only success exits", () => {
  assert.throws(() => analyzeSuiteExecution(
    { kind: "node-test", minimum_tests: 1 },
    ["1..1", "# tests 1", "# pass 0", "# fail 0", "# cancelled 0", "# skipped 1", "# todo 0"].join("\n"),
    "",
    true,
  ), /reported 1 skipped/);
  assert.throws(() => analyzeSuiteExecution(
    { kind: "pytest", minimum_tests: 1 },
    "14 tests collected in 0.33s\n",
    "",
    true,
  ), /positive test count|did not execute/);
  assert.throws(() => analyzeSuiteExecution(
    { kind: "pytest", minimum_tests: 1 },
    "9 passed, 486 deselected in 1.44s\n",
    "",
    true,
  ), /reported 486 deselected/);
  assert.throws(() => analyzeSuiteExecution(
    { kind: "vitest", minimum_tests: 1 },
    " Test Files  1 passed (1)\n Tests  7 passed | 1 skipped (8)\n",
    "",
    true,
  ), /reported 1 skipped/);
});

test("npm resolution prefers the active Node installation and fails closed", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-npm-resolution-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const nodeExecutable = path.join(root, "bin", "node");
  const activeNpm = path.join(root, "lib", "node_modules", "npm", "bin", "npm-cli.js");
  const fallbackNpm = path.join(root, "fallback", "npm-cli.js");
  fs.mkdirSync(path.dirname(activeNpm), { recursive: true });
  fs.mkdirSync(path.dirname(fallbackNpm), { recursive: true });
  fs.writeFileSync(activeNpm, "active");
  fs.writeFileSync(fallbackNpm, "fallback");

  assert.equal(npmCliPath({ nodeExecutable, npmExecPath: fallbackNpm }), activeNpm);
  fs.rmSync(activeNpm);
  assert.equal(npmCliPath({ nodeExecutable, npmExecPath: fallbackNpm }), fallbackNpm);
  fs.rmSync(fallbackNpm);
  assert.throws(
    () => npmCliPath({ nodeExecutable, npmExecPath: fallbackNpm }),
    /npm CLI for the active Node runtime was not found/,
  );
});

test("critical regression files cannot be deleted or removed from the gate", () => {
  const repo = path.resolve(__dirname, "../..");
  const manifest = suiteManifest();
  for (const [suiteId, requiredFiles] of Object.entries(REQUIRED_FILES_BY_SUITE)) {
    const suite = manifest.find((candidate) => candidate.id === suiteId);
    assert.ok(suite, suiteId);
    for (const required of requiredFiles) {
      assert.ok(suite.required_files.includes(required), `${suiteId}: ${required}`);

      const absolute = path.join(repo, required);
      const shrunk = buildSuiteSpecs().map((spec) => spec.id === suiteId ? {
        ...spec,
        requiredFiles: (spec.requiredFiles || []).filter((file) => file !== absolute),
        args: spec.args.filter((arg) => {
          if (typeof arg !== "string") return true;
          const resolved = path.isAbsolute(arg) ? arg : path.resolve(spec.cwd, arg);
          return resolved !== absolute;
        }),
      } : spec);
      assert.throws(
        () => requirePaths(shrunk),
        new RegExp(`required safety file was removed from ${suiteId}`),
      );
    }
  }
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
      suites: evidence.suites.map((suite, index) => index === 0 ? {
        ...suite,
        execution: { ...suite.execution, passed: 0, skipped: suite.execution.tests },
      } : suite),
    }, /reported|did not execute/],
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
