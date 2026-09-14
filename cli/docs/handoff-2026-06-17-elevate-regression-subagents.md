# Handoff: Elevate 1.2.49 regression stabilization and subagent work

Date: 2026-06-17
Repo: `/Users/dartagnanpatricio/elevate`
Branch: `main`
Current HEAD: `18669d395 fix(subagents): persist live steer messages`
Desktop package version: `1.2.49`
Repo state at handoff: `main` is 19 commits ahead of `origin/main`

## Critical context

This work started after `1.2.48` shipped and Justin, the only current customer, began testing the live Elevate app. Several UI/runtime regressions showed up in the installed Electron app:

- reasoning/thinking rows were rendering as broken one-line summaries or duplicated grey "Thinking..." placeholders
- completed reasoning collapsed/truncated after the final answer
- manual `/compact` did not look like automatic compaction and sometimes showed old "compression" language
- gateway disconnect/errors were appearing as transcript rows
- repeated user prompts could appear out of order or at the bottom after restarts
- PDF/preview surfaces regressed
- background subagent cards could stay stuck as running
- subagent completed events appeared visually out of order or did not reliably return to the parent timeline
- opening a running subagent did not replay its full prior thinking/tool timeline
- steering a running subagent from the child chat behaved like a new resumed turn instead of a parent-style mid-turn steer
- after closing/reopening the app, a mid-turn child steer could disappear

The user is testing the real installed app, not localhost:

`/Users/dartagnanpatricio/Applications/Elevate.app`

For visible app testing, patch both repo source and the copied installed bundle under:

`/Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/`

Do not rely on localhost-only verification for these issues.

Do not run `npm run release:apple` without explicit user approval.

## Release/history notes

Earlier release diagnosis:

- `1.2.48` had already gone out before the later local fixes.
- The release mechanism itself was verified as hardened:
  - `disableDifferentialDownload = true`
  - signed/notarized Apple release path
  - blockmaps purged so old stuck clients fall back to full downloads
  - feed is `https://api.elevationrealestatehq.com/updates`
- The next customer-visible patch should be `1.2.49`.
- `desktop/package.json` and `desktop/package-lock.json` are already bumped to `1.2.49` in commit `2001fa6e1`.

Justin is the only customer, so the live release is effectively the soak. There is no separate broader customer group right now.

## Current commit stack

Latest local commits on `main` include:

```text
18669d395 fix(subagents): persist live steer messages
0203b2984 fix(chat): reap stale subagent running state
dc36c88b1 fix(chat): keep live child steers in one turn
e03c0a3eb fix(chat): route live subagent messages in dashboard
0d71ad6a1 feat(subagents): add live child messaging
bf2174c63 fix(delegate): preserve installed agent parity
2001fa6e1 chore(desktop): bump version to 1.2.49
ab373d808 fix(chat): replay running subagent drill-ins
38cc4aaf7 fix(chat): order subagent completion UI
c9365f245 fix(chat): preserve repeated prompts and stale subagents
e36158de2 fix(chat): remove pending thinking placeholder
261b420b2 fix(chat): stabilize completed response rendering
fe154a4c2 fix(chat): repair inverted first-turn transcript order
26fd870d7 fix(chat): keep gateway disconnects out of transcript
56a8c9aa1 fix(chat): render manual compact like auto compact
ea81e430a fix(chat): lock activity digest visibility
6041f62c4 fix(chat): keep completed reasoning expanded
9337d4b30 fix(agent): route admin skill delegation
```

Run this to refresh:

```bash
cd /Users/dartagnanpatricio/elevate
git status --short
git log --oneline -20
git rev-list --count origin/main..HEAD
node -p "require('./desktop/package.json').version"
```

At handoff, only these docs were untracked:

```text
cli/docs/compaction-redesign-buildplan.md
cli/docs/session-flight-recorder-buildplan.md
cli/docs/handoff-2026-06-17-elevate-regression-subagents.md
```

`cli/docs/compaction-redesign-buildplan.md` existed before this final handoff and should stay untouched unless explicitly requested.

## What is currently patched into the installed app

The installed app was patched and restarted after `18669d395`.

Copied into `/Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/`:

- `run_agent.py`
- `tools/delegate_tool.py`
- `tui_gateway/server.py`
- rebuilt `elevate_cli/web_dist/`

The built chat asset in the installed app at handoff:

```text
/Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/elevate_cli/web_dist/assets/ChatPage-D-hVtBci.js
timestamp: Jun 17 11:45:34 2026
```

The app was fully quit, old bundled Python workers were reaped, and reopened so fresh bundled `dashboard` and `gateway run --replace` processes import the patched files.

Check live installed-app processes:

```bash
pgrep -fl "Elevate|elevate_cli|dashboard --port 9120|gateway run"
```

Expected relevant processes:

- `/Users/dartagnanpatricio/Applications/Elevate.app/Contents/MacOS/Elevate`
- bundled Python `-m elevate_cli.main dashboard --port 9120 --host 127.0.0.1 --no-open --tui`
- bundled Python `-m elevate_cli.main gateway run --replace`
- bundled Postgres under `.elevate/pgdata`

There may also be a separate Hermes gateway process. Do not confuse that with Elevate.

## Verified fixes and tests

### Stale subagent running state

Commit:

`0203b2984 fix(chat): reap stale subagent running state`

Purpose:

- if the app is closed while child subagents are "running", reopen should not leave fake running cards forever
- stale child rows absent from the live registry are reaped as `delegation_interrupted`

Tests run:

```bash
cli/.venv/bin/python -m py_compile cli/elevate_state.py cli/elevate_cli/web_server.py
cli/.venv/bin/python -m pytest cli/tests/test_hermes_state.py -k finalize_interrupted_delegate_children -q
PATH=/Users/dartagnanpatricio/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npm --prefix cli/web run build
```

Result:

`3 passed` for the stale-child test slice. Web build passed.

### Durable live child steer messages

Commit:

`18669d395 fix(subagents): persist live steer messages`

Root cause:

- `subagent.message` previously queued the steer into the live child agent only in memory.
- The child transcript row was persisted only later, when the child applied the steer.
- If the app closed before `steer.applied`, the child runner died, stale-child cleanup closed the child, and the user's steer had no DB row to hydrate. The steer disappeared.

Fix:

- `tools.delegate_tool.message_subagent(...)` now creates/accepts a stable `steer.*` `client_message_id`.
- accepted child steers are immediately persisted as `role=user` rows in the child session
- `run_agent.AIAgent.queue_soft_interrupt(...)` can carry the same `client_message_id`
- later session flush reuses/skips the existing `steer.*` row to avoid duplicate bubbles
- `subagent.message` gateway response and relay events include `client_message_id`
- parent-to-child delegation steering now goes through `message_subagent(...)` too, so forwarded child steers use the same durable path

Focused tests run after commit:

```bash
cli/.venv/bin/python -m py_compile cli/run_agent.py cli/tools/delegate_tool.py cli/tui_gateway/server.py
cli/.venv/bin/python -m pytest cli/tests/run_agent/test_soft_interrupts.py cli/tests/tools/test_delegate.py::TestLiveSubagentMessaging cli/tests/tui_gateway/test_protocol.py::test_subagent_message_routes_to_running_child_and_parent_ring -q
PATH=/Users/dartagnanpatricio/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npm --prefix cli/web run build
```

Result:

```text
10 passed
web build passed
```

## Audit verdict on latest child-steer fix

The user asked whether the latest fix was overengineered and requested `ponytail` audit. `ponytail` was not installed/exposed in the session, so a read-only local audit was done instead.

Verdict:

The fix is not wildly overengineered. The core idea is right: durable child steers need stable ids and immediate persistence. But the implementation should be tightened before release.

Audit findings:

1. P1: Accepted does not mean durably persisted
   - File: `cli/tools/delegate_tool.py`
   - Line area: `_persist_subagent_steer_message(...)` is called but its boolean is ignored.
   - Risk: UI can report "Message sent to subagent" even if DB persistence failed. If the app closes, the steer can still vanish.
   - Recommended fix: return `persisted: true/false` per target and expose aggregate persistence status through gateway/UI.

2. P2: Same `client_message_id` reused for task-level multi-child routing
   - File: `cli/tools/delegate_tool.py`
   - Line area: id generated once before looping records.
   - Risk: `task_id` routes to multiple children with the same `steer.*` id. Separate child sessions make this less dangerous, but parent event/UI dedupe can become ambiguous.
   - Recommended fix: generate one id per accepted child unless the request explicitly targets one child and provides an id.

3. P2: Frontend still dedupes queued steers by text
   - File: `cli/web/src/pages/ChatPage.tsx`
   - Line area: `heldSteersRef.current.includes(text)` and `queuedInputs` dedupe by text.
   - Risk: identical follow-up text can collapse visually even though backend now emits stable ids.
   - Recommended fix: store held steers as `{ id, text }` and dedupe by id.

4. P2: Duplicate suppression lives in core session flush
   - File: `cli/run_agent.py`
   - Line area: `_flush_messages_to_session_db(...)` now calls `get_messages(...)` to avoid duplicate `steer.*`.
   - Risk: not catastrophic, but it spreads idempotency into a hot persistence path.
   - Recommended fix: acceptable for patch, but long-term add SessionDB helper like `has_client_message_id(session_id, id)` or idempotent append.

5. P3: Parent forwarding re-scans active subagents
   - File: `cli/tui_gateway/server.py`
   - Line area: `_forward_steer_to_children(...)` already finds each child, then calls `message_subagent(...)`, which scans the registry again.
   - Risk: low due to small child counts.
   - Recommended fix: optional cleanup.

Priority follow-up before release:

- fix P1
- fix per-target ids
- make frontend consume/dedupe by ids
- add tests for the above
- rebuild and patch installed app again

## Important code surfaces

Durable steer path:

- `cli/tools/delegate_tool.py`
  - `message_subagent(...)`
  - `_persist_subagent_steer_message(...)`
  - `_active_subagents`

- `cli/run_agent.py`
  - `AIAgent.queue_soft_interrupt(...)`
  - `_soft_interrupt_client_message_id(...)`
  - `_notify_steer_applied(...)`
  - `_flush_messages_to_session_db(...)`
  - stream-cut path around soft interrupts
  - after-text continuation path around soft interrupts

- `cli/tui_gateway/server.py`
  - `subagent.message`
  - `_emit_subagent_message_to_parent(...)`
  - `_forward_steer_to_children(...)`
  - `_on_tool_progress(... event_type="steer.applied")`

- `cli/web/src/pages/ChatPage.tsx`
  - `SubagentMessageResponse`
  - `submitLiveSubagentMessage(...)`
  - `steer.queued` event handler
  - `consumeAppliedSteers(...)`
  - `normalizeStoredTranscript(...)`

Stale child state:

- `cli/elevate_state.py`
- `cli/elevate_cli/web_server.py`
- `cli/tests/test_hermes_state.py`

Installed app patch path:

- `/Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/run_agent.py`
- `/Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/tools/delegate_tool.py`
- `/Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/tui_gateway/server.py`
- `/Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/elevate_cli/web_dist/`

## Manual test prompts for the next session

Use the installed app, not localhost.

### Subagent live steer and app close

Prompt:

```text
Use subagents if helpful. Compare three ways to improve listing conversion: better pricing strategy, better media, and better seller follow-up. Have each subagent focus on one angle, then synthesize one recommendation.
```

While a child is running:

1. Open the child from Background tasks.
2. Send a steer like:

```text
Change course: focus only on seller follow-up objections and give a specific script, not generic strategy.
```

3. Close the app before the child applies it.
4. Reopen the app.
5. Expected after the latest fix:
   - stale child should close as interrupted if the runner died
   - the steer message should still appear in the child transcript
   - it should not disappear when leaving and re-entering the child

### Running child drill-in replay

Prompt:

```text
Use subagents if helpful. Have one subagent research pricing strategy, one research listing media, and one research seller follow-up. Make them work independently for a bit before summarizing.
```

Open a running child mid-run.

Expected:

- prior thinking/tool timeline replays instead of starting only from the moment you opened it
- sending a child message steers that running child, not a duplicate resumed turn

### Compaction UI

Prompt:

```text
For a UI compaction test, create a detailed real estate transaction checklist with 60 specific items. Make it structured, not fluffy.
```

Then run:

```text
/compact
```

Expected:

- manual compaction should look like automatic compaction
- no "compression" old-language card
- should show "Finished compacting" style behavior
- conversation animation should match automatic compaction behavior

### Repeated prompt/order test

Prompt once:

```text
Create a detailed checklist for a BC resale real estate transaction with 40 steps.
```

Restart app mid/after turn, then send a second prompt:

```text
Now shorten it to the top 12 steps and keep the same order.
```

Expected:

- second user bubble remains in chronological order
- no user bubble stuck at bottom under the input area
- no gateway disconnect rows in transcript

### PDF/preview smoke

Use any workflow that creates or opens a PDF preview.

Expected:

- PDF/preview surface renders in installed app
- no blank preview regression

## Good next-session prompt

Paste this into the next session:

```text
We are in /Users/dartagnanpatricio/elevate on main. Read cli/docs/handoff-2026-06-17-elevate-regression-subagents.md first. Do not run release:apple. Continue the stabilization work by tightening the latest durable subagent steer fix: make accepted subagent.message report whether persistence succeeded, generate per-target steer client ids for multi-child routing, update ChatPage queued steer state to dedupe by client_message_id instead of text, add focused tests, rebuild web_dist, patch /Users/dartagnanpatricio/Applications/Elevate.app, restart the installed app, and report exactly what is verified.
```

## Commands likely needed next

Focused tests:

```bash
cd /Users/dartagnanpatricio/elevate
cli/.venv/bin/python -m py_compile cli/run_agent.py cli/tools/delegate_tool.py cli/tui_gateway/server.py
cli/.venv/bin/python -m pytest cli/tests/run_agent/test_soft_interrupts.py cli/tests/tools/test_delegate.py::TestLiveSubagentMessaging cli/tests/tui_gateway/test_protocol.py::test_subagent_message_routes_to_running_child_and_parent_ring -q
PATH=/Users/dartagnanpatricio/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npm --prefix cli/web run build
```

Patch installed app after source/build changes:

```bash
cd /Users/dartagnanpatricio/elevate
APP="/Users/dartagnanpatricio/Applications/Elevate.app"
APP_CLI="$APP/Contents/Resources/cli"
osascript -e 'tell application "Elevate" to quit' >/dev/null 2>&1 || true
RUNTIME="$APP/Contents/Resources/runtime/python/bin/python3.12"
pkill -f "$RUNTIME -m elevate_cli.main gateway run --replace" >/dev/null 2>&1 || true
pkill -f "$RUNTIME -m elevate_cli.main dashboard --port 9120" >/dev/null 2>&1 || true
pkill -f "$RUNTIME -m tui_gateway.slash_worker" >/dev/null 2>&1 || true
rsync -a cli/run_agent.py "$APP_CLI/run_agent.py"
rsync -a cli/tools/delegate_tool.py "$APP_CLI/tools/delegate_tool.py"
rsync -a cli/tui_gateway/server.py "$APP_CLI/tui_gateway/server.py"
rsync -a --delete cli/elevate_cli/web_dist/ "$APP_CLI/elevate_cli/web_dist/"
open -a "$APP"
```

Verify app/bundle:

```bash
pgrep -fl "Elevate|elevate_cli|dashboard --port 9120|gateway run"
cmp -s cli/run_agent.py /Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/run_agent.py && echo "run_agent matches"
cmp -s cli/tools/delegate_tool.py /Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/tools/delegate_tool.py && echo "delegate_tool matches"
cmp -s cli/tui_gateway/server.py /Users/dartagnanpatricio/Applications/Elevate.app/Contents/Resources/cli/tui_gateway/server.py && echo "gateway server matches"
```

## Release reminder

Do not release until:

- latest follow-up audit fixes are committed
- focused automated tests pass
- web build passes
- installed app is patched/restarted
- manual installed-app tests pass for:
  - child steer survives app close
  - no stale running subagent cards
  - child drill-in replay works
  - compaction UI matches automatic compaction
  - repeated prompts stay ordered
  - PDF/preview still renders

Then, and only with explicit approval:

```bash
npm run release:apple
```

After release:

- verify feed flips to `1.2.49`
- Justin's app sees `1.2.49`
- full download applies through the in-app update action
- app launches cleanly
- `/compact`, slash menu/skills, subagent child steer, and preview surfaces work in Justin's real environment
