# Session Flight Recorder + Diagnostics Build Plan

## Current Handoff State

- Repo: `/Users/dartagnanpatricio/elevate`
- Branch at handoff: `main`
- Latest relevant commit before this plan: `0203b2984 fix(chat): reap stale subagent running state`
- Local app test target: `/Users/dartagnanpatricio/Applications/Elevate.app`
- Do not run `npm run release:apple` without explicit approval.
- Leave `cli/docs/compaction-redesign-buildplan.md` alone unless separately requested.
- Deep-scope note, 2026-06-17: the checkout may contain unrelated dirty build/test/source changes. Do not clean, revert, or normalize those while implementing this plan.

## Problem

Recent live bugs were hard to diagnose from screenshots because the critical facts were split across frontend state, gateway events, DB rows, app logs, and customer-visible UI:

- reasoning/thinking render regressions
- manual/automatic compaction UI divergence
- message ordering after app restart
- gateway disconnected errors
- PDF/preview render failures
- subagent rows stuck as running after a restart or lost completion event
- subagent drill-in not replaying prior timeline
- mid-turn subagent steering disappearing or splitting into a new run

The system needs a privacy-safe "flight recorder" that records enough structured lifecycle events to reconstruct bugs without logging raw customer content by default.

## Goal

Create a per-install, per-session diagnostic event log that can answer:

- What exact app/build/frontend/runtime version was running?
- Which session/turn/subagent/task did the user interact with?
- Did the gateway disconnect, restart, or lose a completion event?
- Did the DB row say a child was running, done, interrupted, or orphaned?
- Did the frontend show a stale state despite durable backend truth?
- Did preview/compaction/subagent/reasoning render fail, and where?
- Can support generate a redacted bundle from the app without asking for screenshots and manual log digging?

## Non-Goals

- Do not log raw prompts, model answers, PDF contents, contact names, client names, message bodies, or full file paths by default.
- Do not build central upload first. Local recorder + exportable bundle comes first.
- Do not replace `agent.log`, `errors.log`, `tui_gateway_crash.log`, or existing `/debug`. Wrap and enrich them.
- Do not make telemetry mandatory or opaque. Upload must be explicit until a privacy policy/product setting exists.

## Existing Seams To Reuse

- `cli/tui_gateway/server.py`
  - per-session event ring buffer around the gateway session lifecycle
  - `debug.trace` appends UI traces to `~/.elevate/logs/blank-trace.log`
  - crash hook writes `~/.elevate/logs/tui_gateway_crash.log`
  - subagent RPCs: `subagent.message`, `subagent.interrupt`, `delegation.status`

- `cli/web/src/pages/ChatPage.tsx`
  - already emits `debug.trace` for blank/vanished-answer diagnostics
  - owns message ordering, background task drawer, compaction UI, preview open/render state
  - can emit frontend lifecycle breadcrumbs

- `cli/elevate_cli/debug.py`
  - existing `/debug` support bundle/paste flow
  - already collects recent `agent.log`, `errors.log`, and related diagnostics
  - should become the export path for recorder data

- `cli/elevate_cli/logs.py`
  - existing CLI log viewer
  - can gain a `session-events` target later

- `cli/elevate_state.py` and `cli/elevate_cli/data/chat_sessions.py`
  - source of truth for `chat_sessions`, `chat_messages`, `ended_at`, `end_reason`, parent/child lineage
  - should not be overloaded with noisy UI event rows unless a PG table is chosen deliberately

## Proposed Architecture

### 1. Local Event Recorder

Add a small recorder module, for example:

- `cli/elevate_cli/diagnostics/session_recorder.py`

Responsibilities:

- append structured JSONL events to `~/.elevate/logs/session-events/YYYY-MM-DD.jsonl`
- keep writes best-effort with a bounded caller cost; diagnostics must never block chat/runtime progress for more than a tiny lock/write window
- sanitize payloads before writing using an event-schema allowlist first and regex redaction only as a second line of defense
- write one complete JSON object per line with process-safe append behavior
- rotate by date and cap by file size, directory size, and retention days
- expose a hard kill switch for support/debugging if the recorder misbehaves
- expose helper functions:
  - `record_session_event(event_type, session_id=None, turn_id=None, payload=None, severity="info")`
  - `record_frontend_trace(payload)`
  - `collect_session_events(session_id=None, child_session_id=None, task_id=None, since_seconds=1800, include_lineage=True)`

Use JSONL first. It is easier to inspect during live customer debugging and can be bundled without schema migrations. Add PG aggregation later if needed.

### 2. Event Envelope

Every event should share a stable envelope:

```json
{
  "schema_version": 1,
  "ts": 1781720257.621,
  "ts_monotonic": 1842.331,
  "event_id": "01JZ8V8MTY8EK6C2VNT3Z9QV5P",
  "seq": 184,
  "event": "subagent.child_reaped",
  "severity": "warning",
  "source": "backend",
  "component": "web_server.children",
  "pid": 83401,
  "session_id": "20260617_110333_086c21",
  "parent_session_id": null,
  "child_session_id": "20260617_110416_216d35",
  "turn_id": "1027f7e72a9c4d4b8d072c0a2bd8880b",
  "task_id": "dt_b4b8bddd",
  "app_version": "1.2.49",
  "frontend_asset": "ChatPage-D-hVtBci.js",
  "backend_build": "0203b2984",
  "process": "dashboard",
  "payload": {
    "end_reason": "delegation_interrupted",
    "output_tokens": 1763,
    "api_calls": 8,
    "source": "children_endpoint_repair"
  }
}
```

Rules:

- IDs are allowed.
- Counts/timestamps/statuses are allowed.
- Error class/message is allowed after redaction.
- Raw message content is not allowed by default.
- Full paths are redacted to basename + extension unless the user opts into full bundle.
- Payload keys are allowlisted per event type. Unknown keys are dropped, not logged "just in case."
- Never mirror a gateway/frontend payload wholesale into the recorder.

### 3. Event Taxonomy

Start with the event types that would have caught the current regressions:

- App/runtime
  - `app.start`
  - `app.version`
  - `dashboard.start`
  - `frontend.asset_loaded`
  - `gateway.connected`
  - `gateway.disconnected`
  - `gateway.reconnected`
  - `gateway.error`

- Chat turn
  - `prompt.submit`
  - `message.start`
  - `message.complete`
  - `message.interrupted`
  - `session.resume`
  - `session.hydrate`
  - `message.order_repair`

- Reasoning/rendering
  - `reasoning.delta_seen`
  - `reasoning.render_start`
  - `reasoning.render_complete`
  - `reasoning.placeholder_removed`
  - `reasoning.truncated_detected`

- Compaction
  - `compact.requested`
  - `compact.started`
  - `compact.animation_started`
  - `compact.completed`
  - `compact.noop`
  - `compact.error`

- Preview/artifacts
  - `preview.open`
  - `preview.render_start`
  - `preview.render_complete`
  - `preview.render_error`
  - `artifact.detected`

- Subagents
  - `subagent.spawn_requested`
  - `subagent.start`
  - `subagent.message_queued`
  - `subagent.message_applied`
  - `subagent.complete`
  - `subagent.interrupt`
  - `subagent.registry_snapshot`
  - `subagent.child_row_seen`
  - `subagent.child_reaped`
  - `subagent.drawer_reconciled`

- Support
  - `diagnostics.bundle_created`
  - `diagnostics.bundle_uploaded`
  - `diagnostics.redaction_warning`

### 4. Frontend Breadcrumbs

In `ChatPage.tsx`, add a small `recordUiEvent(...)` wrapper that sends sanitized data through a new JSON-RPC method:

- required method: `diagnostics.event`
- no `debug.trace` fallback for the flight recorder; the existing trace sink writes payload JSON directly to `blank-trace.log` and is not safe as a privacy boundary
- if `diagnostics.event` is unavailable, the wrapper should no-op silently after an optional dev-console debug line

Frontend events should cover:

- loaded asset name
- active session id and persisted session id
- gateway state transitions
- message submit/start/complete ids
- running task drawer counts and transitions
- preview render errors
- compaction UI state transitions
- subagent drill-in open/replay/steer

Do not send prompt text, assistant text, reasoning text, stack traces, labels, goals, PDF text, full file paths, or artifact text. For labels/goals, send a keyed hash or omit them.

### 5. Backend/Gateway Breadcrumbs

In `tui_gateway/server.py`, record:

- `prompt.submit`
- `message.start`
- `message.complete`
- `session.resume`
- `session.stop`
- `session.steer`
- `subagent.message`
- `subagent.interrupt`
- async delegate sink delivery
- per-session ring replay count

In `tools/delegate_tool.py`, record:

- child built with agent id/toolset mode
- registry insert/remove
- child start/complete
- timeout/error/interruption
- task id, child session id, parent session id

In `elevate_state.py` / `web_server.py`, record:

- stale child repair decisions
- `list_child_sessions` response summary
- session ended/reopened reason changes

### 6. Support Bundle Integration

Extend `cli/elevate_cli/debug.py`:

- include last N session recorder events
- include current frontend asset hash and app version
- include recent `blank-trace.log`
- include `tui_gateway_crash.log`
- include selected `chat_sessions` row summaries for requested session and children
- include redaction report

Add options:

- `elevate debug share --session <id>`
- `elevate debug share --last 30m`
- `elevate debug share --include-content` (explicit, scary, local-only unless user separately confirms upload)
- `elevate debug share --local` continues to mean no upload

Dashboard later:

- "Copy diagnostics"
- "Create support bundle"
- "Upload diagnostics" behind explicit confirmation

### 7. Redaction Policy

Default bundle must redact:

- emails
- phone numbers
- access tokens/API keys
- passwords/codes
- file paths beyond basename
- full message text
- PDF text/content
- contact/client names where detected

Allowed by default:

- event names
- session IDs
- hashed install/customer id
- app/build/frontend version
- timestamps
- model/provider
- token counts
- status/end reasons
- exception class
- redacted exception message

Create central sanitizer tests before any upload work. The recorder sanitizer must be stricter than the existing upload redactor: allowlist payload keys first, then redact string values, then emit a redaction report. Regex redaction alone is not a sufficient privacy boundary.

## Ponytail Deep Scope By Section

This section is the implementation contract. Each section names the exact seams, the allowed data shape, the tests, and the traps to avoid. Work section by section. Do not instrument the next section until the current section has tests and a readable sample timeline.

### Section 0: Repo, Runtime, And Deployment Boundaries

Observed source of truth:

- Local repo: `/Users/dartagnanpatricio/elevate`
- Desktop app runtime to verify against later: `/Users/dartagnanpatricio/Applications/Elevate.app`
- Hetzner release feed host: `root@5.78.46.234`
- Hetzner update directory: `/var/www/elevate-updates/`
- Release feed URL: `https://api.elevationrealestatehq.com/updates/`

Boundary rules:

- Phases 1-4 are local-recorder and support-bundle work only.
- Do not add a central upload endpoint during Phases 1-4.
- Do not store support bundles in `/var/www/elevate-updates/`; that directory is public release-feed infrastructure, not diagnostics storage.
- Do not run release scripts or ship to Hetzner unless the user explicitly asks.
- If testing installed app behavior, patch or rebuild the app runtime deliberately; a source-only change can leave the visible app on stale bundled code.

### Section 1: Local Recorder Foundation

Files:

- Add `cli/elevate_cli/diagnostics/__init__.py`
- Add `cli/elevate_cli/diagnostics/session_recorder.py`
- Add tests in `cli/tests/elevate_cli/test_session_recorder.py`

Recorder defaults:

- Enabled by default for local JSONL writes.
- Disabled when `ELEVATE_SESSION_RECORDER=0`, `false`, `no`, or `off`.
- Base dir: `Path(get_elevate_home()) / "logs" / "session-events"`.
- Directory mode best effort: `0700`.
- Event file mode best effort: `0600`.
- Default retention: 7 days.
- Default max file size: 8 MB per JSONL file.
- Default max directory size: 64 MB.
- Max serialized event line: 16 KB. If sanitization still leaves a larger event, drop oversize payload fields and record `payload_truncated=true`.

Write semantics:

- Serialize compact JSON with sorted keys disabled.
- Use one `os.write(...)` call for the full line.
- Protect rotation and append with a sibling lock file such as `session-events.lock` using `fcntl.flock` on POSIX.
- If the lock cannot be acquired quickly or the write fails, return `False` and do not raise.
- Never call network, DB, model, or frontend code from the recorder.
- Never log recorder failures through the recorder itself.

Collection semantics:

- `collect_session_events(...)` reads only JSONL files in the retention window by default.
- Malformed lines are skipped and counted in the redaction/collection report.
- `include_lineage=True` should include events where any of these match: `session_id`, `parent_session_id`, `child_session_id`, `task_id`.
- Phase 1 can implement direct id matching. Phase 4 can enrich lineage through DB child-session lookup.

Sanitizer contract:

- Start from an event-type payload schema.
- Drop unknown payload keys.
- Drop always-forbidden keys: `text`, `content`, `prompt`, `answer`, `message`, `body`, `html`, `markdown`, `reasoning`, `raw`, `stack`, `traceback`, `pdf_text`, `file_path`, `path`.
- Keep safe numeric/count fields: `input_tokens`, `output_tokens`, `reasoning_tokens`, `api_calls`, `tool_count`, `message_count`, `duration_ms`, `duration_seconds`, `retry_count`, `replay_count`.
- Keep safe state fields: `status`, `end_reason`, `source`, `error_class`, `provider`, `model`, `asset`, `frontend_asset`, `backend_build`.
- Redact emails, phone numbers, API keys/tokens, passwords/codes, URL credentials/query secrets, and absolute paths in any retained strings.
- For labels/goals/titles, do not include plain text. Use `*_hash` fields only when correlation is genuinely useful.

Tests:

- Append and collect one event.
- Malformed JSONL line is skipped and counted.
- Date/file-size rotation does not corrupt adjacent events.
- Concurrent thread writers produce parseable one-line JSON events.
- Concurrent process writers produce parseable one-line JSON events.
- Locked file or write failure returns `False` and does not raise.
- Kill switch prevents file creation.
- Emails, phones, tokens, passwords, codes, full paths, text/content/prompt keys, stack traces, and PDF text do not survive.
- Unknown payload keys are dropped.

### Section 2: Envelope And Event Taxonomy

Envelope required fields:

- `schema_version`
- `ts`
- `ts_monotonic`
- `event_id`
- `seq`
- `event`
- `severity`
- `source`
- `component`
- `pid`
- `session_id` when known
- `payload`

Envelope optional fields:

- `parent_session_id`
- `child_session_id`
- `turn_id`
- `task_id`
- `app_version`
- `frontend_asset`
- `backend_build`
- `install_id_hash`
- `account_id_hash`

Event naming rules:

- Match existing gateway event names where they already exist: `prompt.submit`, `message.start`, `message.complete`, `session.resume`, `session.stop`, `session.steer`, `subagent.message`, `subagent.interrupt`.
- Do not introduce a parallel `turn.*` family for the same lifecycle.
- Use `_seen` suffix when the event means "observed but content omitted", for example `reasoning.delta_seen`.
- Use `_requested`, `_started`, `_completed`, `_failed`, `_skipped`, `_reaped`, or `_reconciled` consistently for state transitions.

Initial canonical taxonomy:

- App/runtime: `app.start`, `app.version`, `dashboard.start`, `frontend.asset_loaded`, `gateway.connected`, `gateway.disconnected`, `gateway.reconnected`, `gateway.error`
- Session/chat: `session.create`, `session.resume`, `session.hydrate`, `session.stop`, `session.steer`, `prompt.submit`, `message.start`, `message.complete`, `message.interrupted`, `message.order_repair`
- Reasoning/rendering: `reasoning.delta_seen`, `reasoning.render_start`, `reasoning.render_complete`, `reasoning.placeholder_removed`, `reasoning.truncated_detected`
- Compaction: `compact.requested`, `compact.started`, `compact.completed`, `compact.noop`, `compact.error`, `compact.ui_animation_started`, `compact.ui_animation_completed`
- Preview/artifacts: `preview.open`, `preview.render_start`, `preview.render_complete`, `preview.render_error`, `artifact.detected`
- Subagents: `subagent.spawn_requested`, `subagent.registry_inserted`, `subagent.registry_removed`, `subagent.start`, `subagent.message_queued`, `subagent.message_applied`, `subagent.complete`, `subagent.interrupt`, `subagent.registry_snapshot`, `subagent.child_row_seen`, `subagent.child_reaped`, `subagent.child_reap_skipped`, `subagent.drawer_reconciled`
- Diagnostics: `diagnostics.bundle_created`, `diagnostics.bundle_upload_requested`, `diagnostics.bundle_uploaded`, `diagnostics.redaction_warning`

### Section 3: Backend And Gateway Instrumentation

Files:

- `cli/tui_gateway/server.py`
- `cli/tools/delegate_tool.py`
- `cli/elevate_state.py`
- `cli/elevate_cli/web_server.py`

Do not instrument `_emit(...)` wholesale. It carries raw event payloads including reasoning/text-bearing deltas. Add narrow recorder calls at lifecycle boundaries instead.

`cli/tui_gateway/server.py` seams:

- Add `@method("diagnostics.event")` after the local recorder exists. It accepts frontend event envelopes, re-sanitizes server-side, and writes through `record_session_event`.
- Keep `debug.trace` as legacy blank-bug tracing only. Do not use it for flight recorder events.
- In `prompt.submit`, record:
  - `prompt.submit` after session lookup and guardrails pass, with ids/counts only.
  - `message.start` when the assistant id is minted.
  - `message.complete` after the final payload is ready, with output token counts/statuses only.
  - `message.interrupted` on interrupt/error paths.
- In `session.resume`, record session id, replay event count, replay sequence, child replay attached/running flags, and whether the session is running.
- In `session.stop`, record stop requested, stop accepted, and whether child interrupts were attempted.
- In `session.steer`, record accepted/queued/forwarded status, target child/task ids, and no steer text.
- In direct `/compact`, record `compact.requested`, `compact.started`, `compact.completed`/`compact.noop`/`compact.error`. Use token counts and summary booleans, not compression summary text.

`cli/tools/delegate_tool.py` seams:

- `_register_subagent`: record `subagent.registry_inserted`.
- `_unregister_subagent`: record `subagent.registry_removed`.
- `_build_child_agent`: record `subagent.spawn_requested` with parent/child ids, toolset count, role, model/provider, and no goal text.
- `message_subagent`: record `subagent.message_queued` or `subagent.message_applied` with target ids, accepted count, and no message text.
- `interrupt_subagent` and `interrupt_subagent_by_session`: record `subagent.interrupt` with target id and success flag.
- `_run_single_child`: record `subagent.start`, `subagent.complete`, timeout/error/interrupted states, token counts, API calls, duration, files-read count, files-written count, and no `summary`, `preview`, `output_tail`, `goal`, or paths.

`cli/elevate_state.py` seam:

- `finalize_interrupted_delegate_children(...)` currently returns a count. For useful diagnostics, either add an optional `return_details=True` mode or a sibling helper that returns each candidate child id with decision: reaped, skipped_live_registry, skipped_grace_period, skipped_compression_child, skipped_no_interrupt_marker, skipped_no_registry_proof.
- Keep the default existing return shape unless all callers are updated.

`cli/elevate_cli/web_server.py` seam:

- In `/api/sessions/{session_id}/children`, record the active child registry size, number of children returned, number of stale rows finalized, and skip/reap details if available.
- Do not include session titles, previews, first-message snippets, or child summaries in recorder payloads.

Backend tests:

- Gateway method `diagnostics.event` rejects forbidden keys.
- `prompt.submit` emits lifecycle events without prompt text.
- Direct `/compact` emits requested/start/completed or noop/error.
- Subagent start/complete events omit goal/summary/output_tail and include counts.
- Stale child finalizer emits reaped/skipped detail without breaking existing count callers.

### Section 4: Frontend Breadcrumbs

Files:

- `cli/web/src/pages/ChatPage.tsx`
- `cli/web/src/lib/gatewayClient.ts` if types need a home outside ChatPage
- optional `cli/web/src/lib/diagnostics.ts` if ChatPage needs to stay smaller

Frontend wrapper:

- `recordUiEvent(event, payload, severity?)`.
- Drop events if there is no session id and the event is not app/runtime scoped.
- Do not call `debug.trace`.
- Do not send raw `Error.stack`; send `error_class`, a redacted/bounded `error_message` only when needed, and a `where` enum.
- Do not send labels, goals, titles, prompts, answers, reasoning, markdown, HTML, file paths, or PDF text.
- Coalesce/reduce noisy state events. No per-token, per-delta, or per-render-loop logging.

ChatPage events:

- `frontend.asset_loaded`: asset basename/hash, app version if available.
- `gateway.connected`, `gateway.disconnected`, `gateway.reconnected`, `gateway.error`: state transition, retry count, no URL tokens.
- `session.hydrate`: message count, server count, cache count, repair flags, same-chat guard flags.
- `message.order_repair`: before/after counts and repair reason.
- `compact.ui_animation_started`, `compact.ui_animation_completed`: manual vs automatic flag and assistant placeholder id.
- `preview.open`, `preview.render_start`, `preview.render_complete`, `preview.render_error`: artifact id/type, renderer kind, error class.
- `subagent.drawer_reconciled`: running/done/error counts and child id counts.
- `subagent.message_queued` / `subagent.message_applied`: target child/task id and accepted status only.

Frontend tests:

- A unit test for the diagnostics sanitizer/wrapper.
- Existing ChatPage tests should assert no raw content keys are sent.
- At least one mocked gateway test for compaction UI events.
- At least one mocked gateway test for subagent drawer reconciliation.

### Section 5: Support Bundle And Logs

Files:

- `cli/elevate_cli/debug.py`
- `cli/elevate_cli/main.py`
- maybe `cli/elevate_cli/logs.py`

CLI shape:

- Add options to `elevate debug share`, not top-level `elevate debug`.
- `--session <id>` filters recorder events and DB row summaries.
- `--last 30m` filters by wall-clock event timestamp.
- `--include-content` is local-only unless a second explicit upload confirmation is added.
- `--local` remains the safest verification path and must not upload.

Bundle contents by default:

- Redacted session event timeline.
- Redaction report with dropped key counts, redacted string counts, malformed line counts, and event count.
- App version, backend build, frontend asset, platform, Python/node versions.
- `blank-trace.log` only after redaction and only as a legacy attachment clearly labeled as higher risk.
- `tui_gateway_crash.log` after redaction.
- DB row summaries for selected session lineage: ids, parent ids, started/ended times, end reasons, counts/tokens/model/source. No title/preview/message text.

Support tests:

- `elevate debug share --local --session <id>` prints timeline and does not upload.
- Uploaded mode redacts recorder events before paste creation.
- Bundle excludes raw chat content by default.
- `--include-content` is rejected for upload unless explicit confirmation is implemented.

### Section 6: Redaction And Privacy Review

Privacy model:

- The recorder is local and explicit-export first.
- Local does not mean careless; support bundles are shareable artifacts and must be safe by default.
- The central sanitizer is authoritative. Existing `agent.redact.redact_sensitive_text(force=True)` is useful but not enough by itself.

Redaction report:

- Include `events_seen`, `events_written`, `events_dropped`, `malformed_lines`, `unknown_keys_dropped`, `forbidden_keys_dropped`, `strings_redacted`, `oversize_payloads_truncated`.
- Include event types present and counts.
- Do not include the values that were redacted.

Hard privacy gates:

- `diagnostics.event` must reject or drop `text`, `content`, `prompt`, `answer`, `message`, `reasoning`, `summary`, `preview`, `output_tail`, `stack`, `traceback`, `path`, `file_path`, `pdf_text`.
- If a developer tries to record one of these, tests should fail.
- If support bundle upload includes recorder events, the upload path must run the same sanitizer again.

### Section 7: Phased Verification

Phase 1 command:

- From repo root: `cd cli && pytest tests/elevate_cli/test_session_recorder.py`

Phase 2 focused commands:

- `cd cli && pytest tests/tui_gateway/test_status_update_pill.py tests/tools/test_delegate.py -k "compact or subagent or delegate"`
- Add narrower new tests as needed rather than relying on broad suites first.

Phase 3 focused commands:

- `cd cli/web && npm test -- --runInBand` or the repo-local equivalent already used for ChatPage tests.
- Add focused tests for the diagnostics wrapper and mocked gateway calls.

Phase 4 focused commands:

- `cd cli && pytest tests/elevate_cli/test_session_recorder.py tests/cli -k "debug or diagnostics"`

Installed app manual gate:

- Run against `/Users/dartagnanpatricio/Applications/Elevate.app`.
- Confirm source and bundled runtime are the same version before trusting a manual pass.
- Generate a local bundle first with `elevate debug share --local --session <id>`.

### Section 8: Hetzner And Future Central Upload

Current Hetzner reality:

- The known host is `root@5.78.46.234`.
- It currently serves the Electron update feed under `/var/www/elevate-updates/`.
- That path is public static release infrastructure.

Future upload rules:

- Do not write diagnostics into the update feed directory.
- Central upload needs a separate authenticated endpoint, retention policy, size limit, delete path, and privacy copy.
- Upload should group by event fingerprint/app version, not raw customer/session content.
- Upload should be opt-in per bundle until a product-level privacy setting exists.
- The first central test should upload one synthetic sanitized bundle, not a real customer bundle.

## Implementation Phases

### Phase 1: Local Recorder Foundation

Files:

- add `cli/elevate_cli/diagnostics/__init__.py`
- add `cli/elevate_cli/diagnostics/session_recorder.py`
- add tests under `cli/tests/elevate_cli/test_session_recorder.py`

Tasks:

- JSONL append with date rotation, size cap, retention cap, and process-safe locking
- bounded caller cost with best-effort failure behavior
- event-schema allowlist sanitizer plus redaction helpers
- kill switch via `ELEVATE_SESSION_RECORDER`
- no-op safely if filesystem write fails
- unit tests for redaction, append, collect-by-session/child/task, malformed line tolerance, and concurrent writers

Done when:

- recorder can append/read events locally
- recorder does not write forbidden content keys
- concurrent test output is parseable JSONL
- tests pass
- no frontend changes yet

### Phase 2: Backend/Gateway Instrumentation

Files:

- `cli/tui_gateway/server.py`
- `cli/tools/delegate_tool.py`
- `cli/elevate_state.py`
- `cli/elevate_cli/web_server.py`

Tasks:

- record gateway session lifecycle
- record prompt/message lifecycle
- record subagent registry/lifecycle
- record stale-child repair decisions
- record compaction start/complete/error from backend path if available

Done when:

- a subagent run creates a readable local timeline without frontend breadcrumbs
- stale child repair logs why it reaped or skipped rows

### Phase 3: Frontend Breadcrumbs

Files:

- `cli/web/src/pages/ChatPage.tsx`
- `cli/web/src/lib/gatewayClient.ts` if needed

Tasks:

- add `diagnostics.event` RPC; do not reuse `debug.trace`
- log gateway state transitions
- log frontend asset loaded
- log background drawer reconciliation
- log compaction UI animation states
- log preview render outcomes
- log subagent drill-in replay/steer states

Done when:

- the same session can be reconstructed across frontend and backend events
- no raw prompt/answer content appears in the recorder file

### Phase 4: Support Bundle

Files:

- `cli/elevate_cli/debug.py`
- `cli/elevate_cli/main.py`
- maybe `cli/elevate_cli/logs.py`
- optional dashboard UI later

Tasks:

- add session recorder events to `elevate debug share`
- add `elevate debug share --session` / `--last` filters
- add DB row summaries for session lineage
- add redaction report
- optionally add dashboard "copy diagnostics" button

Done when:

- support bundle for a failing session contains enough data to diagnose stuck subagent / preview / compaction / gateway issues without screenshots

### Phase 5: Central Upload (Later)

Do this only after local recorder and redaction are proven.

Tasks:

- define upload endpoint
- hash customer/install id
- group by error fingerprint and app version
- opt-in setting or explicit per-bundle confirmation
- central dashboard for support

Done when:

- Justin/customer can click "Send diagnostics" and we can inspect one grouped issue without private content exposure

## Test Plan

### Automated Tests

- recorder redacts emails, phones, tokens, paths, and obvious secrets
- recorder writes malformed-safe JSONL
- recorder filters by session id and time
- `diagnostics.event` rejects raw content keys by default
- `subagent.child_reaped` emitted when stale child row is reaped
- live child is not reaped and recorder logs skip reason
- support bundle includes recorder events and redaction report
- support bundle excludes raw chat content by default

### Manual Tests In Installed App

Run against `/Users/dartagnanpatricio/Applications/Elevate.app`, not localhost-only.

1. Start a normal chat turn.
2. Run `/compact`; confirm `compact.*` events exist.
3. Create a PDF/artifact and open preview; confirm `preview.*` events exist.
4. Spawn a long subagent; open drill-in mid-run; send a steer; confirm `subagent.*` sequence exists.
5. Restart the app mid-subagent; confirm registry loss/stale child handling is logged.
6. Run `elevate debug share --local --session <id>`; confirm bundle includes event timeline and no raw prompt text.

## First Implementation Prompt For Next Session

Use this exact starting prompt:

> Implement Phase 1 from `cli/docs/session-flight-recorder-buildplan.md`. Stay narrow. Add the local session recorder module and tests only. Do not instrument frontend/backend yet. Do not touch release scripts or run `release:apple`. Preserve existing `cli/docs/compaction-redesign-buildplan.md`.

Expanded constraints for that first prompt:

- Add `cli/elevate_cli/diagnostics/__init__.py` and `cli/elevate_cli/diagnostics/session_recorder.py`.
- Implement the Section 1 sanitizer and writer contract, including forbidden-key dropping, redaction report counts, malformed-line tolerance, process-safe locking, retention caps, size caps, and `ELEVATE_SESSION_RECORDER` kill switch.
- Add `cli/tests/elevate_cli/test_session_recorder.py`.
- Run only the focused Phase 1 test command unless the user asks for broader verification.

## Release Notes Draft

Not customer-facing yet. Internal changelog:

- Adds local privacy-safe session flight recorder foundation for debugging app/runtime issues.
- Records structured metadata breadcrumbs without raw customer content.
- Prepares support bundles to include session timelines for compaction, preview, gateway, and subagent regressions.
