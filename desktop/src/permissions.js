const {
  isAllowedAudioPermission,
  requestPermissionOrigin,
} = require("./permission-guard");

function installDesktopPermissions({ session, dashboardOrigin }) {
  const ses = session.defaultSession;
  if (!ses) return;

  // Grant microphone access to the in-app voice-input feature. macOS still
  // gates the device behind its own TCC prompt.
  ses.setPermissionRequestHandler((_webContents, permission, callback, details = {}) => {
    callback(
      isAllowedAudioPermission(
        permission,
        requestPermissionOrigin(details),
        details,
        dashboardOrigin,
      ),
    );
  });

  ses.setPermissionCheckHandler((_webContents, permission, requestingOrigin, details = {}) => {
    return isAllowedAudioPermission(
      permission,
      requestingOrigin || details.securityOrigin || details.requestingUrl,
      details,
      dashboardOrigin,
    );
  });

  ses.webRequest.onHeadersReceived((details, callback) => {
    const isFilePreview = (() => {
      try {
        return new URL(details.url).pathname === "/api/files/preview";
      } catch {
        return false;
      }
    })();
    const frameAncestors = isFilePreview ? "'self'" : "'none'";
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        "Content-Security-Policy": [
          "default-src 'self' data: blob: http://127.0.0.1:* http://localhost:*; " +
            "script-src 'self' 'unsafe-inline' http://127.0.0.1:* http://localhost:*; " +
            "style-src 'self' 'unsafe-inline' https: data:; " +
            "font-src 'self' https: data:; " +
            "img-src 'self' data: blob: https: http://127.0.0.1:* http://localhost:*; " +
            "connect-src 'self' ws: wss: http://127.0.0.1:* http://localhost:* https:; " +
            "frame-src 'self' blob: http://127.0.0.1:* http://localhost:*; " +
            `object-src 'none'; frame-ancestors ${frameAncestors}`,
        ],
      },
    });
  });
}

module.exports = { installDesktopPermissions };
