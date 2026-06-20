const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const repoRoot = path.resolve(__dirname, "../..");
const preloadPath = path.join(repoRoot, "desktop/src/preload.js");
const mainPath = path.join(repoRoot, "desktop/src/main.js");
const updaterPath = path.join(repoRoot, "desktop/src/updater.js");

function read(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

function walk(dir, matcher, files = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === "web_dist") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, matcher, files);
    else if (matcher(full)) files.push(full);
  }
  return files;
}

const rendererText = [
  ...walk(path.join(repoRoot, "desktop/src"), (file) => /\.(html|js)$/.test(file)),
  ...walk(path.join(repoRoot, "cli/web/src"), (file) => /\.(ts|tsx|js|jsx)$/.test(file)),
]
  .map(read)
  .join("\n");

const exposedLeaves = [
  { name: "retry", caller: "elevateDesktop.retry(" },
  { name: "install", caller: "elevateDesktop.install(" },
  { name: "auth.login", caller: "api.login(" },
  { name: "auth.openExternal", caller: "openExternal" },
  { name: "updater.getStatus", caller: ".getStatus()" },
  { name: "updater.checkNow", caller: ".checkNow()" },
  { name: "updater.install", caller: ".install()" },
  { name: "updater.onEvent", caller: "onEvent?.(" },
];

const allowedInvokeChannels = [
  "desktop:retry",
  "desktop:install",
  "auth:login",
  "auth:open-external",
  "updater:status",
  "updater:check",
  "updater:install",
];

function preloadInvokeChannels() {
  const preload = read(preloadPath);
  return [...preload.matchAll(/ipcRenderer\.invoke\("([^"]+)"/g)].map((match) => match[1]);
}

test("preload ipc invokes have main-process handlers", () => {
  const handlerSource = [read(mainPath), read(updaterPath)].join("\n");
  const channels = preloadInvokeChannels();

  assert.deepEqual([...new Set(channels)], channels);
  for (const channel of channels) {
    assert.match(handlerSource, new RegExp(`ipcMain\\.handle\\("${channel.replace(/[-:]/g, "\\$&")}"`));
  }
});

test("exposed desktop bridge leaves have renderer callers", () => {
  const preload = read(preloadPath);

  for (const exposed of exposedLeaves) {
    const [root, leaf = root] = exposed.name.split(".");
    assert.match(preload, new RegExp(`${leaf}:`), `${exposed.name} is missing from preload`);
    assert.ok(rendererText.includes(exposed.caller), `${exposed.name} has no caller needle`);
    if (root !== leaf) assert.match(preload, new RegExp(`${root}:\\s*{`));
  }
});

test("preload exposes only scoped ipc channels", () => {
  const preload = read(preloadPath);

  assert.deepEqual(preloadInvokeChannels().sort(), [...allowedInvokeChannels].sort());
  assert.match(preload, /contextBridge\.exposeInMainWorld\("elevateDesktop"/);
  assert.doesNotMatch(preload, /ipcRenderer\.(send|sendSync|postMessage)\(/);
  assert.doesNotMatch(preload, /ipcRenderer\.invoke\([^"]/);
});

test("external auth opener is path allowlisted", () => {
  const main = read(mainPath);
  const start = main.indexOf('ipcMain.handle("auth:open-external"');
  const end = main.indexOf("// ---------------------------------------------------------------------------", start);
  const handler = main.slice(start, end);

  assert.match(handler, /forgot:\s*"\/forgot\?app=1"/);
  assert.match(handler, /signup:\s*"\/signup"/);
  assert.match(handler, /link:\s*"\/link"/);
  assert.match(handler, /account:\s*"\/account"/);
  assert.match(handler, /const safePath = paths\[target\]/);
  assert.match(handler, /shell\.openExternal\(`\$\{HQ_BASE_URL\}\$\{safePath\}`\)/);
  assert.doesNotMatch(handler, /shell\.openExternal\(target\)/);
});
