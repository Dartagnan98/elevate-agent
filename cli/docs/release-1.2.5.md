# Elevate 1.2.5 — release notes

A reliability release. Two real bugs that could silently lose lead data or leave
a customer on a stale fleet after an update are fixed, plus guardrails so the
whole class of each can't come back.

## Fixes

- **Lofty lead sync no longer silently drops contacts + events.** The contacts
  importer wrote a `lofty_lead_user_id` column that no migration ever created,
  so every Lofty contact INSERT failed — and because the backfill ran every row
  of every source in one Postgres transaction, the first failure aborted the
  whole batch and the rest of the sync was lost (observed: ~300 of ~1,800
  contacts, zero lifecycle events). Migration `0030` adds the column, and the
  importer now wraps each row in a SAVEPOINT so one bad row can only ever drop
  itself — never the rest of the sync. Identity-write errors that used to be
  swallowed silently are now surfaced.

- **Fleet + seeding self-apply after an update.** A desktop auto-update swaps
  the app bundle but the long-lived background gateway kept running the old code
  in memory, so the agent rebuild / heartbeat seeding never re-ran — leaving an
  updated customer on the old roster until a manual restart. The app now
  restarts the gateway once per version change, so the current fleet seeds
  itself on update with no intervention.

## Guardrails (so it can't recur)

- **Nothing ships into a customer's database.** The build now excludes all
  `*.db` / `*.sqlite` files from the bundle, so a stray database file can never
  ride along into an install. Fresh installs come up with an empty board.
- **Schema-vs-code check.** Startup now verifies every column the code writes
  actually exists in the database (and logs loudly if not), and a CI test fails
  the build if a column is added to an INSERT without a matching migration —
  for both the contacts and the deals (admin) boards.
