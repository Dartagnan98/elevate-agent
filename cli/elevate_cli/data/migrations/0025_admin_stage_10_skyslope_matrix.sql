-- Add a dedicated SkySlope & Matrix Prep listing stage after Listing Intake.
-- SQLite cannot ALTER a CHECK constraint directly; the Admin DB is local and
-- the stage check is the only schema text that changes here, so update the
-- recorded CREATE TABLE SQL in place and bump schema_version through the
-- migration transaction.

PRAGMA writable_schema=ON;
UPDATE sqlite_master
SET sql = replace(sql, 'CHECK (current_stage BETWEEN 0 AND 9)', 'CHECK (current_stage BETWEEN 0 AND 10)')
WHERE type = 'table' AND name = 'deals';

UPDATE sqlite_master
SET sql = replace(replace(sql,
  'CHECK (from_stage IS NULL OR from_stage BETWEEN 0 AND 9)',
  'CHECK (from_stage IS NULL OR from_stage BETWEEN 0 AND 10)'),
  'CHECK (to_stage IS NULL OR to_stage BETWEEN 0 AND 9)',
  'CHECK (to_stage IS NULL OR to_stage BETWEEN 0 AND 10)')
WHERE type = 'table' AND name IN ('admin_action_registry', 'deal_events');
PRAGMA writable_schema=OFF;

UPDATE deals
SET current_stage = current_stage + 1,
    updated_at = datetime('now'),
    stage_entered_at = datetime('now')
WHERE side = 'listing'
  AND current_stage >= 3
  AND NOT EXISTS (
    SELECT 1 FROM meta WHERE key = 'admin_stage_10_skyslope_matrix_shift_applied'
  );

INSERT OR IGNORE INTO meta(key, value)
VALUES ('admin_stage_10_skyslope_matrix_shift_applied', datetime('now'));
