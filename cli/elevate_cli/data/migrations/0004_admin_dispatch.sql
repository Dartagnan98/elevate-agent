-- 0004_admin_dispatch.sql
-- Admin Hub stage-action registry + run log + per-province conditional docs.
-- Lives in $ELEVATE_HOME/data/operational.db. The registry is the canonical
-- runtime store; YAML at cli/elevate_cli/admin_actions/registry.yaml is a
-- seed/dev fixture only.

CREATE TABLE IF NOT EXISTS admin_action_registry (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    -- side=NULL means the rule applies to both listing and buyer cards.
    side                 TEXT
                             CHECK (side IS NULL OR side IN ('listing','buyer')),
    -- from_stage/to_stage gate stage_entry/stage_exit triggers. Either or
    -- both may be NULL for triggers that don't carry a stage transition
    -- (toggle_change, recurring, manual, external_event, time_offset).
    from_stage           INTEGER
                             CHECK (from_stage IS NULL OR from_stage BETWEEN 0 AND 9),
    to_stage             INTEGER
                             CHECK (to_stage IS NULL OR to_stage BETWEEN 0 AND 9),
    trigger              TEXT NOT NULL
                             CHECK (trigger IN (
                                 'stage_entry','stage_exit','toggle_change',
                                 'recurring','time_offset','external_event','manual'
                             )),
    -- field_key is required for toggle_change rules ("fire when this field
    -- flips"); null for stage and recurring rules.
    field_key            TEXT,
    -- condition_json is a flat {field:value} dict that must match the deal
    -- before the rule queues a run. NULL = always match.
    condition_json       TEXT,
    skill                TEXT NOT NULL,
    skill_args_json      TEXT,
    -- province_filter_json is a JSON array; NULL = applies to all provinces.
    province_filter_json TEXT,
    enabled              INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    priority             INTEGER NOT NULL DEFAULT 0,
    approval_required    INTEGER NOT NULL DEFAULT 0 CHECK (approval_required IN (0,1)),
    version              INTEGER NOT NULL DEFAULT 1,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,

    CHECK (trigger != 'toggle_change' OR field_key IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_admin_action_registry_trigger_enabled
    ON admin_action_registry(trigger, enabled);
CREATE INDEX IF NOT EXISTS idx_admin_action_registry_side_to_stage
    ON admin_action_registry(side, to_stage)
    WHERE to_stage IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_admin_action_registry_field_key
    ON admin_action_registry(field_key)
    WHERE field_key IS NOT NULL;


CREATE TABLE IF NOT EXISTS admin_action_runs (
    id              TEXT PRIMARY KEY,
    registry_id     TEXT NOT NULL,
    deal_id         TEXT NOT NULL,
    deal_event_id   TEXT,
    -- cron_job_id is set once the worker hands the run off to cron.jobs.
    cron_job_id     TEXT,
    status          TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN (
                            'queued','running','succeeded',
                            'failed','skipped','cancelled'
                        )),
    output_path     TEXT,
    error_message   TEXT,
    -- payload_json snapshots the trigger context (toggle old/new, stage
    -- numbers, etc.) so the run row stays meaningful even after the deal
    -- has moved on.
    payload_json    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    completed_at    TEXT,

    FOREIGN KEY(registry_id)   REFERENCES admin_action_registry(id) ON DELETE CASCADE,
    FOREIGN KEY(deal_id)       REFERENCES deals(id)                  ON DELETE CASCADE,
    FOREIGN KEY(deal_event_id) REFERENCES deal_events(id)            ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_action_runs_deal_created
    ON admin_action_runs(deal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_admin_action_runs_status_created
    ON admin_action_runs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_admin_action_runs_registry_created
    ON admin_action_runs(registry_id, created_at);


CREATE TABLE IF NOT EXISTS conditional_docs (
    id          TEXT PRIMARY KEY,
    province    TEXT NOT NULL DEFAULT 'BC',
    field_key   TEXT NOT NULL,
    field_value TEXT NOT NULL,
    doc_code    TEXT NOT NULL,
    doc_name    TEXT NOT NULL,
    notes       TEXT,
    created_at  TEXT NOT NULL,

    UNIQUE(province, field_key, field_value, doc_code)
);
CREATE INDEX IF NOT EXISTS idx_conditional_docs_lookup
    ON conditional_docs(province, field_key, field_value);
