const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const repoRoot = path.resolve(__dirname, "../..");
const mainPath = path.join(repoRoot, "desktop/src/main.js");
const smsPath = path.join(repoRoot, "desktop/src/sms-outbox.js");
const senderPath = path.join(repoRoot, "cli/elevate_cli/sender.py");

function read(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

test("sms outbox producer and desktop watcher share request/result files", () => {
  const main = read(mainPath);
  const sms = read(smsPath);
  const sender = read(senderPath);

  assert.match(sender, /_SMS_OUTBOX_DIR = os\.path\.expanduser\("~\/\.elevate\/sms-outbox"\)/);
  assert.match(sender, /req_path = os\.path\.join\(_SMS_OUTBOX_DIR, f"\{rid\}\.req\.json"\)/);
  assert.match(sender, /res_path = os\.path\.join\(_SMS_OUTBOX_DIR, f"\{rid\}\.res\.json"\)/);
  assert.match(sender, /os\.replace\(tmp, req_path\)/);
  assert.match(sender, /return \(124, "", "app-send timed out \(Elevate app not draining sms-outbox\?\)"\)/);

  assert.match(sms, /const dir = path\.join\(os\.homedir\(\), "\.elevate", "sms-outbox"\)/);
  assert.match(sms, /f\.endsWith\("\.req\.json"\)/);
  assert.match(sms, /const resPath = path\.join\(dir, `\$\{id\}\.res\.json`\)/);
  assert.match(main, /startSmsOutboxWatcher\(\)/);
});

test("sms outbox writes visible results atomically and consumes each request once", () => {
  const outbox = read(smsPath);

  assert.match(outbox, /fs\.unlinkSync\(reqPath\)/);
  assert.match(outbox, /const tmp = `\$\{resPath\}\.tmp`/);
  assert.match(outbox, /fs\.writeFileSync\(tmp, JSON\.stringify\(obj\)\)/);
  assert.match(outbox, /fs\.renameSync\(tmp, resPath\)/);
  assert.match(outbox, /inFlight\.delete\(f\)/);
  assert.match(outbox, /writeRes\(\{ ok: false, error: "imsg not installed" \}\)/);
});

test("sms outbox forces service, captures failures, retries wedged Messages once", () => {
  const main = read(mainPath);
  const outbox = read(smsPath);

  assert.match(outbox, /const svc = String\(req\.service \|\| "sms"\)\.toLowerCase\(\) === "imessage" \? "imessage" : "sms"/);
  assert.match(outbox, /"send", "--to", String\(req\.to \|\| ""\), "--text", String\(req\.text \|\| ""\), "--service", svc, "--json"/);
  assert.match(outbox, /error: "imsg timed out \(Messages wedged\?\)"/);
  assert.match(outbox, /if \(!res\.ok\) \{[\s\S]+await restartMessages\(\);[\s\S]+res = await runImsg\(imsg, args\);[\s\S]+}/);
  assert.match(outbox, /writeRes\(res\)/);
  assert.match(main, /startSmsOutboxWatcher\(\)/);
});
