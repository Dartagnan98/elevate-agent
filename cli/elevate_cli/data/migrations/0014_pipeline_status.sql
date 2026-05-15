-- 0014_pipeline_status.sql
-- Operator + AI -set pipeline status for /leads. Distinct from `stage`
-- (which tracks the actual sales workflow): `pipeline_status` annotates
-- engagement quality and operator intent so the dashboard can filter
-- "don't reach out to" people and the autopilot can skip dead/ghosting
-- leads when picking who to draft for.
--
-- Allowed values:
--   new_lead       — first inbound in the last 24h, no prior history.
--                    Auto-set by review_contact; cleared once they get a reply.
--   follow_up      — operator says "circle back later"
--   ghosting       — 3+ outbounds, no inbound in 30d
--   dead           — 5+ outbounds, no inbound in 60d
--   closed_seller  — promoted to /admin listing kanban (set via close_to_admin)
--   closed_buyer   — promoted to /admin buyer kanban (future, buyer side)
--
-- AI auto-sets new_lead/ghosting/dead in review_contact, but ONLY if the
-- operator hasn't already set a value (pipeline_status_set_by != 'operator').
-- Operator marks always win.

ALTER TABLE contacts
    ADD COLUMN pipeline_status TEXT
        CHECK (pipeline_status IS NULL OR pipeline_status IN (
            'new_lead', 'follow_up', 'ghosting', 'dead',
            'closed_seller', 'closed_buyer'
        ));

ALTER TABLE contacts
    ADD COLUMN pipeline_status_set_at TEXT;

ALTER TABLE contacts
    ADD COLUMN pipeline_status_set_by TEXT
        CHECK (pipeline_status_set_by IS NULL OR pipeline_status_set_by IN (
            'operator', 'ai'
        ));

-- Partial index: only flagged contacts. The dashboard filters by status
-- to hide dead/closed people from autopilot lists; this keeps that lookup
-- in single-digit ms even at 100k contacts.
CREATE INDEX IF NOT EXISTS idx_contacts_pipeline_status
    ON contacts(pipeline_status, last_activity_at DESC)
    WHERE pipeline_status IS NOT NULL;
