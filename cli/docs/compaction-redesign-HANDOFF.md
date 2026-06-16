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
