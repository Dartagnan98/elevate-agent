-- 0024_relabel_mislabeled_crm_events.sql
-- Repair pre-0.12.2 data drift: lead-events.jsonl rows from the CRM
-- connector landed in the events table as `source_id='ui:lifecycle'` and
-- `kind='lifecycle_change'` regardless of their actual type. Two bugs
-- caused it:
--
--   1. `record_lifecycle()` in data/events.py hardcoded the source_id to
--      'ui:lifecycle' for every caller, so connectors replaying their own
--      JSONL had no way to tag rows with the real source.
--   2. `walk_jsonl_source()` in data/migrate.py collapsed every lead-event
--      to kind='lifecycle_change' instead of dispatching on the row's
--      legacyType (crm_note → 'note', everything else → 'lifecycle_change').
--
-- Symptom for users on 0.12.0/0.12.1: the per-contact "notes" panel was
-- empty even though Lofty notes had been imported, and source-filtered
-- event queries (`WHERE source_id='crm'`) returned zero rows even though
-- the data was on disk in lead-events.jsonl.
--
-- Both bugs are fixed in code as of 0.12.2 (events.py + migrate.py). This
-- migration cleans up the rows already written under the wrong labels so
-- existing installs don't need a manual DELETE + replay step.
--
-- Identification rule: payload_json for these rows always carries a
-- "legacyType":"crm_..." key (written by the walker). Anything matching
-- that pattern with source_id='ui:lifecycle' is definitively a mislabeled
-- CRM lead-event.
--
-- New install: no rows match → no-op.
-- Existing install that synced Lofty before 0.12.2: rows get relabeled in
-- place. event_hash + id are preserved, so any downstream references stay
-- valid.
--
-- Idempotent: re-running this migration is a no-op because after the
-- first run the source_id is 'crm', not 'ui:lifecycle'.

-- Relabel notes first (more specific predicate) so the second UPDATE
-- doesn't accidentally catch them under the lifecycle_change branch.
UPDATE events
SET source_id = 'crm',
    kind      = 'note'
WHERE source_id = 'ui:lifecycle'
  AND payload_json LIKE '%"legacyType":"crm_note"%';

-- Everything else with a crm_* legacyType: activities, tasks, base
-- crm_lead_synced placeholders, future crm_* kinds we haven't named yet.
UPDATE events
SET source_id = 'crm',
    kind      = 'lifecycle_change'
WHERE source_id = 'ui:lifecycle'
  AND payload_json LIKE '%"legacyType":"crm_%';
