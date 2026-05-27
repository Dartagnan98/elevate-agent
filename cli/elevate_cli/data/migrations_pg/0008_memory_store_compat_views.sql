-- 0008_memory_store_compat_views.sql — sqlite-name compat for the
-- holographic-store plugin port.
--
-- 0007 named the new PG tables ``memory_facts``, ``memory_entities``,
-- ``memory_fact_entities``, ``memory_fact_links`` for namespace
-- hygiene inside ``elevate_operational``. The plugin's SQL strings
-- (3700+ lines in plugins/memory/holographic/store.py) all reference
-- the legacy unprefixed names (``facts``, ``entities``, etc.).
--
-- These four views give the plugin a drop-in target so the port is a
-- connection swap (sqlite3 → psycopg) plus FTS-MATCH rewrites — not a
-- 50-string table rename sweep. PG auto-rewrites INSERT/UPDATE/DELETE
-- against simple single-base-table views, so writes go straight to
-- ``memory_*`` and identity sequences increment correctly.
--
-- Views are dropped + recreated rather than CREATE OR REPLACE because
-- 0008 is the first time these names exist in PG — append-only history.

CREATE VIEW facts AS SELECT
    fact_id, content, category, tags, trust_score, retrieval_count,
    helpful_count, created_at, updated_at, hrr_vector, source_type,
    source_uri, source_excerpt, observed_at, memory_space, status,
    superseded_by, search_tsv
FROM memory_facts;

CREATE VIEW entities AS SELECT
    entity_id, name, entity_type, aliases, created_at
FROM memory_entities;

CREATE VIEW fact_entities AS SELECT
    fact_id, entity_id
FROM memory_fact_entities;

CREATE VIEW fact_links AS SELECT
    source_fact_id, target_fact_id, link_type, weight, created_at, updated_at
FROM memory_fact_links;
