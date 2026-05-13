#!/usr/bin/env node
"use strict";

const fs = require("fs");
const http = require("http");
const https = require("https");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");
const { URL } = require("url");

const packageJson = require("../package.json");

const REPO = "Dartagnan98/elevate-agent";
const DEFAULT_BRANCH = process.env.ELEVATE_INSTALL_BRANCH || "main";
const DEFAULT_UNIX_INSTALLER =
  process.env.ELEVATE_INSTALLER_URL ||
  `https://raw.githubusercontent.com/${REPO}/${DEFAULT_BRANCH}/cli/scripts/install.sh`;
const DEFAULT_WINDOWS_INSTALLER =
  process.env.ELEVATE_WINDOWS_INSTALLER_URL ||
  `https://raw.githubusercontent.com/${REPO}/${DEFAULT_BRANCH}/cli/scripts/install.ps1`;

function usage() {
  console.log(`Elevate bootstrap ${packageJson.version}

Usage:
  elevate install [installer options]   Install or refresh the local Elevate runtime
  elevate update                        Forward to the installed Elevate updater
  elevate <command>                     Forward to the installed Elevate CLI

Install examples:
  npx @elevationrealestate/elevate install
  npm install -g @elevationrealestate/elevate
  elevate install --skip-setup

Private beta:
  ELEVATE_GITHUB_TOKEN="$(gh auth token)" npx @elevationrealestate/elevate install

Environment:
  ELEVATE_HOME              Data directory, default ~/.elevate
  ELEVATE_INSTALL_DIR       Runtime checkout, default $ELEVATE_HOME/elevate
  ELEVATE_INSTALLER_URL     Override macOS/Linux installer URL
  ELEVATE_WINDOWS_INSTALLER_URL  Override Windows installer URL
  ELEVATE_GITHUB_TOKEN      Token for private beta downloads
`);
}

function elevateHome() {
  if (process.env.ELEVATE_HOME) {
    return process.env.ELEVATE_HOME;
  }
  if (process.platform === "win32") {
    return path.join(process.env.LOCALAPPDATA || os.homedir(), "elevate");
  }
  return path.join(os.homedir(), ".elevate");
}

function installDir() {
  return process.env.ELEVATE_INSTALL_DIR || path.join(elevateHome(), "elevate");
}

function executableExists(file) {
  if (!file) {
    return false;
  }
  try {
    const stat = fs.statSync(file);
    return stat.isFile() || stat.isSymbolicLink();
  } catch {
    return false;
  }
}

function installedCliCandidates() {
  const root = installDir();
  const explicit = process.env.ELEVATE_CLI_BIN;
  const unix = [
    path.join(root, "venv", "bin", "elevate"),
    path.join(root, "cli", "venv", "bin", "elevate"),
    path.join(root, ".venv", "bin", "elevate"),
    path.join(root, "cli", ".venv", "bin", "elevate")
  ];
  const windows = [
    path.join(root, "venv", "Scripts", "elevate.exe"),
    path.join(root, "venv", "Scripts", "elevate"),
    path.join(root, "cli", "venv", "Scripts", "elevate.exe"),
    path.join(root, "cli", "venv", "Scripts", "elevate")
  ];
  return [explicit, ...(process.platform === "win32" ? windows : unix)].filter(Boolean);
}

function findInstalledCli() {
  return installedCliCandidates().find(executableExists) || null;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    env: process.env,
    shell: false,
    ...options
  });

  if (result.error) {
    console.error(`Elevate bootstrap could not run ${command}: ${result.error.message}`);
    process.exit(1);
  }

  process.exit(result.status === null ? 1 : result.status);
}

function token() {
  return (
    process.env.ELEVATE_DOWNLOAD_TOKEN ||
    process.env.ELEVATE_GITHUB_TOKEN ||
    process.env.GITHUB_TOKEN ||
    ""
  );
}

function authHeaders(url) {
  const headers = {
    "User-Agent": `@elevationrealestate/elevate/${packageJson.version}`,
    Accept: "application/octet-stream,text/plain,*/*"
  };
  const host = url.hostname.toLowerCase();
  const value = token();
  if (value && (host.endsWith("github.com") || host.endsWith("githubusercontent.com"))) {
    headers.Authorization = `Bearer ${value}`;
  }
  return headers;
}

function download(urlString, destination, redirectCount = 0) {
  return new Promise((resolve, reject) => {
    let url;
    try {
      url = new URL(urlString);
    } catch (error) {
      reject(new Error(`Invalid installer URL: ${urlString} (${error.message})`));
      return;
    }

    if (url.protocol === "file:") {
      fs.copyFile(url, destination, (error) => (error ? reject(error) : resolve()));
      return;
    }

    const client = url.protocol === "http:" ? http : https;
    const request = client.get(url, { headers: authHeaders(url) }, (response) => {
      const status = response.statusCode || 0;
      const location = response.headers.location;
      if ([301, 302, 303, 307, 308].includes(status) && location) {
        response.resume();
        if (redirectCount >= 5) {
          reject(new Error("Too many installer redirects"));
          return;
        }
        const next = new URL(location, url).toString();
        download(next, destination, redirectCount + 1).then(resolve, reject);
        return;
      }

      if (status < 200 || status >= 300) {
        response.resume();
        reject(new Error(`Installer download failed with HTTP ${status}: ${urlString}`));
        return;
      }

      const file = fs.createWriteStream(destination, { mode: 0o755 });
      response.pipe(file);
      file.on("finish", () => file.close(resolve));
      file.on("error", reject);
    });

    request.on("error", reject);
  });
}

function windowsInstallerArgs(args) {
  const translated = [];
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === "--skip-setup") {
      translated.push("-SkipSetup");
    } else if (arg === "--no-venv") {
      translated.push("-NoVenv");
    } else if (arg === "--branch") {
      translated.push("-Branch", args[++i] || "");
    } else if (arg === "--dir") {
      translated.push("-InstallDir", args[++i] || "");
    } else if (arg === "--elevate-home") {
      translated.push("-ElevateHome", args[++i] || "");
    } else {
      translated.push(arg);
    }
  }
  return translated;
}

async function install(args) {
  if (args.includes("-h") || args.includes("--help")) {
    usage();
    return;
  }

  const dryRun = args.includes("--dry-run");
  const forwarded = args.filter((arg) => arg !== "--dry-run");
  const isWindows = process.platform === "win32";
  const installerUrl = isWindows ? DEFAULT_WINDOWS_INSTALLER : DEFAULT_UNIX_INSTALLER;

  if (dryRun) {
    console.log("Elevate install dry run");
    console.log(`Installer: ${installerUrl}`);
    console.log(`Elevate home: ${elevateHome()}`);
    console.log(`Install dir: ${installDir()}`);
    console.log(`Token detected: ${token() ? "yes" : "no"}`);
    console.log(
      `Command: ${
        isWindows
          ? `powershell.exe -ExecutionPolicy ByPass -NoProfile -File <installer> ${windowsInstallerArgs(forwarded).join(" ")}`
          : `bash <installer> ${forwarded.join(" ")}`
      }`
    );
    return;
  }

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-npm-"));
  const installerPath = path.join(tmp, isWindows ? "install.ps1" : "install.sh");

  try {
    console.log("▲ Elevate bootstrap");
    console.log(`→ Downloading installer from ${installerUrl}`);
    await download(installerUrl, installerPath);
    fs.chmodSync(installerPath, 0o755);
    if (isWindows) {
      run("powershell.exe", [
        "-ExecutionPolicy",
        "ByPass",
        "-NoProfile",
        "-File",
        installerPath,
        ...windowsInstallerArgs(forwarded)
      ]);
    } else {
      run("bash", [installerPath, ...forwarded]);
    }
  } catch (error) {
    console.error(`Elevate install failed: ${error.message}`);
    if (!token() && installerUrl.includes("githubusercontent.com")) {
      console.error(
        "If this is a private beta build, retry with ELEVATE_GITHUB_TOKEN or publish a public release installer."
      );
    }
    process.exit(1);
  }
}

async function main() {
  const [command, ...args] = process.argv.slice(2);

  if (!command || command === "help" || command === "--help" || command === "-h") {
    usage();
    return;
  }

  if (command === "bootstrap-version") {
    console.log(packageJson.version);
    return;
  }

  if (command === "install") {
    await install(args);
    return;
  }

  const cli = findInstalledCli();
  if (cli) {
    run(cli, [command, ...args]);
    return;
  }

  if (command === "update") {
    console.error("No local Elevate runtime is installed yet. Run: elevate install");
  } else {
    console.error(`No local Elevate runtime found for 'elevate ${command}'. Run: elevate install`);
  }
  process.exit(1);
}

main().catch((error) => {
  console.error(`Elevate bootstrap failed: ${error.message}`);
  process.exit(1);
});
