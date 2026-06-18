# Issue 5 - Installed-runtime compaction smoke

Date: 2026-06-17
Parent epic: `cli/docs/epic-compaction-session-parity-2026-06-17.md`
Status: implemented in `cli/scripts/installed_runtime_smoke.py`

## Implementation evidence

- Script:
  `cli/scripts/installed_runtime_smoke.py`
- Compile check:
  `cli/.venv/bin/python -m py_compile cli/scripts/installed_runtime_smoke.py`
- Installed app smoke:
  `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py` -> `PASS`
- Smoke result:
  `/tmp/elevate-installed-smoke-1781747844.json`
- Verified installed assets:
  `index-BqtJl1UU.js`, `ChatPage-B0tDyOWz.js`
- Verified installed runtime file:
  `gateway/run.py`
- Created installed-runtime session:
  `20260617_185712_addd79`
- Event stream included:
  `gateway.ready`, `session.info`, `message.start`, `thinking.delta`,
  `status.update`, `message.delta`, `reasoning.available`,
  `message.complete`
- Fresh Electron log scan found no `gateway not connected`, `Uncaught`,
  `BLANK-TRACE`, or `did-fail-load` hits.
- The smoke harness now also closes the live sidecar session after a completed
  turn, resumes the persisted session id, and asserts the final assistant text
  reloads from transcript.
- The smoke harness now supports `--telegram-fixture`, which imports installed
  gateway code under a disposable `ELEVATE_HOME` and verifies Telegram-shaped
  raw history trims to cursor summary plus tail while the failed-recovery retry
  guard reloads after a simulated restart.
- Latest Telegram fixture smoke:
  `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --check-file gateway/run.py --check-file agent/conversation_compression.py --check-file tui_gateway/server.py --skip-sidecar --telegram-fixture`
  -> `PASS`, output `/tmp/elevate-installed-smoke-1781751188.json`.
- Current provider-call smoke is auth-gated until the installed app license is
  refreshed; latest auth-gated result:
  `/tmp/elevate-installed-smoke-1781749410.json`.

## Goal

Make the checks we keep doing by hand repeatable against the installed Elevate
runtime, because several regressions only showed up after patching the packaged
app and restarting the real dashboard/gateway.

This is not a new compaction system. It is a smoke harness around the existing
installed app patch flow, dashboard JSON-RPC sidecar, and gateway hygiene paths.

## Why this matters

The source tests passed before, but production pain came from packaging/runtime
edges:

- stale hashed web assets in the installed app
- Electron loading before the dashboard backend was actually ready
- gateway sockets marked open in React while the real WebSocket was closed
- cursor/hygiene behavior that only reproduced with Telegram-style raw history
- app-patched files drifting from repo files

The smoke needs to prove the installed runtime is using the same code we just
verified in source.

## Scope

Build one small script or documented command flow. Prefer `scripts/` or
`cli/scripts/` if there is already a local convention; otherwise keep it as a
single Python script with no new dependency.

Inputs:

- installed app root:
  `/Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli`
- repo root:
  `/Users/dartagnanpatricio/elevate`
- optional dashboard port, default `9120`
- optional smoke prompt, default exact-reply prompt

Outputs:

- printed verdict: `PASS` or `FAIL`
- installed asset hash observed from served HTML
- created/resumed session id
- event sequence summary
- relevant log lines or log paths

## Smoke tiers

### Tier 1: patch parity

Verify the installed bundle is actually patched before running user-facing
checks.

Assertions:

- `diff -qr cli/elevate_cli/web_dist <installed>/elevate_cli/web_dist` passes
- touched Python files, if any, match the repo copy
- installed HTML references the expected `index-*.js`
- installed index chunk references the expected `ChatPage-*.js`

Keep this as a fast file check. No provider call.

### Tier 2: installed dashboard sidecar

Use the installed dashboard service exactly the way ChatPage does:

1. Fetch `http://127.0.0.1:<port>/chat?new=<smoke-id>`.
2. Extract `window.__ELEVATE_SESSION_TOKEN__`.
3. Connect to `ws://127.0.0.1:<port>/api/ws?token=<token>`.
4. Call `session.create`.
5. Call `prompt.submit` with:

```text
Reply exactly: installed compaction smoke ok
```

Assertions:

- `session.create` returns a `persisted_session_id`
- `prompt.submit` returns `status: streaming`
- event stream contains `message.start`
- event stream contains at least one live progress event:
  `thinking.delta`, `status.update`, `tool.start`, or `message.delta`
- event stream ends with `message.complete`
- final text is exactly `installed compaction smoke ok`
- final `message.complete` has a `usage` payload
- closing and resuming the persisted session reloads the final assistant text
- no fresh `gateway not connected`, `Uncaught`, `BLANK-TRACE`, or
  `did-fail-load` appears in the Electron main log after the smoke start time
- if `prompt.submit` returns `sign_in_required`, the smoke reports an explicit
  auth-gated failure and includes non-secret local license state

This is the replacement for "it works in localhost". It uses the installed
dashboard and installed gateway.

### Tier 3: installed app visual sanity

Use Computer Use or an equivalent UI automation only after Tier 2 passes.

Assertions:

- Electron window renders the dashboard, not a black shell
- the smoke session appears in the sidebar as done
- the final assistant text is visible
- context ring displays context left or pending (`--`) with no stale value after
  usage is cleared

Do not make this tier brittle. It is a sanity check, not a pixel-perfect test.

### Tier 4: Telegram-style compaction fixture

Run against installed runtime code with a disposable `ELEVATE_HOME`, not the
user's real production home.

Fixture:

- synthetic Telegram-style session key
- raw transcript with more than the gateway message-count hygiene limit
- one case with existing `compaction_cursor` and `compaction_summary`
- one legacy case with no cursor
- provider/model behavior stubbed where possible

Assertions:

- cursor session estimates `summary + tail` and does not run pre-agent hygiene
  just because raw history is large
- persisted no-op retry guard reloads after a simulated restart
- same raw message count skips the same failed legacy recovery retry
- growth past the retry margin allows a fresh recovery attempt

Full provider-backed recovery remains source-test coverage until the installed
app license is refreshed. Do not fake a provider inside the user's real app
data.

## Minimal implementation plan

1. Create the smoke script with Tier 1 and Tier 2 only.
2. Add optional `--visual` for Tier 3.
3. Add optional `--telegram-fixture` only after Issue 6 defines recovery state.
4. Save each smoke run's short JSON result under `/tmp/elevate-smoke-*.json`.
5. Reference this script from the release checklist.

## Test plan

Source checks before running installed smoke:

```bash
cli/.venv/bin/python -m pytest \
  cli/tests/gateway/test_usage_context_percent.py \
  cli/tests/tui_gateway/test_status_update_pill.py \
  cli/tests/test_tui_gateway_server.py \
  cli/tests/gateway/test_session_hygiene.py \
  cli/tests/gateway/test_hygiene_noop_guard.py -q

PATH="/Users/dartagnanpatricio/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" \
  npm --prefix cli/web test -- slashExec ChatPage.activityDigest gatewayClient
```

Installed smoke after patch/restart:

```bash
<smoke-script> --installed-app /Users/dartagnanpatricio/Applications/Elevate.app
```

## Acceptance criteria

- A single command can prove the installed app is serving the patched web asset.
- A real installed sidecar chat turn streams and completes.
- Fresh logs are checked for the exact stale-socket/blank-shell errors that
  previously hurt production.
- The smoke result includes enough session/log evidence for a handoff.
- The smoke does not mutate real Telegram production history unless explicitly
  run in a manual soak.
