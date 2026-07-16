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
const CLI = path.join(REPO, "cli");
const WEB = path.join(CLI, "web");
const TERMINAL_UI = path.join(CLI, "ui-tui");
const DEFAULT_EVIDENCE_PATH = path.join(DESKTOP, "dist", "evidence", "beta-source-safety.json");

const BETA_SOURCE_SAFETY_SCHEMA_VERSION = 1;
const BETA_SOURCE_SAFETY_KIND = "elevate-beta-source-safety";
const MINIMUM_NODE = Object.freeze({ major: 22, minor: 12 });
const MIXED_CHANNEL_TEST_ENV = Object.freeze({
  ELEVATE_EXACT_BETA: "0",
  ELEVATE_RELEASE_CHANNEL: "stable",
});
const REQUIRED_SUITE_IDS = Object.freeze([
  "python-session-safety",
  "python-tool-policy-core",
  "python-tool-policy-runtime",
  "python-document-coordination",
  "web-session-onboarding-forms",
  "web-production-build",
  "terminal-ui-session",
  "terminal-ui-types",
  "desktop-release-tests",
]);

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

function npmCliPath() {
  const candidates = [
    process.env.npm_execpath,
    path.resolve(path.dirname(process.execPath), "..", "lib", "node_modules", "npm", "bin", "npm-cli.js"),
  ].filter(Boolean);
  const found = candidates.find((candidate) => fs.existsSync(candidate));
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

function buildSuiteSpecs({ python = pythonPath(), npmCli = npmCliPath() } = {}) {
  const npm = (...args) => ({
    command: process.execPath,
    displayCommand: "<active-node>",
    args: [npmCli, ...args],
  });
  const pytest = (...args) => ({
    command: python,
    displayCommand: "<release-python>",
    args: ["-B", "-m", "pytest", "-q", ...args],
  });
  const desktopTests = desktopTestFiles();

  return [
    {
      id: "python-session-safety",
      cwd: CLI,
      timeoutMs: 10 * 60_000,
      environment: MIXED_CHANNEL_TEST_ENV,
      ...pytest(
        "tests/agent/test_turn_fence.py",
        "tests/test_tui_gateway_server.py",
        "tests/tui_gateway/test_atomic_prompt_terminalization.py",
        "tests/tui_gateway/test_resume_singleflight.py",
        "tests/tui_gateway/test_session_stop_adversarial.py",
        "tests/run_agent/test_concurrent_interrupt.py",
        "tests/run_agent/test_interrupt_propagation.py",
        "tests/run_agent/test_soft_interrupts.py",
      ),
    },
    {
      id: "python-tool-policy-core",
      cwd: CLI,
      timeoutMs: 10 * 60_000,
      environment: MIXED_CHANNEL_TEST_ENV,
      ...pytest(
        "tests/test_model_tools.py",
        "tests/tools/test_registry_shadow_execution.py",
        "tests/tools/test_terminal_approval_effect_receipts.py",
        "tests/agent/test_memory_provider.py",
        "tests/agent/test_tool_executor_beta_containment.py",
        "tests/cron/test_beta_execution_disabled.py",
      ),
    },
    {
      id: "python-tool-policy-runtime",
      cwd: CLI,
      timeoutMs: 10 * 60_000,
      environment: MIXED_CHANNEL_TEST_ENV,
      ...pytest(
        "tests/run_agent/test_run_agent.py",
        "-k",
        "exact_beta or nonterminal_tool_call or tool_definition_cache or disabled_toolsets",
      ),
    },
    {
      id: "python-document-coordination",
      cwd: CLI,
      timeoutMs: 10 * 60_000,
      environment: MIXED_CHANNEL_TEST_ENV,
      ...pytest(
        "tests/elevate_cli/test_admin_dispatch_endpoints.py",
        "tests/elevate_cli/test_beta_province_pack.py",
      ),
    },
    {
      id: "web-session-onboarding-forms",
      cwd: WEB,
      timeoutMs: 10 * 60_000,
      ...npm(
        "test",
        "--",
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
    },
    {
      id: "web-production-build",
      cwd: WEB,
      timeoutMs: 10 * 60_000,
      ...npm("run", "build"),
    },
    {
      id: "terminal-ui-session",
      cwd: TERMINAL_UI,
      timeoutMs: 10 * 60_000,
      requiredFiles: [path.join(TERMINAL_UI, "src", "__tests__", "turnController.stop.test.ts")],
      ...npm("test"),
    },
    {
      id: "terminal-ui-types",
      cwd: TERMINAL_UI,
      timeoutMs: 10 * 60_000,
      ...npm("run", "type-check"),
    },
    {
      id: "desktop-release-tests",
      cwd: DESKTOP,
      timeoutMs: 10 * 60_000,
      environment: MIXED_CHANNEL_TEST_ENV,
      command: process.execPath,
      displayCommand: "<active-node>",
      args: ["--test", ...desktopTests],
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
    timeout_ms: spec.timeoutMs,
  }));
}

function suiteManifestId(manifest = suiteManifest()) {
  return sha256(canonicalJson(manifest));
}

function requirePaths(specs) {
  for (const required of [pythonPath(), WEB, TERMINAL_UI, path.join(DESKTOP, "test")]) {
    if (!fs.existsSync(required)) {
      throw new Error(`[beta-source-safety] required path is missing: ${required}`);
    }
  }
  if (!specs.length || specs.map((suite) => suite.id).join("\0") !== REQUIRED_SUITE_IDS.join("\0")) {
    throw new Error("[beta-source-safety] required suite manifest is incomplete or reordered");
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

function sanitizedEnvironment() {
  const env = {
    ...process.env,
    ELEVATE_RELEASE_CHANNEL: "beta",
    ELEVATE_EXACT_BETA: "1",
    NO_COLOR: "1",
    PATH: [path.dirname(process.execPath), process.env.PATH || ""]
      .filter(Boolean)
      .join(path.delimiter),
    PYTHONDONTWRITEBYTECODE: "1",
  };
  for (const key of Object.keys(env)) {
    if (/(_API_KEY|_TOKEN|_SECRET|_PASSWORD)$/.test(key)) delete env[key];
  }
  return env;
}

function outputTail(text, lineCount = 40) {
  return String(text || "").split("\n").slice(-lineCount).join("\n").trim();
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
  const passed = result.status === 0 && !result.error;
  const evidence = {
    id: spec.id,
    passed,
    status: Number.isInteger(result.status) ? result.status : null,
    signal: result.signal || null,
    duration_ms: Date.now() - started,
    output_sha256: sha256(`${stdout}\0${stderr}`),
  };
  console.log(`[beta-source-safety] ${passed ? "PASS" : "FAIL"} ${spec.id} (${evidence.duration_ms}ms)`);
  if (!passed) {
    const tail = outputTail(`${stdout}\n${stderr}`);
    if (tail) console.error(tail);
    if (result.error) console.error(result.error.message || String(result.error));
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
  if (evidence.suites.some((suite) => (
    !suite.passed
    || suite.status !== 0
    || !Number.isInteger(suite.duration_ms)
    || suite.duration_ms < 0
    || !/^[a-f0-9]{64}$/.test(suite.output_sha256 || "")
  ))) {
    throw new Error("[beta-source-safety] source safety evidence contains a failed suite");
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
  REQUIRED_SUITE_IDS,
  buildSuiteSpecs,
  canonicalJson,
  currentNodeAtLeast,
  pythonDescriptor,
  runGate,
  sanitizedEnvironment,
  suiteManifest,
  suiteManifestId,
  validateBetaSourceSafetyEvidence,
};
