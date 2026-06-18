# Issue 6 - Legacy transcript recovery

Date: 2026-06-17
Parent epic: `cli/docs/epic-compaction-session-parity-2026-06-17.md`
Status: implemented for source plus installed synthetic Telegram hygiene soak;
live Telegram network soak with a copied oversized lane is still the remaining
release-confidence check

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
- Disposable Telegram fixture:
  `cli/scripts/installed_runtime_smoke.py --telegram-fixture` imports installed
  gateway code under a temporary `ELEVATE_HOME` and verifies a 450-message raw
  Telegram-shaped transcript trims to 11 effective messages with cursor
  metadata, the failed-recovery guard reloads after a simulated restart, the
  same raw count skips the retry, and growth past the retry margin retries.
- Latest Telegram fixture smoke:
  `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --check-file gateway/run.py --check-file agent/conversation_compression.py --check-file tui_gateway/server.py --skip-sidecar --telegram-fixture`
  -> `PASS`, output `/tmp/elevate-installed-smoke-1781751188.json`.
- Support-facing failure message:
  when legacy message-count recovery fails and the normal agent turn then hits
  context overflow, gateway returns the clean older-thread recovery message
  instead of the generic `/compact` advice or a raw stack/error.
- Regression extension:
  `cli/tests/gateway/test_session_hygiene.py::test_session_hygiene_records_failed_message_count_recovery_guard`
  now proves the same-count retry is skipped, growth past the retry margin
  retries once, and context overflow after failed legacy recovery returns the
  older Telegram thread message.
- Installed `_handle_message` hygiene soak:
  `cli/.venv/bin/python cli/scripts/installed_runtime_smoke.py --check-file gateway/run.py --check-file agent/conversation_compression.py --check-file tui_gateway/server.py --skip-sidecar --telegram-fixture --telegram-hygiene-soak`
  -> `PASS`, output `/tmp/elevate-installed-smoke-1781754329.json`.
- The installed synthetic soak verifies:
  cursor raw history `450`, cursor hygiene calls `0`, normal agent delegation
  `1`, failed recovery calls `2`, same-count retry skipped, persisted guard
  reloaded after simulated restart, growth retried, and the clean older-thread
  recovery message returned without `_emit_warning`.

Remaining work:

- live Telegram network/manual oversized-session soak against a disposable
  copied lane, not the original customer transcript

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

Inventory status: audited in source on 2026-06-17.

| Source | Where it loads | Cursor metadata | Compression tip / child | Live mapping risk | Recovery note |
| --- | --- | --- | --- | --- | --- |
| Gateway platform mapping | `cli/gateway/session.py:617-650`, `789-888` loads/saves `sessions.json` and maps a Telegram/Slack/etc. `session_key` to the active `session_id`. | `sessions.json` has `last_prompt_tokens`, but not cursor fields. Cursor lives in DB. | No tip lookup here. It only points the live lane to a physical session id. | High for Telegram: a restart keeps the same live lane pointed at an oversized old id. | Gateway hygiene must inspect the DB row for cursor metadata before using raw message count. |
| Legacy JSONL transcript | `cli/gateway/session.py:1178-1281` writes every turn to `<session_id>.jsonl` and `load_transcript()` chooses JSONL when it has more rows than SQLite. | None in the file. Cursor must come from `SessionDB.get_session(session_id)`. | None in the file. | High for old Telegram sessions, because JSONL can be the longest source and can stay append-only forever. | Raw count over 400 with no DB cursor is the true legacy-recovery trigger. Raw count over 400 with DB cursor is normal cursor state. |
| SQLite session/messages | `cli/elevate_state.py:192-235`, `975-995`, `2443-2488` stores sessions, messages, `compaction_summary`, and `compaction_cursor`. | Yes: `sessions.compaction_summary` and `sessions.compaction_cursor`. | Child linkage exists through `parent_session_id`, but cursor compaction no longer rotates. | Medium: desktop and gateway both read this path; stale/missing cursor makes an old session look raw. | This is the source of truth for cursor-aware pressure checks. |
| Legacy compression-continuation chain | `cli/elevate_state.py:1598-1645` walks children where parent ended with `end_reason='compression'`; `cli/tui_gateway/server.py:2911-2957` tip-walks only when no cursor exists. | Old rotated children may not have cursor metadata; the child itself carries the smaller transcript. | Yes. | Medium: resuming an original pre-redesign id can reload the full parent unless tip-walk happens. | Keep the tip-walk for old rotated sessions, but skip it for cursor sessions. |
| Desktop/web transcript display | `cli/elevate_cli/web_server.py:4865-4915` resolves active id, loads DB messages, hides internal compaction rows, and adds stable legacy ids. | Indirect: active id resolution uses DB identity, not JSONL. | Yes through `_resolve_active_session_or_404(...)`. | Low for model payload, but high for user perception if internal rows or stale active ids display wrong. | Display filtering must not be confused with model-facing compaction. |
| Agent payload builder | `cli/run_agent.py:5538-5614` applies `compaction_cursor + compaction_summary` only when building API messages. | Hydrated on `AIAgent` from DB session metadata before payload build. | No tip walk; it trims the current transcript copy. | High if gateway pressure checks count raw history instead of this effective payload. | This remains the canonical model-facing contract: append-only transcript, summary-plus-tail request. |
| Manual resume/switch | `cli/gateway/session.py:1109-1138` can repoint a live session key to a previous physical session id. | Depends on the target DB row. | Does not tip-walk by itself. | Medium: a user/admin can point Telegram or desktop at an old raw id. | The next turn must run the same cursor/legacy hygiene gate, not a separate resume rule. |

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
