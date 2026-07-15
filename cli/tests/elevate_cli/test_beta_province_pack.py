from __future__ import annotations

import json
import shutil
import sqlite3
import stat
from pathlib import Path

import pytest

from elevate_cli.data.beta_province_pack import (
    PACK_FORM_COUNT,
    PACK_MEMORY_SOURCE_URIS,
    BetaProvincePackError,
    activate_exact_beta_bc_pack,
    default_exact_beta_bc_pack_root,
    exact_beta_bc_pack_readiness,
    exact_beta_bc_pack_receipt_path,
    load_exact_beta_bc_pack,
)
from elevate_cli.data.province_guides import (
    import_exp_agent_centre,
    list_province_forms,
    province_agent_memory,
    province_coverage,
    province_guide_summary,
)


_SCHEMA = """
CREATE TABLE province_reference_pages (
 id TEXT PRIMARY KEY, province TEXT NOT NULL, slug TEXT NOT NULL, page_type TEXT NOT NULL,
 title TEXT NOT NULL, source_url TEXT, source_path TEXT NOT NULL, content_md TEXT NOT NULL,
 content_hash TEXT NOT NULL, imported_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(province, slug)
);
CREATE TABLE province_checklists (
 id TEXT PRIMARY KEY, province TEXT NOT NULL, slug TEXT NOT NULL, title TEXT NOT NULL,
 source_url TEXT, source_path TEXT NOT NULL, content_md TEXT NOT NULL, content_hash TEXT NOT NULL,
 imported_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(province, slug)
);
CREATE TABLE province_forms (
 id TEXT PRIMARY KEY, province TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
 category TEXT, description TEXT, page_count INTEGER, annotation_count INTEGER,
 image_urls_json TEXT, local_image_paths_json TEXT, source_path TEXT,
 imported_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(province, code)
);
CREATE TABLE conditional_docs (
 id TEXT PRIMARY KEY, province TEXT NOT NULL, field_key TEXT NOT NULL, field_value TEXT NOT NULL,
 doc_code TEXT NOT NULL, doc_name TEXT NOT NULL, notes TEXT, created_at TEXT NOT NULL,
 side TEXT, stage INTEGER, UNIQUE(province, field_key, field_value, doc_code)
);
CREATE TABLE memory_documents (
 document_id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL, source_uri TEXT UNIQUE NOT NULL,
 title TEXT, metadata_json TEXT
);
CREATE TABLE memory_chunks (
 chunk_id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL, chunk_index INTEGER NOT NULL,
 content TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


class _MemoryStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.search_calls = 0
        self.return_no_search_results = False

    @staticmethod
    def chunk_text(content: str) -> list[str]:
        return [content]

    def add_document_chunks(self, *, source_uri, chunks, title, source_type, metadata):
        self.conn.execute(
            "INSERT INTO memory_documents(source_type, source_uri, title, metadata_json) VALUES (?,?,?,?) "
            "ON CONFLICT(source_uri) DO UPDATE SET source_type=excluded.source_type, title=excluded.title, metadata_json=excluded.metadata_json",
            (source_type, source_uri, title, json.dumps(metadata, sort_keys=True)),
        )
        row = self.conn.execute(
            "SELECT document_id FROM memory_documents WHERE source_uri=?", (source_uri,)
        ).fetchone()
        document_id = int(row["document_id"])
        self.conn.execute("DELETE FROM memory_chunks WHERE document_id=?", (document_id,))
        for index, chunk in enumerate(chunks):
            self.conn.execute(
                "INSERT INTO memory_chunks(document_id, chunk_index, content) VALUES (?,?,?)",
                (document_id, index, chunk),
            )
        self.conn.commit()
        return {"document_id": document_id, "chunks": len(chunks)}

    def document_status(self, *, source_type=None, limit=200):
        rows = self.conn.execute(
            "SELECT d.*, COUNT(c.chunk_id) AS chunks FROM memory_documents d "
            "LEFT JOIN memory_chunks c ON c.document_id=d.document_id "
            "WHERE (? IS NULL OR d.source_type=?) GROUP BY d.document_id ORDER BY d.document_id LIMIT ?",
            (source_type, source_type, limit),
        ).fetchall()
        return {
            "documents": [
                {**dict(row), "metadata": json.loads(row["metadata_json"] or "{}")}
                for row in rows
            ]
        }

    def delete_document(self, *, source_uri):
        row = self.conn.execute(
            "SELECT document_id FROM memory_documents WHERE source_uri=?", (source_uri,)
        ).fetchone()
        if row:
            self.conn.execute("DELETE FROM memory_chunks WHERE document_id=?", (row["document_id"],))
            self.conn.execute("DELETE FROM memory_documents WHERE document_id=?", (row["document_id"],))
            self.conn.commit()

    def document_search(self, query, *, source_type=None, limit=8):
        self.search_calls += 1
        if self.return_no_search_results:
            return []
        terms = query.lower().split()
        rows = self.conn.execute(
            "SELECT d.source_uri, d.source_type, c.content FROM memory_chunks c "
            "JOIN memory_documents d ON d.document_id=c.document_id "
            "WHERE (? IS NULL OR d.source_type=?) ORDER BY d.source_uri LIMIT ?",
            (source_type, source_type, limit),
        ).fetchall()
        return [
            dict(row)
            for row in rows
            if all(term in str(row["content"]).lower() for term in terms)
        ]


@pytest.fixture
def exact_beta(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path / "home"))


def _copy_pack(tmp_path: Path) -> Path:
    target = tmp_path / "pack"
    shutil.copytree(default_exact_beta_bc_pack_root(), target)
    return target


def test_pack_loader_is_deterministic_and_enforces_safe_catalog(exact_beta):
    first = load_exact_beta_bc_pack()
    second = load_exact_beta_bc_pack()

    assert first.sha256 == second.sha256
    assert len(first.forms) == PACK_FORM_COUNT == 34
    assert len({form.code for form in first.forms}) == PACK_FORM_COUNT
    assert all(form.availability == "provider_required" for form in first.forms)
    assert all(form.reference_only for form in first.forms)
    assert all(not form.current_version_verified for form in first.forms)
    assert all(form.licensed_blank_required for form in first.forms)
    assert "http://" not in first.guide_content
    assert "https://" not in first.guide_content


@pytest.mark.parametrize("failure", ["missing", "tampered", "symlink"])
def test_pack_loader_fails_closed_for_missing_tampered_or_symlinked_asset(
    exact_beta, tmp_path: Path, failure: str
):
    root = _copy_pack(tmp_path)
    guide = root / "guide.md"
    if failure == "missing":
        guide.unlink()
    elif failure == "tampered":
        guide.write_text(guide.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")
    else:
        outside = tmp_path / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        guide.unlink()
        guide.symlink_to(outside)

    with pytest.raises(BetaProvincePackError):
        load_exact_beta_bc_pack(root=root)


def test_fresh_activation_imports_provider_required_catalog_and_verifies_document_search(
    exact_beta,
):
    conn = _conn()
    store = _MemoryStore(conn)

    result = activate_exact_beta_bc_pack(conn, store=store)

    assert result["ready"] is True
    assert result["forms"] == PACK_FORM_COUNT
    assert result["documentSearchVerified"] is True
    assert {item["source_uri"] for item in store.document_search(
        "licensed blank provider required", source_type="province_guide", limit=40
    )} == set(PACK_MEMORY_SOURCE_URIS)
    forms = list_province_forms(conn, province="BC")
    assert len(forms) == PACK_FORM_COUNT
    assert all(form["availability"] == "provider_required" for form in forms)
    assert all(form["referenceOnly"] is True for form in forms)
    assert all(form["currentVersionVerified"] is False for form in forms)
    assert all(form["licensedBlankRequired"] is True for form in forms)
    assert {
        form["code"]
        for form in forms
        if form.get("requiresLiveFormsProvider") is True
    } == {"CPS-res", "MLC"}
    coverage = province_coverage(conn)[0]
    assert coverage["referenceOnly"] is True
    assert coverage["availability"] == "provider_required"
    summary = province_guide_summary(conn, "BC")
    assert summary["coverage"]["referenceOnly"] is True
    assert summary["forms"][0]["currentVersionVerified"] is False
    memory = province_agent_memory(conn, "BC")
    assert memory["coverage"]["referencePages"] == 2
    assert memory["coverage"]["checklists"] == 0
    assert memory["coverage"]["forms"] == PACK_FORM_COUNT
    assert memory["coverage"]["hasTransactionGuide"] is True
    assert memory["coverage"]["referenceOnly"] is True
    assert memory["coverage"]["availability"] == "provider_required"
    assert memory["coverage"]["licensedBlankRequired"] is True
    assert all(form["availability"] == "provider_required" for form in memory["forms"])
    receipt = exact_beta_bc_pack_receipt_path()
    assert receipt.is_file()
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    calls_after_activation = store.search_calls
    assert calls_after_activation >= 2
    assert exact_beta_bc_pack_readiness(conn, store=store)["ready"] is True
    assert store.search_calls == calls_after_activation + 1

    store.return_no_search_results = True
    broken_search = exact_beta_bc_pack_readiness(conn, store=store)
    assert broken_search["ready"] is False
    assert broken_search["documentSearchVerified"] is False
    assert "document_search did not return every bundled pack document" in broken_search["reason"]
    store.return_no_search_results = False

    conn.execute("UPDATE province_forms SET name='tampered' WHERE code='MLC'")
    assert exact_beta_bc_pack_readiness(conn, store=store)["ready"] is False
    activate_exact_beta_bc_pack(conn, store=store)
    conn.execute("DELETE FROM conditional_docs WHERE doc_code='strata_docs'")
    assert exact_beta_bc_pack_readiness(conn, store=store)["ready"] is False


def test_exact_beta_default_import_uses_bundled_pack_and_rejects_mutable_root(
    exact_beta, tmp_path: Path
):
    conn = _conn()

    imported = import_exp_agent_centre(conn)

    assert imported["packId"] == "bc-residential-resale-reference-v1"
    assert imported["forms"] == PACK_FORM_COUNT
    assert imported["conditionalDocs"] == 4
    assert conn.execute("SELECT COUNT(*) FROM conditional_docs WHERE province='BC'").fetchone()[0] == 4
    with pytest.raises(ValueError, match="signed app bundle"):
        import_exp_agent_centre(conn, root=tmp_path)


def test_provider_name_completes_setup_while_exact_beta_exposes_forms_capability_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    conn = _conn()
    root = tmp_path / "legacy"
    pages = root / "pages"
    pages.mkdir(parents=True)
    (pages / "alberta.md").write_text("# Alberta\n", encoding="utf-8")

    imported = import_exp_agent_centre(conn, root=root)

    assert imported["provinces"] == ["AB"]
    assert imported["pages"] == 1
    from elevate_cli.data.admin_setup import (
        _item_counts_ready,
        _snapshot,
        forms_provider_capability,
    )

    item = {"key": "forms_provider", "status": "configured", "value": {"provider": "WEBForms"}}
    assert _item_counts_ready(item) is True
    assert forms_provider_capability()["available"] is True
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    assert _item_counts_ready(item) is True
    snapshot = _snapshot(
        {},
        [
            {
                **item,
                "required": True,
                "label": "Forms provider",
                "category": "providers",
            }
        ],
    )
    assert snapshot["complete"] is True
    assert snapshot["missingRequiredKeys"] == []
    capability = forms_provider_capability()
    assert capability["available"] is False
    assert capability["reason"] == "live_forms_provider_not_verified"
