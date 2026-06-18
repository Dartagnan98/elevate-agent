# Issue 8 - Release and customer support checklist

Date: 2026-06-17
Parent epic: `cli/docs/epic-compaction-session-parity-2026-06-17.md`
Status: checklist created; installed provider-call and light visual smoke pass;
release still blocked until desktop compacted-session and Telegram/manual soak
pass

## Current go/no-go

Do not send the customer-visible update yet. Source tests, installed file
parity, the disposable Telegram fixture, the real desktop provider-call
close/resume smoke, and a light installed Electron visual check are passing.
The remaining release gate is desktop compacted-session and Telegram/manual
oversized-session soak.

## Source checks

Run before any installed bundle patch:

```bash
cli/.venv/bin/python -m pytest \
  cli/tests/agent/test_real_count_trigger.py \
  cli/tests/run_agent/test_compaction_payload_seam.py \
  cli/tests/agent/test_compress_context_cursor.py \
  cli/tests/gateway/test_usage_context_percent.py \
  cli/tests/tui_gateway/test_status_update_pill.py \
  cli/tests/gateway/test_session_hygiene.py \
  cli/tests/gateway/test_hygiene_noop_guard.py \
  cli/tests/run_agent/test_compaction_resume_hydration.py \
  cli/tests/tui_gateway/test_protocol.py -q
```

Run frontend checks if `cli/web` or `ChatPage.tsx` changed:

```bash
cd cli/web && npm test -- slashExec ChatPage.activityDigest
```

Rebuild web assets only if frontend source changed:

```bash
cd cli/web && npm run build
```

## Installed app patch

Patch only files that changed in source:

```bash
APP="/Users/dartagnanpatricio/Applications/Elevate.app"
cp cli/gateway/run.py "$APP/Contents/Resources/cli/gateway/run.py"
cp cli/agent/conversation_compression.py "$APP/Contents/Resources/cli/agent/conversation_compression.py"
cp cli/tui_gateway/server.py "$APP/Contents/Resources/cli/tui_gateway/server.py"
"$APP/Contents/Resources/runtime/python/bin/python3.12" -m py_compile \
  "$APP/Contents/Resources/cli/gateway/run.py" \
  "$APP/Contents/Resources/cli/agent/conversation_compression.py" \
  "$APP/Contents/Resources/cli/tui_gateway/server.py"
```

If web assets changed:

```bash
rsync -a --delete cli/elevate_cli/web_dist/ \
  "$APP/Contents/Resources/cli/elevate_cli/web_dist/"
```

Restart the real installed app:

```bash
osascript -e 'quit app "Elevate"' || true
sleep 3
open "/Users/dartagnanpatricio/Applications/Elevate.app"
```

## Installed smoke

Fast parity plus disposable Telegram-style fixture:

```bash
cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py \
  --check-file gateway/run.py \
  --check-file agent/conversation_compression.py \
  --check-file tui_gateway/server.py \
  --skip-sidecar \
  --telegram-fixture
```

Expected current evidence:

- `/tmp/elevate-installed-smoke-1781752896.json`
- `ok: true`
- `telegram_fixture.raw_messages: 450`
- `telegram_fixture.effective_messages: 11`
- `telegram_fixture.same_count_skips: true`
- `telegram_fixture.grown_retries: true`

Provider-call close/resume smoke:

```bash
cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py \
  --check-file gateway/run.py \
  --check-file agent/conversation_compression.py \
  --check-file tui_gateway/server.py
```

Current evidence:

- `/tmp/elevate-installed-smoke-1781753062.json`
- `ok: true`
- `license_authenticated: true`
- `license_expired: false`
- `final_text: installed compaction smoke ok`
- `persisted_session_id: 20260617_202412_b52050`
- `session.resume reloaded final assistant text`
- `closed resumed sidecar session`

## Manual desktop smoke

1. Open the installed Elevate app, not localhost.
2. Resume a cursor-compacted desktop session.
3. Send one normal follow-up.
4. Confirm no immediate repeat compaction unless the context is genuinely near
   the critical line.
5. Confirm reasoning/timeline updates continue in real time.
6. Confirm the context ring stays pending after compaction until fresh usage
   arrives.

## Manual Telegram smoke

Use a disposable copied session or a synthetic lane. Do not mutate a real
customer transcript for this check.

1. Point a Telegram-style lane at a compacted session with raw history over 400.
2. Send one message.
3. Confirm gateway does not compact only because raw history is large when
   cursor metadata exists.
4. Point a copied no-cursor oversized session at the lane.
5. Confirm recovery tries once, persists cursor or records the retry guard, and
   does not retry the same failed input after restart.
6. If recovery cannot fit, confirm the user sees the older-thread recovery
   message, not `AttributeError`, `_emit_warning`, or raw provider details.

## Log checks

Use these for support triage:

```bash
rg -n "compaction\\.(decision|started|completed|skipped|failed)|legacy_hygiene|Session hygiene" \
  ~/.elevate/logs ~/Library/Logs/Elevate 2>/dev/null
```

One report should answer:

- which path ran: `legacy_hygiene`, normal full compaction, critical compaction,
  or manual `/compact`
- raw message count and effective message count
- token source and token estimate
- cursor before/after
- retry guard state for legacy recovery

## Release blocker list

- Real desktop compacted-session manual soak still needed.
- Real Telegram/manual oversized-session soak still needed.
- Watch the observed `/api/workspace/git/status` temp-file replace race from
  the installed smoke run; it did not fail the compaction smoke, but it is a
  production-hardening bug.

## Acceptance criteria

- Source checks pass.
- Installed parity plus Telegram fixture passes.
- Installed provider-call close/resume smoke passes with a valid license.
- Manual desktop follow-up on a compacted session does not immediately compact
  again from raw transcript measurement.
- Manual Telegram oversized-session check either recovers once into cursor state
  or fails with the clean older-thread recovery message.
- No fresh `AttributeError`, `_emit_warning`, blank timeline, or stale context
  ring regression appears in logs/manual checks.
