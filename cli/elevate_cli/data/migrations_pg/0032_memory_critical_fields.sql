-- 0032_memory_critical_fields.sql
--
-- Critical / pinned recall-tier fields on memory_facts.
--
-- Backs the "Must-Follow Rules" recall lane: a reserved tier for compliance
-- rules, corrections, and explicit conventions that must survive the trust
-- ratchet and the token-overlap verifier (the recall-starvation fix — see
-- knowledge/clients/skyleigh/elevate-memory-fix-PLAN.md).
--
--   critical        — auto-set by the durability classifier for clear-cut
--                     correction / convention / compliance facts.
--   pinned          — "must-always" facts; reserved for a deliberate pin
--                     action. NOT implied by generic explicit/manual saves.
--   task_tags       — comma-joined task tokens inferred at write time
--                     (task:accepted-offer, task:cma, task:social, ...).
--   critical_reason — which signal fired (correction|convention|compliance).
--
-- These columns are plugin-owned metadata read/written DIRECTLY against
-- memory_facts (mirroring durability/reinforced_count). The compat `facts`
-- view (0008) has a fixed column list and is intentionally NOT modified — it
-- does not expose these columns and is not expected to.
--
-- The plugin's idempotent _init_db ALTER set adds the same columns for
-- fresh/SQLite/test parity; this numbered migration keeps versioned PG parity.

ALTER TABLE memory_facts
    ADD COLUMN IF NOT EXISTS critical BOOLEAN DEFAULT false;

ALTER TABLE memory_facts
    ADD COLUMN IF NOT EXISTS pinned BOOLEAN DEFAULT false;

ALTER TABLE memory_facts
    ADD COLUMN IF NOT EXISTS task_tags TEXT DEFAULT '';

ALTER TABLE memory_facts
    ADD COLUMN IF NOT EXISTS critical_reason TEXT DEFAULT '';

-- Partial index for the reserved-lane query shape:
--   WHERE (critical OR pinned) AND COALESCE(status,'active')='active'
-- The index predicate covers (critical OR pinned) (CONSTRAINT 3 — not only
-- critical), columned on status so the active filter stays index-eligible.
CREATE INDEX IF NOT EXISTS idx_memory_facts_critical
    ON memory_facts (status)
    WHERE (critical OR pinned);
