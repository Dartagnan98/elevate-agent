# Issue 2 - Explainable compaction events

Date: 2026-06-17
Parent epic: `cli/docs/epic-compaction-session-parity-2026-06-17.md`
Status: partially implemented in source; shared compression structured logs are
in; support-facing summary still open

## Implementation evidence

- Shared full/critical compression now logs structured
  `compaction.failed`, `compaction.skipped`, and `compaction.completed` records
  from `cli/agent/conversation_compression.py`.
- Regression coverage:
  `cli/tests/agent/test_compress_context_cursor.py::test_structured_completion_log_includes_cursor_result`
  and
  `cli/tests/agent/test_compress_context_cursor.py::test_abort_logs_structured_failure`.
- Focused source checks:
  `cli/.venv/bin/python -m pytest cli/tests/agent/test_compress_context_cursor.py cli/tests/gateway/test_session_hygiene.py cli/tests/gateway/test_hygiene_noop_guard.py cli/tests/run_agent/test_compaction_resume_hydration.py cli/tests/agent/test_real_count_trigger.py -q`
  -> 79 passed.
- Installed app smoke after patch:
  `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --check-file gateway/run.py --check-file agent/conversation_compression.py`
  -> `PASS`, session `20260617_191844_20d46b`, output
  `/tmp/elevate-installed-smoke-1781749137.json`.

## Problem

Users see compaction as random because the product does not explain which layer
acted, which threshold was crossed, or whether the displayed percentage was
"context used" or "context left".

The visible side is also too loud. Even correct auto-compaction can make the
product feel unstable if the chat timeline treats it like a major event.

Support currently has to reconstruct behavior from separate logs and code paths:

- gateway hygiene token/message-count decisions
- normal agent full compaction
- critical compaction
- prune-only cleanup
- manual `/compact`
- UI status pill and context ring updates

The immediate production bug is fixed, but the next customer report should not
require another source-level forensic pass to answer "why did it compact here?"

## Current behavior

Code map as of 2026-06-17:

- `cli/agent/conversation_compression.py:490` logs "context compression
  started".
- `cli/agent/conversation_compression.py:497` emits the visible compacting
  status.
- `cli/agent/conversation_compression.py:536` sends keepalive status ticks
  during long summaries.
- `cli/agent/conversation_compression.py:580` warns when compression aborts.
- `cli/agent/conversation_compression.py:594` warns when summary generation
  falls back or recovers.
- `cli/agent/conversation_compression.py:637` persists cursor metadata.
- `cli/agent/conversation_compression.py:672` parks the `-1` sentinel after
  compaction.
- `cli/agent/conversation_compression.py:731` logs completion with cursor
  before/after and summary length.
- `cli/run_agent.py:2617` defines `_emit_status(...)`.
- `cli/run_agent.py:2673` defines `_emit_warning(...)`.
- `cli/run_agent.py:13883` imports compression pressure helpers at the
  post-tool boundary.
- `cli/run_agent.py:13919` logs the normal/critical compaction trigger.
- `cli/tui_gateway/server.py:1227` computes removed count for manual compact by
  comparing cursor before/after.
- `cli/tui_gateway/server.py:1276` includes `context_percent` only when current
  prompt usage is positive.
- `cli/tui_gateway/server.py:2988` exposes `session.usage`.
- `cli/web/src/pages/ChatPage.tsx:5447` clears usage when a compacting status
  arrives and handles "compacted" completion copy.

Existing useful tests:

- `cli/tests/tui_gateway/test_status_update_pill.py`
- `cli/tests/gateway/test_usage_context_percent.py`
- `cli/web/src/pages/__tests__/ChatPage.activityDigest.test.ts`
- `cli/tests/gateway/test_session_hygiene.py`

## Deep-read findings

- The frontend already listens to `status.update`, not bare `status`.
  `cli/tests/tui_gateway/test_status_update_pill.py` pins this.
- `_status_update(...)` already emits a payload with `kind` and `text`; use that
  shape before inventing a new UI channel.
- `ChatPage.tsx` already clears stale usage when text matches "Compacting
  context"; keep that behavior until Issue 4 makes the display more explicit.
- `cli/tests/gateway/test_usage_context_percent.py` already pins the important
  post-compaction invariant: omit `context_percent` and `context_used` while
  `last_prompt_tokens <= 0`.
- `cli/elevate_cli/tips.py:114` still says the default threshold is 50 percent.
  That is stale user-facing copy, but not Issue 2 unless touched by status text.
- Read-only subagent audit confirmed the plan is minimal, but event fields must
  vary by event. Decision events cannot require result-only fields such as
  `tokens_after`, `cursor_after`, or `summary_chars`.
- Instrument the shared `agent/conversation_compression.py::compress_context`
  path. Do not spend time instrumenting the old fallback body in `run_agent.py`
  unless a test proves it still runs.
- Manual `/compact` does not run through the normal conversation loop, so it
  needs explicit coverage in `tui_gateway/server.py`.
- Status text is still compatibility-sensitive. Keep existing visible strings
  and add `reason`/`source` only where an existing payload shape can carry them
  safely.
- Claude-style UX decision from the epic: automatic compaction is background
  maintenance. Logs should be explicit; the user-facing timeline should stay
  calm. Manual `/compact` stays visibly explicit.
- Visibility ladder:
  - soft prune around ~72 percent used: silent, no summary LLM, no transcript
    row, no "compacting" status; keep generic Thinking/Working if the turn is
    active
  - full automatic summary compaction: neutral pending/progress while it blocks,
    optional small end-of-cycle signal
  - critical or legacy recovery: visible only if the user needs to understand a
    delay or action
  - manual `/compact`: explicit start/finish copy because the user asked

## Build gates

Before implementation, decide the smallest event surface:

- Backend logs are required.
- Existing `status.update` payload can carry a reason only if it does not break
  current frontend tests.
- No new DB table.
- No new event bus.
- No analytics dependency.

Minimum proof:

- one caplog assertion for each reason that can fire now
- one UI test proving compact-start clears usage
- one UI test proving compact-finished copy is not fabricated
- one manual `/compact` test proving status still rides `status.update`
- one gateway hygiene log test proving `legacy_hygiene` is distinguishable from
  normal agent compaction
- one test proving automatic compaction does not create a fake "Finished
  compacting" user-visible completion state

## Do not do

- Do not build a telemetry framework.
- Do not add a public gateway method.
- Do not add a frontend state machine.
- Do not change threshold behavior here.
- Do not convert every status message in the app; only compaction paths.
- Do not make automatic compaction more visible in the timeline.
- Do not surface soft prune as compaction.

## Desired behavior

Every compaction-related event should be explainable from one structured record
or one clearly formatted log line. Automatic compaction should be quiet in the
user-facing chat timeline; manual `/compact` should remain explicit. Soft prune
is internal cleanup and should stay invisible to users.

Minimum event fields by event:

- `compaction.decision`: `reason`, `source`, `session_id`, `raw_messages`,
  `effective_messages`, `tokens_before`, `context_limit`, `threshold_tokens`,
  `threshold_pct`, `cursor_before`, `note`
- `compaction.started`: decision fields plus `manual` or `force` when relevant
- `compaction.completed`: result fields such as `tokens_after`, `cursor_after`,
  `summary_chars`, `aborted=false`
- `compaction.skipped`: `reason`, `source`, `session_id`, `note`
- `compaction.failed`: `reason`, `source`, `session_id`, `aborted=true`, `note`

This does not require a new DB schema, analytics system, or public gateway
method. Start with consistent internal logging and status payloads that the UI
can consume later.

## Files / seams

Primary:

- `cli/agent/conversation_compression.py`
- `cli/run_agent.py`
- `cli/gateway/run.py`
- `cli/tui_gateway/server.py`

Frontend surface:

- `cli/web/src/pages/ChatPage.tsx`
- `cli/web/src/pages/__tests__/ChatPage.activityDigest.test.ts`

Tests:

- `cli/tests/tui_gateway/test_status_update_pill.py`
- `cli/tests/gateway/test_usage_context_percent.py`
- `cli/tests/gateway/test_session_hygiene.py`

## Implementation steps

1. Add one tiny internal formatter only if duplication gets ugly.

   Preferred minimal shape:

   - new private helper in `cli/agent/conversation_compression.py`, or
   - if gateway/run.py needs the same helper, duplicate a small local formatter
     first; promote to a tiny internal module only if both copies grow.

   Keep it boring: a function that returns a dict and a compact log string.
   No class hierarchy, no persistence layer, no new dependency.

2. Standardize reason/source constants.

   Use plain string constants:

   ```text
   prune
   full_compact
   critical_compact
   manual_compact
   legacy_hygiene
   provider_usage
   real_count_projection
   effective_estimate
   raw_message_count
   manual
   ```

   This is enough for tests to assert against without needing a public enum.

3. Instrument agent pressure decisions.

   In the post-tool boundary around `cli/run_agent.py:13883`:

   - log `compaction.decision`
   - include measured tokens, trigger tokens, context length, output reserve,
     real vs estimate mode, threshold pinned, and whether the branch is prune,
     full, critical, or no-op

   Keep existing human-readable status messages.

4. Instrument `compress_context(...)`.

   In `cli/agent/conversation_compression.py`:

   - emit/log `compaction.started` before the summary call
   - emit/log `compaction.failed` on aborted summary
   - emit/log `compaction.completed` after cursor metadata is persisted
   - include cursor before/after, raw message count, summary length, and
     post-compaction sentinel state

   Do not make logging failures affect the active turn.

5. Instrument gateway hygiene separately.

   In `cli/gateway/run.py`, log the gateway decision as
   `reason=legacy_hygiene` when it runs pre-agent recovery.

   Include:

   - raw message count
   - effective message count
   - token source
   - message-count trigger vs token trigger
   - no-op guard skip
   - cursor before/after
   - legacy rewrite fallback if that branch runs

6. Preserve UI behavior while making room for better copy.

   Keep `ChatPage.tsx` clearing context usage on compact-start.
   Do not add a new UI state machine in this issue.

   Add enough reason/source to logs or existing status payloads that Issue 4 can
   later choose quiet UI behavior:

   - "Pruning stale context"
   - "Compacting context"
   - "Recovering oversized session"
   - "Critical context recovery"

   Keep visible timeline copy quiet for automatic compaction. Reserve
   "Finished compacting" for manual `/compact`.
   Do not display soft prune as "compacting"; it is cheap cleanup with no
   summary LLM. During an active turn, it should look like normal thinking.

7. Add tests.

   Backend:

   - caplog test for normal full compaction decision
   - caplog test for critical compaction decision
   - caplog test for prune-only decision
   - caplog test for gateway legacy hygiene and no-op guard skip
   - test that failed logging/formatting cannot raise into the active turn
   - manual `/compact` status/update test with optional `reason/source` payload

   Frontend:

   - keep existing usage-clearing test
   - add test that completion copy is not fabricated unless compact callback or
     actual compacted status arrives
   - add test that automatic compact-start can clear usage without producing a
     fake "Finished compacting" timeline/status finish
   - add test or source assertion that prune-only does not emit user-facing
     compaction status

8. Run focused tests.

```bash
cli/.venv/bin/python -m pytest \
  cli/tests/tui_gateway/test_status_update_pill.py \
  cli/tests/gateway/test_usage_context_percent.py \
  cli/tests/gateway/test_session_hygiene.py \
  cli/tests/gateway/test_hygiene_noop_guard.py \
  cli/tests/agent/test_compress_context_cursor.py -q

cd cli/web && npm test -- slashExec ChatPage.activityDigest
```

## Tests

Required new/changed tests:

- `test_compaction_decision_logs_full_compact`
- `test_compaction_decision_logs_critical_compact`
- `test_compaction_decision_logs_prune_only`
- `test_gateway_hygiene_logs_legacy_recovery_reason`
- `test_gateway_hygiene_logs_noop_guard_skip`
- frontend test that stale usage clears on compact-start only

Tests that should keep passing:

```bash
cli/.venv/bin/python -m pytest \
  cli/tests/tui_gateway/test_status_update_pill.py \
  cli/tests/gateway/test_usage_context_percent.py -q
```

## Installed app verification

After source tests pass and the installed bundle is patched:

1. Run a desktop chat manual `/compact`.
2. Confirm logs include `reason=manual_compact` or equivalent status/log text.
3. Resume a compacted desktop session and send one message.
4. Confirm no immediate repeat compaction unless effective payload is over
   threshold.
5. Run a Telegram oversized-session smoke.
6. Confirm gateway logs say whether it was `legacy_hygiene`,
   `critical_compact`, or skipped due to cursor-effective payload.
7. Confirm the context ring goes pending after compact-start and only repopulates
   from fresh usage.

## Acceptance criteria

- A future "why did it compact here?" report can be answered from one log/event.
- Gateway hygiene events are distinguishable from normal agent compaction.
- Prune-only is distinguishable from full compaction.
- Critical compaction is distinguishable from normal full compaction.
- Manual `/compact` is distinguishable from automatic compaction.
- Automatic compaction is quiet in user-facing chat by default.
- Soft prune stays invisible to users.
- Context usage remains omitted when `last_prompt_tokens <= 0`.
- No new public API, dependency, or DB schema is introduced.

## Risks / rollback

- Risk: too much logging creates noisy gateway logs. Mitigation: one compact
  decision line and one result line per compaction path, not heartbeat logs.
- Risk: UI starts depending on text matching again. Mitigation: keep structured
  `kind`/reason where possible and only use text as a fallback.
- Rollback: remove the new formatter/log calls. Core compaction behavior should
  remain unchanged because this issue is observability-first.
