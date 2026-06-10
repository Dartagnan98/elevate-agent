-- 0028_deal_agent_activity.sql
-- Record work the agent does AROUND a deal even when it never formally moves a
-- stage or ticks a checklist (drafting a counter, reading a contract, prepping
-- docs). Those turns currently leave no trace on the deal, so the board's
-- freshness/ordering (deals.updated_at) goes stale while real work happens.
--
-- Add an ``agent_activity`` event kind: a timeline marker carrying a short
-- summary + the tools used (in payload_json). It never asserts a stage/field
-- change, so the existing stage/field guard constraints don't apply to it.
ALTER TABLE deal_events
    DROP CONSTRAINT IF EXISTS deal_events_kind_check;
ALTER TABLE deal_events
    ADD CONSTRAINT deal_events_kind_check CHECK (kind = ANY (ARRAY[
        'created',
        'stage_transition',
        'toggle_change',
        'run_result',
        'attachment_added',
        'contact_linked',
        'agent_activity'
    ]));

-- Same marker for contacts/leads: the agent worked a contact (drafted a reply,
-- enriched, researched) without a formal inbound/outbound/lifecycle event. A
-- lightweight ``agent_activity`` event bumps last_activity_at (via the shared
-- insert path) without polluting the human-owned owner_notes field.
ALTER TABLE events
    DROP CONSTRAINT IF EXISTS events_kind_check;
ALTER TABLE events
    ADD CONSTRAINT events_kind_check CHECK (kind = ANY (ARRAY[
        'inbound','outbound','draft','approval','send','bounce',
        'reply_attributed','classified','parked','unparked',
        'pcs_activity','lifecycle_change','note',
        'merge','merge_conflict',
        'template_candidate','template_approved','template_rejected',
        'attribution_ambiguous',
        'ingest_run_started','ingest_run_completed',
        'agent_activity'
    ]));
