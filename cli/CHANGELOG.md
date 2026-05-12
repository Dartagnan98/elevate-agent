# Changelog

## 2026-05-04 — MLS private-search pipeline

CRM-agnostic MLS active-buyer pipeline. Scrapes any MLS board for buyers
with active private searches, writes their search criteria back to whatever
CRM the agent has configured.

### Added

**`elevate_cli/source_connectors.py` — CRM write layer**
- `crm_find_lead(email, config, *, phone="")` — email lookup with phone
  fallback. Returns normalized `{id, stage, tags, raw}`.
- `crm_create_lead(contact, config)` — creates lead with stage + tags + note
  in single API call where supported.
- `crm_add_note(lead_id, note, config)` — adds structured note.
- `crm_update_stage(lead_id, stage, tags, config)` — merges tags + updates
  stage.
- Provider-specific writers: `_lofty_write` (api.chime.me, PUT-based),
  `_sierra_write` (Sierra-ApiKey header), `_brivity_write` (Token auth,
  notes via description).
- BoldTrail explicitly raises `NotImplementedError` pointing to
  support@insiderealestate.com for partner access.

**`elevate_cli/mls_crm_push.py` — new module**
- Reads hot-leads JSON from any MLS scraper, pushes through the write
  layer above. CRM-agnostic via Elevate config.
- Idempotency: hashes note content, stores as `mls-hash-<10char>` tag.
  Re-runs against unchanged criteria skip the note write.
- Branched per-lead actions: `created` / `updated` / `unchanged` /
  `dry_run`. Stage update skipped on create (already set in body).
- Phone fallback when email is missing. Refuses to create when both are
  missing (returns error result instead of duping).

### Changed

- Tag taxonomy → `private-search` and `mls-buyer` (universal across MLS
  boards). Was `pcs-hot-lead` and `xposure-pcs` (client-specific).
- Source label default → `mls-private-search`. Was `mls-pcs`.
- `crm_find_lead` signature added keyword-only `phone` param. Backward
  compatible — single existing caller unchanged.

### Client-specific pilot script integration

- `pcs-hot-leads-analyzer.cjs` refactored: removed inline `updateLoftyStage`
  function, removed Lofty API calls. After saving hot-leads JSON, spawns
  `python -m elevate_cli.mls_crm_push` via `execSync`.
- `--no-crm` flag (or legacy `--no-lofty`) skips the push.
- execSync error capture: stdout + stderr captured separately, falls back
  to non-JSON output preview on parse failure.

### Tested

- Source label propagates correctly into every note.
- Hash tags deterministic across runs (same input → same MD5 signature).
- Hash changes when content changes (source-aware).
- Missing input file errored cleanly with JSON + exit 1.
- Counts tracked separately: `created/updated/unchanged/dry_run/errors`.
- Analyzer dry-run completes without browser pull or CRM push.

### Not yet tested (requires live CRM run)

- `created` / `updated` / `unchanged` actions against Lofty.
- Phone-fallback hitting Lofty `?phone=` query.
- execSync error path catching a Python-side exception.

### Known gaps / follow-ups

- Scraper still lives in `~/client-tools/scripts/`, not in the Elevate
  repo. For "elevate mls sync xposure" command, scraper needs to relocate
  to `elevate_cli/scrapers/mls/xposure/` with configurable Chrome profile
  path and Click subcommand wiring.
- No cron schedule yet. Should run daily before CRM sync + hot-leads-watcher.
- /leads dashboard does not visually distinguish private-search buyers.
  Recommended: badge on Hot Leads Watcher cards when tags include
  `private-search`, plus filter chip on the lane. Separate lane is overkill.
- Brivity has no notes endpoint or public search endpoint. Notes are
  encoded into `description` at create time only.
- Price range not scraping from Xposure (non-standard input field names).
  Areas + beds + property type pull correctly.

### Architecture

```
MLS scraper (Node/Playwright)
  → hot-leads-YYYY-MM-DD.json
  → mls_crm_push.py (Python bridge)
  → CRM write layer (Lofty / FUB / Sierra / Brivity)
        ↓
   CRM sync (Elevate, existing)
        ↓
   contacts.jsonl + lead-events.jsonl
        ↓
   hot-leads-watcher cron (existing)
        ↓
   /leads dashboard
```

The CRM is the data bus. Search criteria travel as structured notes.
