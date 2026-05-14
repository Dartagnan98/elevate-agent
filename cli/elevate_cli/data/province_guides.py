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
    return get_elevate_home() / "knowledge" / "skyleigh" / "admin" / "exp-agent-centre"


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
