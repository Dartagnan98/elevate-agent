# Compaction redesign: payload-time cursor, untouched transcript

**Status: approved direction (Dartagnan, 2026-06-12). Not yet built.**
Reference: jcode `crates/jcode-base/src/compaction.rs` (github.com/1jehuang/jcode).

## The structural problem

Elevate compaction REWRITES the conversation: it replaces the message list
with the compressed list, rotates to a new session id, and persists the
rewritten rows into the tip session. The visible transcript and the model
context are the same object — so every compaction is a user-visible event,
and every compaction bug of the last week traces to that:

- internal rows ([CONTEXT COMPACTION], preserved plan/todo, activity digest)
  rendered as 20KB+ "user messages" (patched display-side in 1.2.47)
- session rotation → orphaned continuations (1.2.39), re-compaction loops
  (1.2.38), client re-hydrate races / list wipes (compaction guard machinery)
- "Worked for" splits and stalls-that-weren't during mid-turn compaction

## The jcode model (adopt this)

The visible transcript is NEVER modified. Compaction maintains:

- `compacted_count` cursor — callers skip the first N messages when building
  the API payload
- a synthetic summary message (role=user) injected ONLY at payload-build
  time (`messages_for_api_with()`), never persisted into the transcript,
  never rendered

No session rotation. No rewritten persistence. No re-hydrate. The UI simply
never knows compaction happened (optionally a small status pill).

## What maps where in Elevate

- `AIAgent.run_conversation` builds API payloads from `messages` — introduce
  a payload-builder seam: `messages_for_api(messages) -> [summary?] +
  messages[compacted_idx:]`.
- `compress_context` becomes: generate summary for `messages[:cutoff]`,
  store `(summary_text, compacted_idx)` on the agent + persist them as
  SESSION METADATA (e.g. sessions.compaction_summary / compaction_cursor
  columns or a sidecar row), NOT as message rows. KILL the session rotation
  (`parent_session_id` tip-walk machinery stays only for legacy sessions).
- Resume: rebuild agent with full persisted rows + stored summary/cursor.
  Cold resume reads the same two fields. No more compression-tip walks.
- Cutoff rule: never split tool_use/tool_result pairs (jcode
  `safe_compaction_cutoff`); keep last N turns verbatim (exists:
  protect_last_n=20).
- Triggers: keep current 0.85/0.90 + output-reserve lines; ADD a 0.95
  critical line that hard-compacts synchronously (halve turns-kept until it
  fits) and emergency tool-result truncation as last resort
  (`recover_within_budget` escalation: compact first, truncate only if
  still over).
- Anti-thrash: min-turns-between-compactions cooldown alongside the
  existing ineffective-compression backoff.

## Migration/compat

- Old sessions with rotation lineage keep working (tip-walk read path stays
  for them); new compactions stop rotating.
- The 1.2.47 display filter stays (it cleans up historical tip sessions).
- Gateway: the whole `_turn_compacted` / history_version force-write-back
  block (1.2.38) becomes unnecessary for new-style compactions.

## Why this kills the bug class

The UI renders one append-only transcript forever. The model sees a window.
Those are different concerns and this finally separates them.
