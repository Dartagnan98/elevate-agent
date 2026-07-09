const assert = require("node:assert/strict");
const test = require("node:test");

const { createCrashReporter } = require("../src/crash-reporter");

function makeReporter({ env = {}, hasFile = false, fetchImpl } = {}) {
  const calls = [];
  const reporter = createCrashReporter({
    app: { getVersion: () => "1.2.63" },
    log: { warn: (m) => calls.push(["warn", m]) },
    fetchImpl:
      fetchImpl ||
      (async (url, opts) => {
        calls.push([url, JSON.parse(opts.body)]);
        return { ok: true };
      }),
    homedir: () => "/home/test",
    env,
    fs: { existsSync: () => hasFile },
    version: "1.2.63",
    now: () => 1700000000000,
  });
  return { reporter, calls };
}

test("crash reporter is opt-out by default (sends nothing)", async () => {
  const { reporter, calls } = makeReporter();
  const result = await reporter.reportCrash(new Error("boom"), "uncaughtException");
  assert.equal(result.sent, false);
  assert.equal(result.reason, "opt-out");
  assert.equal(calls.length, 0);
});

test("crash reporter opts in via env or the ~/.elevate/crash-reports file", () => {
  assert.equal(makeReporter({ env: { ELEVATE_CRASH_REPORTS: "1" } }).reporter.optedIn(), true);
  assert.equal(makeReporter({ hasFile: true }).reporter.optedIn(), true);
  assert.equal(makeReporter().reporter.optedIn(), false);
});

test("crash reporter redacts PII/secrets from message and stack before sending", async () => {
  const { reporter, calls } = makeReporter({ env: { ELEVATE_CRASH_REPORTS: "1" } });
  const err = new Error("failed for skyleigh@exprealty.com with key sk-abcdef123456");
  err.stack =
    "Error: boom\n    at /Users/skyleigh/Applications/Elevate.app/foo.js:1:1\n    at bar (token=supersecret)";

  const result = await reporter.reportCrash(err, "unhandledRejection");
  assert.equal(result.sent, true);
  const [, body] = calls.at(-1);

  // The right stuff is present...
  assert.equal(body.version, "1.2.63");
  assert.equal(body.kind, "unhandledRejection");
  assert.equal(body.platform, process.platform);
  // ...and the dangerous stuff is gone.
  assert.match(body.message, /\[redacted-email\]/);
  assert.match(body.message, /\[redacted-secret\]/);
  assert.doesNotMatch(body.message, /skyleigh@exprealty\.com/);
  assert.doesNotMatch(body.message, /sk-abcdef123456/);
  assert.doesNotMatch(body.stack, /\/Users\/skyleigh/);
  assert.match(body.stack, /\[path:foo\.js:1:1\]/);
  assert.doesNotMatch(body.stack, /token=supersecret/);
});

test("crash reporter swallows a network failure (never crashes the crash path)", async () => {
  const { reporter } = makeReporter({
    env: { ELEVATE_CRASH_REPORTS: "1" },
    fetchImpl: async () => {
      throw new Error("network down");
    },
  });
  const result = await reporter.reportCrash(new Error("boom"), "uncaughtException");
  assert.equal(result.sent, false);
  assert.equal(result.reason, "network");
});
