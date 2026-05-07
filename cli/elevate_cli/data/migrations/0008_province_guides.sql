-- 0008_province_guides.sql
-- Store eXp province/admin guide material in SQLite so deal files can use it
-- without reaching back to scraper output or Google Sheets.

ALTER TABLE conditional_docs ADD COLUMN side TEXT;
ALTER TABLE conditional_docs ADD COLUMN stage INTEGER;

CREATE INDEX IF NOT EXISTS idx_conditional_docs_phase
    ON conditional_docs(province, side, stage, field_key, field_value);

CREATE TABLE IF NOT EXISTS province_reference_pages (
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
CREATE INDEX IF NOT EXISTS idx_province_reference_pages_lookup
    ON province_reference_pages(province, page_type, slug);

CREATE TABLE IF NOT EXISTS province_checklists (
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
CREATE INDEX IF NOT EXISTS idx_province_checklists_lookup
    ON province_checklists(province, slug);

CREATE TABLE IF NOT EXISTS province_forms (
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
CREATE INDEX IF NOT EXISTS idx_province_forms_lookup
    ON province_forms(province, category, code);
