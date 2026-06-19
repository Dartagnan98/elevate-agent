const path = require("path");
const { fileURLToPath } = require("url");

function isInside(root, target) {
  const rel = path.relative(root, target);
  return rel !== "" && !rel.startsWith("..") && !path.isAbsolute(rel);
}

function isTrustedNavigationUrl(url, { backendUrl, appRoot }) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.origin === new URL(backendUrl).origin) return true;
  if (parsed.protocol !== "file:") return false;

  try {
    return isInside(appRoot, fileURLToPath(parsed));
  } catch {
    return false;
  }
}

module.exports = { isTrustedNavigationUrl };
