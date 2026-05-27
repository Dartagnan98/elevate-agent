-- Add a dedicated SkySlope & Matrix Prep listing stage after Listing Intake.

ALTER TABLE deals
    DROP CONSTRAINT IF EXISTS deals_current_stage_check;
ALTER TABLE deals
    ADD CONSTRAINT deals_current_stage_check CHECK (current_stage BETWEEN 0 AND 10);

ALTER TABLE admin_action_registry
    DROP CONSTRAINT IF EXISTS admin_action_registry_from_stage_check;
ALTER TABLE admin_action_registry
    ADD CONSTRAINT admin_action_registry_from_stage_check
    CHECK (from_stage IS NULL OR from_stage BETWEEN 0 AND 10);

ALTER TABLE admin_action_registry
    DROP CONSTRAINT IF EXISTS admin_action_registry_to_stage_check;
ALTER TABLE admin_action_registry
    ADD CONSTRAINT admin_action_registry_to_stage_check
    CHECK (to_stage IS NULL OR to_stage BETWEEN 0 AND 10);

ALTER TABLE deal_events
    DROP CONSTRAINT IF EXISTS deal_events_from_stage_check;
ALTER TABLE deal_events
    ADD CONSTRAINT deal_events_from_stage_check
    CHECK (from_stage IS NULL OR from_stage BETWEEN 0 AND 10);

ALTER TABLE deal_events
    DROP CONSTRAINT IF EXISTS deal_events_to_stage_check;
ALTER TABLE deal_events
    ADD CONSTRAINT deal_events_to_stage_check
    CHECK (to_stage IS NULL OR to_stage BETWEEN 0 AND 10);

UPDATE deals
SET current_stage = current_stage + 1,
    updated_at = CURRENT_TIMESTAMP::text,
    stage_entered_at = CURRENT_TIMESTAMP::text
WHERE side = 'listing'
  AND current_stage >= 3
  AND NOT EXISTS (
    SELECT 1 FROM meta WHERE key = 'admin_stage_10_skyslope_matrix_shift_applied'
  );

INSERT INTO meta(key, value)
VALUES ('admin_stage_10_skyslope_matrix_shift_applied', CURRENT_TIMESTAMP::text)
ON CONFLICT (key) DO NOTHING;
