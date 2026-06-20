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

function installMainCrashCapture({ app, log, formatCrashForLog: crashFormatter = formatCrashForLog }) {
  process.on("uncaughtException", (err) => {
    log.error(`[main:uncaughtException] ${crashFormatter(err)}`);
    try {
      app.exit(1);
    } catch {
      process.exit(1);
    }
  });

  process.on("unhandledRejection", (reason) => {
    log.error(`[main:unhandledRejection] ${crashFormatter(reason)}`);
  });
}

module.exports = {
  createStartupLogger,
  formatCrashForLog,
  installMainCrashCapture,
  trimLogMessage,
};
