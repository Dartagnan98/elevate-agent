const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const installPath = path.resolve(__dirname, "../src/install.html");
const mainPath = path.resolve(__dirname, "../src/main.js");

function loadInstallScript() {
  const html = fs.readFileSync(installPath, "utf8");
  const match = html.match(/<script>([\s\S]*)<\/script>/);
  assert.ok(match);
  return match[1];
}

function installDom({ retry, install }) {
  const elements = new Map();
  for (const id of ["status", "retry", "install"]) {
    elements.set(id, {
      disabled: false,
      textContent: "",
      listeners: {},
      addEventListener(type, handler) {
        this.listeners[type] = handler;
      },
    });
  }
  const context = {
    document: { getElementById: (id) => elements.get(id) },
    window: { elevateDesktop: { retry, install } },
  };
  vm.runInNewContext(loadInstallScript(), context);
  return elements;
}

test("install page recovers from rejected retry and install IPC", async () => {
  const elements = installDom({
    retry: async () => {
      throw new Error("retry failed");
    },
    install: async () => {
      throw new Error("install failed");
    },
  });

  await elements.get("retry").listeners.click();
  assert.equal(elements.get("status").textContent, "RETRY FAILED");
  assert.equal(elements.get("retry").disabled, false);
  assert.equal(elements.get("install").disabled, false);

  await elements.get("install").listeners.click();
  assert.equal(elements.get("status").textContent, "INSTALL FAILED");
  assert.equal(elements.get("retry").disabled, false);
  assert.equal(elements.get("install").disabled, false);
});

test("install page shows retry and installer result states", async () => {
  const elements = installDom({
    retry: async () => ({ ok: false }),
    install: async () => ({ ok: true, message: "Install started." }),
  });

  await elements.get("retry").listeners.click();
  assert.equal(elements.get("status").textContent, "RUNTIME NOT REACHABLE");
  assert.equal(elements.get("retry").disabled, false);
  assert.equal(elements.get("install").disabled, false);

  await elements.get("install").listeners.click();
  assert.equal(elements.get("status").textContent, "INSTALL STARTED.");
  assert.equal(elements.get("retry").disabled, false);
  assert.equal(elements.get("install").disabled, false);
});

test("startup loading page resolves to dashboard or setup page", () => {
  const main = fs.readFileSync(mainPath, "utf8");

  assert.match(
    main,
    /loadLocalPage\("loading\.html"\);\s*const ready = await ensureBackend\(\);[\s\S]+if \(ready\) \{[\s\S]+loadAppPath\(START_PATH\);[\s\S]+} else \{[\s\S]+loadLocalPage\("install\.html"\);/s,
  );
});

test("retry route leaves loading for setup page on backend failure", () => {
  const main = fs.readFileSync(mainPath, "utf8");

  assert.match(
    main,
    /ipcMain\.handle\("desktop:retry"[\s\S]+loadLocalPage\("loading\.html"\);[\s\S]+const ready = await ensureBackend\(\);[\s\S]+if \(ready\) \{[\s\S]+loadAppPath\(START_PATH\);[\s\S]+return \{ ok: true \};[\s\S]+loadLocalPage\("install\.html"\);[\s\S]+return \{ ok: false \};/s,
  );
});

test("installer exit success reloads setup page when backend is still unavailable", () => {
  const main = fs.readFileSync(mainPath, "utf8");

  assert.match(
    main,
    /if \(ready\) \{\s*loadAppPath\(START_PATH\);\s*return;\s*}\s*loadLocalPage\("install\.html"\);/s,
  );
});

test("desktop license writer stores token file at 0600", () => {
  const auth = fs.readFileSync(path.resolve(__dirname, "../src/desktop-auth.js"), "utf8");

  assert.match(
    auth,
    /fs\.writeFileSync\(licensePath, JSON\.stringify\(license, null, 2\), \{ mode: 0o600 \}\);/,
  );
});
