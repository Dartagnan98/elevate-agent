-- 0035_crm_goals.sql
-- Single-row goals store backing the Reporting page "Set goals" card.
--
-- The Reporting view (web/src/pages/real-estate-hub/reporting) lets the agent
-- set monthly lead / appointment / closing targets plus a yearly GCI target,
-- then shows real pipeline progress against them. No such table existed, so we
-- add a tiny single-row store keyed on a fixed 'default' id. TEXT/INTEGER only
-- so the schema is identical on SQLite and Postgres (no numeric/timestamp
-- type drift). All values are nullable so an unset goal simply renders as
-- "no goal set" rather than a fake zero.

CREATE TABLE IF NOT EXISTS crm_goals (
    id            TEXT PRIMARY KEY DEFAULT 'default',
    leads_goal    INTEGER,
    appts_goal    INTEGER,
    closings_goal INTEGER,
    gci_goal      INTEGER,
    updated_at    TEXT
);
