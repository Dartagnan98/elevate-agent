const assert = require("node:assert/strict");
const test = require("node:test");

const { createDeepLinks } = require("../src/deep-links");

function makeWindow() {
  const calls = [];
  return {
    calls,
    focus: () => calls.push("focus"),
    isDestroyed: () => false,
    isMinimized: () => true,
    restore: () => calls.push("restore"),
    show: () => calls.push("show"),
  };
}

test("deep links are replayed once the main window exists", () => {
  const appCalls = [];
  const loginCalls = [];
  let win = null;
  const deepLinks = createDeepLinks({
    app: { focus: (options) => appCalls.push(options) },
    mainWindow: () => win,
    openLoginWindow: () => loginCalls.push("login"),
  });

  deepLinks.handleDeepLink("elevate://signin");
  win = makeWindow();
  deepLinks.replayPending();

  assert.deepEqual(appCalls, [{ steal: true }]);
  assert.deepEqual(win.calls, ["restore", "show", "focus"]);
  assert.deepEqual(loginCalls, ["login"]);
});

test("deep link open-url handler prevents default browser handling", () => {
  let prevented = false;
  let handler = null;
  const win = makeWindow();
  const deepLinks = createDeepLinks({
    app: {
      focus() {},
      on(channel, callback) {
        assert.equal(channel, "open-url");
        handler = callback;
      },
    },
    mainWindow: () => win,
    openLoginWindow() {},
  });

  deepLinks.registerOpenUrl();
  handler({ preventDefault: () => { prevented = true; } }, "elevate://signin");

  assert.equal(prevented, true);
  assert.deepEqual(win.calls, ["restore", "show", "focus"]);
});
