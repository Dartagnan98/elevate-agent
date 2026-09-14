"use strict";

function createLauncherTools({
  app,
  backendPort,
  defaultPath,
  embeddedChat,
  execFileSync,
  fileExists: rawFileExists,
  fs,
  home,
  host,
  os,
  path,
  process,
  repoRoot,
}) {
  function envWithPath(extra = {}) {
    const pythonCacheDir = path.join(home, "Library", "Caches", "Elevate", "python-pycache");
    const env = { ...process.env };
    // CPython treats any non-empty value, including "0", as true here.
    delete env.PYTHONDONTWRITEBYTECODE;
    env.PATH = process.env.PATH ? `${defaultPath}:${process.env.PATH}` : defaultPath;
    env.PYTHONPYCACHEPREFIX = process.env.PYTHONPYCACHEPREFIX || pythonCacheDir;
    return { ...env, ...extra };
  }

  function fileExists(filePath) {
    try {
      return rawFileExists(filePath);
    } catch {
      return false;
    }
  }

  function findCommand(name) {
    try {
      return execFileSync("/usr/bin/env", ["bash", "-lc", `command -v ${name}`], {
        env: envWithPath(),
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
      }).trim();
    } catch {
      return "";
    }
  }

  function dashboardArgs() {
    const args = [
      "dashboard",
      "--port",
      String(backendPort()),
      "--host",
      host,
      "--no-open",
    ];
    if (embeddedChat) args.push("--tui");
    return args;
  }

  function resolveElevateLauncher() {
    const args = dashboardArgs();

    if (process.env.ELEVATE_DESKTOP_CLI) {
      return {
        command: process.env.ELEVATE_DESKTOP_CLI,
        args,
        cwd: os.homedir(),
      };
    }

    if (app.isPackaged) {
      const bundledPython = path.join(
        process.resourcesPath,
        "runtime",
        "python",
        "bin",
        "python3.12",
      );
      const bundledCli = path.join(process.resourcesPath, "cli");
      if (fileExists(bundledPython) && fileExists(bundledCli)) {
        const userWorkspace = path.join(os.homedir(), "Elevation");
        try {
          fs.mkdirSync(userWorkspace, { recursive: true });
        } catch {
          /* best-effort */
        }
        return {
          command: bundledPython,
          args: ["-m", "elevate_cli.main", ...args],
          cwd: userWorkspace,
          extraEnv: {
            PYTHONPATH: bundledCli,
            PYTHONNOUSERSITE: "1",
            ELEVATE_WORKSPACE: userWorkspace,
          },
        };
      }
    }

    const root = repoRoot();
    const localPython = path.join(root, "cli", ".venv", "bin", "python");
    if (fileExists(localPython)) {
      return {
        command: localPython,
        args: ["-m", "elevate_cli.main", ...args],
        cwd: path.join(root, "cli"),
      };
    }

    const elevate = findCommand("elevate");
    if (elevate) {
      return {
        command: elevate,
        args,
        cwd: os.homedir(),
      };
    }

    return null;
  }

  return {
    envWithPath,
    fileExists,
    findCommand,
    resolveElevateLauncher,
  };
}

module.exports = { createLauncherTools };
