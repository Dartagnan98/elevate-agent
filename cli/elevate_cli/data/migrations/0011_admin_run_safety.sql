-- Make dispatcher enqueue durable and idempotent for event-triggered runs.

CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_action_runs_registry_event_once
    ON admin_action_runs(registry_id, deal_event_id)
    WHERE deal_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_admin_action_runs_running_started
    ON admin_action_runs(status, started_at)
    WHERE status = 'running';
