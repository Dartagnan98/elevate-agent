const assert = require("node:assert/strict");
const test = require("node:test");

const {
  isAllowedAudioPermission,
  requestPermissionOrigin,
} = require("../src/permission-guard");

const dashboard = "http://127.0.0.1:9119";

test("desktop permissions allow dashboard audio capture only", () => {
  assert.equal(
    isAllowedAudioPermission("media", `${dashboard}/chat`, { mediaTypes: ["audio"] }, dashboard),
    true,
  );
  assert.equal(
    isAllowedAudioPermission("audioCapture", dashboard, {}, dashboard),
    true,
  );
});

test("desktop permissions reject cross-origin, camera, and unrelated permissions", () => {
  assert.equal(
    isAllowedAudioPermission("media", "https://example.com", { mediaTypes: ["audio"] }, dashboard),
    false,
  );
  assert.equal(
    isAllowedAudioPermission("media", dashboard, { mediaTypes: ["video"] }, dashboard),
    false,
  );
  assert.equal(
    isAllowedAudioPermission("notifications", dashboard, {}, dashboard),
    false,
  );
});

test("desktop permission request origin prefers securityOrigin", () => {
  assert.equal(
    requestPermissionOrigin({
      securityOrigin: dashboard,
      requestingUrl: "https://example.com/frame",
    }),
    dashboard,
  );
  assert.equal(
    requestPermissionOrigin({ requestingUrl: `${dashboard}/chat` }),
    `${dashboard}/chat`,
  );
});
