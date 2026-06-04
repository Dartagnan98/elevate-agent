-- 0020_surface_tasks_approvals.sql
-- Surface Tasks + Approvals (faithful port of CTRL Flow /ai tasks + approvals).
-- Tasks: the realtor (or theta-wave) dispatches work to a surface; the surface's
-- next heartbeat WORK run drains pending tasks (drafts-only). assignee = a surface
-- name or 'human'. Approvals: created internally by a heartbeat/experiment run when
-- it produces something needing sign-off; resolved on the dashboard ONLY (never via
-- Telegram — see feedback_no_telegram_approvals). TEXT/INTEGER only so the SQLite
-- and Postgres data paths stay identical.

CREATE TABLE IF NOT EXISTS surface_tasks (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    priority        TEXT NOT NULL DEFAULT 'normal',
    assignee        TEXT,
    project         TEXT,
    needs_approval  INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT,
    updated_at      TEXT,
    completed_at    TEXT,
    notes           TEXT,
    outputs         TEXT
);
CREATE INDEX IF NOT EXISTS idx_surface_tasks_status ON surface_tasks(status);
CREATE INDEX IF NOT EXISTS idx_surface_tasks_assignee ON surface_tasks(assignee);

CREATE TABLE IF NOT EXISTS surface_approvals (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'other',
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    surface         TEXT,
    created_at      TEXT,
    resolved_at     TEXT,
    resolved_by     TEXT,
    resolution_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_surface_approvals_status ON surface_approvals(status);
