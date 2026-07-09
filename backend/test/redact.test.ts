import assert from "node:assert/strict";
import test from "node:test";

import { redactSensitive } from "../src/lib/redact";

test("redactSensitive scrubs emails, secrets, tokens, and home paths", () => {
  const input =
    "crash for skyleigh@exprealty.com key sk-abcdef123456 at /Users/skyleigh/app/foo.js token=supersecret and /home/justin/x.js";
  const out = redactSensitive(input);

  assert.match(out, /\[redacted-email\]/);
  assert.match(out, /\[redacted-secret\]/);
  assert.doesNotMatch(out, /skyleigh@exprealty\.com/);
  assert.doesNotMatch(out, /sk-abcdef123456/);
  assert.doesNotMatch(out, /\/Users\/skyleigh/);
  assert.doesNotMatch(out, /\/home\/justin/);
  assert.match(out, /\[path:foo\.js\]/);
  assert.match(out, /token=\[redacted-secret\]/);
});
