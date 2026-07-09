function trimLogMessage(value, max = 1200) {
  const text = String(value ?? "");
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function formatCrashForLog(reason) {
  if (reason && reason.stack) return trimLogMessage(reason.stack, 4000);
  if (reason && reason.message) return trimLogMessage(reason.message, 4000);
  return trimLogMessage(reason, 4000);
}

function createStartupLogger(log, startedAt = Date.now()) {
  const events = [];
  let summaryLogged = false;

  return {
    markStartup(name, detail = "") {
      const ms = Date.now() - startedAt;
      const event = { ms, name, detail };
      events.push(event);
      log.info(`[startup] ${ms}ms ${name}${detail ? ` ${detail}` : ""}`);
    },

    finishStartup(reason) {
      if (summaryLogged) return;
      summaryLogged = true;
      const total = Date.now() - startedAt;
      const timeline = events
        .map((event) => `${event.ms}ms:${event.name}${event.detail ? `(${event.detail})` : ""}`)
        .join(" | ");
      log.info(`[startup-summary] ${reason} ${total}ms ${timeline}`);
    },
  };
}

function installMainCrashCapture({
  app,
  log,
  reportCrash,
  formatCrashForLog: crashFormatter = formatCrashForLog,
}) {
  const canReport = typeof reportCrash === "function";

  process.on("uncaughtException", (err) => {
    log.error(`[main:uncaughtException] ${crashFormatter(err)}`);
    const exit = () => {
      try {
        app.exit(1);
      } catch {
        process.exit(1);
      }
    };
    if (!canReport) {
      exit();
      return;
    }
    // Give the (opt-in) crash report a moment to flush, but NEVER let it hang
    // the exit — a bounded timeout always wins.
    let done = false;
    const exitOnce = () => {
      if (done) return;
      done = true;
      exit();
    };
    Promise.resolve()
      .then(() => reportCrash(err, "uncaughtException"))
      .catch(() => {})
      .finally(exitOnce);
    const timer = setTimeout(exitOnce, 1500);
    if (timer && typeof timer.unref === "function") timer.unref();
  });

  process.on("unhandledRejection", (reason) => {
    log.error(`[main:unhandledRejection] ${crashFormatter(reason)}`);
    if (canReport) {
      Promise.resolve()
        .then(() => reportCrash(reason, "unhandledRejection"))
        .catch(() => {});
    }
  });
}

module.exports = {
  createStartupLogger,
  formatCrashForLog,
  installMainCrashCapture,
  trimLogMessage,
};
