const { execFileSync, spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

function createSmsOutbox({ log }) {
  let smsImsgPath = null;

  function resolveImsg() {
    if (smsImsgPath !== null) return smsImsgPath;
    const candidates = ["/opt/homebrew/bin/imsg", "/usr/local/bin/imsg"];
    for (const c of candidates) {
      try { if (fs.existsSync(c)) { smsImsgPath = c; return c; } } catch {}
    }
    try {
      const found = execFileSync("/usr/bin/env", ["bash", "-lc", "command -v imsg"], {
        encoding: "utf8",
      }).trim();
      smsImsgPath = found || "";
    } catch { smsImsgPath = ""; }
    return smsImsgPath;
  }

  function restartMessages() {
    return new Promise((resolve) => {
      try { execFileSync("/usr/bin/killall", ["Messages"]); } catch {}
      setTimeout(() => {
        try { spawn("/usr/bin/open", ["-g", "-a", "Messages"], { stdio: "ignore" }); } catch {}
        setTimeout(resolve, 4000);
      }, 1500);
    });
  }

  function startSmsOutboxWatcher() {
    const dir = path.join(os.homedir(), ".elevate", "sms-outbox");
    try { fs.mkdirSync(dir, { recursive: true }); } catch {}
    const inFlight = new Set();

    // Run one imsg send; resolves {ok, code, stdout, error}. Hang -> killed at 30s.
    const runImsg = (imsg, args) => new Promise((resolve) => {
      const child = spawn(imsg, args, { stdio: ["ignore", "pipe", "pipe"] });
      let out = "", err = "", done = false;
      const finish = (r) => { if (!done) { done = true; resolve(r); } };
      const killer = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} finish({ ok: false, code: null, error: "imsg timed out (Messages wedged?)" }); }, 30000);
      child.stdout.on("data", (d) => { out += d; });
      child.stderr.on("data", (d) => { err += d; });
      child.on("close", (code) => { clearTimeout(killer); finish({ ok: code === 0, code, stdout: out.slice(-500), error: code === 0 ? null : (err || out).slice(-300) }); });
      child.on("error", (e) => { clearTimeout(killer); finish({ ok: false, code: null, error: String(e).slice(-300) }); });
    });

    const drain = async () => {
      let files;
      try { files = fs.readdirSync(dir); } catch { return; }
      for (const f of files) {
        if (!f.endsWith(".req.json") || inFlight.has(f)) continue;
        inFlight.add(f);
        const id = f.slice(0, -".req.json".length);
        const reqPath = path.join(dir, f);
        const resPath = path.join(dir, `${id}.res.json`);
        let req;
        try { req = JSON.parse(fs.readFileSync(reqPath, "utf8")); }
        catch { try { fs.unlinkSync(reqPath); } catch {} inFlight.delete(f); continue; }
        // Remove the request first so a crash can't reprocess/duplicate a send.
        try { fs.unlinkSync(reqPath); } catch {}
        const writeRes = (obj) => {
          try { const tmp = `${resPath}.tmp`; fs.writeFileSync(tmp, JSON.stringify(obj)); fs.renameSync(tmp, resPath); } catch {}
          inFlight.delete(f);
        };
        const imsg = resolveImsg();
        if (!imsg) { writeRes({ ok: false, error: "imsg not installed" }); continue; }
        const svc = String(req.service || "sms").toLowerCase() === "imessage" ? "imessage" : "sms";
        const args = ["send", "--to", String(req.to || ""), "--text", String(req.text || ""), "--service", svc, "--json"];
        let res = await runImsg(imsg, args);
        // Self-heal: if it hung/failed, Messages is likely wedged — restart it and
        // retry ONCE. This is what made every "it stopped working" recover today.
        if (!res.ok) {
          log.warn("[sms-outbox] send failed, restarting Messages + retrying:", res.error);
          await restartMessages();
          res = await runImsg(imsg, args);
        }
        writeRes(res);
      }
    };
    setInterval(() => { drain().catch(() => {}); }, 1500);
    log.info("[sms-outbox] watcher started:", dir);
  }

  return { resolveImsg, restartMessages, startSmsOutboxWatcher };
}

module.exports = { createSmsOutbox };
