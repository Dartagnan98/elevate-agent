const assert = require("node:assert/strict");
const test = require("node:test");

const { installDesktopPermissions } = require("../src/permissions");

const dashboard = "http://127.0.0.1:9119";

test("desktop permission installer wires audio guards and CSP", () => {
  let requestHandler = null;
  let checkHandler = null;
  let headersHandler = null;
  const session = {
    defaultSession: {
      setPermissionRequestHandler(handler) {
        requestHandler = handler;
      },
      setPermissionCheckHandler(handler) {
        checkHandler = handler;
      },
      webRequest: {
        onHeadersReceived(handler) {
          headersHandler = handler;
        },
      },
    },
  };

  installDesktopPermissions({ session, dashboardOrigin: dashboard });

  let allowed = null;
  requestHandler(null, "media", (value) => {
    allowed = value;
  }, { securityOrigin: dashboard, mediaTypes: ["audio"] });
  assert.equal(allowed, true);

  requestHandler(null, "media", (value) => {
    allowed = value;
  }, { securityOrigin: "https://example.com", mediaTypes: ["audio"] });
  assert.equal(allowed, false);

  assert.equal(checkHandler(null, "audioCapture", dashboard, {}), true);
  assert.equal(checkHandler(null, "notifications", dashboard, {}), false);

  let headers = null;
  headersHandler({ url: `${dashboard}/chat`, responseHeaders: { Foo: ["bar"] } }, (value) => {
    headers = value.responseHeaders;
  });
  assert.equal(headers.Foo[0], "bar");
  assert.match(headers["Content-Security-Policy"][0], /frame-ancestors 'none'/);

  headersHandler({ url: `${dashboard}/api/files/preview`, responseHeaders: {} }, (value) => {
    headers = value.responseHeaders;
  });
  assert.match(headers["Content-Security-Policy"][0], /frame-ancestors 'self'/);
});
