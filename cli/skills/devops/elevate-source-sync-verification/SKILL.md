---
name: elevate-source-sync-verification
description: Verify an Elevate source connector sync end-to-end without trusting CLI exit codes alone. Use when asked to backfill or verify an Elevate connector such as CRM, apple-messages, social, or another elevate sync source, checking source workspace files and operational.db writethrough.
---

# Elevate source sync verification

Use this when asked to backfill or verify an Elevate connector such as CRM, apple-messages, social, or another `elevate sync <source-id>` source.

## Workflow

1. Run the sync command with a generous timeout:
   ```bash
   elevate sync <source-id>
   ```
   - Capture stdout/stderr.
   - Watch for missing-key, auth, HTTP 4xx/5xx, rate-limit, traceback, or timeout errors.
   - If the command times out, retry in a tracked background process only if the task expects a long paginated backfill.

2. Verify the per-source workspace under:
   ```bash
   ~/.elevate/tools/data/sources/<source-id>/
   ```
   Expected canonical files may include:
   - `source.json`
   - `status.json`
   - `contacts.jsonl`
   - `conversations.jsonl`
   - `messages.jsonl`
   - `lead-events.jsonl`
   - `tasks.jsonl`
   - `artifacts/`

   Use real file checks, not assumptions:
   ```bash
   /bin/ls -la ~/.elevate/tools/data/sources/<source-id>/
   wc -l ~/.elevate/tools/data/sources/<source-id>/contacts.jsonl \
         ~/.elevate/tools/data/sources/<source-id>/conversations.jsonl \
         ~/.elevate/tools/data/sources/<source-id>/lead-events.jsonl \
         ~/.elevate/tools/data/sources/<source-id>/tasks.jsonl
   /bin/cat ~/.elevate/tools/data/sources/<source-id>/source.json
   /bin/cat ~/.elevate/tools/data/sources/<source-id>/status.json
   ```

3. Verify `operational.db` writethrough using the real schema:
   ```bash
   sqlite3 ~/.elevate/data/operational.db "SELECT COUNT(*) FROM contacts;"
   sqlite3 ~/.elevate/data/operational.db "SELECT COUNT(*) FROM events WHERE kind='lifecycle_change';"
   sqlite3 ~/.elevate/data/operational.db "SELECT COUNT(*) FROM conversations;"
   sqlite3 ~/.elevate/data/operational.db "SELECT COUNT(*) FROM identities;"
   sqlite3 ~/.elevate/data/operational.db "SELECT COUNT(*) FROM identity_conflicts WHERE resolved_at IS NULL;"
   ```

4. Spot-check real rows:
   ```bash
   sqlite3 -header -csv ~/.elevate/data/operational.db \
     "SELECT id, display_name, primary_phone, primary_email FROM contacts ORDER BY updated_at DESC LIMIT 2;"
   ```
   The rows should have a non-empty display name and at least one usable phone/email/handle depending on source.

5. For source-specific attribution, group by source fields before assuming counts belong to the target connector:
   ```bash
   sqlite3 -header -csv ~/.elevate/data/operational.db \
     "SELECT source_id, COUNT(*) AS n FROM conversations GROUP BY source_id ORDER BY n DESC;"
   sqlite3 -header -csv ~/.elevate/data/operational.db \
     "SELECT source_id, kind, COUNT(*) AS n FROM events GROUP BY source_id, kind ORDER BY n DESC;"
   sqlite3 -header -csv ~/.elevate/data/operational.db \
     "SELECT substr(source_key,1,40) AS source_prefix, COUNT(*) AS n FROM contacts GROUP BY source_prefix ORDER BY n DESC;"
   ```

## CRM / Lofty specifics

For `source-id=crm` backed by Lofty:

- The CLI reads the key from `~/.elevate/.env`; do not ask the operator for it.
- If the CLI raises a missing-key error, surface that error verbatim and stop.
- Lead lifecycle changes live in `events` with `kind='lifecycle_change'`; there is no `lead_events` table.
- Tasks live as JSONL only; there is no `tasks` table by design.
- CRM-specific rows can be checked with:
  ```bash
  sqlite3 -header -csv ~/.elevate/data/operational.db \
    "SELECT COUNT(*) AS crm_contacts FROM contacts WHERE source_key LIKE 'crm:%' OR source_key LIKE 'lofty:%' OR source_key LIKE 'crm-%' OR source_key LIKE 'lofty-%';"
  sqlite3 -header -csv ~/.elevate/data/operational.db \
    "SELECT COUNT(*) AS crm_conversations FROM conversations WHERE source_id IN ('crm','lofty');"
  sqlite3 -header -csv ~/.elevate/data/operational.db \
    "SELECT COUNT(*) AS crm_lifecycle_events FROM events WHERE kind='lifecycle_change' AND source_id IN ('crm','lofty');"
  sqlite3 -header -csv ~/.elevate/data/operational.db \
    "SELECT COUNT(*) AS crm_identities FROM identities WHERE source_id IN ('crm','lofty') OR kind LIKE '%crm%' OR kind LIKE '%lofty%';"
  ```

## Failure pattern learned

A sync can hang without emitting stdout/stderr and without writing `source.json`, `status.json`, or JSONL files. Do not treat a still-running command as progress. Check:

```bash
ps -o pid,ppid,etime,stat,command -p <pid>
du -sh ~/.elevate/tools/data/sources/<source-id> 2>/dev/null || true
/bin/ls -la ~/.elevate/tools/data/sources/<source-id> 2>&1 | /bin/cat
```

If it remains hung for an unreasonable duration and the workspace is still empty, inspect the live process before killing/reporting:

```bash
ps -o pid,ppid,etime,pcpu,pmem,stat,command -p <pid>
pgrep -P <pid> -a || true
lsof -p <child-python-pid> | tail -50
sample <child-python-pid> 3 -mayDie 2>/dev/null | head -120   # macOS only
```

Useful diagnosis: many Lofty HTTPS sockets in `CLOSE_WAIT`/`ESTABLISHED` plus a `sample` stack inside SSL read/handshake usually means the connector is hung during the paginated/enrichment HTTP pull, before it reaches the atomic source-file write. In that case, kill the tracked background process, report the sync as failed/hung, and recommend adding progress logging or temporarily reducing/disabling enrichment so the lead snapshot can write and DB writethrough can be verified.

## Reporting format

For CRM-style backfills, report a compact CSV-style line:

```text
contacts_jsonl=N, conversations_jsonl=N, lead_events_jsonl=N, tasks_jsonl=N, contacts_db=N, lifecycle_events_db=N, conversations_db=N, identities_db=N, identity_conflicts_pending=N, last_sync_at=<iso-or-missing>, record_counts_total=N-or-missing, errors=<count-or-none>
```

Then add one verdict line:

```text
Verdict: HEALTHY | DEGRADED | FAILED — <what the operator should inspect next>
```

## Pitfalls

- Do not trust `elevate sync` exit code alone.
- Do not assume nonzero global DB counts are from the target connector; inspect `source_id` and `source_key` prefixes.
- Do not query nonexistent CRM tables such as `tasks` or `lead_events`.
- `source.json` `record_counts` may be cumulative, while JSONL line counts may reflect the latest snapshot/incremental write.
- Avoid shell `printf` strings that start with `---` unless using `printf '%s\n' '--- label ---'`; macOS/bash may treat leading `--` unexpectedly in some contexts.
