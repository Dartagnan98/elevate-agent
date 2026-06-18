# Issue 4 - Claude-style context UI clarity

Date: 2026-06-17
Parent epic: `cli/docs/epic-compaction-session-parity-2026-06-17.md`
Status: implemented in `0a74c5e61`; patched into installed desktop app

## Implementation evidence

- Source commit: `0a74c5e61 fix(web): clarify compaction context status`
- Rebuilt web asset: `ChatPage-B0tDyOWz.js`
- Installed app path patched:
  `/Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/elevate_cli/web_dist/`
- Focused tests:
  `npm --prefix cli/web test -- slashExec ChatPage.activityDigest` -> 25 passed
- Focused backend checks:
  `pytest cli/tests/gateway/test_usage_context_percent.py cli/tests/tui_gateway/test_status_update_pill.py cli/tests/test_tui_gateway_server.py cli/tests/elevate_cli/test_session_recorder.py -q` -> 94 passed
- Installed app smoke:
  created session `20260617_184548_505e53`, streamed
  `message.start`, `thinking.delta`, `status.update`, `message.delta`,
  `reasoning.available`, `message.complete`, and rendered
  `issue 4 context UI smoke ok` in Electron with the context ring showing
  `91%` left.

## Problem

Even when compaction is technically correct, the UI can make it feel like the
app glitched:

- the ring may show a stale percentage after compaction invalidates usage
- the visible ring number is context left, while backend thresholds are context
  used
- automatic compaction can look like a special chat event instead of quiet
  maintenance
- manual `/compact` and automatic compaction share nearby status text
- users sometimes have to re-enter a session to see thinking/reasoning resume
  when timeline events are missed or out of order

The product target is Claude-style calm continuity: automatic maintenance can
show generic working/pending if it blocks, but should not become the main event
in the conversation.

## Current behavior

Verified source state:

- `cli/tui_gateway/server.py::_get_usage(...)` emits `context_percent` only
  when `last_prompt_tokens > 0`; after compaction sentinel `-1`, usage is
  omitted and the UI can render pending.
- `cli/tests/gateway/test_usage_context_percent.py` pins that pending behavior.
- `cli/web/src/pages/ChatPage.tsx::ContextRing(...)` receives
  `usage.context_percent` as context used, but displays context left by
  calculating `100 - used`.
- `ContextRing` currently labels the title as `Context left: ...` and details
  token counts as used.
- `ChatPage.tsx` clears usage when a compaction status arrives.
- `ChatPage.tsx` still relies partly on visible text such as
  `Compacting context`.
- `cli/tui_gateway/server.py` emits manual `/compact` progress through
  `status.update`.
- Manual compact can still display explicit finish copy because the user asked
  for `/compact`.
- `cli/elevate_cli/diagnostics/session_recorder.py` now records content-free
  timeline events, so reasoning/timeline gaps are easier to prove.

## Desired behavior

User-facing convention:

- the ring displays context left
- tooltips/details may include context used
- backend logs/events use context used
- any visible percentage must say whether it is left or used

Automatic compaction behavior:

- no transcript row
- no "Finished compacting" transcript-style event
- no dramatic success moment
- during a blocking summary, show neutral working/pending at most
- soft prune stays invisible
- after compaction starts, the ring shows pending until fresh provider usage
  arrives through `session.usage` or `message.complete`

Manual `/compact` behavior:

- explicit start/progress is allowed
- explicit finish copy is allowed
- cursor compaction success must be described honestly

## Files / seams

Primary:

- `cli/web/src/pages/ChatPage.tsx`
- `cli/tui_gateway/server.py`
- `cli/elevate_cli/diagnostics/session_recorder.py`

Tests:

- `cli/web/src/pages/__tests__/ChatPage.activityDigest.test.ts`
- `cli/tests/tui_gateway/test_status_update_pill.py`
- `cli/tests/gateway/test_usage_context_percent.py`
- `cli/tests/test_tui_gateway_server.py`
- `cli/tests/elevate_cli/test_session_recorder.py`

Build output:

- `cli/elevate_cli/web_dist/` after frontend changes

## Implementation steps

1. Prefer structured status kind over text matching.

   Keep existing visible text for compatibility, but make `ChatPage.tsx` use
   `payload.kind === "compacting_context"` when it is available. Keep the text
   fallback for older gateways.

2. Make ring copy explicit.

   Keep the compact visible label if necessary, but make the tooltip/title
   unambiguous:

   ```text
   Context left: 89%. 11% used. 29,310 / 272,000 tokens used.
   ```

   Pending title:

   ```text
   Context usage pending until the next model response.
   ```

   Do not use threshold words in the ring unless the label also says used/left.

3. Keep automatic compaction out of the activity transcript.

   Auto compaction can affect the processing bar while it blocks, but it should
   not append a visible assistant row saying compaction finished. Manual
   compact remains explicit.

4. Separate manual compact completion from automatic status updates.

   In `ChatPage.tsx`, only call manual completion helpers when a manual compact
   callback is active or the slash command path confirms completion. A generic
   automatic status update must not fabricate "Finished compacting".

5. Preserve pending usage after compaction.

   On compact-start:

   - clear context usage to pending
   - keep it pending through status-only events
   - restore only from `session.usage` or `message.complete` usage payloads

   This matches the backend invariant that `last_prompt_tokens <= 0` omits
   `context_percent`.

6. Keep soft prune invisible.

   If Issue 2 exposes prune-specific metadata, ignore it for visible transcript
   rows. The active turn can continue to show normal Reading/Working.

7. Add one timeline sanity check.

   Use the existing recorder/tests to assert that content-free events such as
   `thinking.delta` and `reasoning.available` can be represented without
   needing message text. This is not a full soak; it is a regression guard.

## Tests

Frontend:

```bash
PATH="/Users/dartagnanpatricio/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" \
  npm --prefix cli/web test -- slashExec ChatPage.activityDigest
```

Required frontend assertions:

- compact-start status with `kind: "compacting_context"` clears usage
- text fallback still clears usage for older gateways
- ring pending renders `--` and pending title
- fresh `session.usage` repopulates the ring
- automatic compaction does not call manual finish helpers
- manual `/compact` still can show explicit finish copy
- visible/tooltip copy says left vs used clearly

Backend:

```bash
cli/.venv/bin/python -m pytest \
  cli/tests/gateway/test_usage_context_percent.py \
  cli/tests/tui_gateway/test_status_update_pill.py \
  cli/tests/test_tui_gateway_server.py \
  cli/tests/elevate_cli/test_session_recorder.py -q
```

Required backend assertions:

- `context_percent` is omitted while `last_prompt_tokens <= 0`
- `status.update` still emits `kind=compacting_context`
- manual `/compact` status still travels through `status.update`
- recorder keeps content-free timeline events

## Installed app verification

After source tests pass:

1. Rebuild web assets:

   ```bash
   PATH="/Users/dartagnanpatricio/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" \
     npm --prefix cli/web run build
   ```

2. Patch installed web assets:

   ```bash
   rsync -a --delete \
     cli/elevate_cli/web_dist/ \
     /Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/elevate_cli/web_dist/
   ```

3. Patch installed CLI source only if backend files changed.

4. Restart the installed app, not localhost.

5. Real desktop smoke:

   - open a chat
   - send a short prompt
   - verify live status and final answer render
   - verify the ring shows a real percentage only after fresh usage

6. Compaction-specific smoke if available:

   - trigger or simulate compact-start status
   - verify ring goes pending
   - verify no automatic "Finished compacting" row appears
   - verify manual `/compact` still reports explicit completion

## Acceptance criteria

- The context ring is unambiguous about left vs used.
- After compaction starts, the ring goes pending and stays pending until fresh
  provider usage arrives.
- Automatic compaction does not produce a dramatic completion row.
- Manual `/compact` remains explicit and truthful.
- Soft prune produces no user-facing compaction event.
- Timeline/reasoning events remain visible without re-entering the session in
  the real desktop smoke.

## Risks / rollback

- Risk: removing visible automatic copy makes real delays look frozen.
  Mitigation: keep neutral processing-bar pending while blocking.
- Risk: relying on `status.update.kind` breaks older gateways. Mitigation: keep
  text fallback for `Compacting context`.
- Risk: ring labels get too wordy. Mitigation: keep visible label compact and
  put clarity in tooltip/title.
- Rollback: revert frontend changes and keep backend pending-usage invariant;
  the source-of-truth safety is still `context_percent` omission after sentinel.
