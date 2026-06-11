-- 0022_surface_task_dependencies.sql
-- CortextOS-style task dependency DAG on Elevate's existing surface_tasks.
-- `blocked_by` is the authoritative dependency edge; `blocks` is maintained
-- as the inverse for dashboard visibility and import compatibility.

ALTER TABLE surface_tasks
    ADD COLUMN IF NOT EXISTS blocked_by TEXT;

ALTER TABLE surface_tasks
    ADD COLUMN IF NOT EXISTS blocks TEXT;

UPDATE surface_tasks
SET blocked_by = '[]'
WHERE blocked_by IS NULL;

UPDATE surface_tasks
SET blocks = '[]'
WHERE blocks IS NULL;
