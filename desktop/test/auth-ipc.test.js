const assert = require("node:assert/strict");
const test = require("node:test");

const { registerAuthIpc } = require("../src/auth-ipc");

function register(overrides = {}) {
  const handlers = {};
  registerAuthIpc({
    hqBaseUrl: "https://api.example.com",
    ipcMain: {
      handle(channel, handler) {
        handlers[channel] = handler;
      },
    },
    loadAppPath: overrides.loadAppPath || (() => {}),
    mainWindow: overrides.mainWindow || (() => ({ isDestroyed: () => false })),
    performLogin: overrides.performLogin || (async () => ({ ok: true })),
    setTimeout: overrides.setTimeout || ((callback) => callback()),
    shell: overrides.shell || { openExternal: async () => {} },
    startPath: "/chat",
  });
  return handlers;
}

test("auth IPC reloads dashboard after successful login", async () => {
  let loadedPath = "";
  const handlers = register({
    loadAppPath(pathname) {
      loadedPath = pathname;
    },
  });

  const result = await handlers["auth:login"](null, { email: "a@example.com" });

  assert.deepEqual(result, { ok: true });
  assert.equal(loadedPath, "/chat");
});

test("auth IPC opens only allowlisted external auth paths", async () => {
  const opened = [];
  const handlers = register({
    shell: {
      openExternal: async (url) => opened.push(url),
    },
  });

  assert.deepEqual(await handlers["auth:open-external"](null, "forgot"), { ok: true });
  assert.deepEqual(await handlers["auth:open-external"](null, "bad"), { ok: false });
  assert.deepEqual(opened, ["https://api.example.com/forgot?app=1"]);
});
