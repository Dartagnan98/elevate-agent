const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const { createLauncherTools } = require("../src/launcher");

function makeTools(overrides = {}) {
  const fakeProcess = {
    env: {
      PATH: "/usr/bin",
      PYTHONDONTWRITEBYTECODE: "1",
      ...(overrides.env || {}),
    },
    resourcesPath: overrides.resourcesPath || "/Applications/Elevate.app/Contents/Resources",
  };
  return createLauncherTools({
    app: { isPackaged: Boolean(overrides.packaged) },
    backendPort: () => overrides.backendPort || 9119,
    defaultPath: "/opt/homebrew/bin:/usr/local/bin",
    embeddedChat: overrides.embeddedChat !== false,
    execFileSync: overrides.execFileSync || (() => ""),
    fileExists: overrides.fileExists || (() => false),
    fs: overrides.fs || { mkdirSync() {} },
    home: "/Users/tester",
    host: "127.0.0.1",
    os: { homedir: () => "/Users/tester" },
    path,
    process: fakeProcess,
    repoRoot: () => "/repo",
  });
}

test("launcher env keeps bytecode cache outside the app bundle", () => {
  const env = makeTools().envWithPath({ EXTRA: "1" });

  assert.equal(env.PYTHONDONTWRITEBYTECODE, undefined);
  assert.equal(env.PYTHONPYCACHEPREFIX, "/Users/tester/Library/Caches/Elevate/python-pycache");
  assert.equal(env.PATH, "/opt/homebrew/bin:/usr/local/bin:/usr/bin");
  assert.equal(env.EXTRA, "1");
});

test("launcher prefers explicit desktop CLI when present", () => {
  const launcher = makeTools({
    backendPort: 9222,
    env: { ELEVATE_DESKTOP_CLI: "/custom/elevate" },
  }).resolveElevateLauncher();

  assert.equal(launcher.command, "/custom/elevate");
  assert.deepEqual(launcher.args, [
    "dashboard",
    "--port",
    "9222",
    "--host",
    "127.0.0.1",
    "--no-open",
    "--tui",
  ]);
  assert.equal(launcher.cwd, "/Users/tester");
});

test("launcher uses bundled runtime when packaged resources exist", () => {
  const created = [];
  const launcher = makeTools({
    packaged: true,
    fileExists: (filePath) =>
      filePath.endsWith("runtime/python/bin/python3.12") || filePath.endsWith("/cli"),
    fs: {
      mkdirSync(dir) {
        created.push(dir);
      },
    },
  }).resolveElevateLauncher();

  assert.equal(
    launcher.command,
    "/Applications/Elevate.app/Contents/Resources/runtime/python/bin/python3.12",
  );
  assert.equal(launcher.cwd, "/Users/tester/Elevation");
  assert.equal(launcher.extraEnv.PYTHONPATH, "/Applications/Elevate.app/Contents/Resources/cli");
  assert.deepEqual(created, ["/Users/tester/Elevation"]);
});
