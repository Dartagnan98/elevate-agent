"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { createMenu } = require("../src/menu");

test("Beta application menu keeps its visible Beta identity", () => {
  let template;
  createMenu({
    app: { quit() {} },
    backendUrl: () => "http://127.0.0.1:9139",
    clearLicense() {},
    hqBaseUrl: "https://example.test",
    loadAppPath() {},
    mainWindow: () => null,
    Menu: {
      buildFromTemplate(value) {
        template = value;
        return value;
      },
      setApplicationMenu() {},
    },
    openLoginWindow() {},
    productName: "Elevate Beta",
    shell: { openExternal() {} },
    startPath: "/chat",
  });

  assert.equal(template[0].label, "Elevate Beta");
  assert.equal(template[0].submenu.at(-1).label, "Quit Elevate Beta");
});
