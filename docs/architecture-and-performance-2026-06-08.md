# Elevate Agent — Architecture & Performance Pass (2026-06-08)

Read-only audit. Four parallel readers mapped the runtime, data layer, web/gateway/cron, and desktop process model. Every claim below cites `file:line`. Nothing was changed.

---

## 1. The runtime topology (the thing to "get down")

Three **independent** process trees. They do not share a parent and only loosely coordinate over localhost HTTP + shared files. This is the single most important architectural fact about Elevate, and the source of most of the operational gotchas in the primer.

```
┌─ Electron main (desktop/src/main.js, 1439 lines) ──────────────────┐
│   • Renderer BrowserWindow → http://127.0.0.1:9119/chat            │
│   • Overlay window (computer-use glow)                             │
│   • SMS-outbox watcher (1.5s setInterval) — drains sms-outbox/*.req│
│   • Updater poll (3min + on focus)                                 │
│   spawns ↓                                                          │
│   ┌─ Dashboard child (BUNDLED python3.12) ──────────────────────┐  │
│   │  Contents/Resources/runtime/python  +  bundled cli/         │  │
│   │  `elevate_cli.main dashboard --port 9119`                   │  │
│   │  = uvicorn + FastAPI, 1 worker, ~360 routes, 4 websockets   │  │
│   │  cwd = ~/Elevation                                          │  │
│   └─────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘

┌─ launchd gateway  ai.elevate.gateway  (SEPARATE, long-lived) ──────┐
│   <repo>/.venv/python -m elevate_cli.main gateway run --replace    │
│   cwd = PROJECT_ROOT,  RunAtLoad, KeepAlive                        │
│   • messaging platforms (telegram/discord/feishu/…)               │
│   • the cron ticker (60s) → heartbeats + automations              │
│   • persistent in-process GatewayRunner (agent cached, LRU)       │
└────────────────────────────────────────────────────────────────────┘

Shared state between trees:  license.json (both read) · sms-outbox/*.json
(GUI drains, headless backend can't reach macOS Messages) · computer-use-active
mtime file · FanoutTransport WS (cron sessions broadcast into the dashboard).
```

**The split-brain (root of the recurring pain):** the dashboard runs the *bundled* interpreter + bundled `cli` code; the gateway runs the *repo `.venv`* + working-tree code (`gateway.py:2531,2588` vs `main.js:366-393`). After a desktop auto-update the GUI ships new code but the launchd gateway keeps running the OLD working tree until `launchctl kickstart -k gui/$(id -u)/ai.elevate.gateway`. That is exactly the "no account-scoped cron running" incident in the primer. Cron/heartbeats live in the gateway; SMS sends + computer-use live in the GUI — the split is by design but nothing supervises both as one unit.

### Agent turn flow (how one message executes)
Gateway/CLI builds an `AIAgent` (`run_agent.py:__init__`) → `run_conversation` forwards to `agent/conversation_loop.py:233`. Per-turn setup (`:263-650`): db session, system-prompt restore-or-build, preflight context compression, one-time memory prefetch. Main loop (`:652`) per iteration: rebuild `api_messages` from history, apply Anthropic cache_control, sanitize, estimate tokens, `_build_api_kwargs` → cached transport → streaming API call → tool dispatch via `model_tools.handle_function_call` → `registry.dispatch`. The gateway caches built agents (LRU + idle-TTL, `gateway/run.py:1505`), so full reconstruction is per cache-miss, not per message.

### Data topology
Four stores, intentionally fragmented:
- **Embedded Postgres, per-account** — the operational store. One DB per login: `elevate_op_<account_key>`, `account_key = "acct_"+sha1(lowercased license email)[:16]` (`elevate_constants.py:70-103`). Runs as in-process `pgserver` (PG16) over a **Unix socket**, data in `$ELEVATE_HOME/pgdata/`. **Local — the Supabase ~68ms RTT stall does NOT apply here.** Pooled (`connection.py:99-173`, min 1 / max 20).
- **SQLite** — external read-only sources only (Apple chat.db, connector indexes, legacy state.db).
- **Supabase / HQ** — license + auth only.
- **JSON / JSONL on disk** — heartbeat surfaces, cron jobs, buyers/tasks/lead-events. Read + parsed live on dashboard requests.

A SQLite-dialect → Postgres **translation shim** (`connection.py:229-451`) rewrites `?`→`%s` and `INSERT OR IGNORE`→`ON CONFLICT` per execute, so 60+ legacy callers stayed unchanged when the store moved from SQLite to PG. This shim is load-bearing infra.

---

## 2. Performance findings — prioritized

### P0 — fix now (correctness-adjacent or cheap + high impact)

| # | Finding | Evidence | Fix |
|---|---------|----------|-----|
| 1 | **`update_elevate` blocks the whole event loop.** It's `async def` but calls `subprocess.run(...)` synchronously — the entire dashboard (every async route + WS heartbeats) freezes for the duration of an update/build. | `web_server.py:1951` + `:1977` | `await asyncio.to_thread(...)` or `create_subprocess_exec`. |
| 2 | **`SessionDB()` rebuilt per request** — new SQLite conn + `_init_schema()` on every call across 15 hot sites incl. `/api/sessions`, `/api/sessions/{id}/messages`. Adds WAL write-lock contention (its own docstring warns). | `web_server.py:1001,3008,3036,4595,4611,4639,4702,4930,4958,5010,5028,5048,5071,11114,11143`; `elevate_state.py:501-525` | Cache one module-level instance, mirror the existing `_get_db()` pattern at `web_server.py:332`. |
| 3 | **`load_config()` is uncached** — re-reads YAML + `copy.deepcopy` of a ~200-line default dict + deep-merge + env-expand on every call; sits behind `_model_supports_vision` which runs per API iteration on image turns. | `config.py:3831-3857`, `:487`; `run_agent.py:7848` | Memoize on `(path, mtime_ns, size)` — the warn-cache already does exactly this nearby. |
| 4 | **Cron `ensure_system_jobs()` runs every 60s** — 6 ensure-* functions (admin sync, op-maintenance, op-freshness, surface heartbeats, automations, theta-wave) each touch the FS/registry every tick. Idempotent *setup* work on a hot loop. | `scheduler.py:2448` → `jobs.py:982`; ticker `run.py:13572,13601` | Run at startup + on-change (dirty flag), or every N ticks. Same for the full `load_jobs()` deepcopy every tick (`jobs.py:2034`). |

### P1 — high value, low risk

| # | Finding | Evidence | Fix |
|---|---------|----------|-----|
| 5 | **No response compression** anywhere — large JSON lists (`/api/comms/feed` 200, `/api/heartbeats/experiments`, `/api/sessions`) ship uncompressed on a WS-heavy dashboard. | no `GZipMiddleware` in `web_server.py` | Add `GZipMiddleware`. One line. |
| 6 | **Memory plugin serializes ALL access through one non-pooled connection + global RLock** — bypasses the 20-conn pool; concurrent dashboard + agent memory access is a hard serialization point. Plus `_prepare_sql` regex on every execute incl. hot recall. | `holographic/store.py:399-432,460-461`; `connection.py:249-304` | Pool the memory connection or narrow the lock to writes; short-circuit the regex when SQL is already `%s`-native. |
| 7 | **Redundant per-iteration serialization** — message text `str()`-ified ~3× per loop iteration; `estimate_request_tokens_rough` re-stringifies all 50+ tool schemas every iteration though tools are immutable per session. | `conversation_loop.py:938-940`; `model_metadata.py:1825-1827` | Compute the message-token estimate once per iteration; cache `len(str(tools))` on the agent. |
| 8 | **Tool schemas rebuilt on every agent construction** — `get_tool_definitions` re-resolves toolsets + rebuilds dynamic schemas; the memo the comments claim does not exist. | `model_tools.py:234,303`; `registry.py:369` | Memoize on `(enabled, disabled, config-mtime)`. |
| 9 | **`SELECT *` over wide tables on dashboard hot paths** — pulls large JSON blobs (`searches_json`, `matching_listings_json`) when few columns are used. | `reads.py:288,1042,1056,1061`; `kanban_db.py:1344,1375` | Project explicit columns. |
| 10 | **List endpoints scan the filesystem per call, no cache** — `/api/heartbeats/surfaces` walks every surface dir; `/api/activity` globs+reads up to 30 JSON/agent each request. JSONL (`lead-events.jsonl` 4000 rows) re-parsed per render. | `web_server.py:6772,7573`; `reads.py:252-265,1313,1329` | mtime-cache the surface/activity scans; index or cap the JSONL tails. |

### P2 — cold start (every launch is slow)

| # | Finding | Evidence | Fix |
|---|---------|----------|-----|
| 11 | **Bytecode never cached → every launch re-parses .py from source.** `PYTHONDONTWRITEBYTECODE=1` is set AND bundled `.pyc` is stripped. The pycache *prefix* is set (writable, outside the bundle) but writes are disabled, so it never helps. | `main.js:312-318`; `package.json:45-46` | The `.pyc` strip existed to protect the codesign seal. But the prefix already points to `~/Library/Caches` — **outside** the signed bundle. So: **drop `PYTHONDONTWRITEBYTECODE`, keep `PYTHONPYCACHEPREFIX`.** Bytecode caches to Caches, the seal stays clean, 2nd+ launches skip parsing. Safe now that differential updates are off (1.1.28). |
| 12 | **Sync seed work runs before the server binds** — `sync_skills()` + `reconcile_agent_hub_defaults()` delay the port going live, extending the renderer's poll. | `main.py:7027,7034` | Bind first, run seed work in a background thread. |
| 13 | **Readiness = 500ms busy-poll, up to 360×, two HTTP GETs each (incl. full 1MB `/` body).** Plus `chooseBackendPort` can fire ~22 sequential 2s probes before spawn. | `main.js:544-552,555-577,514` | Emit a stdout readiness sentinel from the child; drop the HTML-string sniff. |

---

## 3. Architecture smells (the "get it down" cleanup list)

1. **God files.** `gateway/run.py` 14,057 lines · `run_agent.py` 13,768 · `web_server.py` 12,242 (~360 routes) · `cli.py` 11,248 · `main.py` 10,157 · `cron/scheduler.py` 113KB · `cron/jobs.py` 94KB. `run_conversation` is one ~3,900-line function with ~30 local boolean state flags (`conversation_loop.py:992-1006`). This is why the architecture feels un-graspable — it isn't modularized.
2. **Dual-runtime split-brain** (§1). The gateway and dashboard run different interpreters + different code copies; they diverge after every update until manual `kickstart`. Electron even "self-heals" a launchd service it doesn't run, via the *dashboard's* launcher (`main.js:443-477`) — two code paths own the same service. **Recommend:** have Electron supervise one Python tree, or auto-`kickstart` the gateway as part of the post-update hook so the two never diverge silently.
3. **SQLite-dialect-over-Postgres as load-bearing infra.** The store moved to PG but callers/dataclasses still type `sqlite3.Connection`/`sqlite3.Row` and catch both `sqlite3.IntegrityError` and `psycopg.UniqueViolation` (`kanban_db.py:665,1316`). Two migration trees coexist (`migrations_pg/` 0001-0023 + legacy `migrations/` 0001-0028) with overlapping numbers meaning different things. Decide: commit to native PG and migrate callers, or formally bless the shim and delete the SQLite migration tree.
4. **Dead kanban "boards" abstraction.** ~340 lines of board-path resolution still write `board.json` to disk, but task rows ignore boards entirely (collapsed onto one PG tableset, `kanban_db.py:993-997`); `remove_board` warns it doesn't remove tasks. Heavy on-disk machinery with no DB effect — delete it.
5. **Routes fused with business logic.** No service layer — handlers inline FS scans, HTTP calls, and JSON shaping in the route body. Duplicated endpoint pairs kept in parallel (`/api/messages/send` + `/api/comms/messages`, `tasks`+`surface-tasks`, `approvals`+`surface-approvals` — `web_server.py:7771,8428,8462,8499,8521`). Per-handler lazy re-imports (~12 sites).
6. **Ticker is a monolithic side-effect loop** — `_start_cron_ticker` (`run.py:13572-13678`) hard-codes 6 unrelated concerns with `tick_count %` modulo inline. Should be a registry of scheduled tasks.
7. **Provider-specific branching in the hot loop** — nous/codex/anthropic/bedrock/qwen/minimax special-casing inline in the conversation loop instead of behind the `_get_transport` abstraction that already exists (`conversation_loop.py:1017-1251`, `run_agent.py:7884-7978`).

---

## 4. Suggested sequence

1. **P0 batch (1-2 hrs, big felt win):** #1 event-loop unblock, #2 SessionDB cache, #3 config memo, #4 cron-tick gating. Low risk, all hot-path. → dashboard feels snappier, cron stops thrashing the FS.
2. **P2 #11 (cold start):** drop `PYTHONDONTWRITEBYTECODE` — biggest launch-time win, safe post-1.1.28. Ship in the next desktop build.
3. **P1 batch:** gzip, memory-lock, per-iteration serialization, tool-schema memo, SELECT * projection, FS-scan caching.
4. **Structural (own session each):** decide the dual-runtime supervision model (#2 smell) and the PG-shim direction (#3 smell); delete dead boards code (#4); start carving a service layer out of `web_server.py`.

P0+P2#11 are the highest ROI and lowest risk — that's where I'd start if you want to apply fixes.
