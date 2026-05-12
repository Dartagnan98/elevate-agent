-- 0009_agent_handoffs.sql
-- Durable visible-agent handoff bus for $ELEVATE_HOME/data/operational.db.

CREATE TABLE IF NOT EXISTS agent_handoffs (
    id                 TEXT PRIMARY KEY,
    from_agent_id      TEXT NOT NULL,
    to_agent_id        TEXT NOT NULL,
    title              TEXT NOT NULL,
    task               TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'queued'
                           CHECK (status IN (
                             'queued','running','waiting_human',
                             'completed','failed','cancelled'
                           )),
    priority           TEXT NOT NULL DEFAULT 'normal'
                           CHECK (priority IN ('low','normal','high','urgent')),
    deal_id            TEXT,
    profile_id         TEXT,
    contact_id         TEXT,
    conversation_id    TEXT,
    source_run_id      TEXT,
    parent_handoff_id  TEXT,
    cron_job_id        TEXT,
    idempotency_key    TEXT,
    result_idempotency_key TEXT,
    payload_json       TEXT,
    result_json        TEXT,
    error_message      TEXT,
    created_at         TEXT NOT NULL,
    claimed_at         TEXT,
    updated_at         TEXT NOT NULL,
    completed_at       TEXT,

    CHECK (from_agent_id != to_agent_id),
    UNIQUE(from_agent_id, to_agent_id, idempotency_key),
    FOREIGN KEY(deal_id) REFERENCES deals(id) ON DELETE SET NULL,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE SET NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE SET NULL,
    FOREIGN KEY(parent_handoff_id) REFERENCES agent_handoffs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_handoffs_status_created
    ON agent_handoffs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_handoffs_to_status
    ON agent_handoffs(to_agent_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_handoffs_from_status
    ON agent_handoffs(from_agent_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_handoffs_deal
    ON agent_handoffs(deal_id, created_at)
    WHERE deal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_handoffs_contact
    ON agent_handoffs(contact_id, created_at)
    WHERE contact_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_handoffs_profile
    ON agent_handoffs(profile_id, created_at)
    WHERE profile_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_handoffs_source_run
    ON agent_handoffs(source_run_id)
    WHERE source_run_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS agent_handoff_messages (
    id              TEXT PRIMARY KEY,
    handoff_id      TEXT NOT NULL,
    from_agent_id   TEXT NOT NULL,
    to_agent_id     TEXT,
    kind            TEXT NOT NULL DEFAULT 'note'
                        CHECK (kind IN (
                          'request','note','status','result','human_prompt','error'
                        )),
    content         TEXT NOT NULL DEFAULT '',
    payload_json    TEXT,
    created_at      TEXT NOT NULL,

    FOREIGN KEY(handoff_id) REFERENCES agent_handoffs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_handoff_messages_handoff_created
    ON agent_handoff_messages(handoff_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_handoff_messages_kind_created
    ON agent_handoff_messages(kind, created_at);
