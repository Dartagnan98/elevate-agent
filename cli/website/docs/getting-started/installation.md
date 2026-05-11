---
sidebar_position: 2
title: "Installation"
description: "Install Elevate on Linux, macOS, WSL2, or Android via Termux"
---

# Installation

Get Elevate up and running in under two minutes with the one-line installer.
The installer creates the local profile and SQLite databases under
`~/.elevate` during the same run.

## Quick Install

### Linux / macOS / WSL2

```bash
curl -fsSL https://raw.githubusercontent.com/Dartagnan98/elevate-agent/main/cli/scripts/install.sh | bash
```

### Android / Termux

Elevate now ships a Termux-aware installer path too:

```bash
curl -fsSL https://raw.githubusercontent.com/Dartagnan98/elevate-agent/main/cli/scripts/install.sh | bash
```

The installer detects Termux automatically and switches to a tested Android flow:
- uses Termux `pkg` for system dependencies (`git`, `python`, `nodejs`, `ripgrep`, `ffmpeg`, build tools)
- creates the virtualenv with `python -m venv`
- exports `ANDROID_API_LEVEL` automatically for Android wheel builds
- installs a curated `.[termux]` extra with `pip`
- skips the untested browser / WhatsApp bootstrap by default

If you want the fully explicit path, follow the dedicated [Termux guide](./termux.md).

:::warning Windows
Native Windows is **not supported**. Please install [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) and run Elevate from there. The install command above works inside WSL2.
:::

### What the Installer Does

The installer handles everything automatically: source download, dependencies,
virtual environment, global `elevate` command setup, bundled skills, local
profile files, and local SQLite databases. If Git is installed, the installer
uses a normal checkout. If Git is missing, it downloads the Elevate source
archive and continues.

It initializes:

- `~/.elevate/state.db` for sessions, messages, usage, and chat history.
- `~/.elevate/data/operational.db` for leads, profiles, deal files, handoffs,
  tasks, admin runs, and workflow state.
- `~/.elevate/memory_store.db` for local memory and graph recall.

No hosted database project is required for the local runtime. By the end, you're
ready to configure a model and chat.

### After Installation

Reload your shell and start chatting:

```bash
source ~/.bashrc   # or: source ~/.zshrc
elevate             # Start chatting!
```

To reconfigure individual settings later, use the dedicated commands:

```bash
elevate model          # Choose your LLM provider and model
elevate tools          # Configure which tools are enabled
elevate gateway setup  # Set up messaging platforms
elevate db init        # Recreate or verify local SQLite databases
elevate config set     # Set individual config values
elevate setup          # Or run the full setup wizard to configure everything at once
```

---

## Prerequisites

The one-line installer does not require Git. It automatically handles:

- **uv** (fast Python package manager)
- **Python 3.11** (via uv, no sudo needed)
- **Node.js v22** (for browser automation and WhatsApp bridge)
- **ripgrep** (fast file search)
- **ffmpeg** (audio format conversion for TTS)

:::info
You do **not** need to install Python, Node.js, ripgrep, ffmpeg, or Git manually.
Git is still useful for developer checkouts and faster source updates, but a
normal user install can download the source archive directly.
:::

:::tip Nix users
If you use Nix (on NixOS, macOS, or Linux), there's a dedicated setup path with a Nix flake, declarative NixOS module, and optional container mode. See the **[Nix & NixOS Setup](./nix-setup.md)** guide.
:::

---

## Manual / Developer Installation

If you want to clone the repo and install from source — for contributing, running from a specific branch, or having full control over the virtual environment — see the [Development Setup](../developer-guide/contributing.md#development-setup) section in the Contributing guide.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `elevate: command not found` | Reload your shell (`source ~/.bashrc`) or check PATH |
| `API key not set` | Run `elevate model` to configure your provider, or `elevate config set OPENROUTER_API_KEY your_key` |
| Missing config after update | Run `elevate config check` then `elevate config migrate` |

For more diagnostics, run `elevate doctor` — it will tell you exactly what's missing and how to fix it.
