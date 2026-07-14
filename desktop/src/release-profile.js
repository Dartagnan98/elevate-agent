"use strict";

const path = require("node:path");

const STABLE = Object.freeze({
  channel: "latest",
  isBeta: false,
  productName: "Elevate",
  appBundleName: "Elevate.app",
  appId: "com.elevationrealestate.elevate",
  packageName: "@elevationrealestate/elevate-desktop",
  artifactPrefix: "Elevate",
  downloadAliasPrefix: "Elevate-latest",
  downloadAliasPrefixes: Object.freeze(["Elevate-latest"]),
  protocolScheme: "elevate",
  elevateHomeName: ".elevate",
  workspaceName: "Elevation",
  preferredPort: 9119,
  gatewayLabel: "ai.elevate.gateway",
});

const BETA = Object.freeze({
  channel: "beta",
  isBeta: true,
  productName: "Elevate Beta",
  appBundleName: "Elevate Beta.app",
  appId: "com.elevationrealestate.elevate.beta",
  packageName: "elevate-beta-desktop",
  artifactPrefix: "Elevate-Beta",
  downloadAliasPrefix: "Elevate-Beta",
  downloadAliasPrefixes: Object.freeze(["Elevate-Beta", "Elevate-beta"]),
  protocolScheme: "elevate-beta",
  elevateHomeName: ".elevate-beta",
  workspaceName: "Elevation Beta",
  preferredPort: 9139,
  gatewayLabel: "ai.elevate.gateway-beta",
  providerPolicyVersion: "realtor-beta-codex-v1",
  allowedModelsVersion: "2026-07-14-v1",
  allowedProvider: "openai-codex",
  allowedModels: Object.freeze([
    "gpt-5.5",
    "gpt-5.4-mini",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
  ]),
});

function resolveReleaseProfile(channel) {
  return String(channel || "").trim().toLowerCase() === "beta" ? BETA : STABLE;
}

function artifactFileName(profile, version, architecture, extension) {
  return `${profile.artifactPrefix}-${version}-mac-${architecture}.${extension}`;
}

function releaseArtifactNames(profile, version) {
  return ["x64", "arm64"].flatMap((architecture) => [
    artifactFileName(profile, version, architecture, "zip"),
    artifactFileName(profile, version, architecture, "dmg"),
  ]);
}

function downloadAliasFileName(profile, architecture) {
  return `${profile.downloadAliasPrefix}-mac-${architecture}.dmg`;
}

function downloadAliasFileNames(profile, architecture) {
  return (profile.downloadAliasPrefixes || [profile.downloadAliasPrefix])
    .map((prefix) => `${prefix}-mac-${architecture}.dmg`);
}

function resolveRuntimePaths({ profile, home, env = {} }) {
  const elevateHome = profile.isBeta
    ? path.join(home, profile.elevateHomeName)
    : path.resolve(env.ELEVATE_HOME || path.join(home, profile.elevateHomeName));
  const electronUserData = path.join(home, "Library", "Application Support", profile.productName);
  return {
    elevateHome,
    licensePath: path.join(elevateHome, "license.json"),
    dashboardTokenPath: path.join(elevateHome, "dashboard-session-token"),
    computerUseFlag: path.join(elevateHome, "computer-use-active"),
    smsOutbox: path.join(elevateHome, "sms-outbox"),
    workspace: path.join(home, profile.workspaceName),
    pythonCache: path.join(home, "Library", "Caches", profile.productName, "python-pycache"),
    electronUserData,
    electronSessionData: path.join(electronUserData, "Session Data"),
    electronLogs: path.join(home, "Library", "Logs", profile.productName),
    electronCrashDumps: path.join(electronUserData, "Crashpad"),
    gatewayLabel: profile.gatewayLabel,
    gatewayPlistName: `${profile.gatewayLabel}.plist`,
  };
}

function backendRuntimeExpectation({ profile, paths }) {
  if (!profile.isBeta) return null;
  return Object.freeze({
    releaseChannel: profile.channel,
    elevateHome: path.resolve(paths.elevateHome),
    providerPolicyVersion: profile.providerPolicyVersion,
    allowedModelsVersion: profile.allowedModelsVersion,
    allowedProvider: profile.allowedProvider,
    allowedModels: profile.allowedModels,
  });
}

function applyElectronProfile({ app, fs, profile, paths }) {
  app.setName(profile.productName);
  if (!profile.isBeta) return;

  for (const dir of [
    paths.electronUserData,
    paths.electronSessionData,
    paths.electronLogs,
    paths.electronCrashDumps,
  ]) {
    fs.mkdirSync(dir, { recursive: true });
  }
  app.setPath("userData", paths.electronUserData);
  app.setPath("sessionData", paths.electronSessionData);
  app.setPath("crashDumps", paths.electronCrashDumps);
  app.setAppLogsPath(paths.electronLogs);
}

module.exports = {
  BETA,
  STABLE,
  artifactFileName,
  applyElectronProfile,
  backendRuntimeExpectation,
  downloadAliasFileName,
  downloadAliasFileNames,
  releaseArtifactNames,
  resolveReleaseProfile,
  resolveRuntimePaths,
};
