const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const loginPath = path.resolve(__dirname, "../src/login.html");
const mainPath = path.resolve(__dirname, "../src/main.js");

function loadLoginScript() {
  const html = fs.readFileSync(loginPath, "utf8");
  const match = html.match(/<script>([\s\S]*)<\/script>/);
  assert.ok(match);
  return match[1];
}

function loginDom({ login, openExternal }) {
  const elements = new Map();
  for (const id of [
    "loginForm",
    "status",
    "submit",
    "email",
    "password",
    "forgot",
    "signup",
    "link-device",
  ]) {
    elements.set(id, {
      className: "",
      disabled: false,
      listeners: {},
      textContent: "",
      value: "",
      addEventListener(type, handler) {
        this.listeners[type] = handler;
      },
    });
  }

  const context = {
    document: { getElementById: (id) => elements.get(id) },
    window: { elevateDesktop: { auth: { login, openExternal } } },
  };
  vm.runInNewContext(loadLoginScript(), context);
  return elements;
}

test("legacy login page submits credentials and shows success", async () => {
  let loginPayload = null;
  const elements = loginDom({
    login: async (payload) => {
      loginPayload = payload;
      return { ok: true };
    },
    openExternal: async () => ({ ok: true }),
  });

  elements.get("email").value = "user@example.com ";
  elements.get("password").value = "secret";

  await elements.get("loginForm").listeners.submit({ preventDefault() {} });

  assert.equal(loginPayload.email, "user@example.com");
  assert.equal(loginPayload.password, "secret");
  assert.equal(elements.get("status").textContent, "Welcome back. Loading...");
  assert.equal(elements.get("status").className, "status info");
  assert.equal(elements.get("submit").disabled, true);
});

test("legacy login page shows errors and restores controls", async () => {
  const elements = loginDom({
    login: async () => ({ ok: false, error: "Bad password" }),
    openExternal: async () => ({ ok: true }),
  });

  elements.get("email").value = "user@example.com";
  elements.get("password").value = "wrong";

  await elements.get("loginForm").listeners.submit({ preventDefault() {} });

  assert.equal(elements.get("status").textContent, "Bad password");
  assert.equal(elements.get("status").className, "status error");
  assert.equal(elements.get("submit").disabled, false);
});

test("legacy login page external links use allowlisted auth targets", () => {
  const opened = [];
  const elements = loginDom({
    login: async () => ({ ok: true }),
    openExternal: async (target) => {
      opened.push(target);
      return { ok: true };
    },
  });

  elements.get("forgot").listeners.click();
  elements.get("signup").listeners.click();
  elements.get("link-device").listeners.click();

  assert.deepEqual(opened, ["forgot", "signup", "link"]);
});

test("legacy login success reloads the dashboard", () => {
  const main = fs.readFileSync(mainPath, "utf8");

  assert.match(main, /ipcMain\.handle\("auth:login"[\s\S]+performLogin\(payload \|\| \{\}\)/);
  assert.match(main, /if \(result\.ok\)[\s\S]+loadAppPath\(START_PATH\);/);
});
