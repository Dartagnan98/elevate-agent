"use strict";

function assetRefs(html) {
  const set = new Set();
  const re = /assets\/[A-Za-z0-9_.-]+\.(?:js|css)/g;
  let m;
  while ((m = re.exec(html || "")) !== null) set.add(m[0]);
  return set;
}

function bundledIndexHtml({ app, fs, path, process, repoRoot }) {
  const candidates = [];
  if (app.isPackaged) {
    candidates.push(
      path.join(process.resourcesPath, "cli", "elevate_cli", "web_dist", "index.html"),
    );
  }
  try {
    candidates.push(path.join(repoRoot(), "cli", "elevate_cli", "web_dist", "index.html"));
  } catch {
    /* repoRoot may throw when packaged */
  }
  for (const p of candidates) {
    try {
      if (fs.existsSync(p)) return fs.readFileSync(p, "utf8");
    } catch {
      /* try next */
    }
  }
  return "";
}

async function backendBundleMatches({
  app,
  backendPort,
  fs,
  path,
  process,
  repoRoot,
  requestText,
}) {
  const bundledHtml = bundledIndexHtml({ app, fs, path, process, repoRoot });
  const expected = assetRefs(bundledHtml);
  if (expected.size === 0) return true;
  const servedHtml = await requestText("/", 2500, backendPort);
  if (!servedHtml) return true;
  const served = assetRefs(servedHtml);
  if (served.size === 0) return true;
  for (const ref of expected) {
    if (!served.has(ref)) return false;
  }
  return true;
}

module.exports = {
  assetRefs,
  backendBundleMatches,
  bundledIndexHtml,
};
