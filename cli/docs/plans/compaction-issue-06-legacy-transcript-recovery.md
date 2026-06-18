# Issue 6 - Legacy transcript recovery

Date: 2026-06-17
Parent epic: `cli/docs/epic-compaction-session-parity-2026-06-17.md`
Status: partially implemented; failed message-count recovery retry guard is in
source, persisted across gateway restarts, and patched into installed app

## Implementation evidence

- Source change:
  `cli/gateway/run.py` records the hygiene no-op guard when message-count
  legacy recovery fails below the critical token line.
- Regression test:
  `cli/tests/gateway/test_session_hygiene.py::test_session_hygiene_records_failed_message_count_recovery_guard`
- Focused checks:
  `cli/.venv/bin/python -m pytest cli/tests/gateway/test_session_hygiene.py cli/tests/gateway/test_hygiene_noop_guard.py -q` -> 39 passed
- Broader Issue 6 source checks:
  `cli/.venv/bin/python -m pytest cli/tests/gateway/test_session_hygiene.py cli/tests/gateway/test_hygiene_noop_guard.py cli/tests/agent/test_compress_context_cursor.py cli/tests/run_agent/test_compaction_resume_hydration.py -q` -> 46 passed
- Installed app patch:
  `/Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/gateway/run.py`
- Installed smoke after patch:
  `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --check-file gateway/run.py` -> `PASS`
- Persistent retry guard:
  failed message-count recovery now persists the bounded hygiene no-op guard in
  `state_meta` under `gateway:hygiene_noop_guard:v1`, so a gateway restart does
  not immediately retry the same oversized raw transcript.
- Regression extension:
  `cli/tests/gateway/test_session_hygiene.py::test_session_hygiene_records_failed_message_count_recovery_guard`
  now simulates a restart by reloading the persisted guard.
- Broader source checks:
  `cli/.venv/bin/python -m pytest cli/tests/gateway/test_session_hygiene.py cli/tests/gateway/test_hygiene_noop_guard.py cli/tests/agent/test_compress_context_cursor.py cli/tests/run_agent/test_compaction_resume_hydration.py cli/tests/tui_gateway/test_protocol.py -q`
  -> 95 passed.
- Installed parity smoke after persisted-guard patch:
  `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --check-file gateway/run.py --check-file agent/conversation_compression.py --check-file tui_gateway/server.py --skip-sidecar`
  -> `PASS`, output `/tmp/elevate-installed-smoke-1781750758.json`.

Remaining work:

- inventory every legacy raw-history source
- add Telegram fixture coverage with disposable `ELEVATE_HOME`
- define the final support-facing recovery failure message

## Goal

Huge old sessions should recover once into cursor compaction state, then behave
like normal cursor sessions. They must not crash, retry the same oversized
summary on every message, or look like random auto-compaction to the user.

Keep the cursor model. Gateway recovery is a compatibility shim for old raw
history, not a second normal compaction policy.

## Problem shape

Observed production failure:

- Telegram live mapping pointed at an oversized old session.
- The raw transcript had roughly 1,400+ messages.
- Token pressure did not necessarily look critical because current usage
  metrics were stale or cursor-unaware.
- Gateway message-count hygiene forced a pre-agent compression attempt.
- The summary request exceeded the compression model context window.
- The warning path used to crash on missing `_emit_warning`.
- Restarting gateway did not help because the Telegram lane still mapped to the
  same oversized session.

Recent patches fixed the crash and made hygiene cursor-aware, but the recovery
strategy still needs a clear, repeatable contract.

## Sources of legacy raw history

Audit and document each source before patching behavior:

- Telegram JSONL transcript loaded through gateway session store
- SQLite session rows from desktop chat
- old compression-continuation chains
- resumed sessions opened by original id instead of compression tip
- rotated or manually reset Telegram agent lanes
- imported or restored history where `compaction_cursor` is absent

For each source, record:

- where the raw messages load from
- whether cursor metadata is available
- whether a compression tip/child session exists
- whether the session is live-mapped from Telegram/desktop

## Recovery decision contract

Use the smallest decision tree:

1. If `compaction_cursor > 0`, estimate pressure from `summary + tail`.
   Do not recover purely because raw transcript length is large.
2. If no cursor and raw transcript is over the legacy message-count limit,
   enter `legacy_recovery` mode.
3. If effective tokens are at critical pressure, enter `critical_recovery`.
4. Otherwise let the normal `AIAgent` turn own compaction.

Required event/log fields:

- `source`: `gateway_hygiene`
- `reason`: `legacy_raw_message_flood` or `critical_pressure`
- `raw_message_count`
- `effective_prompt_tokens`
- `compaction_cursor_before`
- `compaction_cursor_after`
- `recovery_attempted`
- `recovery_result`: `recovered`, `skipped_cursor`, `failed_oversized`,
  `failed_provider`, or `deferred_to_agent`

## Recovery execution

For `legacy_recovery`:

1. Build a temporary `AIAgent` with the same session db/write path as the real
   lane.
2. Run existing cursor compression on the raw transcript.
3. Persist `compaction_summary` and `compaction_cursor` before the normal agent
   turn starts.
4. Keep the raw transcript append-only.
5. Continue the user's incoming message through the normal agent path.

Do not rewrite/delete the raw Telegram transcript as the success condition.
Cursor advancement is the success condition.

For `critical_recovery`:

1. Prefer the same cursor recovery path.
2. If summarization still cannot fit, fall back to existing oversized tool/media
   truncation only for old heavy tool outputs.
3. If it still cannot fit, report a clean operator-safe failure and stop retrying
   the same doomed recovery input.

## Retry guard

Use a guard to avoid "every Telegram message retries the same failed summary".

Minimum viable behavior:

- in-memory guard keyed by live session key/session id
- records raw message count and failure reason
- suppresses retry while raw message count is within the existing retry margin
- clears when cursor recovery succeeds or raw message count grows materially

If restarts keep re-triggering the same failure, promote the guard to persisted
metadata. Do not write a user-visible transcript row as the first choice.

## User-facing behavior

Normal successful recovery:

- no transcript row
- at most a neutral "working through earlier context" status if blocking
- next response streams normally
- support logs can explain that legacy recovery happened

Recovery failure:

- no AttributeError or raw stack trace
- one actionable message, for example:

```text
This older Telegram thread is too large to recover automatically. Start a new
thread with /new, or ask support to archive the legacy transcript.
```

Use that only when the system cannot safely continue. Do not show it for normal
cursor compaction.

## Test plan

Source unit/integration tests:

```bash
cli/.venv/bin/python -m pytest \
  cli/tests/gateway/test_session_hygiene.py \
  cli/tests/gateway/test_hygiene_noop_guard.py \
  cli/tests/agent/test_compress_context_cursor.py \
  cli/tests/run_agent/test_compaction_resume_hydration.py -q
```

Add or extend tests for:

- cursor session with raw history over 400 messages skips legacy recovery
- no-cursor raw history over the limit recovers once and persists cursor
- failed oversized recovery records retry guard
- next message with same raw count does not retry the same failure
- growth past retry margin allows one new recovery attempt
- recovered session resumes into `messages_for_api()` as summary plus tail

Installed/manual soak:

- Telegram-style fixture in disposable `ELEVATE_HOME`
- one real Telegram lane with a copied oversized session, never the original
  customer session
- restart gateway between messages to verify whether retry state survives or
  needs persisted metadata

## Acceptance criteria

- Legacy oversized sessions either recover once into cursor state or fail with a
  clean, actionable message.
- Cursor-compacted sessions never re-enter recovery because raw transcript
  length is still large.
- Reopening/resuming a recovered session sends summary plus tail.
- The same failed recovery input is not retried on every incoming Telegram
  message.
- No recovery path uses `_emit_warning` or status callbacks in a way that can
  crash the user turn.
