-- 0007_admin_run_contract.sql
-- Track the Admin Hub run lifecycle as a first-class, idempotent contract.

ALTER TABLE admin_action_runs ADD COLUMN callback_token_hash TEXT;
ALTER TABLE admin_action_runs ADD COLUMN started_at TEXT;
ALTER TABLE admin_action_runs ADD COLUMN result_idempotency_key TEXT;
ALTER TABLE admin_action_runs ADD COLUMN result_json TEXT;
ALTER TABLE admin_action_runs ADD COLUMN human_prompt_json TEXT;

CREATE INDEX IF NOT EXISTS idx_admin_action_runs_started
    ON admin_action_runs(started_at)
    WHERE started_at IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_action_runs_result_idempotency
    ON admin_action_runs(id, result_idempotency_key)
    WHERE result_idempotency_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_deal_attachments_run_file
    ON deal_attachments(deal_id, source_run_id, kind, file_path)
    WHERE source_run_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS admin_date_trigger_firings (
    id          TEXT PRIMARY KEY,
    deal_id     TEXT NOT NULL,
    registry_id TEXT NOT NULL,
    run_id      TEXT,
    field_key   TEXT NOT NULL,
    offset_days INTEGER NOT NULL DEFAULT 0,
    target_date TEXT NOT NULL,
    fired_at    TEXT NOT NULL,
    actor       TEXT NOT NULL,

    UNIQUE(deal_id, registry_id, field_key, offset_days, target_date),
    FOREIGN KEY(deal_id) REFERENCES deals(id) ON DELETE CASCADE,
    FOREIGN KEY(registry_id) REFERENCES admin_action_registry(id) ON DELETE CASCADE,
    FOREIGN KEY(run_id) REFERENCES admin_action_runs(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_date_trigger_firings_deal
    ON admin_date_trigger_firings(deal_id, fired_at);
