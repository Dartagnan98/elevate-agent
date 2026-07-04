---
name: browser-use-cli-local-only
description: Install and harden Browser Use CLI for free, local-only automation. Use when the user wants to install Browser Use CLI from the docs, wants only the free/local version, or asks to remove or block the API-key/cloud pathway. Not for day-to-day browser automation calls once installed — use agent-browser for that.
allowed-tools: terminal, read_file, write_file, patch, search_files
---

# Browser Use CLI local-only setup

Use this when the user asks to install Browser Use CLI from the Browser Use docs, wants the free/local version only, or asks to remove/block the API-key/cloud pathway.

## Goal

Set up `browser-use` for local Chromium / local Chrome profile automation only. Do not configure Browser Use Cloud, cloud login, API keys, cloud signup, credits, or profile sync.

## Install

1. Read the current Browser Use CLI docs if needed, but the current one-line installer is:

   ```bash
   curl -fsSL https://browser-use.com/cli/install.sh | bash
   ```

2. Validate install location and PATH:

   ```bash
   command -v browser-use || true
   /Users/admin/.browser-use-env/bin/browser-use doctor
   ```

3. The installer may add `/Users/admin/.browser-use-env/bin` to `~/.zshrc`, but non-zsh tool sessions may not see it. Put wrappers or symlinks in `/Users/admin/.local/bin` because that is normally on PATH.

## Hard-disable Browser Use Cloud/API-key pathway

Create `/Users/admin/.local/bin/browser-use` as a wrapper, not a symlink, so normal calls are guarded:

```bash
#!/usr/bin/env bash
# Local-only wrapper for Browser Use CLI.
set -euo pipefail
REAL="/Users/admin/.browser-use-env/bin/browser-use"
cmd="${1:-}"
sub="${2:-}"
case "$cmd" in
  cloud)
    echo "Blocked: Browser Use Cloud/API-key pathway is disabled. Use local commands only, e.g. 'browser-use open <url>' and 'browser-use state'." >&2
    exit 64
    ;;
  setup)
    echo "Blocked: browser-use setup can configure cloud/API-key access. Local Browser Use is already installed; use 'browser-use doctor' to verify." >&2
    exit 64
    ;;
  profile)
    case "$sub" in
      sync|auth)
        echo "Blocked: browser-use profile $sub uses Browser Use Cloud/API-key access. Use local profile commands only, e.g. 'browser-use profile list' or '--profile <name> open <url>'." >&2
        exit 64
        ;;
    esac
    ;;
esac
exec "$REAL" "$@"
```

Then:

```bash
chmod +x /Users/admin/.local/bin/browser-use
cp /Users/admin/.local/bin/browser-use /Users/admin/.local/bin/browser
cp /Users/admin/.local/bin/browser-use /Users/admin/.local/bin/browseruse
```

## Important pitfall: do not overwrite the real venv command

If `/Users/admin/.local/bin/browser-use` is a symlink to `/Users/admin/.browser-use-env/bin/browser-use`, using `write_file` on the symlink path will overwrite the real venv command and create infinite recursion.

Repair it by restoring the console-script shim from another installed alias, usually `/Users/admin/.browser-use-env/bin/browseruse`, or write this exact content to `/Users/admin/.browser-use-env/bin/browser-use`:

```python
#!/Users/admin/.browser-use-env/bin/python3
# -*- coding: utf-8 -*-
import sys
from browser_use.skill_cli.main import main
if __name__ == "__main__":
    if sys.argv[0].endswith("-script.pyw"):
        sys.argv[0] = sys.argv[0][:-11]
    elif sys.argv[0].endswith(".exe"):
        sys.argv[0] = sys.argv[0][:-4]
    sys.exit(main())
```

Then remove the symlink and recreate the wrapper as a real file:

```bash
chmod +x /Users/admin/.browser-use-env/bin/browser-use
rm -f /Users/admin/.local/bin/browser-use /Users/admin/.local/bin/browser /Users/admin/.local/bin/browseruse
# write wrapper files again
```

## Clean API config

Verify no API key is present:

```bash
printf 'BROWSER_USE_API_KEY env: '; if [ -n "${BROWSER_USE_API_KEY:-}" ]; then echo 'SET'; else echo 'not set'; fi
cat /Users/admin/.browser-use/config.json
browser-use config list
```

Expected config file can be `{}`. `browser-use config list` may still show cloud defaults, but `api_key` should be `not set`.

## Update installed agent skill docs

If `npx skills add https://github.com/browser-use/browser-use --skill browser-use --yes --global` installed a skill at `/Users/admin/.agents/skills/browser-use`, patch it so agents do not suggest cloud/API-key paths:

- Replace cloud/API sections with a `Local-only policy`.
- Remove examples for `browser-use cloud ...`, `cloud login`, `cloud signup`, `profile sync`, credits/top-ups, and x402.
- Keep local examples: `open`, `state`, `click`, `input`, `--headed`, `connect`, `--profile`, local CDP.
- In `references/multi-session.md`, replace cloud session examples with separate local Chromium sessions.

## Local Browser Use Python workflow notes

For Browser Use CLI sessions that need more than simple `open/click/input/state` calls, use `browser-use python` or `browser-use python --file <script.py>` instead of dropping to Playwright directly. The Python namespace exposes a `browser` wrapper with a persistent local session. Useful pattern:

```python
session = browser.__dict__["_session"]
loop = browser.__dict__["_loop"]
async def main():
    page = await session.must_get_current_page()
    await page.goto("https://example.com", wait_until="domcontentloaded")
    data = await page.evaluate("() => document.title")
    print(data)
loop.run_until_complete(main())
```

This keeps the work inside local/free Browser Use while still allowing DOM evaluation, screenshots, and structured extraction for complex portal workflows. If a Browser Use session is already running with a different config, run `browser-use close` once, then restart with the intended local profile/session.

## Verification

Run all of these before reporting done:

```bash
browser-use --help | sed -n '1,8p'
browser-use doctor

# blocked pathways must exit 64
browser-use cloud connect
browser-use cloud login test
browser-use setup
browser-use profile sync --all
browser-use profile auth --apikey test

# local smoke test must still work
browser-use open https://example.com
browser-use state
browser-use close
```

If `doctor` or `--help` hangs after adding the wrapper, suspect the symlink overwrite recursion pitfall above.

## What to tell the user

Report that Browser Use is local/free only, list the blocked commands, and confirm the local smoke test succeeded. Do not mention API-key setup as an option unless the user explicitly asks to reverse the local-only policy.
