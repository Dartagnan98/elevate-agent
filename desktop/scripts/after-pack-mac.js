const { spawnSync } = require("node:child_process");

exports.default = async function afterPackMac(context) {
  if (context.electronPlatformName !== "darwin") return;

  const result = spawnSync("/usr/bin/xattr", ["-cr", context.appOutDir], {
    encoding: "utf8",
  });
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim();
    throw new Error(`[after-pack] failed to clear macOS extended attributes${detail ? `: ${detail}` : ""}`);
  }
  console.log(`[after-pack] cleared macOS extended attributes from ${context.appOutDir}`);
};
