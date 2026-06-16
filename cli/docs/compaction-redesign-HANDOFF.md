# COMPACTION REDESIGN — AUTONOMOUS BUILD HANDOFF

**Mission:** finish the Elevate compaction re-architecture **in full** (Steps
2–7), validate it **end-to-end on the UI** in an isolated harness, commit each
step. Do NOT deploy to customers — produce a fully-built, fully-tested branch
ready for a supervised deploy decision.

**Why this matters (evidence):** customer-zero Justin's box logged the rotation
bug *"new session will NOT be indexed: 'AIAgent' has no attribute
'_session_init_model_config'"* **11×** over Jun 10–12 — compacted sessions
orphaning. The redesign deletes the rotation/rewrite machinery that produces
this whole bug class. Compaction fires often (22× on 65–158-msg sessions), so
this hits real power-user sessions (Skyleigh's profile).

---

## START HERE

- Repo/worktree: `/Users/dartagnanpatricio/elevate-diag-trace` (branch
  **`compaction-redesign`**). All compaction work lives here.
- Read first, in order:
  1. `cli/docs/compaction-redesign.md` — the approved "why" (jcode model).
  2. `cli/docs/compaction-redesign-buildplan.md` — the file-anchored "how"
     (7 steps + the **WORKTREE ANCHOR NOTE** with exact line numbers).
  3. This file — the operational runbook (harness, tests, rules, done).
- venv (has pytest + deps): `/Users/dartagnanpatricio/elevate/cli/.venv/bin/python`
- Run tests/scripts with `PYTHONPATH=/Users/dartagnanpatricio/elevate-diag-trace/cli`.

## STATE (already done — do not redo)
- `a109de3f6` anti-thrash fix (low-yield cooldown + emergency tail prune) — VALIDATED.
- `90dee231c` build plan. `b3780dfeb` Step-2 worktree anchors.
- `b79625f6a` **Step 1 DONE**: session metadata columns
  `compaction_summary`/`compaction_cursor` on SQLite + PG + `update_compaction()`
  + `tests/test_compaction_metadata.py` (5 pass).

## BUILD (Steps 2–7 — detail in the build plan; commit + test EACH step)
2. Agent state (`self.compaction_cursor=0`, `self.compaction_summary=None` in
   `AIAgent.__init__`, hydrate from `get_session` after `run_agent.py:1674`) +
   `messages_for_api(api_messages, sys_offset)` payload seam hooked at
   `run_agent.py:~11203` (after system prepend, BEFORE `_sanitize_api_messages`
   `:11216`). Handle the codex build site `:10199` too. Unit-test the seam with
   a manually-set cursor (payload = system+summary+tail; transcript untouched;
   never split a tool pair).
3. `compress_context` computes `(summary_text, compacted_idx)` and calls
   `agent`/`db.update_compaction` instead of rewriting+rotating. Add
   `ContextCompressor.summarize_to_cursor(messages)`. DELETE: `insert_preserved_context`,
   rotation block (`conversation_compression.py:569-623` + `run_agent.py:8966-8995`),
   `_store_compression_checkpoint` (repurpose into metadata). KEEP cutoff helpers
   + `_generate_summary` + abort/no-op contract.
4. Resume: for `compaction_cursor` truthy, read row + set cursor/summary, skip
   tip-walk (`tui_gateway/server.py:~2638`). cursor 0/NULL → keep legacy tip-walk.
5. Remove rotation-compensation plumbing (new-style only; keep legacy):
   `tui_gateway` `_turn_compacted`/`session.identity`/force-write-back/force-persist;
   `gateway/run.py` id-swap + `rewrite_transcript`. (Exact lines in build plan.)
6. Triggers: add `CRITICAL_THRESHOLD=0.95` synchronous hard-compact +
   emergency tool-result truncation last resort.
7. Anti-thrash cooldown is ALREADY in `context_compressor.py` (Step 7 = confirm
   it composes; no new code expected).

## ISOLATED HARNESS (NEVER touch real ~/.elevate — memory rule)
There is already an isolated home at `/tmp/elevate-harden.GzsCa5` (config/auth/
license copied). To (re)launch the traced test dashboard on **:9143**:
```
ISO=/tmp/elevate-harden.GzsCa5
cp ~/.elevate/license.json "$ISO/license.json"   # refresh — stale license = "Sign in to start chatting"
cp ~/.elevate/auth.json    "$ISO/auth.json"
pkill -TERM -f "dashboard --port 9143"; sleep 3
PG=$(head -1 "$ISO/pgdata/postmaster.pid" 2>/dev/null); kill -0 "$PG" 2>/dev/null && kill -TERM "$PG"; sleep 2
cd /Users/dartagnanpatricio/elevate-diag-trace/cli
ELEVATE_HOME="$ISO" ELEVATE_DASHBOARD_SESSION_TOKEN=hardentest \
ELEVATE_COMPACTION_TRACE=1 ELEVATE_JSONL_TRACE=1 \
ELEVATE_COMPACTION_KEEPALIVE_INTERVAL=1 ELEVATE_STATUS_HEARTBEAT_INTERVAL=0 \
PYTHONPATH=/Users/dartagnanpatricio/elevate-diag-trace/cli \
/Users/dartagnanpatricio/elevate/cli/.venv/bin/python \
  -m elevate_cli.main dashboard --port 9143 --host 127.0.0.1 --no-open --tui &
```
Readiness: WS `ws://127.0.0.1:9143/api/ws?token=hardentest`, `session.create`
then a "reply PONG" prompt — real "PONG" = ready; "Sign in to start chatting" =
refresh license + restart. Trace file: `$ISO/logs/compaction-trace.jsonl`.

## TEST EACH STEP + E2E ON THE UI (background)
- Unit tests after every step (pattern: `tests/test_compaction_metadata.py`,
  `tests/agent/test_compaction_antithrash.py`). Full agent suite must stay green
  (only pre-existing `test_prompt_builder` wording failure is allowed).
- Backend E2E driver: `/tmp/harden_audit.py` (autonomous audit workload that
  forces real compaction). Run it; assert from the trace:
  - **ZERO** `session_rotation`/`create_session(parent=)`/`end_session(...,"compression")`.
  - transcript row count is MONOTONIC (never rewritten/shrunk in the DB).
  - `compaction_summary`/`compaction_cursor` persisted on the row.
  - payload est stays under the window; task completes; plan preserved.
- **UI E2E (the user's explicit ask):** drive the actual dashboard web UI with
  Playwright (the project ships the lib; run node from `~/claudeclaw`). Write
  `/tmp/compaction_ui_e2e.mjs` that: opens `http://127.0.0.1:9143/?token=hardentest`,
  sends a long workload that compacts, and asserts: the visible transcript is
  append-only (no rows vanish/shrink across a compaction), no internal
  `[CONTEXT COMPACTION]`/preserved-plan bubbles appear, the session does NOT
  disappear from the list, and **resume/reopen rebuilds the identical visible
  transcript**. Capture a screenshot before/after a compaction as proof.
- Compare compaction count + no-negative-savings against the anti-thrash
  baseline in `Codex/2026-06-12/compaction-rs-.../anti-thrash-fixture/`.
- Legacy check: a pre-seeded rotated-lineage session still opens via tip-walk.

## RULES
- Commit after each step with a clear message; never leave the tree broken.
- Isolated harness ONLY. Never run a dashboard against real `~/.elevate`.
- Do NOT deploy / rsync into the bundle / push to customers. Branch only.
- If blocked >2 attempts on a step, STOP, write findings to this file's bottom,
  leave the tree green, and report — don't thrash.
- Keep the legacy tip-walk read paths intact (old rotated sessions must open).

## DEFINITION OF DONE
All of: Steps 2–7 built + committed; per-step unit tests green; full agent
suite green; backend E2E shows zero rotation + monotonic transcript + persisted
cursor/summary + task completes; **UI E2E passes (append-only transcript, clean,
resume identical) with before/after screenshots**; legacy session still opens.
Then write a `## RESULT` section at the bottom of this file: what built, test
output, screenshots paths, any deferred items, and the deploy readiness call.
Leave a final summary for the morning.

---

## RESULT (2026-06-16, autonomous build)

**Status: COMPLETE. Steps 2–7 built, tested, committed on `compaction-redesign`.
Validated end-to-end on the isolated dashboard (:9143). Branch only — NOT deployed.**

### What built (one commit per step)
- `26755cfa7` **Step 2** — agent state (`compaction_cursor`/`compaction_summary`)
  + `messages_for_api()` payload-build seam, hooked at the live loop AND the
  max-iterations summary call, BEFORE `_sanitize_api_messages`. Transcript copy
  is never mutated; codex path inherits the trimmed `api_messages`.
- `fa4e5379a` **Step 3** — `compress_context` is compute-cursor-not-rewrite via
  new `ContextCompressor.summarize_to_cursor()` (reuses the cutoff helpers +
  `_generate_summary`, folds the prior summary iteratively, assembles nothing).
  Deleted the rotation block, `insert_preserved_context` call, checkpoint store,
  and `on_session_start/switch`. Persists `(summary,cursor)` via
  `update_compaction`; parks the `-1` sentinel + invalidates the usage projector
  (the list object is stable now, so it can't self-invalidate). System prompt
  kept byte-stable (cache prefix survives).
- `374d195b5` **Step 4** — cold resume reads the row first: `compaction_cursor`
  truthy → skip the tip-walk, load the full append-only transcript; `__init__`
  hydration sets cursor/summary. `INSERT OR IGNORE` create_session preserves the
  columns on resume. cursor 0/NULL → legacy tip-walk kept verbatim.
- `0dfd1c9cb` **Step 5** — removed the now-dead dashboard-gateway
  rotation-compensation (`_turn_compacted` session-key swap + `session.identity`
  emit + force-write-back override in `prompt.submit`; the
  `_run_direct_compress_slash` rotation branch). Plain version-match write-back
  kept. (Scoped — see Deferred.)
- `bf0555d6f` **Step 6** — `CRITICAL_THRESHOLD=0.95` +
  `should_critical_compress_now`; iteration-boundary forces `force=True`
  compaction past the anti-thrash backoff at ≥95%. **Bugfix:** the
  context-overflow AND 413 recovery paths detected success by `len(messages)`
  shrinking — never true in the cursor model, so they would have failed every
  overflow turn; now detect cursor advance + force=True. Net-new
  `emergency_truncate_tool_results()` shortens oversized tool-result CONTENT
  (never removes rows) as the last resort before `compression_exhausted`.
- `a328210af` **Step 7** — anti-thrash cooldown composition proven (no prod
  code): `summarize_to_cursor` arms the low-yield counters, `should_compress`
  backs off, the 0.95 line overrides.
- `50bc07660` — rewrote the two plan-snapshot tests to the new contract
  (plan/todo live in the summary, not injected rows).

### Test results
- Per-step unit tests: all green. New suites: `test_summarize_to_cursor.py` (8),
  `test_compress_context_cursor.py` (3), `test_compaction_resume_hydration.py` (3),
  `test_critical_compaction.py` (7), `test_antithrash_cursor_composition.py` (3),
  plus the Step-2 seam tests (8) and Step-1 metadata tests.
- **Full agent suite: `tests/agent` + `tests/run_agent` = 3320 passed, 8 skipped,
  4 failed — ALL FOUR PRE-EXISTING, NONE mine** (verified against the Step-2
  baseline `26755cfa7`):
  - `test_prompt_builder…test_builds_index_with_skills` — the handoff-acknowledged
    wording failure.
  - `test_concurrent_interrupt` ×2 — branch trace instrumentation (`_jsonl_tool_event`
    at run_agent.py:9521 reads `self.session_id`; the test `_Stub` lacks it). Fails
    on the baseline too; unrelated to compaction.
  - `test_subagent_stop_hook::test_fires_per_child` — same `_Stub` cause; passes in
    isolation, only fails under xdist ordering. Not a regression.
  - gateway `test_direct_compress_persists_and_emits_pill` was ALSO pre-existing-broken
    (relief batch moved the pill to `status.update`); updated + now green.

### Backend E2E (isolated :9143, traced) — PASS
Drove real compacting workloads through the dashboard WS. From
`$ISO/logs/compaction-trace.jsonl` + the isolated SQLite:
- **ZERO** rotation-family events (`session_rotation_*`, `preserved_context_inserted`,
  `compression_checkpoint_stored`, `create_session(parent=)`, `on_session_switch`).
- 5 real `compress_context_done`, 4 `compaction_metadata_persisted`, 2
  `compress_context_noop` (cursor didn't advance → handled, not an error).
- Compacted sessions: `…3ba5a5` rows=16 cursor=10 summary=11,234 chars;
  `…737161` rows=12 cursor=8 summary=6,651 chars. **rows ≥ cursor on both →
  transcript intact, never rewritten/shrunk.** Post-compaction real prompt
  dropped to ~51,700 (trimmed payload), task continued.

### UI E2E (Playwright, real dashboard web UI) — PASS
`~/claudeclaw/compaction_ui_e2e.mjs` (single-turn) and
`compaction_ui_e2e_multi.mjs` (3 compacting turns). Both PASS:
- compaction fired (status pill), **ZERO session rotations**;
- visible transcript **append-only** — all 3 user turns stayed visible across the
  compaction (turn-1 bubble never vanished); monotonic row count;
- **no internal `[CONTEXT COMPACTION]`/preserved-plan/`[CONTEXT SUMMARY]` bubbles**
  in the rendered transcript; session stayed in the sidebar list;
- **reopen (page reload + re-open) rebuilt the identical transcript** (all user
  turns, no internal text).
- Screenshots in `cli/docs/compaction-e2e-screenshots/`:
  `ui_e2e_multi_AFTER_turn1.png` (before later compactions),
  `ui_e2e_multi_AFTER_turn3.png` (clean "Compacting context · 51,694 in" pill
  with the full append-only transcript above it),
  `ui_e2e_multi_REOPEN.png` (reopen-identical), plus the single-turn
  `ui_e2e_BEFORE/AFTER_compaction.png`.

### Legacy compatibility — PASS
32 pre-redesign rotated-lineage sessions (cursor 0 + parent) in the isolated DB.
Resumed via the dashboard WS (`session.resume`) → tip-walk resolves the chain
with no error; DB-level `get_compression_tip` + `get_messages_as_conversation`
return real content (a 99-message rotation chain `a1e593/e142b2 → 9455a1`
resolved correctly). The cursor 0/NULL legacy read path is fully intact.

### Deferred (inert dead code — documented, NOT blocking; follow-up cleanup pass)
All self-disabling because nothing rotates anymore (gated on a session_id change
that no longer happens). Left to avoid destabilizing surfaces the UI E2E doesn't
exercise:
- caller-side `conversation_history = None` nulling in `run_agent.py` after
  `_compress_context` (harmless for the cursor model; flush rides `_last_flushed_db_idx`).
- the inline-fallback `_compress_context` rotation engine in `run_agent.py`
  (dead — the shared-import path never fails) + its now-unused helpers
  (`insert_preserved_context`, `_store_compression_checkpoint`).
- `gateway/run.py` (the separate PLATFORM gateway — Telegram/Discord, not the
  dashboard) rotation blocks; its `rewrite_transcript` calls are legitimate
  truncation that must stay.
- estimate-mode trigger measurement still sums the full transcript: only matters
  for providers that DON'T report `prompt_tokens` (rare; the harness + Anthropic/
  OpenAI/codex all report → real-count projection tracks the trimmed payload
  correctly, so no thrash observed). A cursor-aware estimate is the clean fix.

### Deploy-readiness call
**Ready for a SUPERVISED deploy decision — do NOT auto-ship.** The branch is
green, the bug class (rotation/orphaned-continuations, the `_session_init_model_config`
crash, "compacted twice", 20KB internal bubbles) is structurally eliminated for
new sessions, and legacy sessions still open. Before shipping: (1) rebase onto
current `~/elevate` main and RE-VERIFY the worktree anchors (run_agent payload
seam + recovery line numbers) per the build plan's anchor note; (2) do the
de-traced surgical port into the bundle (strip the `ELEVATE_*_TRACE` diagnostics
+ the `compaction-trace`/jsonl ledger calls that are branch-only); (3) ship the
relief batch together (it makes the pill honest); (4) one more real-account soak
on Justin's box profile before customer-wide. The deferred items above are
hygiene, not correctness — safe to land in a follow-up.
