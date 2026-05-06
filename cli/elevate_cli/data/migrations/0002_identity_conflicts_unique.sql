-- 0002_identity_conflicts_unique.sql
--
-- Re-running `elevate migrate-data` previously inserted a fresh
-- `identity_conflicts` row each time the same (kind,value) collided. The
-- table only had non-unique indexes on (resolved_at) and (kind,value), so
-- no upsert was possible. Codex audit P1 (2026-05-05).
--
-- Add a partial unique index across open conflicts on
-- (kind, value, reason). On re-sync the python layer can then do an
-- INSERT OR IGNORE / pre-check, and the index gives us race-safety.

CREATE UNIQUE INDEX IF NOT EXISTS idx_identity_conflicts_open_uniq
    ON identity_conflicts(kind, value, reason)
    WHERE resolved_at IS NULL;
