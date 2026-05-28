"""SQLite-backed province guide import/read helpers.

The scraped eXp Agent Centre markdown files are useful as source material, but
Admin Hub runtime should read durable SQLite rows.  This module imports the
local knowledge folder into the operational store and exposes compact shapes
for deal context, tasks, and skills.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

from elevate_cli.config import get_elevate_home
from elevate_cli.data._util import new_id, now_iso, sha256


PROVINCE_LABELS = {
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "ON": "Ontario",
    "PEI": "Prince Edward Island",
    "QC": "Quebec",
    "SK": "Saskatchewan",
    "YK": "Yukon",
}

_LANDING_TO_PROVINCE = {
    "alberta": "AB",
    "british-columbia": "BC",
    "manitoba": "MB",
    "new-brunswick": "NB",
    "newfoundland-and-labrador": "NL",
    "nova-scotia": "NS",
    "ontario": "ON",
    "prince-edward-island": "PEI",
    "quebec": "QC",
    "saskatchewan": "SK",
    "yukon": "YK",
}
_PREFIX_TO_PROVINCE = {
    "ab": "AB",
    "bc": "BC",
    "mb": "MB",
    "nb": "NB",
    "nl": "NL",
    "ns": "NS",
    "on": "ON",
    "ontario": "ON",
    "pei": "PEI",
    "qc": "QC",
    "sk": "SK",
    "yk": "YK",
    "yt": "YK",
}
_PROVINCE_ALIASES = {
    **{code.lower(): code for code in PROVINCE_LABELS},
    **{label.lower(): code for code, label in PROVINCE_LABELS.items()},
    **_LANDING_TO_PROVINCE,
    **_PREFIX_TO_PROVINCE,
    "newfoundland": "NL",
    "nwt": "NT",
    "northwest-territories": "NT",
    "prince edward island": "PEI",
    "p.e.i.": "PEI",
    "yukon territory": "YK",
}
_PAGE_TYPES = {
    "boards": "boards",
    "deposit-instructions": "deposit_instructions",
    "events-training": "events_training",
    "listings-sales": "listings_sales",
}
_GUIDE_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)

_DEFAULT_CONDITIONAL_DOCS = [
    {
        "province": "BC",
        "side": "listing",
        "stage": 6,
        "field_key": "property_subtype",
        "field_value": "strata",
        "doc_code": "strata_docs",
        "doc_name": "Strata documents",
        "notes": "Seeded from the BC transaction guide strata/condo resale topics.",
    },
    {
        "province": "BC",
        "side": "listing",
        "stage": 2,
        "field_key": "tenanted",
        "field_value": "true",
        "doc_code": "tenancy_docs",
        "doc_name": "Tenancy documents / notice requirements",
        "notes": "Seeded from the BC transaction guide tenants topic.",
    },
    {
        "province": "BC",
        "side": None,
        "stage": 6,
        "field_key": "multiple_offers",
        "field_value": "true",
        "doc_code": "offer_matrix",
        "doc_name": "Multiple-offer comparison matrix",
        "notes": "Seeded from the BC transaction guide multiple offers topic.",
    },
    {
        "province": "BC",
        "side": None,
        "stage": 3,
        "field_key": "poa_signing",
        "field_value": "true",
        "doc_code": "poa_authority",
        "doc_name": "Power of attorney authority review",
        "notes": "Seeded from the BC transaction guide POA/corporate client topic.",
    },
]


def default_exp_agent_centre_root() -> Path:
    return get_elevate_home() / "knowledge" / "real-estate" / "admin" / "exp-agent-centre"


def _decode_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _encode_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"), default=str)


def _split_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    match = _GUIDE_FRONTMATTER_RE.match(markdown)
    if not match:
        return {}, markdown
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, markdown[match.end():]


def _title_from_markdown(body: str, fallback: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback.replace("-", " ").title()


def _province_for_page(slug: str) -> str | None:
    if slug in _LANDING_TO_PROVINCE:
        return _LANDING_TO_PROVINCE[slug]
    prefix = slug.split("-", 1)[0]
    return _PREFIX_TO_PROVINCE.get(prefix)


def _page_type(slug: str) -> str:
    if slug in _LANDING_TO_PROVINCE:
        return "landing"
    for marker, page_type in _PAGE_TYPES.items():
        if slug.endswith(marker):
            return page_type
    return "other"


def normalize_province_code(value: str | None) -> str | None:
    """Return a canonical province code, or raise for unknown values.

    Province guide import supports an explicit destructive prune path. Unknown
    labels must fail closed so typos cannot delete all guide rows.
    """
    text = str(value or "").strip()
    if not text:
        return None
    code = text.upper()
    if code in PROVINCE_LABELS:
        return code
    key = text.lower().replace("_", "-").strip()
    if key in _PROVINCE_ALIASES:
        return _PROVINCE_ALIASES[key]
    spaced = key.replace("-", " ")
    if spaced in _PROVINCE_ALIASES:
        return _PROVINCE_ALIASES[spaced]
    raise ValueError(f"unknown province {text!r}")


def _row_to_reference_page(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "province": row["province"],
        "slug": row["slug"],
        "pageType": row["page_type"],
        "title": row["title"],
        "sourceUrl": row["source_url"],
        "sourcePath": row["source_path"],
        "content": row["content_md"],
        "contentHash": row["content_hash"],
        "importedAt": row["imported_at"],
        "updatedAt": row["updated_at"],
    }


def _row_to_checklist(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "province": row["province"],
        "slug": row["slug"],
        "title": row["title"],
        "sourceUrl": row["source_url"],
        "sourcePath": row["source_path"],
        "content": row["content_md"],
        "contentHash": row["content_hash"],
        "importedAt": row["imported_at"],
        "updatedAt": row["updated_at"],
    }


def _row_to_form(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "province": row["province"],
        "code": row["code"],
        "name": row["name"],
        "category": row["category"],
        "description": row["description"],
        "pageCount": row["page_count"],
        "annotationCount": row["annotation_count"],
        "imageUrls": _decode_json(row["image_urls_json"]) or [],
        "localImagePaths": _decode_json(row["local_image_paths_json"]) or [],
        "sourcePath": row["source_path"],
        "importedAt": row["imported_at"],
        "updatedAt": row["updated_at"],
    }


def _upsert_reference_page(
    conn: sqlite3.Connection,
    *,
    province: str,
    slug: str,
    page_type: str,
    title: str,
    source_url: str | None,
    source_path: str,
    content_md: str,
    now: str,
) -> None:
    digest = sha256(content_md)
    existing = conn.execute(
        "SELECT id FROM province_reference_pages WHERE province=? AND slug=?",
        (province, slug),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE province_reference_pages
            SET page_type=?, title=?, source_url=?, source_path=?,
                content_md=?, content_hash=?, updated_at=?
            WHERE id=?
            """,
            (page_type, title, source_url, source_path, content_md, digest, now, existing["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO province_reference_pages(
                id, province, slug, page_type, title, source_url, source_path,
                content_md, content_hash, imported_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (new_id(), province, slug, page_type, title, source_url, source_path, content_md, digest, now, now),
        )


def _upsert_checklist(
    conn: sqlite3.Connection,
    *,
    province: str,
    slug: str,
    title: str,
    source_url: str | None,
    source_path: str,
    content_md: str,
    now: str,
) -> None:
    digest = sha256(content_md)
    existing = conn.execute(
        "SELECT id FROM province_checklists WHERE province=? AND slug=?",
        (province, slug),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE province_checklists
            SET title=?, source_url=?, source_path=?, content_md=?,
                content_hash=?, updated_at=?
            WHERE id=?
            """,
            (title, source_url, source_path, content_md, digest, now, existing["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO province_checklists(
                id, province, slug, title, source_url, source_path,
                content_md, content_hash, imported_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (new_id(), province, slug, title, source_url, source_path, content_md, digest, now, now),
        )


def _form_local_images(forms_root: Path, code: str) -> list[str]:
    form_dir = forms_root / code
    if not form_dir.exists():
        for candidate in (forms_root.iterdir() if forms_root.exists() else []):
            if candidate.is_dir() and candidate.name.lower() == code.lower():
                form_dir = candidate
                break
    if not form_dir.exists():
        return []
    return [str(path) for path in sorted(form_dir.glob("*.png"))]


def _upsert_form(
    conn: sqlite3.Connection,
    *,
    province: str,
    code: str,
    form: Mapping[str, Any],
    local_image_paths: list[str],
    source_path: str,
    now: str,
) -> None:
    existing = conn.execute(
        "SELECT id FROM province_forms WHERE province=? AND code=?",
        (province, code),
    ).fetchone()
    values = (
        str(form.get("name") or code),
        form.get("category"),
        form.get("description"),
        form.get("pageCount"),
        form.get("annotationCount"),
        _encode_json(form.get("imageUrls") or []),
        _encode_json(local_image_paths),
        source_path,
        now,
    )
    if existing:
        conn.execute(
            """
            UPDATE province_forms
            SET name=?, category=?, description=?, page_count=?,
                annotation_count=?, image_urls_json=?, local_image_paths_json=?,
                source_path=?, updated_at=?
            WHERE id=?
            """,
            (*values, existing["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO province_forms(
                id, province, code, name, category, description, page_count,
                annotation_count, image_urls_json, local_image_paths_json,
                source_path, imported_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (new_id(), province, code, *values[:-1], now, now),
        )


def _upsert_conditional_doc(
    conn: sqlite3.Connection,
    *,
    province: str,
    field_key: str,
    field_value: str,
    doc_code: str,
    doc_name: str,
    notes: str | None,
    side: str | None,
    stage: int | None,
    now: str,
) -> None:
    existing = conn.execute(
        """
        SELECT id FROM conditional_docs
        WHERE province=? AND field_key=? AND field_value=? AND doc_code=?
        """,
        (province, field_key, field_value, doc_code),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE conditional_docs
            SET doc_name=?, notes=?, side=?, stage=?
            WHERE id=?
            """,
            (doc_name, notes, side, stage, existing["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO conditional_docs(
                id, province, field_key, field_value, doc_code, doc_name,
                notes, created_at, side, stage
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (new_id(), province, field_key, field_value, doc_code, doc_name, notes, now, side, stage),
        )


def import_exp_agent_centre(
    conn: sqlite3.Connection,
    root: str | Path | None = None,
    *,
    province: str | None = None,
    prune_other_provinces: bool = False,
) -> dict[str, Any]:
    """Import local eXp Agent Centre markdown/forms into SQLite.

    Missing roots return a summary instead of raising so fresh installs can run
    without private scrape output. By default the product imports all available
    provinces so onboarding can show users their choices. When ``province`` is
    provided, import can be narrowed to that province; ``prune_other_provinces``
    is an explicit maintenance escape hatch, not the onboarding default.
    """
    base = Path(root).expanduser() if root is not None else default_exp_agent_centre_root()
    target_province = normalize_province_code(province)
    target_set = {target_province} if target_province else None
    if not base.exists():
        return {
            "ok": False,
            "root": str(base),
            "error": "knowledge root does not exist",
            "pages": 0,
            "checklists": 0,
            "forms": 0,
            "conditionalDocs": 0,
            "provinces": [],
        }

    now = now_iso()
    page_count = 0
    checklist_count = 0
    form_count = 0
    conditional_count = 0
    provinces: set[str] = set()

    pages_root = base / "pages"
    if pages_root.exists():
        for path in sorted(pages_root.glob("*.md")):
            slug = path.stem
            province = _province_for_page(slug)
            if not province:
                continue
            if target_set and province not in target_set:
                continue
            raw = path.read_text(encoding="utf-8")
            meta, body = _split_frontmatter(raw)
            _upsert_reference_page(
                conn,
                province=province,
                slug=slug,
                page_type=_page_type(slug),
                title=meta.get("title") or _title_from_markdown(body, slug),
                source_url=meta.get("url"),
                source_path=str(path),
                content_md=raw,
                now=now,
            )
            page_count += 1
            provinces.add(province)

    for guide_root in sorted(base.glob("transaction-guide-*")):
        if not guide_root.is_dir():
            continue
        suffix = guide_root.name[len("transaction-guide-"):].lower()
        guide_province = _PREFIX_TO_PROVINCE.get(suffix)
        if not guide_province:
            continue
        if target_set and guide_province not in target_set:
            continue
        provinces.add(guide_province)

        for path in sorted(guide_root.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            meta, body = _split_frontmatter(raw)
            _upsert_checklist(
                conn,
                province=guide_province,
                slug=path.stem,
                title=meta.get("title") or _title_from_markdown(body, path.stem),
                source_url=meta.get("url"),
                source_path=str(path),
                content_md=raw,
                now=now,
            )
            checklist_count += 1

        topics_root = guide_root / "best-practices-topics"
        if topics_root.exists():
            for path in sorted(topics_root.glob("*.md")):
                raw = path.read_text(encoding="utf-8")
                meta, body = _split_frontmatter(raw)
                _upsert_reference_page(
                    conn,
                    province=guide_province,
                    slug=f"best-practices/{path.stem}",
                    page_type="best_practice",
                    title=meta.get("title") or _title_from_markdown(body, path.stem),
                    source_url=meta.get("url"),
                    source_path=str(path),
                    content_md=raw,
                    now=now,
                )
                page_count += 1

        inventory = guide_root / "forms" / "inventory.json"
        if inventory.exists():
            data = json.loads(inventory.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for code, form in sorted(data.items()):
                    if not isinstance(form, Mapping):
                        continue
                    _upsert_form(
                        conn,
                        province=guide_province,
                        code=str(code),
                        form=form,
                        local_image_paths=_form_local_images(inventory.parent, str(code)),
                        source_path=str(inventory),
                        now=now,
                    )
                    form_count += 1

    if not target_set or "BC" in target_set:
        for item in _DEFAULT_CONDITIONAL_DOCS:
            _upsert_conditional_doc(conn, now=now, **item)
            conditional_count += 1

    if prune_other_provinces and target_set:
        placeholders = ",".join("?" for _ in target_set)
        params = tuple(sorted(target_set))
        for table in ("province_reference_pages", "province_checklists", "province_forms", "conditional_docs"):
            conn.execute(f"DELETE FROM {table} WHERE province NOT IN ({placeholders})", params)

    return {
        "ok": True,
        "root": str(base),
        "pages": page_count,
        "checklists": checklist_count,
        "forms": form_count,
        "conditionalDocs": conditional_count,
        "provinces": sorted(provinces),
    }


def list_province_reference_pages(
    conn: sqlite3.Connection,
    *,
    province: str | None = None,
    page_type: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM province_reference_pages WHERE 1=1"
    params: list[Any] = []
    if province:
        sql += " AND province=?"
        params.append(province.upper())
    if page_type:
        sql += " AND page_type=?"
        params.append(page_type)
    sql += " ORDER BY province, page_type, slug"
    return [_row_to_reference_page(row) for row in conn.execute(sql, params).fetchall()]


def list_province_checklists(
    conn: sqlite3.Connection,
    *,
    province: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM province_checklists WHERE 1=1"
    params: list[Any] = []
    if province:
        sql += " AND province=?"
        params.append(province.upper())
    sql += " ORDER BY province, slug"
    return [_row_to_checklist(row) for row in conn.execute(sql, params).fetchall()]


def list_province_forms(
    conn: sqlite3.Connection,
    *,
    province: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM province_forms WHERE 1=1"
    params: list[Any] = []
    if province:
        sql += " AND province=?"
        params.append(province.upper())
    if category:
        sql += " AND category=?"
        params.append(category)
    sql += " ORDER BY province, category, name, code"
    return [_row_to_form(row) for row in conn.execute(sql, params).fetchall()]


_AGENT_PAGE_PRIORITY = {
    "listings_sales": 0,
    "deposit_instructions": 1,
    "boards": 2,
    "landing": 3,
    "events_training": 4,
    "other": 5,
}


def _compact_markdown(value: str | None, *, limit: int = 900) -> str:
    text = str(value or "")
    text = _GUIDE_FRONTMATTER_RE.sub("", text).strip()
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[#>*`\-]+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def province_agent_memory(
    conn: sqlite3.Connection,
    province: str,
    *,
    max_reference_pages: int = 8,
    max_checklists: int = 10,
    max_forms: int = 40,
    excerpt_chars: int = 900,
) -> dict[str, Any]:
    """Return compact province guide material safe to inject into skill prompts.

    The full markdown/PDF-derived corpus stays in SQLite.  This shape gives an
    admin skill immediate working memory plus source paths for deeper local
    reads when it needs the full guide.
    """
    province = (province or "").upper()
    page_rows = list_province_reference_pages(conn, province=province)
    checklist_rows = list_province_checklists(conn, province=province)
    form_rows = list_province_forms(conn, province=province)

    page_rows = sorted(
        page_rows,
        key=lambda row: (
            _AGENT_PAGE_PRIORITY.get(str(row.get("pageType") or "other"), 99),
            str(row.get("slug") or ""),
        ),
    )

    return {
        "source": "sqlite:province_guides",
        "province": province,
        "provinceLabel": PROVINCE_LABELS.get(province, province),
        "coverage": {
            "referencePages": len(page_rows),
            "checklists": len(checklist_rows),
            "forms": len(form_rows),
            "hasTransactionGuide": bool(checklist_rows or form_rows),
        },
        "referencePages": [
            {
                "slug": row["slug"],
                "pageType": row["pageType"],
                "title": row["title"],
                "sourcePath": row["sourcePath"],
                "excerpt": _compact_markdown(row.get("content"), limit=excerpt_chars),
            }
            for row in page_rows[:max_reference_pages]
        ],
        "checklists": [
            {
                "slug": row["slug"],
                "title": row["title"],
                "sourcePath": row["sourcePath"],
                "excerpt": _compact_markdown(row.get("content"), limit=excerpt_chars),
            }
            for row in checklist_rows[:max_checklists]
        ],
        "forms": [
            {
                "code": row["code"],
                "name": row["name"],
                "category": row["category"],
                "pageCount": row["pageCount"],
                "annotationCount": row["annotationCount"],
                "sourcePath": row["sourcePath"],
            }
            for row in form_rows[:max_forms]
        ],
        "truncated": {
            "referencePages": max(0, len(page_rows) - max_reference_pages),
            "checklists": max(0, len(checklist_rows) - max_checklists),
            "forms": max(0, len(form_rows) - max_forms),
        },
    }


def condition_docs_for_conditions(
    conn: sqlite3.Connection,
    *,
    province: str,
    conditions: Mapping[str, Any],
    side: str | None = None,
    stage: int | None = None,
) -> list[dict[str, Any]]:
    province = (province or "").upper()
    if not province or not conditions:
        return []
    rows = conn.execute(
        """
        SELECT * FROM conditional_docs
        WHERE province=?
        ORDER BY field_key, doc_code
        """,
        (province,),
    ).fetchall()
    docs: list[dict[str, Any]] = []
    for row in rows:
        if row["field_key"] not in conditions:
            continue
        expected = str(row["field_value"] or "").strip().lower()
        raw_value = conditions.get(row["field_key"])
        actual = str(raw_value).strip().lower() if raw_value is not None else ""
        if actual != expected:
            continue
        row_side = row["side"] if "side" in row.keys() else None
        row_stage = row["stage"] if "stage" in row.keys() else None
        if row_side and side and row_side != side:
            continue
        if row_stage is not None and stage is not None and int(row_stage) != int(stage):
            continue
        docs.append(
            {
                "id": row["id"],
                "province": row["province"],
                "side": row_side,
                "stage": row_stage,
                "fieldKey": row["field_key"],
                "fieldValue": row["field_value"],
                "docCode": row["doc_code"],
                "docName": row["doc_name"],
                "notes": row["notes"],
            }
        )
    return docs


def province_guide_summary(conn: sqlite3.Connection, province: str) -> dict[str, Any]:
    province = (province or "").upper()
    page_rows = list_province_reference_pages(conn, province=province)
    checklist_rows = list_province_checklists(conn, province=province)
    form_rows = list_province_forms(conn, province=province)
    page_counts: dict[str, int] = {}
    for page in page_rows:
        page_type = str(page.get("pageType") or "other")
        page_counts[page_type] = page_counts.get(page_type, 0) + 1
    return {
        "province": province,
        "provinceLabel": PROVINCE_LABELS.get(province, province),
        "coverage": {
            "referencePages": len(page_rows),
            "checklists": len(checklist_rows),
            "forms": len(form_rows),
            "pageTypes": page_counts,
            "hasTransactionGuide": bool(checklist_rows or form_rows),
        },
        "pages": [
            {k: page[k] for k in ("province", "slug", "pageType", "title", "sourceUrl", "sourcePath")}
            for page in page_rows
        ],
        "checklists": [
            {k: item[k] for k in ("province", "slug", "title", "sourceUrl", "sourcePath")}
            for item in checklist_rows
        ],
        "forms": [
            {
                "province": form["province"],
                "code": form["code"],
                "name": form["name"],
                "category": form["category"],
                "pageCount": form["pageCount"],
                "annotationCount": form["annotationCount"],
                "localImagePaths": form["localImagePaths"],
            }
            for form in form_rows
        ],
    }


# --- Stage-aware document mapping --------------------------------------------
#
# The 10-stage admin kanban spine is identical for every deal. What changes by
# province is the *set of documents* a Realtor must produce inside each stage.
# We surface that adaptive layer by mapping the structured `province_forms`
# inventory (code/name/category) to a stage, then layering `conditional_docs`
# on top based on the card's runtime conditions (tenanted, multiple_offers,
# strata, etc.).
#
# Parsing the free-text `province_checklists` bodies is intentionally avoided
# here -- scrapes vary widely in markup quality. The forms inventory is clean
# and durable; checklists stay as reference material the UI links to.

_STAGE_COMMITMENT = 0
_STAGE_INTAKE = 1
_STAGE_DOCS = 2
_STAGE_PHOTOS = 3
_STAGE_MLS = 4
_STAGE_LIVE = 5
_STAGE_CONTRACT = 6
_STAGE_SUBJECTS = 7
_STAGE_CLOSING = 8
_STAGE_CLOSED = 9


# Each rule: (regex against lower(code + ' ' + name + ' ' + category), side, stage)
# `side` of None matches both listing and buyer. Province-specific rules run
# first; generic rules act as a fallback when no province rule matches.
_FORM_STAGE_PATTERNS: dict[str, list[tuple[str, str | None, int]]] = {
    "BC": [
        (r"\bmlc\b|multiple\s*listing", "listing", _STAGE_INTAKE),
        (r"\bbaec\b|buyer\s+agency|buyer\s+representation", "buyer", _STAGE_INTAKE),
        (r"\bpnc\b|privacy\s+notice", None, _STAGE_COMMITMENT),
        (r"\bpds\b|property\s+disclosure", "listing", _STAGE_DOCS),
        (r"\bcps\b|contract\s+of\s+purchase", None, _STAGE_CONTRACT),
        (r"disc(losure)?[-\s]of[-\s]rem|remuneration", None, _STAGE_INTAKE),
        (r"strata", "listing", _STAGE_DOCS),
        (r"\brental\b|tenancy", "listing", _STAGE_DOCS),
        (r"\bfee[-\s]for[-\s]service|fee-service", None, _STAGE_INTAKE),
        (r"general\s+release|authorization\s+to\s+pay\s+deposit", None, _STAGE_CONTRACT),
        (r"\bdisclosure\b", None, _STAGE_DOCS),
    ],
    "ON": [
        # Listing / representation
        (r"\bform\s*200\b|\bform\s*201\b|listing\s+agreement", "listing", _STAGE_INTAKE),
        (r"\bform\s*240\b|\bform\s*241\b|\bform\s*242\b|individual\s+identification", None, _STAGE_INTAKE),
        (r"\bform\s*218\b|\bform\s*371\b|\bform\s*372\b|working\s+with\s+a\s+realtor", None, _STAGE_COMMITMENT),
        (r"\bform\s*299\b|customer\s+service", None, _STAGE_COMMITMENT),
        (r"\bform\s*271\b|\bform\s*272\b|buyer\s+representation", "buyer", _STAGE_INTAKE),
        (r"\bform\s*145\b|confirmation\s+of\s+co-?operation", None, _STAGE_INTAKE),
        # Contract
        (r"\bform\s*100\b|\bform\s*101\b|\bform\s*500\b|agreement\s+of\s+purchase\s+and\s+sale", None, _STAGE_CONTRACT),
        (r"\bform\s*110\b|seller\s+property\s+information", "listing", _STAGE_DOCS),
        (r"\bform\s*400\b|\bform\s*410\b|commercial", None, _STAGE_CONTRACT),
        # Subjects / amendments / waivers
        (r"\bform\s*120\b|amendment\s+to\s+agreement", None, _STAGE_SUBJECTS),
        (r"\bform\s*121\b|\bform\s*124\b|notice\s+of\s+fulfill", None, _STAGE_SUBJECTS),
        (r"\bform\s*122\b|mutual\s+release", None, _STAGE_SUBJECTS),
        (r"\bform\s*123\b|waiver", None, _STAGE_SUBJECTS),
        (r"\bform\s*125\b|\bform\s*126\b|\bform\s*127\b|notice.+(condition|remove)", None, _STAGE_SUBJECTS),
        # Schedules / disclosures
        (r"\bform\s*320\b|disclosure", None, _STAGE_DOCS),
        (r"\bform\s*150\b|\bform\s*170\b", None, _STAGE_INTAKE),
        # Multiple representation, referral, co-brokerage, seller direction
        (r"\bform\s*244\b|seller'?s?\s+direction", "listing", _STAGE_CONTRACT),
        (r"\bform\s*325\b|\bform\s*326\b|multiple\s+representation", None, _STAGE_COMMITMENT),
        (r"\bform\s*641\b|referral\s+agreement", None, _STAGE_COMMITMENT),
        (r"\bform\s*650\b|co-?brokerage", None, _STAGE_COMMITMENT),
    ],
    "AB": [
        (r"\besra\b|exclusive\s+seller", "listing", _STAGE_INTAKE),
        (r"\bebra\b|exclusive\s+buyer", "buyer", _STAGE_INTAKE),
        (r"residential\s+purchase|\brps\b|rps-?condo", None, _STAGE_CONTRACT),
        (r"agri-?purchase|agricultural", None, _STAGE_CONTRACT),
        (r"country-?schedule|^schedule\b|manufactured-?schedule", None, _STAGE_DOCS),
        (r"dower", None, _STAGE_CONTRACT),
        (r"notice.+condition|satisfy.+condition|non-?satisfy", None, _STAGE_SUBJECTS),
        (r"addendum|amendment", None, _STAGE_SUBJECTS),
        (r"property\s+data\s+sheet|seller\s+property\s+information", "listing", _STAGE_DOCS),
        (r"fintrac|individual\s+identification", None, _STAGE_INTAKE),
        # Representation, fee, cooperation, disclosure
        (r"represent\s+both|both\s+buyer\s+and\s+seller|multiple\s+representation", None, _STAGE_COMMITMENT),
        (r"customer\s+acknowledgement|cust-?acknowledgement", None, _STAGE_COMMITMENT),
        (r"fee\s+disclosure", None, _STAGE_INTAKE),
        (r"realtor\s+cooperation|cooperation\s+policy", None, _STAGE_COMMITMENT),
        (r"realtor\s+disclosure|disclosure\s+to\s+(an?\s+)?(un)?represented|disclosure\s+to\s+(un)?rep", None, _STAGE_COMMITMENT),
        (r"ebra-?termination|termination", None, _STAGE_SUBJECTS),
    ],
    "MB": [
        (r"listing\s+contract|mls-?listing", "listing", _STAGE_INTAKE),
        (r"joint\s+representation|limited\s+representation", None, _STAGE_INTAKE),
        (r"\bform-?e\b", None, _STAGE_INTAKE),
        (r"condo.*(pds|disclosure)|pds-?condo", "listing", _STAGE_DOCS),
        (r"marketing\s+release", None, _STAGE_MLS),
        (r"direction.+offer", None, _STAGE_CONTRACT),
        (r"offer\s+to\s+purchase|purchase\s+agreement", None, _STAGE_CONTRACT),
        (r"working\s+with\s+a\s+realtor|wwar", None, _STAGE_COMMITMENT),
    ],
    "YK": [
        (r"\besra\b|exclusive\s+seller", "listing", _STAGE_INTAKE),
        (r"\bebra\b|exclusive\s+buyer", "buyer", _STAGE_INTAKE),
        (r"residential\s+purchase|\brps\b", None, _STAGE_CONTRACT),
        (r"agri-?purchase|agricultural", None, _STAGE_CONTRACT),
        (r"^schedule\b|country-?schedule", None, _STAGE_DOCS),
        (r"notice.+condition|satisfy.+condition", None, _STAGE_SUBJECTS),
        (r"addendum|amendment", None, _STAGE_SUBJECTS),
    ],
}

# Generic fallback rules tried after province-specific rules. These cover the
# long tail (NB/NL/NS/PEI/QC/SK) that only have the create-deal-sheet form.
_GENERIC_STAGE_PATTERNS: list[tuple[str, str | None, int]] = [
    (r"listing\s+(agreement|contract)", "listing", _STAGE_INTAKE),
    (r"buyer\s+(representation|agency|rep)", "buyer", _STAGE_INTAKE),
    (r"purchase\s+(agreement|contract|and\s+sale)", None, _STAGE_CONTRACT),
    (r"deal\s+sheet", None, _STAGE_CONTRACT),
    (r"\bfintrac\b|identification|kyc\b", None, _STAGE_INTAKE),
    (r"privacy\s+notice|consent", None, _STAGE_COMMITMENT),
    (r"property\s+disclosure|seller\s+disclosure", "listing", _STAGE_DOCS),
    (r"strata|condo(minium)?\s+document", "listing", _STAGE_DOCS),
    (r"amendment|waiver|notice\s+of\s+fulfill", None, _STAGE_SUBJECTS),
    (r"mutual\s+release", None, _STAGE_SUBJECTS),
    (r"deposit|trust\s+account", None, _STAGE_CONTRACT),
    (r"commission|remuneration", None, _STAGE_INTAKE),
    (r"closing|conveyance|completion", None, _STAGE_CLOSING),
    (r"\bmls\b|marketing\s+release", None, _STAGE_MLS),
]

# Heuristics by category alone, used only if name-level patterns missed.
_CATEGORY_STAGE_RULES: list[tuple[str, str | None, int]] = [
    ("listing", "listing", _STAGE_INTAKE),
    ("buyer", "buyer", _STAGE_INTAKE),
    ("disclosure", "listing", _STAGE_DOCS),
    ("rental", "listing", _STAGE_DOCS),
    ("additional", None, _STAGE_DOCS),
]


def _match_form_stage(
    form: Mapping[str, Any],
    province: str,
    side: str,
) -> tuple[int | None, str | None, str]:
    """Return ``(stage, form_side, status)``.

    ``status`` is one of:
      * ``"matched"`` -- mapped to a stage on this side
      * ``"other_side"`` -- matched a rule but the rule is for the other side
      * ``"unmapped"`` -- no rule fired
    """
    haystack = " ".join(
        filter(
            None,
            (
                str(form.get("code") or ""),
                str(form.get("name") or ""),
                str(form.get("category") or ""),
            ),
        )
    ).lower()
    rules = list(_FORM_STAGE_PATTERNS.get(province, ()))
    rules.extend(_GENERIC_STAGE_PATTERNS)
    other_side_hit: tuple[int, str | None] | None = None
    for pattern, form_side, stage in rules:
        if not re.search(pattern, haystack):
            continue
        if form_side and side and form_side != side:
            if other_side_hit is None:
                other_side_hit = (stage, form_side)
            continue
        return stage, form_side, "matched"
    category = str(form.get("category") or "").strip().lower()
    if category:
        for cat_key, form_side, stage in _CATEGORY_STAGE_RULES:
            if cat_key not in category:
                continue
            if form_side and side and form_side != side:
                if other_side_hit is None:
                    other_side_hit = (stage, form_side)
                continue
            return stage, form_side, "matched"
    if other_side_hit is not None:
        return other_side_hit[0], other_side_hit[1], "other_side"
    return None, None, "unmapped"


def province_stage_documents(
    conn: sqlite3.Connection,
    *,
    province: str,
    side: str = "listing",
    conditions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return per-stage document checklist for a deal.

    Output shape::

        {
          "province": "BC",
          "side": "listing",
          "stages": {
            "0": [ {code, name, source, side, category, sourcePath, condition?}, ... ],
            "1": [...],
            ...
          },
          "unmapped": [ {code, name, category}, ... ],
          "coverage": {"forms": int, "mapped": int, "conditional": int},
        }

    `source` is one of ``"form"`` (from province_forms inventory) or
    ``"conditional"`` (from conditional_docs triggered by ``conditions``).
    The caller's existing hardcoded stage checklist items can still be merged
    on top of this output.
    """
    province = (province or "").upper()
    side = (side or "").strip().lower() or "listing"
    if side not in {"listing", "buyer"}:
        side = "listing"
    conditions = dict(conditions or {})

    stages: dict[int, list[dict[str, Any]]] = {}
    unmapped: list[dict[str, Any]] = []
    other_side: list[dict[str, Any]] = []
    mapped_count = 0
    conditional_count = 0

    forms = list_province_forms(conn, province=province)
    for form in forms:
        stage, form_side, status = _match_form_stage(form, province=province, side=side)
        if status == "matched" and stage is not None:
            stages.setdefault(stage, []).append(
                {
                    "code": form.get("code"),
                    "name": form.get("name") or form.get("code"),
                    "source": "form",
                    "side": form_side,
                    "category": form.get("category"),
                    "sourcePath": form.get("sourcePath"),
                    "condition": None,
                }
            )
            mapped_count += 1
        elif status == "other_side":
            other_side.append(
                {
                    "code": form.get("code"),
                    "name": form.get("name") or form.get("code"),
                    "category": form.get("category"),
                    "side": form_side,
                }
            )
        else:
            unmapped.append(
                {
                    "code": form.get("code"),
                    "name": form.get("name") or form.get("code"),
                    "category": form.get("category"),
                }
            )

    cond_rows = conn.execute(
        "SELECT * FROM conditional_docs WHERE province=? ORDER BY stage, doc_code",
        (province,),
    ).fetchall()
    for row in cond_rows:
        field_key = row["field_key"]
        expected = str(row["field_value"] or "").strip().lower()
        actual = str(conditions.get(field_key) or "").strip().lower()
        if not actual or actual != expected:
            continue
        row_side = row["side"] if "side" in row.keys() else None
        if row_side and row_side != side:
            continue
        row_stage = row["stage"] if "stage" in row.keys() else None
        stage_int = int(row_stage) if row_stage is not None else _STAGE_DOCS
        stages.setdefault(stage_int, []).append(
            {
                "code": row["doc_code"],
                "name": row["doc_name"],
                "source": "conditional",
                "side": row_side,
                "category": None,
                "sourcePath": None,
                "condition": {"field": field_key, "value": row["field_value"]},
            }
        )
        conditional_count += 1

    for stage_int in list(stages.keys()):
        stages[stage_int].sort(
            key=lambda item: (
                0 if item["source"] == "form" else 1,
                str(item.get("category") or ""),
                str(item.get("name") or ""),
                str(item.get("code") or ""),
            )
        )

    return {
        "province": province,
        "side": side,
        "stages": {str(k): v for k, v in sorted(stages.items())},
        "unmapped": unmapped,
        "otherSide": other_side,
        "coverage": {
            "forms": len(forms),
            "mapped": mapped_count,
            "conditional": conditional_count,
            "otherSide": len(other_side),
            "unmapped": len(unmapped),
        },
    }


def province_coverage(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT province,
               COUNT(*) AS reference_pages,
               SUM(CASE WHEN page_type='listings_sales' THEN 1 ELSE 0 END) AS listings_sales_pages
        FROM province_reference_pages
        GROUP BY province
        ORDER BY province
        """
    ).fetchall()
    checklist_counts = {
        row["province"]: row["count"]
        for row in conn.execute(
            "SELECT province, COUNT(*) AS count FROM province_checklists GROUP BY province"
        ).fetchall()
    }
    form_counts = {
        row["province"]: row["count"]
        for row in conn.execute(
            "SELECT province, COUNT(*) AS count FROM province_forms GROUP BY province"
        ).fetchall()
    }
    return [
        {
            "province": row["province"],
            "provinceLabel": PROVINCE_LABELS.get(row["province"], row["province"]),
            "referencePages": row["reference_pages"],
            "listingsSalesPages": row["listings_sales_pages"],
            "checklists": checklist_counts.get(row["province"], 0),
            "forms": form_counts.get(row["province"], 0),
            "hasTransactionGuide": bool(checklist_counts.get(row["province"]) or form_counts.get(row["province"])),
        }
        for row in rows
    ]
