#!/usr/bin/env node
"use strict";

// Deterministic, fail-closed source gate for the Realtor Beta release lane.
// This runs before a Beta source receipt can be minted. The successful suite
// manifest is embedded into that immutable receipt, so build-mac cannot reuse
// a receipt that skipped or failed the source safety checks.

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const DESKTOP = path.resolve(__dirname, "..");
const REPO = path.resolve(DESKTOP, "..");
const BACKEND = path.join(REPO, "backend");
const CLI = path.join(REPO, "cli");
const WEB = path.join(CLI, "web");
const TERMINAL_UI = path.join(CLI, "ui-tui");
const DEFAULT_EVIDENCE_PATH = path.join(DESKTOP, "dist", "evidence", "beta-source-safety.json");

const BETA_SOURCE_SAFETY_SCHEMA_VERSION = 2;
const BETA_SOURCE_SAFETY_KIND = "elevate-beta-source-safety";
const MINIMUM_NODE = Object.freeze({ major: 22, minor: 12 });
const MIXED_CHANNEL_TEST_ENV = Object.freeze({
  ELEVATE_EXACT_BETA: "0",
  ELEVATE_RELEASE_CHANNEL: "stable",
});
const SAFE_PASSTHROUGH_ENV_KEYS = Object.freeze([
  "HOME",
  "LANG",
  "LC_ALL",
  "LC_CTYPE",
  "LOGNAME",
  "SHELL",
  "SYSTEM_VERSION_COMPAT",
  "TEMP",
  "TERM",
  "TMP",
  "TMPDIR",
  "USER",
  "XDG_CACHE_HOME",
  "XDG_CONFIG_HOME",
  "XDG_DATA_HOME",
]);
const REQUIRED_SUITE_IDS = Object.freeze([
  "python-session-safety",
  "python-tool-policy-core",
  "python-tool-policy-runtime",
  "python-document-coordination",
  "python-recovery-roll-forward",
  "backend-tests",
  "backend-deploy-static",
  "backend-production-build",
  "web-session-onboarding-forms",
  "web-production-build",
  "terminal-ui-session",
  "terminal-ui-types",
  "desktop-release-tests",
]);
const REQUIRED_FILES_BY_SUITE = Object.freeze({
  "python-session-safety": Object.freeze([
    "cli/tests/agent/test_realtor_beta_skill_surface.py",
    "cli/tests/agent/transports/test_hermes_tools_mcp_server.py",
    "cli/tests/elevate_cli/test_beta_oauth_containment.py",
    "cli/tests/elevate_cli/test_beta_pty_provider_repair_bridge.py",
    "cli/tests/elevate_cli/test_beta_status_receipt.py",
    "cli/tests/elevate_cli/test_channel_telegram_routes.py",
    "cli/tests/elevate_cli/test_gateway_launchd_reliability.py",
    "cli/tests/elevate_cli/test_beta_unregistered_runtime_disabled.py",
    "cli/tests/test_tui_gateway_server.py",
    "cli/tests/tui_gateway/test_beta_session_runtime_repair.py",
    "cli/tests/tools/test_delegate_partial.py",
  ]),
  "python-tool-policy-core": Object.freeze([
    "cli/tests/tools/test_agent_owned_registry_dispatch.py",
    "cli/tests/tools/test_todo_registry_dispatch.py",
    "cli/tests/tools/test_send_message_effects.py",
    "cli/tests/tools/test_composio_tool.py",
    "cli/tests/tools/test_manage_agent_tool.py",
    "cli/tests/tools/test_leads_overview_tool.py",
    "cli/tests/tools/test_working_state_tool.py",
    "cli/tests/hermes_cli/test_beta_agent_setup_memory_policy.py",
    "cli/tests/hermes_cli/test_beta_cli_provider_policy.py",
    "cli/tests/hermes_cli/test_beta_config_write_policy.py",
    "cli/tests/hermes_cli/test_beta_provider_policy.py",
    "cli/tests/tools/test_admin_deal_effects.py",
    "cli/tests/tools/test_lead_status_effects.py",
    "cli/tests/tools/test_outreach_templates_effects.py",
    "cli/tests/tools/test_discord_effects.py",
    "cli/tests/tools/test_elevate_db_effects.py",
    "cli/tests/tools/test_file_tools_effects.py",
    "cli/tests/tools/test_file_materialize.py",
    "cli/tests/tools/test_file_read_guards.py",
    "cli/tests/tools/test_effect_policy.py",
    "cli/tests/tools/test_workspace_effect_policy.py",
    "cli/tests/tools/test_workspace_severances.py",
    "cli/tests/tools/test_workspace_starved_declarations.py",
    "cli/tests/tools/test_workspace_board_writes_live.py",
    "cli/tests/tools/test_kanban_tools.py",
    "cli/tests/tools/test_skills_tool.py",
    "cli/tests/tools/test_memory_provider_registry_dispatch.py",
    "cli/tests/tools/test_context_engine_registry_dispatch.py",
    "cli/tests/tools/test_delegate_registry_dispatch.py",
    "cli/tests/tools/test_memory_tool_registry_dispatch.py",
    "cli/tests/tools/test_session_search_registry_dispatch.py",
    "cli/tests/tools/test_plugin_registry_dispatch.py",
    "cli/tests/tools/test_tool_effect_receipts_store.py",
    "cli/tests/tools/test_effect_broker.py",
    "cli/tests/tools/test_registry_effect_claims.py",
    "cli/tests/tools/test_dispatch_companion_liveness.py",
    "cli/tests/tools/test_terminal_transform_receipt_evidence.py",
    "cli/tests/run_agent/test_beta_memory_flush_policy.py",
    "cli/tests/agent/test_memory_write_metadata_wiring.py",
    "cli/tests/tools/test_policy_inheritance.py",
    "cli/tests/tools/test_delegate_policy_inheritance.py",
    "cli/tests/tools/test_policy_inheritance_boundaries.py",
    "cli/tests/tools/test_beta_enforcement_flip.py",
    "cli/tests/tools/test_beta_unrouted_lane_containment.py",
    "cli/tests/elevate_cli/test_beta_sender_containment.py",
    "cli/tests/run_agent/test_exact_beta_lane_dispatch_outcome.py",
  ]),
  "python-tool-policy-runtime": Object.freeze([
    "cli/tests/run_agent/test_run_agent.py",
  ]),
  "python-recovery-roll-forward": Object.freeze([
    "cli/tests/elevate_cli/test_exact_candidate_realtor_beta_gate.py",
  ]),
  "backend-tests": Object.freeze([
    "backend/test/deploy-health-verifier.test.ts",
    "backend/test/entitlement-assertion.test.ts",
    "backend/test/hosted-routes.test.ts",
  ]),
  "backend-deploy-static": Object.freeze([
    "backend/scripts/deploy.sh",
    "backend/scripts/verify-entitlement-health.ts",
    "backend/test/deploy-script-static.sh",
  ]),
  "web-session-onboarding-forms": Object.freeze([
    "cli/web/src/pages/agent-onboarding/__tests__/beta-memory-policy.test.ts",
    "cli/web/src/pages/agent-onboarding/__tests__/beta-provider-ui.test.ts",
    "cli/web/src/pages/agent-onboarding/__tests__/oauth-readiness.test.ts",
  ]),
  "desktop-release-tests": Object.freeze([
    "desktop/test/backend-runner.test.js",
    "desktop/test/beta-source-safety-gate.test.js",
    "desktop/test/candidate-receipt.test.js",
    "desktop/test/gateway-self-heal.test.js",
    "desktop/test/recovery-containment.test.js",
    "desktop/test/recovery-packaging.test.js",
    "desktop/test/rollback-realtor-beta.test.js",
  ]),
});

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}

function canonicalJson(value) {
  return JSON.stringify(canonicalize(value));
}

function relativeToRepo(absolutePath) {
  return path.relative(REPO, absolutePath).split(path.sep).join("/");
}

function currentNodeAtLeast(major, minor) {
  const [actualMajor = 0, actualMinor = 0] = process.versions.node
    .split(".")
    .map((part) => Number.parseInt(part, 10) || 0);
  return actualMajor > major || (actualMajor === major && actualMinor >= minor);
}

function npmCliPath({
  nodeExecutable = process.execPath,
  npmExecPath = process.env.npm_execpath,
} = {}) {
  const nodeRoot = path.resolve(path.dirname(nodeExecutable), "..");
  const candidates = [
    path.join(nodeRoot, "lib", "node_modules", "npm", "bin", "npm-cli.js"),
    path.join(nodeRoot, "libexec", "lib", "node_modules", "npm", "bin", "npm-cli.js"),
    npmExecPath ? path.resolve(npmExecPath) : null,
  ].filter(Boolean).filter((candidate, index, all) => all.indexOf(candidate) === index);
  const found = candidates.find(
    (candidate) => fs.statSync(candidate, { throwIfNoEntry: false })?.isFile(),
  );
  if (!found) {
    throw new Error("[beta-source-safety] npm CLI for the active Node runtime was not found");
  }
  return found;
}

function pythonPath() {
  return path.resolve(
    process.env.ELEVATE_RELEASE_PYTHON || path.join(CLI, ".venv", "bin", "python"),
  );
}

function pythonDescriptor() {
  const executable = pythonPath();
  const result = spawnSync(executable, ["--version"], {
    cwd: CLI,
    encoding: "utf8",
    timeout: 30_000,
  });
  if (result.status !== 0) {
    throw new Error(
      `[beta-source-safety] release Python is unavailable: ${(result.stderr || result.error?.message || "").trim()}`,
    );
  }
  return {
    path: relativeToRepo(executable),
    version: `${result.stdout || ""}${result.stderr || ""}`.trim(),
  };
}

function desktopTestFiles() {
  const testRoot = path.join(DESKTOP, "test");
  return fs.readdirSync(testRoot, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".test.js"))
    .map((entry) => path.join(testRoot, entry.name))
    .sort();
}

function backendTestFiles() {
  const testRoot = path.join(BACKEND, "test");
  return fs.readdirSync(testRoot, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".test.ts"))
    .map((entry) => path.join(testRoot, entry.name))
    .sort();
}

function buildSuiteSpecs({ python = pythonPath(), npmCli = npmCliPath() } = {}) {
  const npm = (...args) => ({
    command: process.execPath,
    displayCommand: "<active-node>",
    args: [npmCli, ...args],
  });
  const pytest = (expectedTests, ...args) => ({
    command: python,
    displayCommand: "<release-python>",
    args: ["-B", "-m", "pytest", "-q", "-o", "addopts=", "--color=no", ...args],
    resultContract: { kind: "pytest", minimum_tests: expectedTests, expected_tests: expectedTests },
  });
  const backendTests = backendTestFiles();
  const desktopTests = desktopTestFiles();

  return [
    {
      id: "python-session-safety",
      cwd: CLI,
      timeoutMs: 10 * 60_000,
      environment: MIXED_CHANNEL_TEST_ENV,
      requiredFiles: REQUIRED_FILES_BY_SUITE["python-session-safety"].map((relative) => path.join(REPO, relative)),
      ...pytest(
        429,
        "tests/agent/test_turn_fence.py",
        "tests/agent/test_realtor_beta_skill_surface.py",
        "tests/agent/transports/test_hermes_tools_mcp_server.py",
        "tests/elevate_cli/test_beta_oauth_containment.py",
        "tests/elevate_cli/test_beta_pty_provider_repair_bridge.py",
        "tests/elevate_cli/test_channel_telegram_routes.py",
        "tests/elevate_cli/test_gateway_launchd_reliability.py",
        "tests/elevate_cli/test_beta_status_receipt.py",
        "tests/elevate_cli/test_beta_unregistered_runtime_disabled.py",
        "tests/test_tui_gateway_server.py",
        "tests/tui_gateway/test_atomic_prompt_terminalization.py",
        "tests/tui_gateway/test_beta_session_runtime_repair.py",
        "tests/tui_gateway/test_resume_singleflight.py",
        "tests/tui_gateway/test_session_stop_adversarial.py",
        "tests/run_agent/test_concurrent_interrupt.py",
        "tests/run_agent/test_interrupt_propagation.py",
        "tests/run_agent/test_soft_interrupts.py",
        "tests/tools/test_delegate_partial.py",
      ),
    },
    {
      id: "python-tool-policy-core",
      cwd: CLI,
      timeoutMs: 10 * 60_000,
      environment: MIXED_CHANNEL_TEST_ENV,
      requiredFiles: REQUIRED_FILES_BY_SUITE["python-tool-policy-core"].map(
        (relative) => path.join(REPO, relative),
      ),
      ...pytest(
        1365,
        "tests/test_model_tools.py",
        "tests/tools/test_registry_shadow_execution.py",
        "tests/tools/test_terminal_approval_effect_receipts.py",
        "tests/tools/test_agent_owned_registry_dispatch.py",
        "tests/tools/test_todo_registry_dispatch.py",
        "tests/tools/test_send_message_effects.py",
        "tests/tools/test_composio_tool.py",
        "tests/tools/test_manage_agent_tool.py",
        "tests/tools/test_leads_overview_tool.py",
        "tests/tools/test_working_state_tool.py",
        "tests/agent/test_memory_provider.py",
        "tests/agent/test_tool_executor_beta_containment.py",
        "tests/cron/test_beta_execution_disabled.py",
        "tests/hermes_cli/test_beta_agent_setup_memory_policy.py",
        "tests/hermes_cli/test_beta_cli_provider_policy.py",
        "tests/hermes_cli/test_beta_config_write_policy.py",
        "tests/hermes_cli/test_beta_provider_policy.py",
        "tests/tools/test_admin_deal_effects.py",
        "tests/tools/test_lead_status_effects.py",
        "tests/tools/test_outreach_templates_effects.py",
        "tests/tools/test_discord_effects.py",
        "tests/tools/test_elevate_db_effects.py",
        "tests/tools/test_file_tools_effects.py",
        "tests/tools/test_file_materialize.py",
        "tests/tools/test_file_read_guards.py",
        "tests/tools/test_effect_policy.py",
        "tests/tools/test_workspace_effect_policy.py",
        "tests/tools/test_workspace_severances.py",
        "tests/tools/test_workspace_starved_declarations.py",
        "tests/tools/test_workspace_board_writes_live.py",
        "tests/tools/test_kanban_tools.py",
        "tests/tools/test_skills_tool.py",
        "tests/tools/test_memory_provider_registry_dispatch.py",
        "tests/tools/test_context_engine_registry_dispatch.py",
        "tests/tools/test_delegate_registry_dispatch.py",
        "tests/tools/test_memory_tool_registry_dispatch.py",
        "tests/tools/test_session_search_registry_dispatch.py",
        "tests/tools/test_plugin_registry_dispatch.py",
        "tests/tools/test_tool_effect_receipts_store.py",
        "tests/tools/test_effect_broker.py",
        "tests/tools/test_registry_effect_claims.py",
        "tests/tools/test_dispatch_companion_liveness.py",
        "tests/tools/test_terminal_transform_receipt_evidence.py",
        "tests/run_agent/test_beta_memory_flush_policy.py",
        "tests/agent/test_memory_write_metadata_wiring.py",
        "tests/tools/test_policy_inheritance.py",
        "tests/tools/test_delegate_policy_inheritance.py",
        "tests/tools/test_policy_inheritance_boundaries.py",
        "tests/tools/test_beta_enforcement_flip.py",
        "tests/tools/test_beta_unrouted_lane_containment.py",
        "tests/elevate_cli/test_beta_sender_containment.py",
        "tests/run_agent/test_exact_beta_lane_dispatch_outcome.py",
      ),
    },
    {
      id: "python-tool-policy-runtime",
      cwd: CLI,
      timeoutMs: 10 * 60_000,
      environment: MIXED_CHANNEL_TEST_ENV,
      requiredFiles: REQUIRED_FILES_BY_SUITE["python-tool-policy-runtime"].map(
        (relative) => path.join(REPO, relative),
      ),
      ...pytest(
        9,
        "tests/run_agent/test_run_agent.py::TestConcurrentToolExecution::test_exact_beta_direct_agent_tools_fail_before_every_handler[todo]",
        "tests/run_agent/test_run_agent.py::TestConcurrentToolExecution::test_exact_beta_direct_agent_tools_fail_before_every_handler[session-search]",
        "tests/run_agent/test_run_agent.py::TestConcurrentToolExecution::test_exact_beta_direct_agent_tools_fail_before_every_handler[delegate-task]",
        "tests/run_agent/test_run_agent.py::TestConcurrentToolExecution::test_exact_beta_agent_dispatch_skips_hooks_when_start_turns_stale",
        "tests/run_agent/test_run_agent.py::TestConcurrentToolExecution::test_exact_beta_sequential_agent_branches_have_zero_side_effects[todo]",
        "tests/run_agent/test_run_agent.py::TestConcurrentToolExecution::test_exact_beta_sequential_agent_branches_have_zero_side_effects[session-search]",
        "tests/run_agent/test_run_agent.py::TestConcurrentToolExecution::test_exact_beta_sequential_agent_branches_have_zero_side_effects[delegate-task]",
        "tests/run_agent/test_run_agent.py::TestRunConversation::test_nonterminal_tool_call_fails_without_execution[None]",
        "tests/run_agent/test_run_agent.py::TestRunConversation::test_nonterminal_tool_call_fails_without_execution[future_reason]",
      ),
    },
    {
      id: "python-document-coordination",
      cwd: CLI,
      timeoutMs: 10 * 60_000,
      environment: MIXED_CHANNEL_TEST_ENV,
      ...pytest(
        64,
        "tests/elevate_cli/test_admin_dispatch_endpoints.py",
        "tests/elevate_cli/test_beta_province_pack.py",
      ),
    },
    {
      id: "python-recovery-roll-forward",
      cwd: CLI,
      timeoutMs: 10 * 60_000,
      environment: MIXED_CHANNEL_TEST_ENV,
      requiredFiles: REQUIRED_FILES_BY_SUITE["python-recovery-roll-forward"].map(
        (relative) => path.join(REPO, relative),
      ),
      ...pytest(
        8,
        "tests/elevate_cli/test_exact_candidate_realtor_beta_gate.py",
      ),
    },
    {
      id: "backend-tests",
      cwd: BACKEND,
      timeoutMs: 10 * 60_000,
      requiredFiles: REQUIRED_FILES_BY_SUITE["backend-tests"].map((relative) => path.join(REPO, relative)),
      command: process.execPath,
      displayCommand: "<active-node>",
      args: ["--import", "tsx", "--test", "--test-reporter=tap", ...backendTests],
      resultContract: { kind: "node-test", minimum_tests: 187, expected_tests: 187 },
    },
    {
      id: "backend-deploy-static",
      cwd: BACKEND,
      timeoutMs: 2 * 60_000,
      requiredFiles: REQUIRED_FILES_BY_SUITE["backend-deploy-static"].map((relative) => path.join(REPO, relative)),
      command: "/bin/bash",
      displayCommand: "/bin/bash",
      args: ["test/deploy-script-static.sh"],
      resultContract: { kind: "command", minimum_commands: 1 },
    },
    {
      id: "backend-production-build",
      cwd: BACKEND,
      timeoutMs: 10 * 60_000,
      resultContract: { kind: "command", minimum_commands: 1 },
      ...npm("run", "build"),
    },
    {
      id: "web-session-onboarding-forms",
      cwd: WEB,
      timeoutMs: 10 * 60_000,
      requiredFiles: REQUIRED_FILES_BY_SUITE["web-session-onboarding-forms"].map(
        (relative) => path.join(REPO, relative),
      ),
      ...npm(
        "test",
        "--",
        "--reporter=default",
        "src/pages/__tests__/ChatPage.activityDigest.test.ts",
        "src/pages/__tests__/ChatPage.artifactPreviewSafety.test.ts",
        "src/pages/__tests__/ChatPage.blockingPrompts.test.ts",
        "src/pages/__tests__/ChatPage.queue.test.ts",
        "src/pages/agent-onboarding/__tests__/beta-memory-policy.test.ts",
        "src/pages/agent-onboarding/__tests__/beta-provider-ui.test.ts",
        "src/pages/agent-onboarding/__tests__/oauth-readiness.test.ts",
        "src/pages/agent-onboarding/__tests__/onboarding-exit.test.ts",
        "src/pages/agent-onboarding/__tests__/onboarding-ui-recovery.test.ts",
        "src/pages/real-estate-hub/admin/__tests__/admin-onboarding-behavior.test.ts",
        "src/pages/real-estate-hub/admin/__tests__/admin-ui-recovery.test.ts",
        "src/pages/real-estate-hub/admin/__tests__/forms-provider-option-b.test.ts",
      ),
      resultContract: { kind: "vitest", minimum_tests: 142, expected_tests: 142 },
    },
    {
      id: "web-production-build",
      cwd: WEB,
      timeoutMs: 10 * 60_000,
      resultContract: { kind: "command", minimum_commands: 1 },
      ...npm("run", "build"),
    },
    {
      id: "terminal-ui-session",
      cwd: TERMINAL_UI,
      timeoutMs: 10 * 60_000,
      requiredFiles: [path.join(TERMINAL_UI, "src", "__tests__", "turnController.stop.test.ts")],
      ...npm("test", "--", "--reporter=default"),
      resultContract: { kind: "vitest", minimum_tests: 296, expected_tests: 296 },
    },
    {
      id: "terminal-ui-types",
      cwd: TERMINAL_UI,
      timeoutMs: 10 * 60_000,
      resultContract: { kind: "command", minimum_commands: 1 },
      ...npm("run", "type-check"),
    },
    {
      id: "desktop-release-tests",
      cwd: DESKTOP,
      timeoutMs: 10 * 60_000,
      environment: MIXED_CHANNEL_TEST_ENV,
      requiredFiles: REQUIRED_FILES_BY_SUITE["desktop-release-tests"].map((relative) => path.join(REPO, relative)),
      command: process.execPath,
      displayCommand: "<active-node>",
      args: ["--test", "--test-reporter=tap", ...desktopTests],
      resultContract: { kind: "node-test", minimum_tests: 506, expected_tests: 506 },
    },
  ];
}

function requiredSuiteFiles(spec) {
  const explicit = spec.requiredFiles || [];
  const fromArgs = spec.args
    .filter((arg) => typeof arg === "string" && /\.(?:py|[cm]?js|tsx?)$/.test(arg))
    .map((arg) => (path.isAbsolute(arg) ? arg : path.resolve(spec.cwd, arg)))
    .filter((absolute) => absolute === REPO || absolute.startsWith(`${REPO}${path.sep}`));
  return [...new Set([...explicit, ...fromArgs])].sort();
}

function suiteManifest(specs = buildSuiteSpecs()) {
  return specs.map((spec) => ({
    id: spec.id,
    cwd: relativeToRepo(spec.cwd),
    command: spec.displayCommand,
    args: spec.args.map((arg) => {
      if (arg === process.env.npm_execpath || arg === npmCliPath()) return "<active-npm-cli>";
      if (path.isAbsolute(arg) && arg.startsWith(REPO)) return relativeToRepo(arg);
      return arg;
    }),
    environment: spec.environment || {},
    required_files: requiredSuiteFiles(spec).map(relativeToRepo),
    result_contract: spec.resultContract,
    timeout_ms: spec.timeoutMs,
  }));
}

function suiteManifestId(manifest = suiteManifest()) {
  return sha256(canonicalJson(manifest));
}

function requirePaths(specs) {
  for (const required of [pythonPath(), BACKEND, WEB, TERMINAL_UI, path.join(DESKTOP, "test")]) {
    if (!fs.existsSync(required)) {
      throw new Error(`[beta-source-safety] required path is missing: ${required}`);
    }
  }
  if (!specs.length || specs.map((suite) => suite.id).join("\0") !== REQUIRED_SUITE_IDS.join("\0")) {
    throw new Error("[beta-source-safety] required suite manifest is incomplete or reordered");
  }
  for (const [suiteId, requiredFiles] of Object.entries(REQUIRED_FILES_BY_SUITE)) {
    const spec = specs.find((candidate) => candidate.id === suiteId);
    const actual = new Set(requiredSuiteFiles(spec).map(relativeToRepo));
    for (const required of requiredFiles) {
      if (!actual.has(required)) {
        throw new Error(
          `[beta-source-safety] required safety file was removed from ${suiteId}: ${required}`,
        );
      }
    }
  }
  for (const spec of specs) {
    for (const required of requiredSuiteFiles(spec)) {
      if (!fs.statSync(required, { throwIfNoEntry: false })?.isFile()) {
        throw new Error(`[beta-source-safety] required safety test is missing: ${required}`);
      }
    }
  }
  if (!currentNodeAtLeast(MINIMUM_NODE.major, MINIMUM_NODE.minor)) {
    throw new Error(
      `[beta-source-safety] Node ${MINIMUM_NODE.major}.${MINIMUM_NODE.minor}+ is required; found ${process.version}`,
    );
  }
}

function gitOutput(args) {
  const result = spawnSync("git", args, {
    cwd: REPO,
    encoding: "utf8",
    timeout: 30_000,
  });
  if (result.status !== 0) {
    throw new Error(`[beta-source-safety] git ${args.join(" ")} failed: ${(result.stderr || "").trim()}`);
  }
  return (result.stdout || "").trim();
}

function gitState() {
  const status = gitOutput(["status", "--porcelain=v1", "--untracked-files=all"]);
  return {
    commit: gitOutput(["rev-parse", "HEAD"]),
    branch: gitOutput(["branch", "--show-current"]),
    clean: status === "",
    status_sha256: sha256(status),
  };
}

function sanitizedEnvironment({ environment = process.env } = {}) {
  const env = Object.fromEntries(
    SAFE_PASSTHROUGH_ENV_KEYS
      .filter((key) => typeof environment[key] === "string" && environment[key] !== "")
      .map((key) => [key, environment[key]]),
  );
  Object.assign(env, {
    ELEVATE_RELEASE_CHANNEL: "beta",
    ELEVATE_EXACT_BETA: "1",
    NEXT_TELEMETRY_DISABLED: "1",
    NO_COLOR: "1",
    PATH: [
      path.dirname(process.execPath),
      "/opt/homebrew/bin",
      "/usr/local/bin",
      "/usr/bin",
      "/bin",
      "/usr/sbin",
      "/sbin",
    ]
      .filter((entry, index, entries) => entry && entries.indexOf(entry) === index)
      .join(path.delimiter),
    PYTHONDONTWRITEBYTECODE: "1",
    PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1",
  });
  return env;
}

function outputTail(text, lineCount = 40) {
  return String(text || "").split("\n").slice(-lineCount).join("\n").trim();
}

function stripAnsi(value) {
  return String(value || "").replaceAll(/\u001b\[[0-?]*[ -/]*[@-~]/g, "");
}

function lastIntegerMatch(text, pattern, fallback = null) {
  const matches = [...text.matchAll(pattern)];
  if (!matches.length) return fallback;
  return Number.parseInt(matches.at(-1)[1], 10);
}

function assertPositiveInteger(value, label) {
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`[beta-source-safety] ${label} did not execute a positive test count`);
  }
  return value;
}

function validateSuiteExecutionRecord(execution, contract) {
  if (!execution || execution.kind !== contract?.kind) {
    throw new Error("[beta-source-safety] suite execution evidence does not match its contract");
  }
  if (contract.kind === "command") {
    const commands = Number(execution.commands_executed || 0);
    if (!Number.isSafeInteger(commands) || commands < Number(contract.minimum_commands || 1)) {
      throw new Error("[beta-source-safety] command suite did not complete its required command");
    }
    return execution;
  }
  assertPositiveInteger(execution.tests, contract.kind);
  const minimum = Number(contract.minimum_tests || 1);
  if (!Number.isSafeInteger(minimum) || minimum <= 0 || execution.tests < minimum) {
    throw new Error(
      `[beta-source-safety] ${contract.kind} executed ${execution.tests} tests; expected at least ${minimum}`,
    );
  }
  if (contract.expected_tests != null && execution.tests !== contract.expected_tests) {
    throw new Error(
      `[beta-source-safety] ${contract.kind} executed ${execution.tests} tests; expected exactly ${contract.expected_tests}`,
    );
  }
  const nonPassing = ["failed", "errors", "cancelled", "skipped", "todo", "deselected", "xfailed", "xpassed"];
  for (const field of nonPassing) {
    const value = Number(execution[field] || 0);
    if (!Number.isSafeInteger(value) || value !== 0) {
      throw new Error(`[beta-source-safety] ${contract.kind} reported ${execution[field]} ${field}`);
    }
  }
  if (execution.collected_only !== false || execution.passed !== execution.tests) {
    throw new Error(`[beta-source-safety] ${contract.kind} did not execute every selected test`);
  }
  if (contract.kind === "vitest"
      && (!Number.isSafeInteger(execution.test_files) || execution.test_files <= 0
        || execution.test_files_passed !== execution.test_files)) {
    throw new Error("[beta-source-safety] Vitest did not execute every selected test file");
  }
  return execution;
}

function analyzeSuiteExecution(contract, stdout, stderr, processPassed) {
  if (!contract || typeof contract !== "object") {
    throw new Error("[beta-source-safety] suite result contract is missing");
  }
  const text = stripAnsi(`${stdout || ""}\n${stderr || ""}`);
  if (contract.kind === "command") {
    const commands = processPassed ? 1 : 0;
    if (commands < Number(contract.minimum_commands || 1)) {
      throw new Error("[beta-source-safety] command suite did not complete its required command");
    }
    return validateSuiteExecutionRecord(
      { kind: "command", commands_executed: commands },
      contract,
    );
  }

  let execution;
  if (contract.kind === "node-test") {
    const value = (name) => lastIntegerMatch(
      text,
      new RegExp(`^# ${name} (\\d+)\\s*$`, "gm"),
      name === "tests" ? null : 0,
    );
    execution = {
      kind: "node-test",
      tests: value("tests"),
      passed: value("pass"),
      failed: value("fail"),
      cancelled: value("cancelled"),
      skipped: value("skipped"),
      todo: value("todo"),
      deselected: 0,
      collected_only: false,
    };
  } else if (contract.kind === "pytest") {
    const summaries = text.split("\n").filter((line) => /\b(?:passed|failed|skipped|deselected|xfailed|xpassed|errors?)\b/.test(line));
    const summary = summaries.at(-1) || "";
    const count = (name) => Number.parseInt(summary.match(new RegExp(`(\\d+) ${name}\\b`))?.[1] || "0", 10);
    const passed = count("passed");
    const failed = count("failed");
    const skipped = count("skipped");
    const deselected = count("deselected");
    const xfailed = count("xfailed");
    const xpassed = count("xpassed");
    const errors = count("errors?");
    execution = {
      kind: "pytest",
      tests: passed + failed + skipped + xfailed + xpassed + errors,
      passed,
      failed,
      errors,
      skipped,
      deselected,
      xfailed,
      xpassed,
      collected_only: /\b(?:tests?|items?) collected(?: in|$)/m.test(text) && passed === 0,
    };
  } else if (contract.kind === "vitest") {
    const testLine = text.split("\n").filter((line) => /^\s*Tests\s+/.test(line)).at(-1) || "";
    const fileLine = text.split("\n").filter((line) => /^\s*Test Files\s+/.test(line)).at(-1) || "";
    const count = (line, name) => Number.parseInt(line.match(new RegExp(`(\\d+) ${name}\\b`))?.[1] || "0", 10);
    const total = Number.parseInt(testLine.match(/\((\d+)\)\s*$/)?.[1] || "0", 10);
    const fileTotal = Number.parseInt(fileLine.match(/\((\d+)\)\s*$/)?.[1] || "0", 10);
    execution = {
      kind: "vitest",
      tests: total,
      passed: count(testLine, "passed"),
      failed: count(testLine, "failed"),
      skipped: count(testLine, "skipped"),
      todo: count(testLine, "todo"),
      deselected: 0,
      collected_only: false,
      test_files: fileTotal,
      test_files_passed: count(fileLine, "passed"),
    };
  } else {
    throw new Error(`[beta-source-safety] unsupported suite result contract: ${contract.kind}`);
  }

  return validateSuiteExecutionRecord(execution, contract);
}

function runSuite(spec, env) {
  const started = Date.now();
  console.log(`[beta-source-safety] RUN ${spec.id}`);
  const result = spawnSync(spec.command, spec.args, {
    cwd: spec.cwd,
    env: { ...env, ...(spec.environment || {}) },
    encoding: "utf8",
    timeout: spec.timeoutMs,
    maxBuffer: 50 * 1024 * 1024,
  });
  const stdout = result.stdout || "";
  const stderr = result.stderr || "";
  const processPassed = result.status === 0 && !result.error;
  let execution = null;
  let executionError = null;
  try {
    execution = analyzeSuiteExecution(spec.resultContract, stdout, stderr, processPassed);
  } catch (error) {
    executionError = error;
  }
  const passed = processPassed && !executionError;
  const evidence = {
    id: spec.id,
    passed,
    status: Number.isInteger(result.status) ? result.status : null,
    signal: result.signal || null,
    duration_ms: Date.now() - started,
    execution,
    output_sha256: sha256(`${stdout}\0${stderr}`),
  };
  console.log(`[beta-source-safety] ${passed ? "PASS" : "FAIL"} ${spec.id} (${evidence.duration_ms}ms)`);
  if (!passed) {
    const tail = outputTail(`${stdout}\n${stderr}`);
    if (tail) console.error(tail);
    if (result.error) console.error(result.error.message || String(result.error));
    if (executionError) console.error(executionError.message || String(executionError));
  }
  return evidence;
}

function writeAtomicJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const temp = `${filePath}.tmp-${process.pid}-${crypto.randomUUID()}`;
  fs.writeFileSync(temp, `${JSON.stringify(canonicalize(value), null, 2)}\n`, { flag: "wx" });
  fs.renameSync(temp, filePath);
}

function validateBetaSourceSafetyEvidence(evidence, {
  expectedGit,
  requireClean = true,
  expectedManifestId = suiteManifestId(),
} = {}) {
  if (!evidence || typeof evidence !== "object") {
    throw new Error("[beta-source-safety] missing source safety evidence");
  }
  if (
    evidence.schema_version !== BETA_SOURCE_SAFETY_SCHEMA_VERSION
    || evidence.kind !== BETA_SOURCE_SAFETY_KIND
    || evidence.channel !== "beta"
  ) {
    throw new Error("[beta-source-safety] unsupported source safety evidence");
  }
  if (evidence.manifest_id !== expectedManifestId) {
    throw new Error("[beta-source-safety] source safety suite manifest drift");
  }
  if (!Array.isArray(evidence.manifest) || suiteManifestId(evidence.manifest) !== evidence.manifest_id) {
    throw new Error("[beta-source-safety] source safety evidence manifest does not match its ID");
  }
  if (evidence.node !== process.version || !currentNodeAtLeast(MINIMUM_NODE.major, MINIMUM_NODE.minor)) {
    throw new Error("[beta-source-safety] source safety Node runtime drift");
  }
  const python = pythonDescriptor();
  if (evidence.python !== python.path || evidence.python_version !== python.version) {
    throw new Error("[beta-source-safety] source safety Python runtime drift");
  }
  if (!evidence.passed || !Array.isArray(evidence.suites)) {
    throw new Error("[beta-source-safety] source safety suites did not pass");
  }
  if (evidence.checkout_stable !== true) {
    throw new Error("[beta-source-safety] checkout changed during source safety execution");
  }
  const startedAt = Date.parse(evidence.started_at);
  const completedAt = Date.parse(evidence.completed_at);
  if (!Number.isFinite(startedAt) || !Number.isFinite(completedAt) || completedAt < startedAt) {
    throw new Error("[beta-source-safety] source safety evidence timestamps are invalid");
  }
  const ids = evidence.suites.map((suite) => suite?.id);
  if (ids.join("\0") !== REQUIRED_SUITE_IDS.join("\0")) {
    throw new Error("[beta-source-safety] source safety suite evidence is incomplete or reordered");
  }
  for (let index = 0; index < evidence.suites.length; index += 1) {
    const suite = evidence.suites[index];
    if (!suite.passed
        || suite.status !== 0
        || suite.signal != null
        || !Number.isInteger(suite.duration_ms)
        || suite.duration_ms < 0
        || !/^[a-f0-9]{64}$/.test(suite.output_sha256 || "")) {
      throw new Error("[beta-source-safety] source safety evidence contains a failed suite");
    }
    validateSuiteExecutionRecord(suite.execution, evidence.manifest[index].result_contract);
  }
  if (!evidence.git || (requireClean && evidence.git.clean !== true)) {
    throw new Error("[beta-source-safety] source safety evidence was not produced from a clean checkout");
  }
  if (requireClean && evidence.git.status_sha256 !== sha256("")) {
    throw new Error("[beta-source-safety] clean source safety status digest is invalid");
  }
  if (expectedGit && (
    evidence.git.commit !== expectedGit.commit
    || evidence.git.branch !== expectedGit.branch
    || evidence.git.clean !== expectedGit.clean
  )) {
    throw new Error("[beta-source-safety] source safety checkout drift");
  }
  return evidence;
}

function runGate({
  evidencePath = path.resolve(process.env.ELEVATE_BETA_SOURCE_EVIDENCE || DEFAULT_EVIDENCE_PATH),
  now = () => new Date().toISOString(),
} = {}) {
  const specs = buildSuiteSpecs();
  requirePaths(specs);
  const manifest = suiteManifest(specs);
  const python = pythonDescriptor();
  const before = gitState();
  const startedAt = now();
  const suites = [];
  const env = sanitizedEnvironment();

  for (const spec of specs) {
    const result = runSuite(spec, env);
    suites.push(result);
    if (!result.passed) break;
  }

  const after = gitState();
  const complete = suites.length === specs.length && suites.every((suite) => suite.passed);
  const checkoutStable = canonicalJson(before) === canonicalJson(after);
  const evidence = {
    schema_version: BETA_SOURCE_SAFETY_SCHEMA_VERSION,
    kind: BETA_SOURCE_SAFETY_KIND,
    channel: "beta",
    started_at: startedAt,
    completed_at: now(),
    node: process.version,
    python: python.path,
    python_version: python.version,
    manifest,
    manifest_id: suiteManifestId(manifest),
    git: after,
    checkout_stable: checkoutStable,
    passed: complete && checkoutStable,
    suites,
  };
  writeAtomicJson(evidencePath, evidence);

  if (!checkoutStable) {
    throw new Error("[beta-source-safety] checkout changed while the safety suites were running");
  }
  if (!complete) {
    throw new Error("[beta-source-safety] one or more required suites failed");
  }
  console.log(`[beta-source-safety] evidence ${evidencePath}`);
  console.log(`[beta-source-safety] manifest ${evidence.manifest_id}`);
  return evidence;
}

function main() {
  try {
    runGate();
  } catch (error) {
    console.error(error?.message || String(error));
    process.exitCode = 1;
  }
}

if (require.main === module) main();

module.exports = {
  BETA_SOURCE_SAFETY_KIND,
  BETA_SOURCE_SAFETY_SCHEMA_VERSION,
  DEFAULT_EVIDENCE_PATH,
  MINIMUM_NODE,
  REQUIRED_FILES_BY_SUITE,
  REQUIRED_SUITE_IDS,
  SAFE_PASSTHROUGH_ENV_KEYS,
  analyzeSuiteExecution,
  backendTestFiles,
  buildSuiteSpecs,
  canonicalJson,
  currentNodeAtLeast,
  npmCliPath,
  pythonDescriptor,
  requirePaths,
  runGate,
  runSuite,
  sanitizedEnvironment,
  suiteManifest,
  suiteManifestId,
  validateSuiteExecutionRecord,
  validateBetaSourceSafetyEvidence,
};
