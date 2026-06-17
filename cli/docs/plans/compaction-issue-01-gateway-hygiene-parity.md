# Issue 1 - Gateway hygiene parity

Date: 2026-06-17
Parent epic: `cli/docs/epic-compaction-session-parity-2026-06-17.md`
Status: detailed build plan, not implemented

## Problem

Telegram and desktop now share the cursor compaction mechanism at the model
payload boundary, but Telegram still has a pre-agent "session hygiene" block in
`gateway/run.py` that makes its own compaction decision before the normal agent
turn starts.

That gateway block is necessary as a legacy recovery wrapper, because Telegram
sessions can arrive through platform mapping, JSONL/SQLite history loading, and
restart recovery before an `AIAgent` has a chance to run. It should not remain a
parallel normal compaction policy.

The customer symptom is that Telegram can appear to compact at strange times or
repeat compaction after resume, while desktop chat appears closer to the normal
agent-owned behavior.

## Current behavior

Code map as of 2026-06-17:

- `cli/gateway/run.py:155` has `_hygiene_should_skip(...)`, the bounded no-op
  guard for previously ineffective message-count hygiene compactions.
- `cli/gateway/run.py:190` has `_hygiene_record(...)`, which records or clears
  that guard.
- `cli/gateway/run.py:212` has `_hygiene_effective_messages_for_pressure(...)`,
  which estimates cursor-trimmed summary-plus-tail payloads instead of the raw
  append-only transcript.
- `cli/gateway/run.py:6350` starts the pre-agent session hygiene block.
- `cli/gateway/run.py:6378` hard-codes hygiene threshold to `0.85`.
- `cli/gateway/run.py:6475` reads raw message count and session compaction
  metadata.
- `cli/gateway/run.py:6505` prefers `session_entry.last_prompt_tokens` when it
  is positive, otherwise estimates tokens from the effective history.
- `cli/gateway/run.py:6533` defines `_HARD_MSG_LIMIT = 400`.
- `cli/gateway/run.py:6534` correctly disables the raw message-count trigger
  when cursor metadata exists.
- `cli/gateway/run.py:6574` applies the no-op guard.
- `cli/gateway/run.py:6625` constructs a temporary `AIAgent` and passes
  `session_db=self._session_db`.
- `cli/gateway/run.py:6642` runs `_hyg_agent._compress_context(...)` in an
  executor.
- `cli/gateway/run.py:6667` still contains a legacy rewrite fallback.
- `cli/gateway/run.py:6691` treats cursor advancement as successful compaction
  with unchanged raw transcript length.
- `cli/gateway/run.py:6728` records effective vs ineffective hygiene results.
- `cli/run_agent.py:5524` is the source-of-truth payload seam:
  `messages_for_api(...)` injects synthetic summary and keeps tail.
- `cli/run_agent.py:5602` builds an effective API-shaped copy for pressure
  estimation without mutating transcript history.
- `cli/agent/conversation_compression.py:637` persists cursor compaction state
  as session metadata, not message rows.
- `cli/agent/conversation_compression.py:672` sets the post-compaction `-1`
  usage sentinel and invalidates the projector to prevent immediate re-trigger.

Existing useful tests:

- `cli/tests/gateway/test_session_hygiene.py`
- `cli/tests/gateway/test_hygiene_noop_guard.py`
- `cli/tests/agent/test_compress_context_cursor.py`
- `cli/tests/run_agent/test_compaction_payload_seam.py`

## Deep-read findings

- `cli/run_agent.py:1970` still defaults agent compression threshold to `0.85`,
  while `cli/agent/conversation_compression.py:994` can raise real-count
  unpinned triggers toward the newer effective line. Gateway has its own
  separate `0.85` at `cli/gateway/run.py:6379`.
- `cli/elevate_cli/config.py:3458` migrates stale pre-June `0.5` configs to
  `0.85`. Do not mix this threshold cleanup into Issue 1; it belongs to Issue 3.
- `cli/tests/gateway/test_session_hygiene.py` has many direct `0.85`
  expectations. Issue 1 must update only the tests whose premise changes:
  gateway ordinary token pressure should no longer mean pre-agent compaction.
- `session_entry.last_prompt_tokens > 0` currently wins over estimates in
  gateway hygiene. This is only safe when it represents the post-cursor payload.
  Add one test proving cursor metadata plus fresh real usage behaves correctly,
  and one test proving cursor metadata plus `last_prompt_tokens <= 0` estimates
  summary-plus-tail.
- The source-of-truth payload seam is `AIAgent.messages_for_api(...)`; gateway
  helper payloads should match its shape closely enough for pressure decisions,
  but should not duplicate the full sanitizer/tool-pair machinery.
- Read-only subagent audit confirmed this plan is correct: gateway still
  instantiates temporary hygiene `AIAgent` for ordinary token pressure at the
  hard-coded `0.85` line. Narrowing that to legacy recovery plus critical
  overflow protection is the intended behavior change.
- High-risk gotcha: `session_entry.last_prompt_tokens > 0` currently wins over
  effective cursor estimates. If that value is stale/full-transcript after
  resume, gateway can still pre-compact despite cursor metadata. Prove it is
  post-cursor/fresh, or change gateway so cursor metadata plus stale stored
  tokens cannot force ordinary pre-agent compaction.
- Existing gateway tests are partly stale. In particular,
  `test_session_hygiene_messages_stay_in_originating_topic` currently expects
  token-pressure hygiene to instantiate a temporary `AIAgent`; that assertion
  likely needs to become a critical/legacy recovery case.
- Gateway's effective-pressure helper is lighter than `AIAgent`'s full payload
  builder: it uses summary plus tail, not system prompt, prefill, plan suffix,
  or tools. That is acceptable only if agent preflight remains the final guard
  before the model call.

## Build gates

Do not start implementation until these are answered from tests or code:

- Which gateway trigger categories still instantiate a temporary `AIAgent`?
- Which categories only log and let the normal agent turn proceed?
- What exact condition preserves the hard raw-message guard?
- Does cursor metadata always survive the temporary hygiene agent path?
- Can a previous no-op guard suppress a critical 95 percent pressure case? It
  must not.
- Is positive `last_prompt_tokens` fresh for the effective cursor payload, or
  can it be stale from the raw transcript? This is the main pre-code unknown.
- Which current tests are stale because they encode the old "85 percent token
  pressure means gateway pre-agent compaction" behavior?

## Do not do

- Do not delete gateway hygiene outright.
- Do not rewrite transcript history as the new normal path.
- Do not change the default threshold policy in this issue.
- Do not add a new persistence table, migration, queue, or background worker.
- Do not touch memory behavior.

## Desired behavior

`AIAgent` owns normal model-facing compaction.

Gateway hygiene should become a thin wrapper with only two jobs:

1. Recover legacy or imported transcripts that are too large to safely hand to a
   normal agent turn.
2. Protect transport-specific gateway sessions from repeated failed recovery.

It should not decide ordinary full compaction at its own 85 percent line while
the normal agent loop has a separate threshold ladder.

Target behavior:

- If cursor metadata exists and effective summary-plus-tail payload is under the
  overflow/recovery line, gateway does not pre-compact even if raw transcript
  has more than 400 messages.
- If cursor metadata exists and effective payload is high, gateway logs that as
  effective token pressure and lets the normal agent path own ordinary
  compaction unless the session is in legacy recovery or overflow danger.
- If no cursor metadata exists and raw message count is beyond the hard limit,
  gateway may run legacy hygiene once and persist cursor metadata before the
  normal agent turn.
- If legacy hygiene produces no cursor advance and no rewrite, the no-op guard
  suppresses repeated message-count retries until the transcript grows.
- Cursor compaction success never rewrites the append-only transcript.

## Files / seams

Primary:

- `cli/gateway/run.py`

Shared seams to preserve:

- `cli/run_agent.py:5524` - `AIAgent.messages_for_api(...)`
- `cli/run_agent.py:5602` - `_messages_for_compression_pressure(...)`
- `cli/agent/conversation_compression.py:480` - shared `compress_context(...)`
- `cli/agent/conversation_compression.py:1036` - `resolve_compression_pressure(...)`
- `cli/agent/context_compressor.py` - compressor thresholds, pruning, cursor
  summarization, anti-thrash behavior

Tests:

- `cli/tests/gateway/test_session_hygiene.py`
- `cli/tests/gateway/test_hygiene_noop_guard.py`
- `cli/tests/agent/test_compress_context_cursor.py`
- `cli/tests/run_agent/test_compaction_payload_seam.py`

## Implementation steps

1. Name the gateway decision states without changing behavior first.

   Add small private helpers in `gateway/run.py`, close to the existing hygiene
   helpers:

   - `_hygiene_pressure_snapshot(...)`
   - `_hygiene_should_recover_legacy_session(...)`

   Keep return values simple dicts or tuples; no new dependency and no public
   gateway method.

   The snapshot should include:

   - raw message count
   - effective message count
   - compaction cursor present
   - token estimate
   - token source
   - context length
   - normal threshold
   - critical/warn threshold
   - reason

2. Split "normal pressure" from "legacy recovery".

   Keep the existing effective payload estimate, but change the decision labels
   so they cannot be confused:

   - `below_threshold`
   - `normal_pressure`
   - `critical_pressure`
   - `legacy_message_count`
   - `noop_guard_skip`

   The important behavior change is that raw message count can only produce
   `legacy_message_count` when cursor metadata is absent.

3. Narrow pre-agent compaction.

   Gateway should run `_hyg_agent._compress_context(...)` for:

   - `legacy_message_count`
   - `critical_pressure` where effective payload is at or above the 95 percent
     line and waiting for the normal turn is unsafe

   Gateway should not run ordinary pre-agent full compaction merely because the
   effective estimate crossed the current 85 percent hygiene threshold. That
   belongs to the normal `AIAgent` turn.

4. Preserve the current cursor-aware fixes.

   Do not remove:

   - `_hygiene_effective_messages_for_pressure(...)`
   - the cursor-metadata read from `session_db`
   - `session_db=self._session_db` when creating the temporary hygiene agent
   - cursor-advance success detection
   - no-op guard recording

5. Treat legacy rewrite as explicit legacy fallback.

   Keep the `rewrite_transcript(...)` branch for now, but gate/log it as
   `legacy_rewrite_fallback` so it cannot look like normal cursor compaction.
   Do not expand this path.

6. Update comments.

   The comments currently say rough estimates firing early are "safe and
   harmless". That is not true for user experience. Replace with language that
   explains why normal pressure belongs to the agent and why gateway is only
   recovery/overflow protection.

7. Add tests.

   Add or adjust tests for:

   - cursor metadata + raw messages over 400 + effective payload below threshold
     does not instantiate temporary `AIAgent`
   - cursor metadata + raw messages over 400 + effective payload below threshold
     still runs the normal agent turn
   - no cursor + raw messages over 400 runs legacy recovery
   - no cursor + recovery cursor advance persists via `session_db`
   - no cursor + no-op recovery records the guard
   - guard skip never suppresses critical token pressure
   - ordinary token pressure below critical does not pre-agent compact in gateway

8. Run focused tests.

```bash
cli/.venv/bin/python -m pytest \
  cli/tests/gateway/test_session_hygiene.py \
  cli/tests/gateway/test_hygiene_noop_guard.py \
  cli/tests/agent/test_compress_context_cursor.py \
  cli/tests/run_agent/test_compaction_payload_seam.py -q
```

## Tests

Required new/changed tests:

- `test_session_hygiene_skips_message_count_for_cursor_compacted_session`
  should remain and become the baseline parity test.
- Add a test where `last_prompt_tokens=0`, cursor metadata exists, and token
  estimate uses effective history.
- Add a test where ordinary effective estimate crosses the old 85 percent
  hygiene line but stays below critical; gateway should not run pre-agent
  hygiene.
- Add a test where effective estimate crosses 95 percent; gateway may run
  recovery before the normal turn.
- Add a test that legacy message-count recovery still works for uncompacted
  transcripts.
- Add or adjust the topic-routing hygiene test so it still proves hygiene
  messages stay in the originating topic, but only for legacy/critical recovery
  cases that should still run gateway hygiene.
- Add a test for cursor metadata plus positive `last_prompt_tokens`, either
  proving the value is fresh/effective or pinning the corrected fallback.

Regression tests to keep passing:

```bash
cli/.venv/bin/python -m pytest \
  cli/tests/gateway/test_session_hygiene.py \
  cli/tests/gateway/test_hygiene_noop_guard.py -q
```

## Installed app verification

After source tests pass:

1. Patch the installed app bundle only for touched files under:

```text
/Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/
```

2. Restart the installed gateway/app.

3. Verify in real runtime, not localhost:

   - compacted Telegram-style session with raw history over 400 messages does
     not repeat hygiene when effective payload is under threshold
   - old uncompacted Telegram-style session over 400 messages recovers once
   - cursor persists before the normal agent turn
   - no new lines appear in `gateway.error.log`

## Acceptance criteria

- Telegram and desktop share the same model-facing compaction contract: system
  plus summary plus tail.
- Gateway raw message count is legacy recovery only.
- Cursor-compacted sessions do not pre-agent compact just because the raw
  transcript is large.
- Legacy oversized sessions recover once and then behave like cursor sessions.
- No app-facing warning/crash path can throw because of hygiene failure.
- The tests above pass.

## Risks / rollback

- Risk: removing ordinary gateway token hygiene too aggressively could hand a
  too-large first request to the normal agent. Mitigation: keep critical 95
  percent recovery and run installed-runtime smoke before release.
- Risk: legacy rewrite fallback might still hide old behavior. Mitigation: log
  it as explicit legacy fallback and keep tests around cursor success.
- Rollback: restore the previous `_needs_compress` decision block while keeping
  the `session_db` cursor-persistence fix and `_emit_warning` fix.
