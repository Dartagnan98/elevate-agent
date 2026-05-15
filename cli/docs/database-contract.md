# Database Contract

**The rule for every connector and every reader in Elevate.**

This is not a suggestion or a pattern we sometimes use — it's the contract.
Every connector that imports a lead, every reader that surfaces one, follows
this shape. Deviation creates the kind of source-coupled mess we just spent a
month untangling (CRM-prefixed columns, three places that store a phone
number, no shared join key).

## Core principle

> **Operational.db owns relationships. Source DBs stay canonical.**

We do not copy message bodies, contact attributes, or transaction records into
operational.db where the source already stores them. We store the relationship
— *this contact_id maps to that external record* — and join live to the source
when the UI needs the body.

The exception is `events` (message inbound/outbound) because we need to sort,
score, and run cron logic across messages from many sources. Those are
denormalized into operational.db so a single SQL query spans Apple Messages +
Lofty inbox + Instagram DMs without ATTACH-ing four databases.

## The two-layer model

```
┌─────────────────────────────────────────────────────────────────┐
│ operational.db  — the joiner (one per Elevate install)          │
├─────────────────────────────────────────────────────────────────┤
│ contacts          one row per person                            │
│ identities        one row per external id (THE universal join)  │
│ conversations     one per thread/channel                        │
│ events            one per message (denormalized, all sources)   │
│ lead_inquiries    buyer search criteria (1:1 per contact)       │
│ lead_properties   properties of interest (many per contact)     │
│ notes             annotations (round-trip with CRM)             │
│ deals             transactions (1:1 with CRM deal)              │
└─────────────────────────────────────────────────────────────────┘
                            ▲
                            │ joined via identities.kind + value
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ Source DBs — canonical storage, never copied                    │
├─────────────────────────────────────────────────────────────────┤
│ ~/Library/Messages/chat.db                                      │
│ ~/Library/Application Support/AddressBook/.../v22.abcddb        │
│ Lofty cloud API                                                 │
│ Follow Up Boss cloud API                                        │
│ Sierra cloud API                                                │
│ Brivity cloud API                                               │
│ BoldTrail cloud API   (partner-only, blocked)                   │
│ Instagram / Facebook / WhatsApp (via Composio MCP)              │
└─────────────────────────────────────────────────────────────────┘
```

## The universal join key: `identities`

Every external id a contact has lives in `identities`. Never on the contacts
table itself, never duplicated, never in a source-specific FK column.

```sql
CREATE TABLE identities (
    id          TEXT PRIMARY KEY,
    contact_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,    -- discriminator (see enum below)
    value       TEXT NOT NULL,    -- the external id
    source_id   TEXT NOT NULL,    -- which connector wrote it
    verified    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX uniq_identities_kind_value ON identities(kind, value);
```

### Kind enum (extend in migration when a new source lands)

| Kind | Source | Value example | Joins to |
|---|---|---|---|
| `email` | any | `sarah@example.com` | any inbox |
| `phone` | any | `+17787163070` (E.164) | any SMS source |
| `apple_handle` | apple-messages | `+17787163070` or `user@icloud.com` | `chat.db handle.id` |
| `apple_addressbook_id` | apple-messages | `ABCD1234-EF56-78GH-...` | `AddressBook ZABCDRECORD.ZUNIQUEID` |
| `apple_chat_id` | apple-messages | `42` (chat.db ROWID) | `chat.db chat.ROWID` |
| `lofty_id` | lofty | `99876` | Lofty `/v1.0/leads/{id}` |
| `fub_id` | followupboss | `12345` | FUB `/v1/people/{id}` |
| `sierra_id` | sierra | `lead-uuid` | Sierra `/leads/{id}` |
| `brivity_id` | brivity | `7890` | Brivity `/people/{id}` |
| `boldtrail_id` | boldtrail | TBD | partner-only |
| `instagram_id` | instagram | `1234567890` | Composio Instagram |
| `instagram_handle` | instagram | `@sarah_realtor` | Composio Instagram |
| `facebook_id` | facebook | `100012345` | Composio Facebook |
| `telegram_id` | telegram | `987654321` | Telegram Bot API |
| `wa_id` | whatsapp | `+17787163070@c.us` | WhatsApp Business API |

Add to the CHECK constraint via numbered migration when a new source lands.
Never short-cut by using `email` to mean "this person's apple-messages email" —
add `apple_handle` and store it there.

## Write contract — every connector follows this shape

Every connector's sync function does these things, in this order, for every
lead it pulls:

1. **Build the identity bundle.** Collect every external id this person has
   from the source: phones, emails, native CRM id, AddressBook id, chat id,
   etc. Normalize phones to E.164 before they touch SQL.

2. **Resolve to a contact_id.** For each identity in the bundle, query:
   ```sql
   SELECT contact_id FROM identities WHERE kind=? AND value=?;
   ```
   If ANY identity in the bundle resolves to an existing contact, reuse that
   contact_id. If MULTIPLE identities resolve to DIFFERENT contact_ids, the
   bundle is straddling a duplicate — record an `identity_conflict` row and
   let the operator merge.

3. **Upsert the contacts row.** New contact_id if nothing matched. Update
   `display_name`, `primary_phone`, `primary_email`, `last_activity_at` —
   never overwrite with a worse value (a phone-shaped name doesn't replace a
   human name; an empty field doesn't replace a populated one).

4. **Write the identity rows.** One per external id, idempotent via
   `INSERT OR IGNORE` on the (kind, value) unique index. The same handle
   showing up twice doesn't duplicate.

5. **Conversation + events.** One conversation per thread. Append-only events
   keyed on `event_hash` so re-imports don't double-write.

6. **Source-specific tables.** If the adapter exposes inquiry / properties /
   qualification / consent / notes / deals, hydrate them. Otherwise skip — no
   half-filled rows. (See `crm_adapters/base.py`.)

The Python surface for steps 1-4 lives in:

- `data/identities.add_identity(conn, contact_id, kind, value, source_id)`
- `data/identities.resolve_identity(conn, kind, value)` → `contact_id | None`
- `data/contacts.upsert_contact(conn, **fields)` — handles the "don't
  overwrite with worse data" merge rules

Never write to these tables directly with raw SQL. Use the helpers — they
encode the conflict-detection and source-key invariants.

## Read contract — every reader uses this shape

```python
# "Get me everything about this contact across all systems"
contact = get_contact(conn, contact_id)
ids = {row["kind"]: row["value"] for row in
       conn.execute("SELECT kind, value FROM identities WHERE contact_id=?",
                    (contact_id,)).fetchall()}

# Now fan out:
if "apple_handle" in ids:
    messages = chat_db.messages_for_handle(ids["apple_handle"])
if "lofty_id" in ids:
    inquiry = lofty_adapter.fetch_lead_detail(ids["lofty_id"])
if "apple_addressbook_id" in ids:
    addressbook = apple_contacts.lookup(ids["apple_addressbook_id"])
```

The drawer reader (`data/reads.db_thread_context_response`) follows this
exact pattern. Any new reader does the same.

### Common query patterns

**"Show all chat.db messages for this contact" (live join, no copy):**
```sql
ATTACH '/Users/.../Messages/chat.db' AS msg;

SELECT m.text, m.date, m.is_from_me
FROM msg.message m
JOIN msg.handle h ON h.ROWID = m.handle_id
JOIN identities i ON i.kind='apple_handle' AND i.value = h.id
WHERE i.contact_id = ?
ORDER BY m.date DESC;
```

**"Which contact does this incoming handle belong to?":**
```sql
SELECT contact_id FROM identities
WHERE kind='apple_handle' AND value = ?;
```
This is the single hot path on every inbound message. The
`uniq_identities_kind_value` index makes it O(log n).

**"All threads this contact participates in":**
```sql
SELECT value AS chat_id FROM identities
WHERE contact_id=? AND kind='apple_chat_id';
```

**"Pull live CRM detail":**
```python
provider = settings.crm_provider          # 'lofty' / 'followupboss' / ...
remote_id = identity_value(conn, contact_id, f"{provider.replace('followupboss','fub')}_id")
adapter = get_adapter(provider, env_values)
detail = adapter.fetch_lead_detail(remote_id)
```

## CRM-agnostic columns

Where source-specific data DOES land in operational.db (qualification,
consent, deals, notes-sync-state), the column names are CRM-agnostic:
`crm_remote_id`, `crm_sync_state`, `crm_provider`, etc. The `crm_provider`
discriminator column tells the sync worker which adapter to use.

Migration 0020 enforced this rename across notes + deals. Future tables
follow the same convention. There are no `lofty_*` or `fub_*` columns on
shared tables — that's adapter territory, not schema territory.

## Sentinel: things that must NOT happen

- ❌ A contacts column named `lofty_user_id` or `fub_email` or `apple_phone`.
  Use identities.
- ❌ Copying message bodies from chat.db into operational.db (events table
  stores a reference / hash, not the body).
- ❌ Two source-specific reader functions (`get_contact_from_lofty`,
  `get_contact_from_apple`). One reader, identities-keyed.
- ❌ Source ids stored as the value of a generic kind (`kind='phone',
  value='lofty-99876'`). Add an enum entry; one kind per source.
- ❌ Joining anything by display_name. Names are not stable. Always
  join on (kind, value) in identities, or on contact_id.

## Migration cadence

When a new source lands:
1. Add its `<source>_id` (or whatever ids it exposes) to the
   `identities.kind` CHECK constraint via numbered migration.
2. If the source exposes inquiry/properties/qualification/consent/deals,
   write its adapter under `crm_adapters/` (or analog for non-CRM).
3. The connector's sync function follows the write contract above.
4. No new columns on contacts/conversations/events unless the data is
   genuinely shared across all sources.

## See also

- `docs/central-data-model.md` — the original sprint plan
- `docs/source-keys.md` — per-source dedupe key contract
- `docs/lofty-api-catalog.md` — Lofty endpoint inventory (template for
  other CRM catalogs)
- `crm_adapters/base.py` — adapter ABC + normalized dataclasses
- `data/identities.py` — the resolve/add/merge helpers
