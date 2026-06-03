# Per-Account Data Scoping (WIP — building 2026-06-03)

## Goal
Scope **chats, automations, heartbeats, and dashboards** to the logged-in account.
Shared (unchanged): home folder, `config.yaml`, skills, `auth.json`, `license.json`,
`SOUL.md`, memory store.

Trigger: switching accounts lost chats/automations and forced re-onboarding, because the
operational store is **one DB per install**, not per-account.

## Account key
`get_account_key()` in `cli/elevate_constants.py` (DONE): `acct_<sha1(lowercased
license.json email)[:16]>`. No login → `"default"`. Matches PG identifier rules
(alnum/_, ≤63). mtime-cached on `license.json` so an account switch is picked up live —
no process restart. `get_account_data_dir()` → `<ELEVATE_HOME>/accounts/<key>/` (0700).

## What gets scoped + how
- **Operational Postgres** (chats `chat_sessions` + dashboards/onboarding tables):
  DB name `elevate_op_<key>` instead of `elevate_operational`. `pg_server.ensure_database`
  + `get_uri` already take a db name. Pool rebuilds when `get_account_key()` changes
  (track `_pool_account` in `connection.py`; close+reopen on mismatch; reset
  `_schema_ready` so migrations run on the new DB).
- **Cron** (automations + heartbeats) — `cli/cron/jobs.py`:
  `CRON_DIR`/`JOBS_FILE`/`OUTPUT_DIR` become functions over `get_account_data_dir()/cron`
  (not import-time constants) so they re-resolve per call. Scheduler must re-read each tick.
- **Chat session files + state.db**:
  `sessions/` → `accounts/<key>/sessions/`; `state.db` → `accounts/<key>/state.db`.

## Account-switch
`license.json` email changes → `get_account_key()` returns new key → next `connect()`
rebuilds the pool to `elevate_op_<newkey>`; cron tick reads new `jobs.json`; session ops
use new dir. Frontend already refetches on login. No process restart required.

## Legacy adoption (existing installs, e.g. Skyleigh's box)
One-time at gateway boot: if `accounts/.legacy_migrated` absent AND legacy
`elevate_operational` / `cron` / `sessions` / `state.db` exist → first logged-in account
adopts them (rename DB, move dirs), write sentinel = key.

## Dartagnan data restore (THIS install)
His real pre-scrub data is in backups, NOT the current post-scrub `elevate_operational`:
- `pg_restore ~/.elevate-backups/elevate_operational_20260602-222031.dump` → `elevate_op_<dartagnan_key>`
- move `~/.elevate.skyleigh-FULL-20260602-222526/{cron/jobs.json, sessions/, state.db}`
  → `~/.elevate/accounts/<dartagnan_key>/`
- write the adoption sentinel so it doesn't grab the post-scrub data.
- `dartagnan_key = acct_<sha1('dartagnan@ctrlstrategies.com')[:16]>`

## Files to touch
- `cli/elevate_constants.py` — DONE (`get_account_key`, `get_account_data_dir`)
- `cli/elevate_cli/data/connection.py` — per-account DB name + pool rebuild on key change
- `cli/cron/jobs.py` — `CRON_DIR`/`JOBS_FILE`/`OUTPUT_DIR` → functions
- `cli/cron/scheduler.py` — verify per-tick reload
- session-file + `state.db` path resolvers (pending Explore map)
- gateway boot — legacy adoption hook

## Test
Two accounts → each sees only its own chats/automations/onboarding; switch back → data
returns. Cross-account isolation: B cannot see A's sessions/jobs/leads/dashboards.

## Ship
Hot-swap `cli/` into Elevate.app for a live test, then bake into 1.1.12.
