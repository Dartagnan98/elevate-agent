"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

// finalize-mac-dist validates the release channel at require time; the desktop
// suite runs with ELEVATE_RELEASE_CHANNEL=stable, which the script rejects.
process.env.ELEVATE_RELEASE_CHANNEL = "beta";

const {
  APPLE_RETRY_ATTEMPTS,
  APPLE_RETRY_DELAYS_MS,
  isTransientAppleFailure,
  retryDelayMs,
  runAppleEvidence,
  withAppleRetry,
} = require("../scripts/finalize-mac-dist");

function recorder() {
  const lines = { log: [], warn: [], error: [] };
  return {
    lines,
    logger: {
      log: (message) => lines.log.push(message),
      warn: (message) => lines.warn.push(message),
      error: (message) => lines.error.push(message),
    },
  };
}

test("Apple retry backoff is bounded at three attempts with 5s/15s/45s waits", () => {
  assert.equal(APPLE_RETRY_ATTEMPTS, 3);
  assert.deepEqual(APPLE_RETRY_DELAYS_MS, [5_000, 15_000, 45_000]);
  assert.equal(retryDelayMs(1), 5_000);
  assert.equal(retryDelayMs(2), 15_000);
  assert.equal(retryDelayMs(3), 45_000);
  assert.equal(retryDelayMs(9), 45_000);
});

test("transient Apple-service failures are classified as retryable", () => {
  for (const message of [
    "codesign --force --sign X --timestamp <desktop>/dist/Elevate.dmg failed with exit 1: The timestamp service is not available.",
    "xcrun notarytool submit failed with exit 1: Error: HTTP status code: 503. Service Unavailable",
    "xcrun notarytool submit failed with exit 1: The request timed out.",
    "xcrun notarytool submit failed with exit 1: A server with the specified hostname could not be found.",
    "xcrun stapler staple failed with exit 1: The network connection was lost.",
    "xcrun notarytool submit failed with exit 1: Connection reset by peer",
    "xcrun notarytool submit failed with exit 1: Error: HTTP status code: 429. Too Many Requests",
  ]) {
    assert.equal(isTransientAppleFailure(message), true, message);
  }
});

test("genuine Apple rejections are never classified as retryable", () => {
  for (const message of [
    "xcrun notarytool submit failed with exit 1: status: Invalid",
    'xcrun notarytool submit failed with exit 1: {"status":"Rejected"}',
    "No Developer ID Application identity found. Set CODESIGN_IDENTITY or CSC_NAME.",
    "codesign failed with exit 1: no identity found",
    "codesign failed with exit 1: <desktop>/dist/Elevate.dmg: No such file or directory",
    "codesign failed with exit 1: <desktop>/dist/Elevate.dmg: is not a valid disk image",
    "codesign failed with exit 1: unable to read <desktop>/dist/Elevate.dmg",
    "xcrun notarytool submit failed with exit 1: Error: Unauthorized. Check your credentials.",
    "codesign failed with exit 5: resource fork, Finder information, or similar detritus not allowed",
  ]) {
    assert.equal(isTransientAppleFailure(message), false, message);
  }
});

test("unrecognized failures are not retried — classification is conservative", () => {
  assert.equal(isTransientAppleFailure("codesign failed with exit 1: something nobody has seen before"), false);
  assert.equal(isTransientAppleFailure(""), false);
  assert.equal(isTransientAppleFailure(undefined), false);
});

test("a hard rejection wins even when the text also carries network-shaped words", () => {
  const message = "xcrun notarytool submit failed with exit 1: status: Invalid (the request timed out while polling)";
  assert.equal(isTransientAppleFailure(message), false);
});

test("withAppleRetry retries a transient failure and returns the successful attempt", () => {
  const { lines, logger } = recorder();
  const slept = [];
  const attempts = [];
  const result = withAppleRetry("codesign fixture.dmg", (attempt) => {
    attempts.push(attempt);
    if (attempt < 3) throw new Error("codesign failed with exit 1: The timestamp service is not available.");
    return { ok: true, attempt, output: "signed" };
  }, { sleep: (ms) => slept.push(ms), logger });

  assert.deepEqual(attempts, [1, 2, 3]);
  assert.deepEqual(result, { ok: true, attempt: 3, output: "signed" });
  assert.deepEqual(slept, [5_000, 15_000]);
  assert.equal(lines.warn.length, 2);
  assert.match(lines.warn[0], /codesign fixture\.dmg attempt 1\/3 hit a transient Apple-service failure; retrying in 5s/);
  assert.match(lines.warn[0], /timestamp service is not available/);
  assert.match(lines.warn[1], /attempt 2\/3 .*retrying in 15s/);
  assert.equal(lines.log.length, 1);
  assert.match(lines.log[0], /codesign fixture\.dmg succeeded on attempt 3\/3/);
  assert.deepEqual(lines.error, []);
});

test("withAppleRetry fails fast and loudly on a genuine rejection", () => {
  const { lines, logger } = recorder();
  const slept = [];
  let calls = 0;

  assert.throws(() => withAppleRetry("notarytool submit fixture.dmg", () => {
    calls += 1;
    throw new Error("xcrun notarytool submit failed with exit 1: status: Invalid");
  }, { sleep: (ms) => slept.push(ms), logger }), /status: Invalid/);

  assert.equal(calls, 1, "a rejection must not be re-submitted");
  assert.deepEqual(slept, []);
  assert.deepEqual(lines.warn, []);
  assert.equal(lines.error.length, 1);
  assert.match(lines.error[0], /failed on attempt 1\/3 and is not retryable/);
});

test("withAppleRetry gives up after the attempt cap and rethrows the last error", () => {
  const { lines, logger } = recorder();
  const slept = [];
  let calls = 0;

  assert.throws(() => withAppleRetry("stapler staple fixture.dmg", () => {
    calls += 1;
    throw new Error(`xcrun stapler staple failed with exit ${calls}: The network connection was lost.`);
  }, { sleep: (ms) => slept.push(ms), logger }), /failed with exit 3: The network connection was lost\./);

  assert.equal(calls, APPLE_RETRY_ATTEMPTS);
  assert.deepEqual(slept, [5_000, 15_000]);
  assert.equal(lines.warn.length, 2);
  assert.equal(lines.error.length, 1);
  assert.match(lines.error[0], /still failing after 3 attempt\(s\) against Apple services/);
});

test("runAppleEvidence records the successful attempt in the unchanged evidence shape", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-finalize-retry-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const marker = path.join(root, "attempts");
  const script = [
    `printf x >> "${marker}"`,
    `if [ "$(wc -c < "${marker}" | tr -d " ")" -lt 2 ]`,
    'then echo "The timestamp service is not available." >&2; exit 1',
    'else echo "signed and stapled"; fi',
  ].join("; ");
  const { lines, logger } = recorder();

  const evidence = runAppleEvidence("codesign fixture.dmg", "/bin/sh", ["-c", script], {}, {
    sleep: () => {},
    logger,
  });

  assert.equal(fs.readFileSync(marker, "utf8"), "xx", "the command must have been re-run once");
  assert.deepEqual(evidence, {
    ok: true,
    status: 0,
    stdout: "signed and stapled",
    stderr: "",
    output: "signed and stapled",
    output_sha256: crypto.createHash("sha256").update("signed and stapled").digest("hex"),
  });
  assert.equal(evidence.output.includes("timestamp service"), false, "evidence must describe the successful attempt");
  assert.equal(lines.warn.length, 1);
  assert.match(lines.log[0], /succeeded on attempt 2\/3/);
});

test("runAppleEvidence surfaces a hard command failure without re-running it", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-finalize-hard-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const marker = path.join(root, "attempts");
  const script = `printf x >> "${marker}"; echo "no identity found" >&2; exit 1`;
  const { logger } = recorder();

  assert.throws(() => runAppleEvidence("codesign fixture.dmg", "/bin/sh", ["-c", script], {}, {
    sleep: () => {},
    logger,
  }), /no identity found/);

  assert.equal(fs.readFileSync(marker, "utf8"), "x");
});
