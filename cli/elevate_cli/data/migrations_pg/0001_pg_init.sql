-- _schema_migrations is created by the migration runner itself
-- (see elevate_cli/data/migrations.py::_ensure_ledger).

CREATE TABLE contacts (
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
    source_key      TEXT,
    ingest_run_id   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    heat_label TEXT NOT NULL DEFAULT 'normal'
        CHECK (heat_label IN ('hot','warm','watch','normal')),
    heat_score INTEGER NOT NULL DEFAULT 0
        CHECK (heat_score BETWEEN 0 AND 100),
    heat_reason TEXT,
    needs_follow_up INTEGER NOT NULL DEFAULT 0
        CHECK (needs_follow_up IN (0,1)),
    next_follow_up_at TEXT,
    buyer_search_active INTEGER NOT NULL DEFAULT 0
        CHECK (buyer_search_active IN (0,1)),
    listing_active INTEGER NOT NULL DEFAULT 0
        CHECK (listing_active IN (0,1)),
    ai_last_reviewed_at TEXT,
    ai_review_run_id TEXT,
    pipeline_status TEXT
        CHECK (pipeline_status IS NULL OR pipeline_status IN (
            'new_lead', 'follow_up', 'ghosting', 'dead',
            'closed_seller', 'closed_buyer'
        )),
    pipeline_status_set_at TEXT,
    pipeline_status_set_by TEXT
        CHECK (pipeline_status_set_by IS NULL OR pipeline_status_set_by IN (
            'operator', 'ai'
        )),
    cannot_text INTEGER NOT NULL DEFAULT 0
        CHECK (cannot_text IN (0,1)),
    cannot_call INTEGER NOT NULL DEFAULT 0
        CHECK (cannot_call IN (0,1)),
    cannot_email INTEGER NOT NULL DEFAULT 0
        CHECK (cannot_email IN (0,1)),
    unsubscribed INTEGER NOT NULL DEFAULT 0
        CHECK (unsubscribed IN (0,1)),
    hidden INTEGER NOT NULL DEFAULT 0
        CHECK (hidden IN (0,1)),
    buying_time_frame TEXT,
    selling_time_frame TEXT,
    pre_qual_status TEXT,
    has_house_to_sell TEXT,
    first_time_home_buyer TEXT,
    with_buyer_agent TEXT,
    with_listing_agent TEXT,
    mortgage_status TEXT,
    buy_house_intent TEXT,
    opportunity TEXT,
    referred_by TEXT,
    pond_id TEXT,
    pond_name TEXT,
    lead_types_json TEXT,
    segments_json TEXT,
    crm_user_id TEXT
);
CREATE UNIQUE INDEX uniq_contacts_source_key
    ON contacts(source_key) WHERE source_key IS NOT NULL;
CREATE INDEX idx_contacts_stage ON contacts(stage);
CREATE INDEX idx_contacts_type ON contacts(type);
CREATE INDEX idx_contacts_last_activity ON contacts(last_activity_at);
CREATE INDEX idx_contacts_email ON contacts(primary_email);
CREATE INDEX idx_contacts_phone ON contacts(primary_phone);
CREATE TABLE conversations (
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
    updated_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX uniq_conversations_source_thread
    ON conversations(source_id, thread_key);
CREATE INDEX idx_conversations_contact ON conversations(contact_id);
CREATE INDEX idx_conversations_heat ON conversations(heat_label, heat_score);
CREATE INDEX idx_conversations_last_in ON conversations(last_inbound_at);
CREATE TABLE events (
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
    ts              TEXT NOT NULL
);
CREATE UNIQUE INDEX uniq_events_event_hash ON events(event_hash);
CREATE INDEX idx_events_contact_ts ON events(contact_id, ts);
CREATE INDEX idx_events_conv_ts ON events(conversation_id, ts);
CREATE INDEX idx_events_kind_ts ON events(kind, ts);
CREATE INDEX idx_events_template ON events(template_id) WHERE template_id IS NOT NULL;
CREATE INDEX idx_events_ingest_run ON events(ingest_run_id);
CREATE TABLE events_summary (
    bucket          TEXT NOT NULL CHECK (bucket IN ('template','contact')),
    template_id     TEXT,
    contact_id      TEXT,
    day             TEXT NOT NULL,
    sends           INTEGER NOT NULL DEFAULT 0,
    replies         INTEGER NOT NULL DEFAULT 0,
    replies_confident INTEGER NOT NULL DEFAULT 0,
    replies_ambiguous INTEGER NOT NULL DEFAULT 0,
    bounces         INTEGER NOT NULL DEFAULT 0,
    refreshed_at    TEXT NOT NULL,
    PRIMARY KEY (bucket, template_id, contact_id, day)
);
CREATE INDEX idx_events_summary_day ON events_summary(day);
CREATE TABLE ingest_runs (
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
CREATE INDEX idx_ingest_runs_source ON ingest_runs(source_id, started_at);
CREATE INDEX idx_ingest_runs_status ON ingest_runs(status);
CREATE TABLE identity_conflicts (
    id                       TEXT PRIMARY KEY,
    kind                     TEXT NOT NULL,
    value                    TEXT NOT NULL,
    candidate_contact_ids    TEXT NOT NULL,
    reason                   TEXT NOT NULL
                                CHECK (reason IN (
                                  'multiple_matches',
                                  'non_deterministic_merge_blocked',
                                  'cross_kind_mismatch'
                                )),
    created_at               TEXT NOT NULL,
    resolved_at              TEXT,
    resolved_by              TEXT,
    resolution               TEXT
);
CREATE INDEX idx_identity_conflicts_open
    ON identity_conflicts(resolved_at) WHERE resolved_at IS NULL;
CREATE INDEX idx_identity_conflicts_kv
    ON identity_conflicts(kind, value);
CREATE TABLE lead_signals (
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
    updated_at               TEXT NOT NULL
);
CREATE UNIQUE INDEX uniq_lead_signals_source_native
    ON lead_signals(source_id, source_native_id);
CREATE INDEX idx_lead_signals_open
    ON lead_signals(last_activity_at) WHERE graduated_at IS NULL;
CREATE TABLE pcs_buyers (
    contact_id               TEXT PRIMARY KEY,
    lead_signal_id           TEXT NOT NULL,
    score                    INTEGER,
    tier                     TEXT,
    days                     INTEGER,
    searches_json            TEXT,
    matching_listings_json   TEXT,
    last_activity_at         TEXT,
    last_scraped_at          TEXT,
    profile_url              TEXT
);
CREATE INDEX idx_pcs_buyers_tier ON pcs_buyers(tier);
CREATE INDEX idx_pcs_buyers_last_activity ON pcs_buyers(last_activity_at);
CREATE TABLE templates (
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
    match_rules           TEXT,
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
    CHECK (
      status != 'live'
      OR (approved_at IS NOT NULL AND approved_by IS NOT NULL)
    ),
    CHECK (status != 'proposed' OR approved_at IS NULL)
);
CREATE INDEX idx_templates_lane ON templates(lane, active);
CREATE INDEX idx_templates_status ON templates(status);
CREATE INDEX idx_templates_origin ON templates(origin);
CREATE UNIQUE INDEX uniq_templates_lane_name
    ON templates(lane, name, version);
CREATE TABLE draft_attempts (
    id                  TEXT PRIMARY KEY,
    template_id         TEXT NOT NULL,
    lane                TEXT NOT NULL,
    source_id           TEXT,
    conversation_id     TEXT,
    thread_id           TEXT,
    task_id             TEXT,
    source_key          TEXT,
    status              TEXT NOT NULL DEFAULT 'drafted',
    outcome             TEXT,
    replied_at          TEXT,
    created_at          TEXT NOT NULL,
    outcome_recorded_at TEXT
);
CREATE INDEX idx_attempts_template ON draft_attempts(template_id);
CREATE INDEX idx_attempts_thread ON draft_attempts(thread_id);
CREATE INDEX idx_attempts_conversation ON draft_attempts(conversation_id);
CREATE UNIQUE INDEX uniq_attempts_source_key
    ON draft_attempts(source_key) WHERE source_key IS NOT NULL;
CREATE TABLE send_queue (
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
    updated_at          TEXT NOT NULL
);
CREATE INDEX idx_send_queue_status ON send_queue(status, next_retry_at);
CREATE INDEX idx_send_queue_task ON send_queue(source_id, thread_id, task_id);
CREATE UNIQUE INDEX uniq_send_queue_source_key
    ON send_queue(source_key) WHERE source_key IS NOT NULL;
CREATE TABLE thread_meta (
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
CREATE INDEX idx_thread_meta_label ON thread_meta(label);
CREATE INDEX idx_thread_meta_score ON thread_meta(score);
CREATE TABLE lane_config (
    lane                  TEXT PRIMARY KEY,
    enabled_channels_json TEXT NOT NULL DEFAULT '[]',
    updated_at            TEXT NOT NULL
);
CREATE TABLE inbound_seen (
    toolkit             TEXT NOT NULL,
    provider_message_id TEXT NOT NULL,
    source_key          TEXT,
    seen_at             TEXT NOT NULL,
    PRIMARY KEY (toolkit, provider_message_id)
);
CREATE UNIQUE INDEX uniq_inbound_seen_source_key
    ON inbound_seen(source_key) WHERE source_key IS NOT NULL;
CREATE TABLE data_parity_snapshots (
    id                  TEXT PRIMARY KEY,
    endpoint            TEXT NOT NULL,
    request_args_json   TEXT NOT NULL,
    jsonl_response_hash TEXT NOT NULL,
    db_response_hash    TEXT NOT NULL,
    diff_json           TEXT,
    captured_at         TEXT NOT NULL
);
CREATE INDEX idx_parity_endpoint_ts
    ON data_parity_snapshots(endpoint, captured_at);
CREATE INDEX idx_parity_diffs
    ON data_parity_snapshots(captured_at) WHERE diff_json IS NOT NULL;
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_identity_conflicts_open_uniq
    ON identity_conflicts(kind, value, reason)
    WHERE resolved_at IS NULL;
CREATE TABLE deals (
    id                       TEXT PRIMARY KEY,
    title                    TEXT NOT NULL,
    side                     TEXT NOT NULL
                                 CHECK (side IN ('listing','buyer')),
    current_stage            INTEGER NOT NULL DEFAULT 0
                                 CHECK (current_stage BETWEEN 0 AND 9),
    status                   TEXT NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active','closed','archived')),
    province                 TEXT NOT NULL DEFAULT 'BC',
    primary_contact_id       TEXT,
    lofty_contact_id         TEXT,
    listing_address          TEXT,
    signing_authority        TEXT,
    fintrac_form_type        TEXT,
    listing_track            TEXT,
    property_subtype         TEXT,
    estate_status            TEXT,
    transaction_type         TEXT,
    listing_type             TEXT,
    pep                      INTEGER CHECK (pep IN (0,1)),
    tenanted                 INTEGER CHECK (tenanted IN (0,1)),
    poa_signing              INTEGER CHECK (poa_signing IN (0,1)),
    corporate                INTEGER CHECK (corporate IN (0,1)),
    has_suite                INTEGER CHECK (has_suite IN (0,1)),
    multiple_offers          INTEGER CHECK (multiple_offers IN (0,1)),
    family_member            INTEGER CHECK (family_member IN (0,1)),
    dual_rep                 INTEGER CHECK (dual_rep IN (0,1)),
    unrepresented_other_side INTEGER CHECK (unrepresented_other_side IN (0,1)),
    lockbox                  INTEGER CHECK (lockbox IN (0,1)),
    delayed_offer            INTEGER CHECK (delayed_offer IN (0,1)),
    sale_of_buyers_property  INTEGER CHECK (sale_of_buyers_property IN (0,1)),
    extra_toggles_json       TEXT,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    stage_entered_at         TEXT NOT NULL,
    closed_at                TEXT,
    board TEXT,
    market TEXT,
    listing_date TEXT,
    offer_date TEXT,
    subject_removal_date TEXT,
    deposit_due_date TEXT,
    completion_date TEXT,
    possession_date TEXT,
    anniversary_date TEXT,
    list_price DOUBLE PRECISION,
    offer_price DOUBLE PRECISION,
    deposit_amount DOUBLE PRECISION,
    commission_pct DOUBLE PRECISION,
    mls_number TEXT,
    legal_description TEXT,
    lot_size_sqft DOUBLE PRECISION,
    year_built INTEGER,
    deposit_in_trust_at TEXT,
    listing_published_at TEXT,
    offer_accepted_at TEXT,
    subjects_removed_at TEXT,
    completed_at TEXT,
    source_key TEXT,
    source_row_id TEXT,
    source_label TEXT,
    source_synced_at TEXT,
    crm_transaction_id TEXT,
    crm_lead_id TEXT,
    crm_property_id TEXT,
    crm_transaction_status TEXT,
    crm_transaction_type TEXT,
    crm_assigned_agent_id TEXT,
    crm_synced_at TEXT,
    home_price DOUBLE PRECISION,
    gci DOUBLE PRECISION,
    team_revenue DOUBLE PRECISION,
    agent_revenue DOUBLE PRECISION,
    expected_close_date TEXT,
    appointment_date TEXT,
    agreement_signed_date TEXT,
    contract_date TEXT,
    appraisal_date TEXT,
    home_inspection_date TEXT,
    escrow_date TEXT,
    expiration_date TEXT,
    crm_provider TEXT
    CHECK (crm_provider IS NULL OR crm_provider IN (
        'lofty', 'followupboss', 'sierra', 'brivity', 'boldtrail'
    ))
);
CREATE INDEX idx_deals_side_stage_status
    ON deals(side, current_stage, status);
CREATE INDEX idx_deals_contact
    ON deals(primary_contact_id) WHERE primary_contact_id IS NOT NULL;
CREATE INDEX idx_deals_updated_at
    ON deals(updated_at);
CREATE TABLE admin_action_registry (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    side                 TEXT
                             CHECK (side IS NULL OR side IN ('listing','buyer')),
    from_stage           INTEGER
                             CHECK (from_stage IS NULL OR from_stage BETWEEN 0 AND 9),
    to_stage             INTEGER
                             CHECK (to_stage IS NULL OR to_stage BETWEEN 0 AND 9),
    trigger              TEXT NOT NULL
                             CHECK (trigger IN (
                                 'stage_entry','stage_exit','toggle_change',
                                 'recurring','time_offset','external_event','manual'
                             )),
    field_key            TEXT,
    condition_json       TEXT,
    skill                TEXT NOT NULL,
    skill_args_json      TEXT,
    province_filter_json TEXT,
    enabled              INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    priority             INTEGER NOT NULL DEFAULT 0,
    approval_required    INTEGER NOT NULL DEFAULT 0 CHECK (approval_required IN (0,1)),
    version              INTEGER NOT NULL DEFAULT 1,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    CHECK (trigger != 'toggle_change' OR field_key IS NOT NULL)
);
CREATE INDEX idx_admin_action_registry_trigger_enabled
    ON admin_action_registry(trigger, enabled);
CREATE INDEX idx_admin_action_registry_side_to_stage
    ON admin_action_registry(side, to_stage)
    WHERE to_stage IS NOT NULL;
CREATE INDEX idx_admin_action_registry_field_key
    ON admin_action_registry(field_key)
    WHERE field_key IS NOT NULL;
CREATE TABLE conditional_docs (
    id          TEXT PRIMARY KEY,
    province    TEXT NOT NULL DEFAULT 'BC',
    field_key   TEXT NOT NULL,
    field_value TEXT NOT NULL,
    doc_code    TEXT NOT NULL,
    doc_name    TEXT NOT NULL,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    side TEXT,
    stage INTEGER,
    UNIQUE(province, field_key, field_value, doc_code)
);
CREATE INDEX idx_conditional_docs_lookup
    ON conditional_docs(province, field_key, field_value);
CREATE INDEX idx_deals_jurisdiction_status
    ON deals(province, board, market, status, updated_at);
CREATE INDEX idx_deals_province_status
    ON deals(province, status, updated_at);
CREATE INDEX idx_deals_subject_removal
    ON deals(subject_removal_date) WHERE subject_removal_date IS NOT NULL;
CREATE INDEX idx_deals_completion
    ON deals(completion_date) WHERE completion_date IS NOT NULL;
CREATE INDEX idx_deals_possession
    ON deals(possession_date) WHERE possession_date IS NOT NULL;
CREATE TABLE deal_contacts (
    id          TEXT PRIMARY KEY,
    deal_id     TEXT NOT NULL,
    role        TEXT NOT NULL,
    contact_id  TEXT NOT NULL,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(deal_id, role, contact_id)
);
CREATE INDEX idx_deal_contacts_deal_role
    ON deal_contacts(deal_id, role);
CREATE INDEX idx_deal_contacts_contact
    ON deal_contacts(contact_id);
CREATE TABLE deal_attachments (
    id                  TEXT PRIMARY KEY,
    deal_id             TEXT NOT NULL,
    kind                TEXT NOT NULL,
    file_path           TEXT NOT NULL,
    summary             TEXT,
    source_run_id       TEXT,
    source_snapshot_id  TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_deal_attachments_deal_kind
    ON deal_attachments(deal_id, kind, created_at);
CREATE INDEX idx_deal_attachments_source_run
    ON deal_attachments(source_run_id) WHERE source_run_id IS NOT NULL;
CREATE TABLE deal_events (
    id              TEXT PRIMARY KEY,
    deal_id         TEXT NOT NULL,
    kind            TEXT NOT NULL
                        CHECK (kind IN (
                            'created','stage_transition','toggle_change',
                            'run_result','attachment_added','contact_linked'
                        )),
    actor           TEXT NOT NULL,
    from_stage      INTEGER CHECK (from_stage IS NULL OR from_stage BETWEEN 0 AND 9),
    to_stage        INTEGER CHECK (to_stage IS NULL OR to_stage BETWEEN 0 AND 9),
    field_name      TEXT,
    old_value_json  TEXT,
    new_value_json  TEXT,
    payload_json    TEXT,
    created_at      TEXT NOT NULL,
    CHECK (kind != 'stage_transition' OR to_stage IS NOT NULL),
    CHECK (kind != 'toggle_change' OR field_name IS NOT NULL)
);
CREATE INDEX idx_deal_events_deal_created
    ON deal_events(deal_id, created_at);
CREATE INDEX idx_deal_events_kind_created
    ON deal_events(kind, created_at);
CREATE INDEX idx_deal_events_field_created
    ON deal_events(field_name, created_at)
    WHERE field_name IS NOT NULL;
CREATE TABLE admin_action_runs (
    id              TEXT PRIMARY KEY,
    registry_id     TEXT NOT NULL,
    deal_id         TEXT NOT NULL,
    deal_event_id   TEXT,
    cron_job_id     TEXT,
    harness_run_id  TEXT,
    status          TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN (
                            'queued','running','succeeded','completed',
                            'failed','skipped','cancelled',
                            'waiting_human','waiting_external'
                        )),
    output_path     TEXT,
    error_message   TEXT,
    payload_json    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    completed_at    TEXT,
    callback_token_hash TEXT,
    started_at TEXT,
    result_idempotency_key TEXT,
    result_json TEXT,
    human_prompt_json TEXT
);
CREATE INDEX idx_admin_action_runs_deal_created
    ON admin_action_runs(deal_id, created_at);
CREATE INDEX idx_admin_action_runs_status_created
    ON admin_action_runs(status, created_at);
CREATE INDEX idx_admin_action_runs_registry_created
    ON admin_action_runs(registry_id, created_at);
CREATE INDEX idx_admin_action_runs_harness
    ON admin_action_runs(harness_run_id) WHERE harness_run_id IS NOT NULL;
CREATE UNIQUE INDEX idx_deals_source_key
    ON deals(source_key)
    WHERE source_key IS NOT NULL;
CREATE INDEX idx_deals_source_row
    ON deals(source_label, source_row_id)
    WHERE source_row_id IS NOT NULL;
CREATE INDEX idx_admin_action_runs_started
    ON admin_action_runs(started_at)
    WHERE started_at IS NOT NULL;
CREATE UNIQUE INDEX idx_admin_action_runs_result_idempotency
    ON admin_action_runs(id, result_idempotency_key)
    WHERE result_idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX idx_deal_attachments_run_file
    ON deal_attachments(deal_id, source_run_id, kind, file_path)
    WHERE source_run_id IS NOT NULL;
CREATE TABLE admin_date_trigger_firings (
    id          TEXT PRIMARY KEY,
    deal_id     TEXT NOT NULL,
    registry_id TEXT NOT NULL,
    run_id      TEXT,
    field_key   TEXT NOT NULL,
    offset_days INTEGER NOT NULL DEFAULT 0,
    target_date TEXT NOT NULL,
    fired_at    TEXT NOT NULL,
    actor       TEXT NOT NULL,
    UNIQUE(deal_id, registry_id, field_key, offset_days, target_date)
);
CREATE INDEX idx_admin_date_trigger_firings_deal
    ON admin_date_trigger_firings(deal_id, fired_at);
CREATE INDEX idx_conditional_docs_phase
    ON conditional_docs(province, side, stage, field_key, field_value);
CREATE TABLE province_reference_pages (
    id            TEXT PRIMARY KEY,
    province      TEXT NOT NULL,
    slug          TEXT NOT NULL,
    page_type     TEXT NOT NULL,
    title         TEXT NOT NULL,
    source_url    TEXT,
    source_path   TEXT NOT NULL,
    content_md    TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    imported_at   TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE(province, slug)
);
CREATE INDEX idx_province_reference_pages_lookup
    ON province_reference_pages(province, page_type, slug);
CREATE TABLE province_checklists (
    id            TEXT PRIMARY KEY,
    province      TEXT NOT NULL,
    slug          TEXT NOT NULL,
    title         TEXT NOT NULL,
    source_url    TEXT,
    source_path   TEXT NOT NULL,
    content_md    TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    imported_at   TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE(province, slug)
);
CREATE INDEX idx_province_checklists_lookup
    ON province_checklists(province, slug);
CREATE TABLE province_forms (
    id                     TEXT PRIMARY KEY,
    province               TEXT NOT NULL,
    code                   TEXT NOT NULL,
    name                   TEXT NOT NULL,
    category               TEXT,
    description            TEXT,
    page_count             INTEGER,
    annotation_count       INTEGER,
    image_urls_json        TEXT,
    local_image_paths_json TEXT,
    source_path            TEXT,
    imported_at            TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    UNIQUE(province, code)
);
CREATE INDEX idx_province_forms_lookup
    ON province_forms(province, category, code);
CREATE TABLE agent_handoffs (
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
    UNIQUE(from_agent_id, to_agent_id, idempotency_key)
);
CREATE INDEX idx_agent_handoffs_status_created
    ON agent_handoffs(status, created_at);
CREATE INDEX idx_agent_handoffs_to_status
    ON agent_handoffs(to_agent_id, status, created_at);
CREATE INDEX idx_agent_handoffs_from_status
    ON agent_handoffs(from_agent_id, status, created_at);
CREATE INDEX idx_agent_handoffs_deal
    ON agent_handoffs(deal_id, created_at)
    WHERE deal_id IS NOT NULL;
CREATE INDEX idx_agent_handoffs_contact
    ON agent_handoffs(contact_id, created_at)
    WHERE contact_id IS NOT NULL;
CREATE INDEX idx_agent_handoffs_profile
    ON agent_handoffs(profile_id, created_at)
    WHERE profile_id IS NOT NULL;
CREATE INDEX idx_agent_handoffs_source_run
    ON agent_handoffs(source_run_id)
    WHERE source_run_id IS NOT NULL;
CREATE TABLE agent_handoff_messages (
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
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_agent_handoff_messages_handoff_created
    ON agent_handoff_messages(handoff_id, created_at);
CREATE INDEX idx_agent_handoff_messages_kind_created
    ON agent_handoff_messages(kind, created_at);
CREATE TABLE admin_setup_profile (
    id                         TEXT PRIMARY KEY,
    realtor_legal_name         TEXT,
    license_name               TEXT,
    brokerage_name             TEXT,
    team_name                  TEXT,
    country                    TEXT NOT NULL DEFAULT 'CA',
    province                   TEXT NOT NULL DEFAULT '',
    market                     TEXT,
    board_memberships_json     TEXT,
    email_provider             TEXT,
    calendar_provider          TEXT,
    drive_provider             TEXT,
    crm_provider               TEXT,
    mls_provider               TEXT,
    forms_provider             TEXT,
    signing_provider           TEXT,
    compliance_provider        TEXT,
    showing_provider           TEXT,
    fintrac_provider           TEXT,
    approval_channel           TEXT,
    managing_broker_email      TEXT,
    default_folder_pattern     TEXT,
    commission_notes           TEXT,
    services_schedule          TEXT,
    regional_memory_json       TEXT,
    approval_policy_json       TEXT,
    completed_at               TEXT,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL
);
CREATE TABLE admin_setup_items (
    key          TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    label        TEXT NOT NULL,
    description  TEXT,
    required     INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0,1)),
    status       TEXT NOT NULL DEFAULT 'missing'
                     CHECK (status IN ('missing','configured','connected','manual','skipped')),
    provider     TEXT,
    value_json   TEXT,
    notes        TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL
);
CREATE INDEX idx_admin_setup_items_required_status
    ON admin_setup_items(required, status, sort_order);
CREATE UNIQUE INDEX idx_admin_action_runs_registry_event_once
    ON admin_action_runs(registry_id, deal_event_id)
    WHERE deal_event_id IS NOT NULL;
CREATE INDEX idx_admin_action_runs_running_started
    ON admin_action_runs(status, started_at)
    WHERE status = 'running';
CREATE TABLE pack_onboarding_profiles (
    pack_id        TEXT PRIMARY KEY,
    label          TEXT NOT NULL,
    entitlement    TEXT NOT NULL,
    description    TEXT,
    status         TEXT NOT NULL DEFAULT 'missing'
                     CHECK (status IN ('missing','configured','connected','manual','skipped')),
    completed_at   TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE TABLE pack_onboarding_items (
    pack_id        TEXT NOT NULL,
    key            TEXT NOT NULL,
    category       TEXT NOT NULL,
    label          TEXT NOT NULL,
    description    TEXT,
    required       INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0,1)),
    status         TEXT NOT NULL DEFAULT 'missing'
                     CHECK (status IN ('missing','configured','connected','manual','skipped')),
    provider       TEXT,
    env_keys_json  TEXT,
    value_json     TEXT,
    notes          TEXT,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (pack_id, key)
);
CREATE INDEX idx_pack_onboarding_items_pack_ready
    ON pack_onboarding_items(pack_id, required, status, sort_order);
CREATE INDEX idx_contacts_heat_label
    ON contacts(heat_label, heat_score DESC, last_activity_at DESC)
    WHERE heat_label IN ('hot','warm');
CREATE INDEX idx_contacts_needs_follow_up
    ON contacts(next_follow_up_at)
    WHERE needs_follow_up = 1;
CREATE INDEX idx_contacts_buyer_search_active
    ON contacts(buyer_search_active, last_activity_at DESC)
    WHERE buyer_search_active = 1;
CREATE INDEX idx_contacts_listing_active
    ON contacts(listing_active, last_activity_at DESC)
    WHERE listing_active = 1;
CREATE INDEX idx_contacts_closed_by_type
    ON contacts(type, last_activity_at DESC)
    WHERE stage = 'closed';
CREATE INDEX idx_contacts_pipeline_status
    ON contacts(pipeline_status, last_activity_at DESC)
    WHERE pipeline_status IS NOT NULL;
CREATE TABLE lead_inquiries (
    contact_id           TEXT PRIMARY KEY,
    price_min            INTEGER,
    price_max            INTEGER,
    property_types_json  TEXT,
    bedrooms_min         INTEGER,
    bedrooms_max         INTEGER,
    bathrooms_min        TEXT,
    bathrooms_max        TEXT,
    locations_json       TEXT,
    modify_by_agent      INTEGER NOT NULL DEFAULT 0
                            CHECK (modify_by_agent IN (0,1)),
    is_default           INTEGER NOT NULL DEFAULT 0
                            CHECK (is_default IN (0,1)),
    source_created_at    TEXT,
    source_updated_at    TEXT,
    synced_at            TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX idx_lead_inquiries_synced_at
    ON lead_inquiries(synced_at);
CREATE TABLE lead_properties (
    id                   TEXT PRIMARY KEY,
    contact_id           TEXT NOT NULL,
    source_record_id     TEXT,
    listing_id           TEXT,
    auto_listing_id      TEXT,
    street_address       TEXT,
    city                 TEXT,
    state                TEXT,
    zip_code             TEXT,
    county               TEXT,
    property_type        TEXT,
    bedrooms             INTEGER,
    bathrooms            DOUBLE PRECISION,
    square_feet          INTEGER,
    lot_size_acres       DOUBLE PRECISION,
    parking_space        INTEGER,
    floors               INTEGER,
    price                INTEGER,
    price_min            INTEGER,
    price_max            INTEGER,
    label                TEXT,
    label_type           TEXT,
    label_list_json      TEXT,
    note                 TEXT,
    listing_status       TEXT,
    picture_url          TEXT,
    site_listing_url     TEXT,
    is_mailing_address   INTEGER NOT NULL DEFAULT 0
                            CHECK (is_mailing_address IN (0,1)),
    source_created_at    TEXT,
    source_updated_at    TEXT,
    synced_at            TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX idx_lead_properties_contact
    ON lead_properties(contact_id, label, source_updated_at DESC);
CREATE INDEX idx_lead_properties_listing
    ON lead_properties(listing_id)
    WHERE listing_id IS NOT NULL;
CREATE UNIQUE INDEX uniq_lead_properties_source
    ON lead_properties(contact_id, source_record_id)
    WHERE source_record_id IS NOT NULL;
CREATE INDEX idx_contacts_dnc_text
    ON contacts(id) WHERE cannot_text = 1;
CREATE INDEX idx_contacts_dnc_call
    ON contacts(id) WHERE cannot_call = 1;
CREATE INDEX idx_contacts_dnc_email
    ON contacts(id) WHERE cannot_email = 1;
CREATE INDEX idx_contacts_unsubscribed
    ON contacts(id) WHERE unsubscribed = 1;
CREATE INDEX idx_contacts_pond
    ON contacts(pond_id) WHERE pond_id IS NOT NULL;
CREATE TABLE notes (
    id                  TEXT PRIMARY KEY,
    contact_id          TEXT NOT NULL,
    body                TEXT NOT NULL,
    author_kind         TEXT NOT NULL
                            CHECK (author_kind IN ('ai','operator','system')),
    author_name         TEXT NOT NULL,
    source_event_id     TEXT,
    pinned              INTEGER NOT NULL DEFAULT 0
                            CHECK (pinned IN (0,1)),
    deleted             INTEGER NOT NULL DEFAULT 0
                            CHECK (deleted IN (0,1)),
    crm_remote_id       TEXT,
    crm_sync_state    TEXT
                            CHECK (crm_sync_state IS NULL OR
                                   crm_sync_state IN ('pending','synced','failed','deleted')),
    crm_synced_at     TEXT,
    crm_last_error    TEXT,
    crm_attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    crm_provider TEXT
    CHECK (crm_provider IS NULL OR crm_provider IN (
        'lofty', 'followupboss', 'sierra', 'brivity', 'boldtrail'
    ))
);
CREATE INDEX idx_notes_contact_created
    ON notes(contact_id, created_at DESC)
    WHERE deleted = 0;
CREATE INDEX idx_notes_contact_author_recent
    ON notes(contact_id, author_kind, author_name, created_at DESC);
CREATE INDEX idx_notes_pending_sync
    ON notes(created_at)
    WHERE crm_sync_state = 'pending';
CREATE UNIQUE INDEX uniq_notes_crm_remote
    ON notes(crm_provider, crm_remote_id)
    WHERE crm_remote_id IS NOT NULL;
CREATE UNIQUE INDEX uniq_deals_crm_transaction
    ON deals(crm_provider, crm_transaction_id)
    WHERE crm_transaction_id IS NOT NULL;
CREATE INDEX idx_deals_crm_lead
    ON deals(crm_provider, crm_lead_id)
    WHERE crm_lead_id IS NOT NULL;
CREATE INDEX idx_deals_crm_synced_at
    ON deals(crm_synced_at)
    WHERE crm_transaction_id IS NOT NULL;
CREATE TABLE identities (
    id          TEXT PRIMARY KEY,
    contact_id  TEXT NOT NULL,
    kind        TEXT NOT NULL
                  CHECK (kind IN (
                    'email','phone',
                    'instagram_id','instagram_handle',
                    'facebook_id','telegram_id',
                    'lofty_id','fub_id','sierra_id','brivity_id','boldtrail_id',
                    'apple_handle','apple_addressbook_id','apple_chat_id',
                    'wa_id'
                  )),
    value       TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    verified    INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0,1)),
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX uniq_identities_kind_value
    ON identities(kind, value);
CREATE INDEX idx_identities_contact
    ON identities(contact_id);
CREATE TABLE leads_setup_items (
    key          TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    label        TEXT NOT NULL,
    description  TEXT,
    required     INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0,1)),
    status       TEXT NOT NULL DEFAULT 'missing'
                     CHECK (status IN ('missing','configured','connected','manual','skipped')),
    provider     TEXT,
    value_json   TEXT,
    notes        TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL
);
CREATE INDEX idx_leads_setup_items_required_status
    ON leads_setup_items(required, status, sort_order);
CREATE TABLE leads_setup_state (
    id            TEXT PRIMARY KEY,
    completed_at  TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE agent_setup_items (
    key          TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    label        TEXT NOT NULL,
    description  TEXT,
    required     INTEGER NOT NULL DEFAULT 0 CHECK (required IN (0,1)),
    status       TEXT NOT NULL DEFAULT 'missing'
                     CHECK (status IN ('missing','configured','connected','manual','skipped')),
    provider     TEXT,
    value_json   TEXT,
    notes        TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL
);
CREATE INDEX idx_agent_setup_items_required_status
    ON agent_setup_items(required, status, sort_order);
CREATE TABLE agent_setup_state (
    id            TEXT PRIMARY KEY,
    completed_at  TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);


-- Foreign keys (deferred to end so referenced tables exist)
ALTER TABLE contacts ADD CONSTRAINT fk_contacts_1 FOREIGN KEY (ingest_run_id) REFERENCES ingest_runs(id);
ALTER TABLE conversations ADD CONSTRAINT fk_conversations_1 FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE;
ALTER TABLE events ADD CONSTRAINT fk_events_1 FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE;
ALTER TABLE events ADD CONSTRAINT fk_events_2 FOREIGN KEY (conversation_id) REFERENCES conversations(id);
ALTER TABLE events ADD CONSTRAINT fk_events_3 FOREIGN KEY (template_id) REFERENCES templates(id);
ALTER TABLE events ADD CONSTRAINT fk_events_4 FOREIGN KEY (ingest_run_id) REFERENCES ingest_runs(id);
ALTER TABLE events_summary ADD CONSTRAINT fk_events_summary_1 FOREIGN KEY (template_id) REFERENCES templates(id);
ALTER TABLE events_summary ADD CONSTRAINT fk_events_summary_2 FOREIGN KEY (contact_id) REFERENCES contacts(id);
ALTER TABLE lead_signals ADD CONSTRAINT fk_lead_signals_1 FOREIGN KEY (graduated_to_contact_id) REFERENCES contacts(id);
ALTER TABLE pcs_buyers ADD CONSTRAINT fk_pcs_buyers_1 FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE;
ALTER TABLE pcs_buyers ADD CONSTRAINT fk_pcs_buyers_2 FOREIGN KEY (lead_signal_id) REFERENCES lead_signals(id);
ALTER TABLE templates ADD CONSTRAINT fk_templates_1 FOREIGN KEY (proposed_by_event_id) REFERENCES events(id);
ALTER TABLE templates ADD CONSTRAINT fk_templates_2 FOREIGN KEY (parent_template_id) REFERENCES templates(id);
ALTER TABLE draft_attempts ADD CONSTRAINT fk_draft_attempts_1 FOREIGN KEY (template_id) REFERENCES templates(id);
ALTER TABLE draft_attempts ADD CONSTRAINT fk_draft_attempts_2 FOREIGN KEY (conversation_id) REFERENCES conversations(id);
ALTER TABLE send_queue ADD CONSTRAINT fk_send_queue_1 FOREIGN KEY (conversation_id) REFERENCES conversations(id);
ALTER TABLE deals ADD CONSTRAINT fk_deals_1 FOREIGN KEY (primary_contact_id) REFERENCES contacts(id) ON DELETE SET NULL;
ALTER TABLE deal_contacts ADD CONSTRAINT fk_deal_contacts_1 FOREIGN KEY (deal_id) REFERENCES deals(id)    ON DELETE CASCADE;
ALTER TABLE deal_contacts ADD CONSTRAINT fk_deal_contacts_2 FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE;
ALTER TABLE deal_attachments ADD CONSTRAINT fk_deal_attachments_1 FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE CASCADE;
ALTER TABLE deal_events ADD CONSTRAINT fk_deal_events_1 FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE CASCADE;
ALTER TABLE admin_action_runs ADD CONSTRAINT fk_admin_action_runs_1 FOREIGN KEY (registry_id) REFERENCES admin_action_registry(id) ON DELETE CASCADE;
ALTER TABLE admin_action_runs ADD CONSTRAINT fk_admin_action_runs_2 FOREIGN KEY (deal_id) REFERENCES deals(id)                  ON DELETE CASCADE;
ALTER TABLE admin_action_runs ADD CONSTRAINT fk_admin_action_runs_3 FOREIGN KEY (deal_event_id) REFERENCES deal_events(id)            ON DELETE SET NULL;
ALTER TABLE admin_date_trigger_firings ADD CONSTRAINT fk_admin_date_trigger_firings_1 FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE CASCADE;
ALTER TABLE admin_date_trigger_firings ADD CONSTRAINT fk_admin_date_trigger_firings_2 FOREIGN KEY (registry_id) REFERENCES admin_action_registry(id) ON DELETE CASCADE;
ALTER TABLE admin_date_trigger_firings ADD CONSTRAINT fk_admin_date_trigger_firings_3 FOREIGN KEY (run_id) REFERENCES admin_action_runs(id) ON DELETE SET NULL;
ALTER TABLE agent_handoffs ADD CONSTRAINT fk_agent_handoffs_1 FOREIGN KEY (deal_id) REFERENCES deals(id) ON DELETE SET NULL;
ALTER TABLE agent_handoffs ADD CONSTRAINT fk_agent_handoffs_2 FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL;
ALTER TABLE agent_handoffs ADD CONSTRAINT fk_agent_handoffs_3 FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL;
ALTER TABLE agent_handoffs ADD CONSTRAINT fk_agent_handoffs_4 FOREIGN KEY (parent_handoff_id) REFERENCES agent_handoffs(id) ON DELETE SET NULL;
ALTER TABLE agent_handoff_messages ADD CONSTRAINT fk_agent_handoff_messages_1 FOREIGN KEY (handoff_id) REFERENCES agent_handoffs(id) ON DELETE CASCADE;
ALTER TABLE pack_onboarding_items ADD CONSTRAINT fk_pack_onboarding_items_1 FOREIGN KEY (pack_id) REFERENCES pack_onboarding_profiles(pack_id) ON DELETE CASCADE;
ALTER TABLE lead_inquiries ADD CONSTRAINT fk_lead_inquiries_1 FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE;
ALTER TABLE lead_properties ADD CONSTRAINT fk_lead_properties_1 FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE;
ALTER TABLE notes ADD CONSTRAINT fk_notes_1 FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE;
ALTER TABLE notes ADD CONSTRAINT fk_notes_2 FOREIGN KEY (source_event_id) REFERENCES events(id) ON DELETE SET NULL;
ALTER TABLE identities ADD CONSTRAINT fk_identities_1 FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE;
