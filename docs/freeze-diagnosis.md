# Multi-Agent UI Freeze — Diagnosis (2026-06-03)

Step 2 of the feature stress test (nested "agent team": orchestrator role, depth 2,
concurrency 4) froze/glitched the desktop app. The user had to restart it. This is the
evidence-led diagnosis.

## What it is NOT (ruled out with evidence)
- **NOT the blank bug.** That's a `setMessages` state wipe; it's fixed + verified. No
  `LIST WIPED` involved here.
- **NOT a backend crash.** `agent.log` shows the Python side kept running through the
  freeze window (title generation fired at 16:35). No traceback at step-2 time.
- **NOT a native crash.** No `.ips` crash report, no Crashpad `.dmp`, no Electron
  `render-process-gone`. The Electron **main** process stayed alive the whole time
  (kept polling for updates + logging window-focus events). The user reopened the window.
- **NOT a UI rendering cost.** Built a synthetic event-flood profiler
  (`~/claudeclaw/scripts/freeze-profile.mjs`): injects tool/subagent/activity events
  through the live `GatewayClient.dispatch()` seam (`window.__elevateChatGateway`, gated
  behind `localStorage.__elevate_expose_gw="1"`), spread across animation frames.
  **Result: 400 events/class = 0ms long-task time, steady 9ms frame gaps (60fps), on both
  big and small chats.** The render path is already well-optimized: assistant deltas are
  throttled (50ms flush, ChatPage ~2856), message rows are memoized (`MemoMessageRow`),
  tool/subagent arrays are capped (`slice(-TOOL_LIMIT)`, `slice(-12)`). So UI event volume
  is not the bottleneck — the "throttle the events" fix I was about to write would have
  been wasted. (Aside: a "145-message" chat renders only ~6 visible bubbles —
  `message_count` counts tool/system rows; `visibleMessages` collapses them.)

## What it most likely IS (resource exhaustion from nested delegation)
- `delegate_task` runs children in a **ThreadPoolExecutor (in-process threads)**, not
  subprocesses (`cli/tools/delegate_tool.py:28,59`).
- A **depth-2 orchestrator** (`role: "orchestrator"`) spawns a *tree*: orchestrator(1) →
  up to `max_concurrent_children` leaves. At the crash, concurrency was **4**, so ~5–6
  child AIAgent threads ran at once **inside one Python process**, each doing GIL-bound
  work (JSON, tool dispatch) + its own Codex network streaming + a memory-provider init.
- That process also serves the renderer's gateway WebSocket. When the child threads
  saturate it, the **WS event loop starves** → the renderer stops receiving events/pings
  → the window appears frozen/glitched. Consistent with: main process alive, backend not
  crashed, only the *chat view* froze.
- Aggravator seen in logs: the **holographic memory provider** repeatedly fails with
  Postgres `FATAL: sorry, too many clients already` (max_connections=100). Each agent/child
  that inits memory opens a PG connection; under churn/fan-out they pile up (likely a
  connection leak — connections from my 135-relaunch churn were still showing at 15:29).
- **Step 1 (flat, 3 leaves) survived; Step 2 (nested, ~6 concurrent) froze** — the
  difference is total concurrent in-process agent load, which fits the resource-exhaustion
  model, not a render model.
- Plugin discovery is **cached per-process** (`PluginManager._discovered`, `plugins.py:797`)
  so children do NOT reload 23 plugins each — that earlier suspicion is ruled out.

## Mitigation already applied
- `~/.elevate/config.yaml`: `delegation.max_concurrent_children` **4 → 2** (lighter
  in-process load), `max_spawn_depth` kept at 2 so teams still work. Backup saved.

## To CONFIRM the mechanism (next step — needs a live monitored run)
Re-run Step 2 at concurrency 2 while sampling, once per second:
- `ps` thread count + CPU% of the dashboard/worker python process,
- PG `select count(*) from pg_stat_activity` (watch it climb toward 100),
- WS responsiveness (a cheap `/` ping latency from the renderer side).
If it survives at 2 → mitigation works. If PG climbs to ~100 and stalls → the memory-
provider connection leak is the real bug. If CPU pins and WS latency spikes with PG fine →
it's GIL/WS starvation → fix by capping TOTAL tree concurrency and/or moving agent work
off the WS-serving process.

## Candidate real fixes (pick after the confirming run)
1. **Cap total concurrent agents across the whole tree** (not just per-parent) — depth ×
   concurrency currently multiplies.
2. **Fix the holographic memory PG usage** — pool/reuse connections, or skip holographic
   init for short-lived subagents, or fall back cleanly when PG is saturated (stop the
   retry storm).
3. **Isolate the gateway WS loop** from agent compute (separate thread/process with
   priority) so a busy fan-out can't freeze the renderer.
4. Keep concurrency conservative by default for `orchestrator` trees.

Profiler kept at `~/claudeclaw/scripts/freeze-profile.mjs` for re-use.

---

## FIXES IMPLEMENTED (2026-06-03)

Two backend fixes (no UI change — the profiler proved rendering wasn't the cost).

### Fix 1 — global leaf-concurrency cap (`cli/tools/delegate_tool.py`)
- New module-global `BoundedSemaphore` (`_get_leaf_semaphore`, default size 3 via
  `delegation.max_total_concurrent` / `DELEGATION_MAX_TOTAL_CONCURRENT`, clamped [1,16]).
- Acquired/released around the child run in `_run_single_child`. **Only LEAF agents
  acquire** — orchestrators run free, which avoids the holds-slot-waits-for-leaf deadlock.
  Bounded 120s wait then proceeds (degrade to slower, never hang).
- Caps total concurrent real-work agents across the whole tree regardless of how many
  orchestrators/levels exist. Per-parent `max_concurrent_children` (now 2) still applies.
- Verified: `_get_leaf_semaphore()` → BoundedSemaphore size 3; acquire pattern
  `[True,True,True,False,False]` (caps at 3). Existing delegate tests pass single-process
  (the 2 "failures" in the parallel run are xdist pollution — green when run alone).

### Fix 2 — holographic Postgres connection leak (`server.py` + `run_agent.py`)
- Root cause: the gateway dropped/replaced `session["agent"]` at three sites WITHOUT
  closing the old agent's holographic PG connection (opened `autocommit=False`, so it sits
  as "idle in transaction"): `_reset_session_agent`, the resume re-attach (~2348), and
  `session.close` (~2575). Each reset/close/resume orphaned one connection → they pile up
  into `FATAL: too many clients already` over a long-lived dashboard process.
- New `AIAgent.close_memory_connections()` — closes provider connections via
  `memory_manager.shutdown_all()` WITHOUT running `on_session_end` (no mid-session
  consolidation, since a reset/resume isn't a real session end).
- New `server._release_agent_memory(agent, *, ended)` wired at all three drop sites:
  `ended=False` (connection-close only) for reset + resume-replace, `ended=True` (full
  `shutdown_memory_provider`, runs on_session_end) for genuine `session.close`.
- Verified live: after 40 resume-replace flips, holographic ("idle in transaction")
  connections held steady at **2** (the live agents) instead of climbing — without the fix
  each flip would orphan one. Total PG ~32 is slash_workers/pool, not holographic.

### Caveat / separate follow-up (NOT fixed, flagged)
- The live run showed ~17 app `slash_worker` processes + ~32 total PG connections after
  churn, and there is **no session reaper** (sessions only clean up on explicit
  `session.close`). `_restart_slash_worker` DOES close the old worker (no per-reset leak),
  but long-lived sessions accumulate workers+connections until closed. Bounded by session
  count, but a heavy multi-session day with no closes trends connections upward. Worth a
  session TTL/idle-reaper or a worker cap later — distinct from the two fixes above.

### Decisive integration test still to run
Re-run stress-test Step 2 (nested orchestrator) at `max_concurrent_children=2` with both
fixes loaded. Expect: no freeze, total concurrent leaves ≤ 3, holographic connections flat.
