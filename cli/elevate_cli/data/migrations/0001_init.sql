-- 0001_init.sql
-- Initial schema for $ELEVATE_HOME/data/operational.db
--
-- Owner: Dartagnan
-- Source-of-truth contracts:
--   docs/central-data-model.md
--   docs/source-keys.md
--
-- This file MUST be append-only — once shipped, edits become a numbered
-- 0002_*.sql migration, never an in-place rewrite. The migration runner
-- (elevate_cli/data/migrations.py) applies files in lexical order and
-- records each in `_schema_migrations`.

-- ─── PRAGMAs (set at connection time, not in this file) ─────────────────
-- See connection.py for journal_mode=WAL / synchronous=NORMAL /
-- foreign_keys=ON / busy_timeout=5000.

-- ─── Migration ledger ──────────────────────────────────────────────────
-- Created lazily by the runner if missing. Listed here for documentation;
-- the runner short-circuits the CREATE if it already exists.

CREATE TABLE IF NOT EXISTS _schema_migrations (
    version TEXT PRIMARY KEY,        -- the leading number, e.g. '0001'
    name    TEXT NOT NULL,           -- full filename, e.g. '0001_init.sql'
    sha256  TEXT NOT NULL,           -- hash of file content at apply time
    applied_at TEXT NOT NULL         -- ISO timestamp
);

-- ─── Identity / contact graph ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS contacts (
    id              TEXT PRIMARY KEY,
    display_name    TEXT,
    primary_email   TEXT,
    primary_phone   TEXT,
    type            TEXT NOT NULL DEFAULT 'unclassified'
                       CHECK (type IN ('unclassified','buyer','listing','other')),
    stage           TEXT NOT NULL DEFAULT 'cold',
    owner_notes     TEXT,
    parked_reason   TEXT,
    has_open_conflict INTEGER NOT NULL DEFAULT 0
                       CHECK (has_open_conflict IN (0,1)),
    last_activity_at TEXT,
    classified_at   TEXT,
    -- source_key locks the upstream id so re-imports collide instead of
    -- duplicating. See docs/source-keys.md per-source contracts.
    source_key      TEXT,
    ingest_run_id   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY(ingest_run_id) REFERENCES ingest_runs(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_contacts_source_key
    ON contacts(source_key) WHERE source_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_stage ON contacts(stage);
CREATE INDEX IF NOT EXISTS idx_contacts_type ON contacts(type);
CREATE INDEX IF NOT EXISTS idx_contacts_last_activity ON contacts(last_activity_at);
CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(primary_email);
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(primary_phone);

CREATE TABLE IF NOT EXISTS identities (
    id          TEXT PRIMARY KEY,
    contact_id  TEXT NOT NULL,
    kind        TEXT NOT NULL
                  CHECK (kind IN (
                    'email','phone',
                    'instagram_id','instagram_handle',
                    'facebook_id','telegram_id',
                    'lofty_id','fub_id','sierra_id','brivity_id','boldtrail_id',
                    'apple_handle','wa_id'
                  )),
    value       TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    verified    INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0,1)),
    created_at  TEXT NOT NULL,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_identities_kind_value
    ON identities(kind, value);
CREATE INDEX IF NOT EXISTS idx_identities_contact ON identities(contact_id);

-- ─── Conversations & events ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS conversations (
    id              TEXT PRIMARY KEY,
    contact_id      TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    channel         TEXT NOT NULL
                      CHECK (channel IN (
                        'email','sms','imessage','messenger','instagram',
                        'whatsapp','telegram','voice','crm'
                      )),
    thread_key      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open','done','archived')),
    inbound_count   INTEGER NOT NULL DEFAULT 0,
    outbound_count  INTEGER NOT NULL DEFAULT 0,
    last_inbound_at  TEXT,
    last_outbound_at TEXT,
    heat_score      INTEGER NOT NULL DEFAULT 0,
    heat_label      TEXT NOT NULL DEFAULT 'normal'
                      CHECK (heat_label IN ('hot','warm','watch','normal')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_conversations_source_thread
    ON conversations(source_id, thread_key);
CREATE INDEX IF NOT EXISTS idx_conversations_contact ON conversations(contact_id);
CREATE INDEX IF NOT EXISTS idx_conversations_heat ON conversations(heat_label, heat_score);
CREATE INDEX IF NOT EXISTS idx_conversations_last_in ON conversations(last_inbound_at);

-- Append-only audit log. events.kind is a frozen enum — adding a new
-- value requires a numbered migration that updates this CHECK.
CREATE TABLE IF NOT EXISTS events (
    id              TEXT PRIMARY KEY,
    contact_id      TEXT NOT NULL,
    conversation_id TEXT,
    kind            TEXT NOT NULL CHECK (kind IN (
                      'inbound','outbound','draft','approval','send','bounce',
                      'reply_attributed','classified','parked','unparked',
                      'pcs_activity','lifecycle_change','note',
                      'merge','merge_conflict',
                      'template_candidate','template_approved','template_rejected',
                      'attribution_ambiguous',
                      'ingest_run_started','ingest_run_completed'
                    )),
    channel         TEXT,
    source_id       TEXT NOT NULL,
    actor           TEXT NOT NULL,
    template_id     TEXT,
    payload_json    TEXT,
    payload_ref     TEXT,
    ingest_run_id   TEXT,
    event_hash      TEXT NOT NULL,
    ts              TEXT NOT NULL,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id),
    FOREIGN KEY(template_id) REFERENCES templates(id),
    FOREIGN KEY(ingest_run_id) REFERENCES ingest_runs(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_events_event_hash ON events(event_hash);
CREATE INDEX IF NOT EXISTS idx_events_contact_ts ON events(contact_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_conv_ts ON events(conversation_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_kind_ts ON events(kind, ts);
CREATE INDEX IF NOT EXISTS idx_events_template ON events(template_id) WHERE template_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_ingest_run ON events(ingest_run_id);

-- Nightly rollup, refreshed by a maintenance task. Two row shapes share
-- the same table — one keyed by template_id, one by contact_id. The
-- non-keyed FK column is NULL.
CREATE TABLE IF NOT EXISTS events_summary (
    bucket          TEXT NOT NULL CHECK (bucket IN ('template','contact')),
    template_id     TEXT,
    contact_id      TEXT,
    day             TEXT NOT NULL,        -- YYYY-MM-DD UTC
    sends           INTEGER NOT NULL DEFAULT 0,
    replies         INTEGER NOT NULL DEFAULT 0,
    replies_confident INTEGER NOT NULL DEFAULT 0,
    replies_ambiguous INTEGER NOT NULL DEFAULT 0,
    bounces         INTEGER NOT NULL DEFAULT 0,
    refreshed_at    TEXT NOT NULL,
    PRIMARY KEY (bucket, template_id, contact_id, day),
    FOREIGN KEY(template_id) REFERENCES templates(id),
    FOREIGN KEY(contact_id)  REFERENCES contacts(id)
);
CREATE INDEX IF NOT EXISTS idx_events_summary_day ON events_summary(day);

-- ─── Ingest tracking ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ingest_runs (
    id                TEXT PRIMARY KEY,
    source_id         TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    completed_at      TEXT,
    status            TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','completed','failed','partial')),
    rows_seen         INTEGER NOT NULL DEFAULT 0,
    rows_written      INTEGER NOT NULL DEFAULT 0,
    rows_quarantined  INTEGER NOT NULL DEFAULT 0,
    error             TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_source ON ingest_runs(source_id, started_at);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_status ON ingest_runs(status);

-- ─── Identity conflict quarantine ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS identity_conflicts (
    id                       TEXT PRIMARY KEY,
    kind                     TEXT NOT NULL,
    value                    TEXT NOT NULL,
    candidate_contact_ids    TEXT NOT NULL,   -- JSON array
    reason                   TEXT NOT NULL
                                CHECK (reason IN (
                                  'multiple_matches',
                                  'non_deterministic_merge_blocked',
                                  'cross_kind_mismatch'
                                )),
    created_at               TEXT NOT NULL,
    resolved_at              TEXT,
    resolved_by              TEXT,
    resolution               TEXT             -- merged_into:<id> | kept_separate | discarded
);
CREATE INDEX IF NOT EXISTS idx_identity_conflicts_open
    ON identity_conflicts(resolved_at) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_identity_conflicts_kv
    ON identity_conflicts(kind, value);

-- ─── Lead signals (cold MLS / scrape data) ─────────────────────────────

CREATE TABLE IF NOT EXISTS lead_signals (
    id                       TEXT PRIMARY KEY,
    source_id                TEXT NOT NULL,
    source_native_id         TEXT NOT NULL,
    payload_json             TEXT NOT NULL,
    name                     TEXT,
    email                    TEXT,
    phone                    TEXT,
    last_activity_at         TEXT,
    graduated_at             TEXT,
    graduated_to_contact_id  TEXT,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    FOREIGN KEY(graduated_to_contact_id) REFERENCES contacts(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_lead_signals_source_native
    ON lead_signals(source_id, source_native_id);
CREATE INDEX IF NOT EXISTS idx_lead_signals_open
    ON lead_signals(last_activity_at) WHERE graduated_at IS NULL;

CREATE TABLE IF NOT EXISTS pcs_buyers (
    contact_id               TEXT PRIMARY KEY,
    lead_signal_id           TEXT NOT NULL,
    score                    INTEGER,
    tier                     TEXT,
    days                     INTEGER,
    searches_json            TEXT,
    matching_listings_json   TEXT,
    last_activity_at         TEXT,
    last_scraped_at          TEXT,
    profile_url              TEXT,
    FOREIGN KEY(contact_id)     REFERENCES contacts(id) ON DELETE CASCADE,
    FOREIGN KEY(lead_signal_id) REFERENCES lead_signals(id)
);
CREATE INDEX IF NOT EXISTS idx_pcs_buyers_tier ON pcs_buyers(tier);
CREATE INDEX IF NOT EXISTS idx_pcs_buyers_last_activity ON pcs_buyers(last_activity_at);

-- ─── Templates (folded in from outreach.db) ────────────────────────────
--
-- Existing semantic columns from outreach.db: id, lane, name, body,
-- channel, active, uses, replies, wins, status, rationale, created_at,
-- updated_at. New for V1: version, match_rules, origin,
-- proposed_by_event_id, parent_template_id, approved_at, approved_by.

CREATE TABLE IF NOT EXISTS templates (
    id                    TEXT PRIMARY KEY,
    lane                  TEXT NOT NULL,
    name                  TEXT NOT NULL,
    body                  TEXT NOT NULL,
    channel               TEXT NOT NULL DEFAULT 'any',
    active                INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    status                TEXT NOT NULL DEFAULT 'live'
                            CHECK (status IN ('proposed','live','superseded','retired')),
    rationale             TEXT,
    uses                  INTEGER NOT NULL DEFAULT 0,
    replies               INTEGER NOT NULL DEFAULT 0,
    wins                  INTEGER NOT NULL DEFAULT 0,
    version               INTEGER NOT NULL DEFAULT 1,
    match_rules           TEXT,                    -- JSON eligibility predicates
    origin                TEXT NOT NULL DEFAULT 'human'
                            CHECK (origin IN (
                              'human','ai_oneoff','ai_pattern','ai_failure_analysis'
                            )),
    proposed_by_event_id  TEXT,
    parent_template_id    TEXT,
    approved_at           TEXT,
    approved_by           TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    FOREIGN KEY(proposed_by_event_id) REFERENCES events(id),
    FOREIGN KEY(parent_template_id)   REFERENCES templates(id),
    -- Approval invariant: a template can only be 'live' if a human signed off.
    CHECK (
      status != 'live'
      OR (approved_at IS NOT NULL AND approved_by IS NOT NULL)
    ),
    -- Proposed templates are not yet approved.
    CHECK (status != 'proposed' OR approved_at IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_templates_lane ON templates(lane, active);
CREATE INDEX IF NOT EXISTS idx_templates_status ON templates(status);
CREATE INDEX IF NOT EXISTS idx_templates_origin ON templates(origin);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_templates_lane_name
    ON templates(lane, name, version);

-- ─── Outreach plumbing (carried over from outreach.db) ─────────────────

CREATE TABLE IF NOT EXISTS draft_attempts (
    id                  TEXT PRIMARY KEY,
    template_id         TEXT NOT NULL,
    lane                TEXT NOT NULL,
    source_id           TEXT,
    -- During backfill (Sprint 1E) we map outreach.db's `thread_id` to the
    -- new `conversation_id`. Both columns coexist during the cutover so
    -- shadow reads can join either way; legacy `thread_id` will be
    -- dropped in a later migration once Sprint 2 is green.
    conversation_id     TEXT,
    thread_id           TEXT,
    task_id             TEXT,
    source_key          TEXT,
    status              TEXT NOT NULL DEFAULT 'drafted',
    outcome             TEXT,
    replied_at          TEXT,
    created_at          TEXT NOT NULL,
    outcome_recorded_at TEXT,
    FOREIGN KEY(template_id)     REFERENCES templates(id),
    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);
CREATE INDEX IF NOT EXISTS idx_attempts_template ON draft_attempts(template_id);
CREATE INDEX IF NOT EXISTS idx_attempts_thread ON draft_attempts(thread_id);
CREATE INDEX IF NOT EXISTS idx_attempts_conversation ON draft_attempts(conversation_id);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_attempts_source_key
    ON draft_attempts(source_key) WHERE source_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS send_queue (
    id                  TEXT PRIMARY KEY,
    idempotency_key     TEXT NOT NULL UNIQUE,
    source_id           TEXT NOT NULL,
    thread_id           TEXT NOT NULL,
    conversation_id     TEXT,
    task_id             TEXT NOT NULL,
    channel             TEXT NOT NULL,
    payload_json        TEXT NOT NULL,
    source_key          TEXT,
    status              TEXT NOT NULL DEFAULT 'queued',
    attempts            INTEGER NOT NULL DEFAULT 0,
    next_retry_at       TEXT,
    last_error          TEXT,
    provider_message_id TEXT,
    attempt_id          TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);
CREATE INDEX IF NOT EXISTS idx_send_queue_status ON send_queue(status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_send_queue_task ON send_queue(source_id, thread_id, task_id);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_send_queue_source_key
    ON send_queue(source_key) WHERE source_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS thread_meta (
    source_id   TEXT NOT NULL,
    thread_id   TEXT NOT NULL,
    score       INTEGER NOT NULL DEFAULT 0,
    label       TEXT NOT NULL DEFAULT 'unknown',
    reason      TEXT,
    scored_by   TEXT,
    scored_at   TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (source_id, thread_id)
);
CREATE INDEX IF NOT EXISTS idx_thread_meta_label ON thread_meta(label);
CREATE INDEX IF NOT EXISTS idx_thread_meta_score ON thread_meta(score);

CREATE TABLE IF NOT EXISTS lane_config (
    lane                  TEXT PRIMARY KEY,
    enabled_channels_json TEXT NOT NULL DEFAULT '[]',
    updated_at            TEXT NOT NULL
);

-- O(1) provider-message dedupe for composio inbound (and any other
-- toolkit-keyed source). Provider message ids are only unique within a
-- toolkit's namespace, so we key on (toolkit, provider_message_id).
CREATE TABLE IF NOT EXISTS inbound_seen (
    toolkit             TEXT NOT NULL,
    provider_message_id TEXT NOT NULL,
    source_key          TEXT,
    seen_at             TEXT NOT NULL,
    PRIMARY KEY (toolkit, provider_message_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_inbound_seen_source_key
    ON inbound_seen(source_key) WHERE source_key IS NOT NULL;

-- ─── Shadow-read parity (Sprint 2 cutover safety) ──────────────────────

CREATE TABLE IF NOT EXISTS data_parity_snapshots (
    id                  TEXT PRIMARY KEY,
    endpoint            TEXT NOT NULL,
    request_args_json   TEXT NOT NULL,
    jsonl_response_hash TEXT NOT NULL,
    db_response_hash    TEXT NOT NULL,
    diff_json           TEXT,                 -- nullable, populated only on mismatch
    captured_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_parity_endpoint_ts
    ON data_parity_snapshots(endpoint, captured_at);
CREATE INDEX IF NOT EXISTS idx_parity_diffs
    ON data_parity_snapshots(captured_at) WHERE diff_json IS NOT NULL;

-- ─── Generic key/value meta ────────────────────────────────────────────
-- Used by the existing seed-marker logic and by future maintenance flags
-- (e.g. last events_summary refresh ts). Kept loose on purpose.

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
