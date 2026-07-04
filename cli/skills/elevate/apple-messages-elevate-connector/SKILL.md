---
name: apple-messages-elevate-connector
description: Wire Apple Messages into Elevate Agent as a local source and guarded outbound transport. Use when wiring Apple Messages/iMessage/SMS into Elevate as a source connector, producing normalized contacts/conversations/messages/lead-events/tasks JSONL files and routing approved Lead Desk texts through imsg.
---

# Apple Messages Elevate Connector

Use when wiring Apple Messages/iMessage/SMS into Elevate Agent as a local source and guarded outbound send transport. Earlier versions were read-only; current Lead Desk repair work may require send-enabled metadata, background sync, and a one-message self-test before live queued lead sends are allowed.

## Requirements / Safety

- Start read-only.
- Do not send messages, submit forms, move files, change permissions, upload data, or create persistent API keys unless the operator explicitly approves.
- If credentials, OAuth, exports, webhook approval, app review, or permission changes are needed, set `status.json` to `needs_operator` / blocked with the exact `next_operator_step`.
- Outbound/reply work goes to `tasks.jsonl` with `approval_required=true` unless sending has been explicitly authorized.

## Paths

1. Read customer tools root from `sources.tools_root` or `ELEVATE_TOOLS_ROOT`.
2. Source directory: `data/sources/apple-messages` inside the customer tools root.
3. Raw/provider files go under `artifacts/`.

## Source metadata

Create/update `source.json` with:

- `provider`
- `account_label`
- `connection_type`
- `auth_status`
- `sync_mode`
- `owner_agent`: `Outreach`
- `enabled_ui_surfaces`: `Outreach`, `Leads`, `Today`, `Approvals`
- `setup_status`
- `last_sync_at`
- `setup_notes`

Create/update `status.json` with:

- `connected`
- `import_only`
- `blocked`
- `last_error`
- `next_operator_step`
- `last_checked_at`

## Normalized files

Write JSONL files:

- `contacts.jsonl` for people/handles
- `conversations.jsonl` for threads
- `messages.jsonl` for inbound/outbound items
- `lead-events.jsonl` for qualified moments
- `tasks.jsonl` for human work/replies needing approval

Each relevant record should include when available:

- `source_id`
- `source_record_id`
- `source_url`
- `display_name`
- `channel`
- `direction`
- `timestamp`
- `text` or `summary`
- `confidence`
- `tags`
- `target_ui_surfaces`

## Repeatable connector entrypoint

Add/document one repeatable entrypoint such as:

```bash
python3 <tools_root>/data/sources/apple-messages/import_readonly.py
```

Include a `CONNECTOR.md` explaining the import command, read-only behavior, and any operator steps.

## Done condition

Verify that a synced iMessage/SMS conversation appears as:

1. a thread in `conversations.jsonl`,
2. a lead event in `lead-events.jsonl`, and
3. a reply-needed task in `tasks.jsonl` with `approval_required=true`.

## Leads dashboard send-readiness check

When the user asks whether the Leads dashboard is connected to send texts from Messages.app, verify the whole path instead of answering from memory:

1. Run `leads_overview` and check `pendingByChannel.imessage`, `pendingBySource.apple-messages`, and recent send counts.
2. Inspect the local connector files, usually under `~/.elevate/tools/data/sources/apple-messages/`:
   - `status.json`: `connected`, `import_only`, `blocked`, `last_error`, `last_checked_at`, `last_imported_at`, counts.
   - `source.json`: `auth_status`, `sync_mode`, `enabled_ui_surfaces`, `setup_status`, `last_sync_at`.
3. Verify the Mac Messages command path with `command -v imsg`, `imsg status`, and a small `imsg chats --limit 3 --json` probe. `imsg status` alone is not enough.
4. Query the send queue for channel/source state:
   - `send_queue` grouped by `channel,status`.
   - Recent `channel='imessage'` rows with `source_id`, `thread_id`, `task_id`, `status`, `attempts`, `last_error`, and payload preview.
5. Interpret results carefully:
   - `connected=true` plus `import_only=true` means the dashboard can use imported Messages data, but live background sync is not enabled.
   - 207 pending `imessage` rows means drafting/approval queue exists, but actual dashboard-to-Messages sending is not proven.
   - only claim send capability is fully wired if a queued approval has actually sent via Messages and has a provider/message proof or history confirmation.
5. Verify the runtime sender mapping before declaring the dashboard send-ready:
   - `_channel_for_source('apple-messages')` should return `imessage`.
   - `sender.get_dispatcher('imessage').__name__` should be `_messages_native_dispatch`, not `_stub_dispatch`.
   - `sender.tick(batch=1)` should claim 0 rows unless the operator has just approved a draft; do not run a tick when queued rows are present unless sending is intended.


## Lead Desk / Action Board outbound routing repair

Use this when approvals in the Lead Desk / Action Board show Sent rows with provider IDs such as `stub-crm-note-*` instead of actually texting via Messages.

Trace the real path before changing code:

1. Active code is usually under `~/.elevate/elevate/cli`, not the shallow dashboard checkout.
2. Approval flow:
   - `cli/elevate_cli/web_routes/source_connectors.py` → `POST /api/source-inbox/draft`
   - `cli/elevate_cli/source_connectors.py` → `update_source_task_state(...)` → `_approve_atomic(...)`
   - `cli/elevate_cli/outreach_db.py` → `enqueue_send(...)`
   - `cli/elevate_cli/sender.py` → `tick(...)` → dispatcher by `channel`
3. Fix routing at enqueue time, not only in the sender:
   - `_SOURCE_TO_CHANNEL['apple-messages']` should resolve to `imessage`.
   - CRM-sourced lead texts may still be real SMS/iMessage drafts. Do not blindly enqueue `crm_note` when the merged task record has message evidence such as `channel/template_channel` containing `imessage`, `sms`, `text`, `apple-messages`, or `messages`, plus a phone / Apple handle / recipient email.
   - Add a task-aware helper such as `_channel_for_task(source_id, merged_task_record)` and test that CRM lead text tasks enqueue `imessage` while true CRM note tasks remain `crm_note`.
4. The local Messages sender should register a real dispatcher for both `sms` and `imessage`:
   - `sender.get_dispatcher('imessage').__name__` should be `_messages_native_dispatch` or an `imsg`-backed dispatcher, never `_stub_dispatch`.
   - Prefer the real local gateway when available: `imsg send --to <handle> --text <draft> --service <imessage|sms|auto>`. Validate the local CLI shape with `imsg send --help` before coding because flags vary by version. In the verified 0.11.0 CLI the supported flags are `--to`, `--text`, `--service`, and `--json`; provider IDs should be generated by Elevate as `imsg-*` unless the CLI returns a durable id.
   - Keep AppleScript as fallback only if deliberately supported, and never silently convert an attempted `imsg` failure into a fake success.
5. Add a hard safety gate before any live fix can drain existing queued rows:
   - default normal `imessage`/`sms` rows to blocked unless a live-confirmation flag is set, e.g. `ELEVATE_MESSAGES_LIVE_CONFIRMED=1`.
   - if the operator wants “unlocked, but only when I hit Approve on the dashboard,” do **not** rely on the global live flag alone. Mark rows created by the Approve handler with `payload.safety.approved_dashboard_send=true` and `approved_at`, let only those rows bypass the global gate, and keep older/pre-existing queue rows blocked.
   - in `_approve_atomic(...)`, dispatch the exact `queued_row` returned by `outreach_db.enqueue_send(...)` with `sender.dispatch_one(queued_row)` instead of starting a general `sender.tick(batch=...)`; a global tick can claim unrelated old queued leads.
   - allow exactly one self-test row marked in payload safety metadata, e.g. `payload.safety.test_send=true`, to send to the operator's own number.
   - do not mark existing lead rows failed just because live mode is not confirmed; leave them queued/visible.
6. Add a self-test function/API/CLI that sends exactly one message to the operator's own number and never calls a general `tick(batch=...)` that could claim normal queued rows. Return a non-stub provider ID and transport info.
   - If testing an SMS contact by nickname from Messages/Contacts, do not trust the first fuzzy name match. Confirm the exact phone/handle with the user, or use the exact number they provide, before sending. In one run, a Contacts search by nickname matched the wrong person entirely; the correct test number had to be supplied explicitly afterward.
   - For an SMS smoke test, build a direct test row with `channel='sms'`, `payload.safety.test_send=true`, and call `sender.get_dispatcher('sms')(row)` with `ELEVATE_MESSAGES_TEST_RECIPIENT=<exact-number>` instead of using the generic iMessage self-test helper.
   - Do not treat `imsg` stdout `sent` as final proof for SMS. In one repair, `imsg send --service sms` returned success, but Messages later showed Not Delivered and chat.db stored `message.error=4`, `is_sent=0`, `is_delivered=0`. After any phone/SMS test, wait briefly and verify the latest outbound row in `~/Library/Messages/chat.db` for that handle before reporting success.
   - Prefer `imsg send --service auto` for phone/SMS/RCS lead sends unless there is a confirmed reason to force `sms`. Some current phone threads are stored as RCS in chat.db, and forcing `sms` can create a local row that flips to Not Delivered. The sender should check chat.db after `imsg` returns and raise a transient error instead of marking the queue row sent when `error != 0`.
7. Update connector metadata after the real sender exists:
   - `source.json`: send-enabled local gateway metadata, `send_transport='imsg'`, live/background sync mode.
   - `status.json`: `connected=true`, `import_only=false`, `outbound_enabled=true`, and a next step that says outbound lead sends remain gated until the one-message self-test is confirmed.
8. Targeted tests to add/run:
   - `tests/elevate_cli/test_leads_action_wiring.py` for task-aware channel routing and enqueue payload metadata.
   - a sender dispatch test that mocks `subprocess.run` and proves `imsg send` is called and provider IDs do not start with `stub-`.
   - a safety-gate test proving normal queued `imessage`/`sms` rows are not dispatched before live confirmation, while the one self-test row is.
   - an approve-only unlock test proving a row with `payload.safety.approved_dashboard_send=true` bypasses the global live gate, and that the approve handler dispatches the exact queued row rather than calling a general queue tick.
   - run with the repo venv if system Python lacks pytest: `cli/.venv/bin/pytest ... -q` from `~/.elevate/elevate`.
   - also run `PYTHONPATH=cli python3 -m py_compile <touched files>` and `git diff --check` before commit.

Operational findings from a successful repair:

- On a real desktop app install: the active packaged code path was `/Applications/Elevate.app/Contents/Resources/cli`, not `~/.elevate/elevate/cli`. Do not edit the app bundle; hotfix by overlaying modules under `~/Elevation/elevate_cli/` (or the tenant's equivalent local override root) with `__path__` extended back to the app bundle, then restart/reopen Elevate so the dashboard process imports the overlay. In that install, `sender.get_dispatcher('sms').__name__` was `_messages_native_dispatch` but `sender.get_dispatcher('imessage').__name__` was `_stub_dispatch`. Existing `apple-messages` approval rows used `channel='imessage'`, so clicking Approve would not use the native Messages sender. Safe no-send repair was to back up those pending rows, update only `source_id='apple-messages' AND status='pending_approval' AND channel='imessage'` to `channel='sms'`, and set `status.json/source.json` outbound metadata to `outbound_enabled=true`, `send_transport='imsg'`, `import_only=false`. If approval still logs CRM notes instead of texting, also patch/overlay `source_connectors._channel_for_task()` and `outreach_db.approve_pending_send()` so CRM lead follow-up rows with phone/draft metadata release as `sms`, while real `email` rows stay email. Verify with `leads_overview` showing Apple/CRM text approvals under `pendingByChannel.sms`, `queued=0`, and both `sender.get_dispatcher('sms')` and `sender.get_dispatcher('imessage')` returning `_messages_native_dispatch`.
- The active code path was `~/.elevate/elevate/cli`; a shallow dashboard checkout may contain UI context but not the real sender/approval path.
- The branch may be far behind upstream and the working tree may have many unrelated dirty files. Stage/commit only scoped files and do not revert rebuilt web assets or unrelated admin work.
- If pushing upstream fails with GitHub 403 for the active account, create/use the user's fork remote and open the PR with `gh pr create --repo <upstream> --head <user>:<branch> --base main`.
- `scheduler install --force` may immediately launch `sync apple-messages`; a manual `scheduler run --source apple-messages` can fail with `database is locked` while launchd's sync process is already running. Check `ps`/scheduler status and wait for the running sync instead of killing it unless it hangs past the watchdog.
- Verify post-install status shows `ai.elevate.sync-apple-messages` installed and loaded, and inspect `status.json`/`source.json` for `import_only=false`, `outbound_enabled=true`, `send_transport=imsg`, and `sync_mode=background_live_sync`.

Important safety: `_approve_atomic(...)` may auto-start `sender.tick(batch=1)` via `ELEVATE_APPROVE_AUTO_TICK`. Disable or gate this before testing against a queue with real lead rows.

## Permission-block handling

The sync command can exit with code 0 and return top-level `ok: true` even when the connector is blocked. Always inspect `view.blocked`, `view.authStatus`, `view.lastError`, and the generated `status.json` before continuing.

If macOS blocks Messages/AddressBook access, stop immediately and report the one-line permission reason from `status.json`. A common blocked state is:

- `authStatus`: `needs_full_disk_access`
- `last_error`: `unable to open database file`
- `next_operator_step`: `Grant Full Disk Access to the terminal/app running Elevate, make sure Messages are synced to this Mac at ~/Library/Messages/chat.db, then click Initialize again.`

Do not run Postgres writethrough verification after a blocked state unless the operator specifically asks for it.

## Known local result from prior run

In one environment the source path was `~/.elevate/tools/data/sources/apple-messages`, and a verified example produced:

- thread: `apple-chat:183`
- lead event: `apple-lead-event:apple-message:653251:183`
- reply-needed task: `apple-reply-needed:apple-message:653251:183`

Do not assume these IDs exist in future environments; verify live state when tools are available.
