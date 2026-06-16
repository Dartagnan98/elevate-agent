# Compaction redesign — implementation build plan (file-anchored)

Companion to `compaction-redesign.md` (the approved "why"). This is the "how":
exact seams, ordered steps, delete/keep tags. Built from a 4-agent source map
of HEAD `f5e5c9fb4` (2026-06-16). Build against the ISOLATED harness only
(`ELEVATE_HOME=$(mktemp -d)` + copied config/auth/license; port 9131/9143).

## Loop correction (CRITICAL — verified)

There are two `run_conversation` definitions:
- `run_agent.py:10168` — `AIAgent.run_conversation` METHOD. **This is the live
  loop** (dashboard calls `agent.run_conversation`, tui_gateway/server.py:4083).
  Uses RealUsageProjector + effective-trigger math.
- `agent/conversation_loop.py:256` — module function. **DEAD CODE**: zero
  importers, zero call sites. Ignore it for the build (do NOT mirror changes
  there; optionally delete in a separate cleanup).

The shared seam both used is `context_compressor.py` (compress/should_compress)
and `conversation_compression.py::compress_context` — those ARE live.

## The two new pieces of state

Per-agent (AIAgent, `run_agent.py:1619`+ `__init__`):
- `self.compaction_cursor: int = 0` — number of leading `messages` to skip at
  payload build (0 = no compaction).
- `self.compaction_summary: str | None = None` — synthetic summary text.

Persisted as SESSION METADATA (NOT message rows):
- SQLite: 2 columns on `sessions` (`elevate_state.py:192-224` SCHEMA_SQL):
  `compaction_summary TEXT, compaction_cursor INTEGER DEFAULT 0`. Auto-applied
  by `_reconcile_columns()` (`elevate_state.py:671-713`) — no SCHEMA_VERSION
  bump.
- Postgres: new migration `migrations_pg/0032_chat_session_compaction.sql`
  (`ALTER TABLE chat_sessions ADD COLUMN ...`); append both names to
  `_SESSION_COLUMNS` (`chat_sessions.py:29-38`). `get_session` is `SELECT *`,
  so reads pick the columns up for free.
- `cursor` itself is the new-vs-legacy discriminator: `0`/NULL + no summary →
  legacy session → keep tip-walk read path.

## Build order (each step testable in isolation)

### Step 1 — Schema + write/read plumbing (additive, safe, no behavior change)
- Add the 2 SQLite columns (`elevate_state.py:192`).
- Add PG migration `0032_*.sql` + `_SESSION_COLUMNS` append.
- Add `SessionDB.update_compaction(session_id, summary, cursor)` (mirror
  `update_system_prompt`, `elevate_state.py:959`) + `shadow_update_compaction`
  (`sessiondb_shadow.py`, mirror `shadow_update_system_prompt:84`) + PG
  `update_compaction` (`chat_sessions.py`).
- `get_session` already returns the fields. TEST: write+read round-trips both
  backends in the isolated harness.

### WORKTREE ANCHOR NOTE (read before Step 2)
The 4-agent map used `~/elevate` (current main `f5e5c9fb4`). The build lives in
worktree `~/elevate-diag-trace` (branch `compaction-redesign`, older base +
trace + anti-thrash), so line numbers DIFFER. Re-anchored worktree lines:
- `AIAgent.run_conversation` method: `run_agent.py:10351`.
- Live chat payload seam (inside run_conversation): build `api_messages=[]`
  `:11133` -> system prepend `:11203` -> `_sanitize_api_messages` `:11216` ->
  `_hydrate_media_refs_for_api` `:11217` -> `_build_api_kwargs` `:11454`.
  Hook `messages_for_api()` AFTER `:11203`, BEFORE `:11216`.
- SECOND build site at `:10199-10304` (codex `codex_kwargs` path, in a method
  BEFORE run_conversation) — apply the same seam or route both through one
  helper. CONFIRM it's a live codex path before editing.
- Agent state init: `self.session_id` `:1634`, `self._session_db = session_db`
  `:1674` (hydrate `compaction_cursor`/`compaction_summary` right after 1674).
- When deploying, rebase onto current main and RE-VERIFY these anchors against
  the deploy target (compaction files unlikely to have diverged, but check).

### Step 2 — Agent state + payload seam (the core mechanism)
- Init `self.compaction_cursor=0`, `self.compaction_summary=None` in
  `AIAgent.__init__` (`run_agent.py:1619`+); hydrate from
  `self._session_db.get_session(self.session_id)` after `_session_db` is set
  (~`run_agent.py:1668`) so fresh + resume share one path.
- Introduce `messages_for_api(self, api_messages, sys_offset)` →
  `api_messages[:sys_offset]  +  [synthetic_summary?]  +
   api_messages[sys_offset + compaction_cursor:]`.
  - synthetic_summary = one `{"role": "user", "content": SUMMARY_PREFIX-wrapped
    compaction_summary}` (reuse `context_compressor.SUMMARY_PREFIX` + END
    marker). role chosen to avoid same-role collision with the first kept msg.
  - Hook it in the LIVE loop at `run_agent.py:~11006` (right after the system
    prepend, computing sys_offset = 1 if system present else 0) and **BEFORE
    `_sanitize_api_messages` at `run_agent.py:11019`** so orphan-repair re-stubs
    any tool_result whose tool_call was skipped by the cursor.
  - Never split tool pairs: the cursor is always a value produced by the cutoff
    machinery (Step 3), which already aligns on tool boundaries — but assert it
    in `messages_for_api` (if `api_messages[sys_offset+cursor]` is a `role:tool`
    with no preceding tool_call in the kept window, nudge cursor back — defensive).
- TEST: with cursor=N + summary set, the API payload = system + summary +
  tail; transcript (`self._session_messages`) is unchanged; token estimate
  reflects the trimmed payload.

### Step 3 — `compress_context` becomes compute-cursor-not-rewrite
`agent/conversation_compression.py::compress_context` (`:440`):
- KEEP: feasibility probe, pre-compress memory hook, summary generation,
  token re-estimate, pressure telemetry, file-dedup reset, abort/no-op contract.
- CHANGE the compressor call: instead of `compress()` returning a rewritten
  head+summary+tail list, compute `compacted_idx` (= `compress_end` from the
  existing cutoff machinery: `_protect_head_size` → `_align_boundary_forward` →
  `_find_tail_cut_by_tokens` → `_align_boundary_backward` →
  `_ensure_last_user_message_in_tail`) and generate the summary for
  `messages[:compacted_idx]` via `_generate_summary`. Add a compressor method
  `summarize_to_cursor(messages) -> (summary_text, compacted_idx)` that reuses
  all the cutoff helpers and `_generate_summary` but does NOT assemble/rewrite.
  (Keep `compress()` intact for legacy callers until they're migrated.)
- Set `agent.compaction_summary = summary_text`, `agent.compaction_cursor =
  compacted_idx`; call `db.update_compaction(session_id, summary_text,
  compacted_idx)`. On re-compaction, summarize `messages[:new_idx]` with the
  PRIOR summary folded in (iterative summary — `_previous_summary` already
  exists) and advance the cursor.
- DELETE: `insert_preserved_context` (plan/todo become agent state surfaced via
  the summary or a small metadata blob, not injected rows); the SESSION
  ROTATION block (`:569-623`); `_store_compression_checkpoint` (`:173-227`) —
  repurpose its plan/todo capture into the `update_compaction` metadata if
  needed; context-engine `on_session_start(boundary_reason="compression")` and
  memory `on_session_switch` (no rotation → no switch). Return a status, not a
  rewritten list.
- The cursor advances monotonically; `protect_last_n=20` keeps recent turns
  verbatim.

### Step 4 — Resume reads cursor+summary (not tip-walk) for new sessions
- `tui_gateway/server.py:2638-2647`: for `get_session(target)` where
  `compaction_cursor` truthy → load `get_messages(target)`, set
  `agent.compaction_cursor`/`compaction_summary` from the row (covered by Step 2
  hydration if the agent is built with the right session_id), DON'T walk the
  tip. Cursor 0/NULL → keep `get_compression_tip` + `get_messages_as_conversation`
  legacy path verbatim.
- The agent hydration in Step 2 already covers `_make_agent` resume
  (`tui_gateway/server.py:2685`). Confirm REST resume paths
  (`web_server.py:4843/4916/4979/5245/5300`) build the agent via the same
  `__init__` so they inherit hydration.

### Step 5 — Remove rotation-compensation plumbing (new-style only; keep legacy)
- `run_agent.py:8966-8995` (`_compress_context` rotation engine: end_session →
  new sid → create_session(parent) → title autonumber → `_last_flushed_db_idx=0`)
  — REMOVE for new-style. Keep `commit_memory_session` + memory flush. Keep the
  `-1` sentinel / `_usage_projector.invalidate()` as a "don't re-trigger off
  stale count" guard.
- Caller-side: delete the `conversation_history = None` nulling +
  `_last_flushed_db_idx=0` reliance at the compress callers
  (`run_agent.py:10567,12462,12600,12768,13588`). Transcript is never
  re-appended; only metadata is written.
- `tui_gateway/server.py`: REMOVE `_turn_compacted` flag + session-key swap
  (`:4091-4102`), `session.identity` on rotation (`:4105-4109`), the
  `_turn_compacted` branch of the `history_version` force-write-back
  (`:4115-4124` — keep the plain version-match write-back), and
  `_run_direct_compress_slash` force-persist + identity emit (`:6048-6063`).
- `gateway/run.py`: REMOVE session-id swap + `rewrite_transcript(new_sid,...)`
  (`:6471-6480`) and the post-compression `session_id changed` update (`:6718`).
  Keep `compression_exhausted` auto-reset (`:6812`) + `-1` clamp (`:6884`).
- All "KEEP for legacy" tip-walk read paths stay so pre-migration rotated
  chains still open.

### Step 6 — Triggers: 0.95 critical hard-compact + emergency truncation
- Add `CRITICAL_THRESHOLD = 0.95` (`conversation_compression.py:~893`) and
  `should_critical_compress_now(measured, window)`; check it in the live
  iteration-boundary block `run_agent.py:13558-13572` BEFORE the normal
  `should_compress_now` — when `measured >= 0.95*window`, force a synchronous
  compaction that halves turns-kept until it fits (bypass anti-thrash backoff +
  prune-only).
- Emergency tool-result truncation (net-new last resort): after a forced
  compaction STILL doesn't fit (`run_agent.py:8933` no-op branch; the
  context-overflow "minimum tier" before `compression_exhausted`), run an
  aggressive `_prune_old_tool_results` with minimal `protect_tail_count`
  truncating oversized tool results. (This is the same family as the
  anti-thrash emergency-tail-prune already landed in context_compressor.py.)

### Step 7 — Fold in the anti-thrash patch (already built, branch compaction-relief)
- `should_compress` low-yield cooldown + emergency tail prune (commit
  `a109de3f6`) is the "min-turns-between-compactions cooldown alongside the
  existing ineffective-compression backoff" the design calls for. Port it onto
  the redesign branch (it's in context_compressor.py, shared by the live loop).

## Migration / compat invariants
- Old rotated sessions: tip-walk read paths KEPT (Steps 4/5 gate on cursor).
- 1.2.47 display filter STAYS (cleans historical tip sessions).
- New compactions: no rotation, no rewrite, no force-write-back.
- `cursor==0 && summary is None` is the legacy sentinel everywhere.

## Test plan (isolated harness)
1. Unit: `summarize_to_cursor` returns aligned cutoff (never splits tool pairs)
   + monotonic cursor advance + iterative summary fold.
2. Unit: `messages_for_api` shape (system + summary + tail), transcript
   untouched, defensive tool-pair guard.
3. Schema round-trip both backends.
4. E2E on the traced isolated dashboard: the harden_audit workload — assert
   ZERO `session_rotation`/`create_session(parent=)` events, transcript row
   count grows monotonically (never rewritten), payload stays under window,
   summary+cursor persisted, resume rebuilds identical payload, task completes.
5. Compare against the anti-thrash retest baseline
   (`Codex/.../anti-thrash-fixture/`): compaction count + no negative-savings.
6. Legacy session (pre-seeded rotated lineage) still opens via tip-walk.

## Deploy (after full validation)
De-traced surgical port into the live bundle (or proper
`npm run release:apple`), preserving the steer-replay WIP (now safe on branch
`steer-replay-rehydrate`). Relief batch (keepalive/pill/filters/hygiene) ships
together — the redesign makes the pill honest and the filters mostly redundant
for new sessions (kept for legacy).
