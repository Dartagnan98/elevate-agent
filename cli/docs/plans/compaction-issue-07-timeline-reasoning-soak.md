# Issue 7 - Real-time timeline and reasoning continuity soak

Date: 2026-06-17
Parent epic: `cli/docs/epic-compaction-session-parity-2026-06-17.md`
Status: implemented for installed desktop compact/resume/follow-up smoke;
protocol replay/follow-up ring coverage and light visual smoke pass

## Current evidence

- Installed runtime smoke already verifies live `message.start`,
  `message.delta`, `message.complete`, usage payloads, asset parity, and fresh
  Electron log scans.
- `cli/scripts/installed_runtime_smoke.py` now closes the live sidecar session
  after completion, resumes the persisted session id, and asserts the final
  assistant text reloads from transcript.
- Latest installed provider-call close/resume smoke passed:
  `/tmp/elevate-installed-smoke-1781753062.json`.
  It streamed `message.start`, `thinking.delta`, `status.update`,
  `message.delta`, `reasoning.available`, and `message.complete`, included
  usage, and reloaded the final assistant text after `session.resume`.
- Latest installed desktop compacted follow-up smoke passed:
  `/tmp/elevate-installed-smoke-1781753993.json`.
  It created a real installed desktop session, sent four provider-backed turns,
  ran `session.compress`, advanced cursor `0 -> 5`, resumed the persisted
  session `20260617_203915_5c739f`, completed the follow-up with final text
  `compacted followup ok`, and found no post-follow-up `compaction.*` log lines
  for that session.
- Light installed Electron visual smoke passed: the latest smoke session rendered
  in the real Elevate window and showed `installed compaction smoke ok` without
  requiring session re-entry.
- Installed Electron visual check for the compacted smoke session passed: search
  opened `20260617_203915_5c739f`, the UI showed all four setup turns plus
  `compacted followup ok`, and the context indicator rendered pending (`--`)
  instead of a stale pre-compaction percentage.
- The smoke output now reports `license_authenticated`, `license_expired`, and
  a non-secret license status string so auth gating is not mistaken for a
  timeline or compaction regression.
- Source fix:
  `cli/tui_gateway/server.py` now preserves the replay ring for
  follow-up/steer `message.complete` events where the `followup` flag lives
  inside the event payload.
- Regression coverage:
  `cli/tests/tui_gateway/test_protocol.py::test_event_ring_coalesces_thinking_deltas_for_resume`
  and
  `cli/tests/tui_gateway/test_protocol.py::test_event_ring_clears_only_terminal_complete`.
- Focused checks:
  `cli/.venv/bin/python -m pytest cli/tests/tui_gateway/test_protocol.py cli/tests/tui_gateway/test_message_ids.py cli/tests/test_tui_gateway_server.py -q`
  -> 129 passed.
- Installed app patch:
  `/Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/tui_gateway/server.py`
- Installed parity smoke after patch:
  `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --check-file gateway/run.py --check-file agent/conversation_compression.py --check-file tui_gateway/server.py --skip-sidecar`
  -> `PASS`, output `/tmp/elevate-installed-smoke-1781750199.json`.

## Goal

Prove that compaction and long turns do not make the desktop chat feel stalled,
blank, or out of order. A user should not need to leave and re-enter a session
to see thinking, reasoning, streaming response text, or the final transcript.

## Bug classes to cover

- Live response chunks stop rendering even though the gateway is still working.
- `thinking.delta` or `reasoning.available` arrives but does not attach to the
  active assistant turn.
- `message.complete` arrives without the final text hydrating into the visible
  transcript.
- Re-entering a session shows content that was missing during the live turn.
- Compaction status clears or replaces context usage without a fresh pending
  state.
- Stale websocket state makes submit appear accepted but no live stream follows.

## Minimum soak ladder

1. Source protocol tests.

   Extend existing gateway/TUI tests before touching the frontend:

   - event order: `message.start` before deltas before `message.complete`
   - content-free events: `thinking.delta` and `reasoning.available` survive
     recorder/replay
   - resume replay: running session returns replay events and still receives new
     live events once reattached
   - completed resume: completed session reloads transcript without replaying a
     fake live turn

2. Installed sidecar smoke.

   Keep the script single-file and boring:

   - create session
   - submit exact-response prompt
   - require streaming events and usage
   - close sidecar session
   - resume persisted session id
   - assert final assistant text is present after resume

   Latest passing command:

   ```bash
   cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py \
     --check-file gateway/run.py \
     --check-file agent/conversation_compression.py \
     --check-file tui_gateway/server.py
   ```

3. UI visual sanity.

   After the sidecar smoke passes, use the real installed Electron window:

   - latest smoke session appears in the sidebar
   - final assistant text is visible without reload
   - context ring is pending or fresh, not stale
   - reasoning/thinking area does not blank after `message.complete`

4. Compaction-boundary soak.

   The installed compacted-session smoke is now green:

   - preloaded cursor metadata
   - compact-start status
   - pending usage ring
   - final text streams after the compaction boundary
   - resume reloads the final transcript
   - follow-up does not immediately trigger compaction again

## Do not do

- Do not add a new frontend state machine just for this soak.
- Do not fake provider success by editing `license.json`.
- Do not use localhost dev as release proof.
- Do not mutate real Telegram production history for this check.

## Acceptance criteria

- Installed sidecar smoke passes with close-and-resume transcript verification.
- A real installed Electron view shows the same final answer without requiring a
  manual session re-entry.
- Installed compact/resume/follow-up smoke passes without fresh post-follow-up
  compaction logs for the persisted session.
- Fresh logs contain no `gateway not connected`, `Uncaught`, `BLANK-TRACE`, or
  `did-fail-load` entries after the smoke start time.
- Any auth-gated run reports the license blocker clearly and does not get filed
  as a timeline/compaction failure.
