# Source-natural keys

**Status:** locked — change only with a numbered DB migration
**Owner:** Product
**Companion to:** [central-data-model.md](./central-data-model.md), [central-data-model-v1-plan.md](./central-data-model-v1-plan.md)

Pin the upstream id we use to dedupe each connector's records on
re-import. Without this, `migrate-data --force` can double-create rows.

Conventions:
- `contacts.source_key = '<source_id>:<source_native_id>'` UNIQUE
- `events.event_hash = sha256(source_id + thread_key + ts + body_hash)` UNIQUE
- `lead_signals(source_id, source_native_id)` UNIQUE
- `draft_attempts.source_key`, `send_queue.source_key`,
  `inbound_seen.source_key` UNIQUE
- `conversations(source_id, thread_key)` UNIQUE

Per-source contract below. If an upstream id is missing/unstable for a
given record, fall back to the documented synthetic hash.

## crm (Lofty / FUB / Sierra / Brivity / BoldTrail)

| row | natural key | source field |
|---|---|---|
| contact | `<provider>-lead:<lead_id>` | `source_record_id` (e.g. `lofty-lead:1142409008547568`) |
| conversation | `(crm, source_record_id)` | same as contact for CRM-only threads |
| event | sha256(`crm`, `source_record_id`, `timestamp`, body_hash) | `lead-events.jsonl` rows |
| identity (email) | normalized email lowercase | `emails` (string or array) |
| identity (phone) | E.164 of `phones` | `phones` (string or array) |

Lofty exposes a stable numeric `lead_id`. We embed the provider prefix so
multi-CRM households (pilot realtor + a future second CRM) don't collide.

## apple-messages

| row | natural key | source field |
|---|---|---|
| contact | `apple-handle:<handle>` | `source_record_id` (e.g. `apple-handle:+17787163070`) |
| conversation | `(apple-messages, conversation_id)` | from `conversations.jsonl` |
| event (message) | sha256(`apple-messages`, `chat_guid`, `message_guid`) | `messages.jsonl` |
| identity (phone) | E.164 if handle parses as phone | `handle` |
| identity (email) | normalized email if handle is `mailto:`-style | `handle` |

Apple's chat.db rotates `ROWID` on iCloud restore — we use Apple's GUIDs
(`message_guid` from `chat.db.message.guid`), which are stable across
restores. If `message_guid` is missing on an old export, fall back to
sha256(`chat_guid`, ts, body) and quarantine the row to `ingest_status='retry'`.

## composio-gmail

| row | natural key | source field |
|---|---|---|
| contact | `gmail:<email_lower>` | derived from `from`/`to` headers |
| conversation | `(composio-gmail, thread_id)` | Gmail thread id (e.g. `19df0681ca53cca2`) |
| event (message) | sha256(`composio-gmail`, `provider_message_id`) | `messages.jsonl` |
| identity (email) | normalized email | from header |

Gmail provider IDs are stable. `provider_message_id` is the natural key
for messages.

## composio-facebook

| row | natural key | source field |
|---|---|---|
| contact | `fb:<facebook_id>` | `from.id` (e.g. `26484541827864273`) |
| conversation | `(composio-facebook, thread_id)` | (e.g. `t_122207969504329290`) |
| event (message) | sha256(`composio-facebook`, `provider_message_id`) | `messages.jsonl` |
| identity (facebook_id) | numeric id | `from.id` |

`provider_message_id` is FB's stable id (`m_<base64>`). Always present.

## composio-instagram

| row | natural key | source field |
|---|---|---|
| contact | `ig:<instagram_id>` | `from.id` |
| conversation | `(composio-instagram, thread_id)` | |
| event (message) | sha256(`composio-instagram`, `provider_message_id`) | `messages.jsonl` |
| identity (instagram_id) | IG numeric id | `from.id` |
| identity (instagram_handle) | `from.username` lowercased | display, not for matching alone |

IG ids are stable; usernames change. Always match on numeric `id`.

## composio-whatsapp (when wired)

| row | natural key | source field |
|---|---|---|
| contact | `wa:<wa_id>` | `from.id` (E.164-shaped without `+`) |
| conversation | `(composio-whatsapp, chat_id)` | |
| event (message) | sha256(`composio-whatsapp`, `provider_message_id`) | |
| identity (phone) | `+<wa_id>` if numeric | |

Not in current data set; documented for the next connector.

## sms-provider (Twilio)

| row | natural key | source field |
|---|---|---|
| contact | `sms:<E.164_phone>` | derived from `from`/`to` |
| conversation | `(sms-provider, conversation_id)` | Twilio Conversation SID or synth from sorted (from,to) |
| event (message) | sha256(`sms-provider`, `MessageSid`) | Twilio webhook payload |
| identity (phone) | E.164 | |

`MessageSid` is Twilio's stable id (e.g. `SM...`). Use it directly.

## telegram (when wired)

| row | natural key | source field |
|---|---|---|
| contact | `tg:<telegram_user_id>` | bot API `from.id` |
| conversation | `(telegram, chat_id)` | bot API `chat.id` |
| event (message) | sha256(`telegram`, `chat_id`, `message_id`) | `(chat_id, message_id)` is unique per chat |
| identity (telegram_id) | numeric id | |

Documented for parity; no current ingest.

## mls-private-search (Xposure / future MLS feeds)

| row | natural key | source field |
|---|---|---|
| lead_signal | `<source>:<scraper_id>` | `id` (e.g. `mls-39d379df1c`) — already prefixed |
| identity (email) | normalized email | `email` if present |
| identity (phone) | E.164 | `phone` if parsable |
| pcs_buyers (post-graduation) | by `contact_id` | linked from `lead_signal_id` |

MLS rows do **not** auto-create contacts. They live in `lead_signals` and
graduate via verified identity match or manual classify. No `event_hash`
on first ingest — only `pcs_activity` events generated when
`last_activity_at` advances post-graduation.

## social (Buffer / cross-post inbox)

Documented as a connector slot; currently empty. Same shape as
composio-* with platform-specific id under `provider_message_id`.

## skills

Internal/meta source — outputs of skill runs, not customer data. Not
backfilled by `migrate-data`. Stays out of the central data model.

---

## Synthetic-hash fallback

When the upstream id is missing or unstable, the hash is computed as:

```
sha256(f"{source_id}|{thread_key}|{iso_ts}|{sha256(body or '')}")
```

Any row that requires the synthetic fallback gets logged via
`ingest_run.rows_quarantined++` and stays in JSONL with
`ingest_status='retry'` so a future run with better data can replace it.

## Changing this document

Adding a new connector → add a new section here, ship a numbered
migration if it touches schema, and run the no-SQL-outside-module CI
test. Renaming an existing key requires a migration that rewrites
historical `source_key` values.
