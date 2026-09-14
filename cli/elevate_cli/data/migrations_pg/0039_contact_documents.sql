-- 0039_contact_documents.sql
-- Client-level (contact-scoped) compliance documents that are reusable across
-- a client's deals: DORTS, PNC, FINTRAC ID, LOTR, Buyer Agency Agreement.
-- Sibling of deal_attachments (which is deal-scoped). Deal collapse promotes
-- client-class attachments here so they survive and can be reused / re-filed on
-- the client's next deal. See knowledge/deals/client-doc-reuse-architecture.md.

CREATE TABLE IF NOT EXISTS contact_documents (
    id                   TEXT PRIMARY KEY,
    contact_id           TEXT NOT NULL,
    doc_type             TEXT NOT NULL,          -- canonical client-class type: dorts|pnc|fintrac_id|lotr|baec
    file_path            TEXT NOT NULL,          -- canonical local copy under client-docs/<contact_id>/
    drive_file_id        TEXT,                   -- optional per-client Drive mirror
    sha256               TEXT,                   -- dedupe + contamination audit
    signed_status        TEXT NOT NULL DEFAULT 'unknown',  -- only 'fully_signed' is reuse-eligible
    signed_at            TEXT,
    valid_from           TEXT,
    valid_until          TEXT,                   -- NULL = durable (dorts/pnc); date = expiry (baec/fintrac window)
    scope_json           TEXT,                   -- baec area/property scope; NULL otherwise
    fintrac_method       TEXT,                   -- fintrac_id only: photo_id|credit_file|dual_process
    fintrac_verified_at  TEXT,                   -- fintrac_id only
    source_deal_id       TEXT,                   -- provenance: deal it was promoted from
    source_attachment_id TEXT,                   -- provenance: deal_attachments.id it came from
    status               TEXT NOT NULL DEFAULT 'valid',  -- valid|expired|superseded|revoked
    superseded_by        TEXT,                   -- points at replacement row; never DELETE
    verified_by          TEXT,                   -- who asserted signatures/dates
    summary              TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_contact_documents_contact
    ON contact_documents(contact_id, doc_type, status);

-- One current (valid) doc per type per person. Supersede (not delete) to replace.
CREATE UNIQUE INDEX IF NOT EXISTS ux_contact_documents_current
    ON contact_documents(contact_id, doc_type) WHERE status = 'valid';
