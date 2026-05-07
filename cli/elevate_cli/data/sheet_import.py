"""Import Skyleigh-style listing workflow sheets into Admin Hub deals.

The Google Sheet is treated as a typed source feed:

* ``Current Stage`` becomes ``deals.current_stage``.
* Known yes/no columns become named toggles.
* Known date/money columns become first-class deal fields.
* Every non-empty source column is also preserved under ``extraToggles`` using
  a ``sheet_`` key so the original row remains inspectable.

The importer is idempotent. Rows are matched by
``google_sheet:{sheet_id}:{gid}:{row_id}``, so repeated syncs update the same
deal instead of creating duplicates.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import urllib.request
from typing import Any, Mapping

from elevate_cli.data._util import now_iso
from elevate_cli.data.deals import (
    _NAMED_FIELDS,
    _TOGGLE_FIELDS,
    _decode_json,
    _encode_json,
    _insert_deal_event,
    _row_to_deal,
    _split_fields,
    _validate_stage,
    create_deal,
    get_deal,
    set_deal_fields,
)


DEFAULT_LISTING_SHEET_ID = "1OQDduX6hqpEiErA8Q6Mx86vaKX5dQhHS5btPfxJMMrw"
DEFAULT_LISTING_SHEET_GID = "204411937"


_STAGE_RE = re.compile(r"\bStage\s*(\d+)\b", re.IGNORECASE)
_CONTACT_ID_RE = re.compile(r"/contact/(\d+)")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


NAMED_FIELD_COLUMNS = {
    "Signing Authority": "signing_authority",
    "FINTRAC Form Type": "fintrac_form_type",
    "Politically Exposed Person?": "pep",
    "Listing Track": "listing_track",
    "Property Sub-Type": "property_subtype",
    "Tenanted Property?": "tenanted",
    "Estate / Probate Status": "estate_status",
    "POA Signing?": "poa_signing",
    "Corporate Seller?": "corporate",
    "Listing Type": "listing_type",
    "Has Suite?": "has_suite",
}


DETAIL_FIELD_COLUMNS = {
    "Listing Price": "list_price",
    "Commission Rate (%)": "commission_pct",
    "Planned Go-Live Date": "listing_date",
    "MLS Listing URL": "mls_number",
    "Live Date (Actual)": "listing_published_at",
    "Offer Received Date": "offer_date",
    "Accepted Offer Date": "offer_accepted_at",
    "Deposit ROF Received Date": "deposit_in_trust_at",
    "Completion Date": "completion_date",
    "Subject Removal Date": "subject_removal_date",
    "Possession Date": "possession_date",
}


def google_sheet_csv_url(
    *,
    sheet_id: str = DEFAULT_LISTING_SHEET_ID,
    gid: str = DEFAULT_LISTING_SHEET_GID,
) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def fetch_public_google_sheet_csv(
    *,
    sheet_id: str = DEFAULT_LISTING_SHEET_ID,
    gid: str = DEFAULT_LISTING_SHEET_GID,
    timeout: int = 20,
) -> str:
    """Fetch a public Google Sheet tab as CSV."""
    req = urllib.request.Request(
        google_sheet_csv_url(sheet_id=sheet_id, gid=gid),
        headers={"User-Agent": "Elevate Admin Hub"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - operator-provided public sheet id
        body = resp.read()
        return body.decode(resp.headers.get_content_charset() or "utf-8")


def import_google_listing_sheet(
    conn: sqlite3.Connection,
    *,
    sheet_id: str = DEFAULT_LISTING_SHEET_ID,
    gid: str = DEFAULT_LISTING_SHEET_GID,
    province: str = "BC",
    actor: str = "sheet:google",
) -> dict[str, Any]:
    csv_text = fetch_public_google_sheet_csv(sheet_id=sheet_id, gid=gid)
    return import_listing_sheet_csv(
        conn,
        csv_text,
        sheet_id=sheet_id,
        gid=gid,
        province=province,
        actor=actor,
    )


def import_listing_sheet_csv(
    conn: sqlite3.Connection,
    csv_text: str,
    *,
    sheet_id: str = DEFAULT_LISTING_SHEET_ID,
    gid: str = DEFAULT_LISTING_SHEET_GID,
    province: str = "BC",
    actor: str = "sheet:google",
) -> dict[str, Any]:
    """Parse and upsert all data rows from a listing workflow sheet CSV."""
    parsed_rows = parse_listing_sheet_csv(csv_text, sheet_id=sheet_id, gid=gid)
    created = 0
    updated = 0
    items: list[dict[str, Any]] = []
    for row in parsed_rows:
        deal, action = upsert_listing_sheet_row(
            conn,
            row,
            province=province,
            actor=actor,
        )
        if action == "created":
            created += 1
        else:
            updated += 1
        items.append(deal)
    return {
        "source": "google_sheet",
        "sheetId": sheet_id,
        "gid": gid,
        "province": province,
        "count": len(items),
        "created": created,
        "updated": updated,
        "items": items,
    }


def parse_listing_sheet_csv(
    csv_text: str,
    *,
    sheet_id: str = DEFAULT_LISTING_SHEET_ID,
    gid: str = DEFAULT_LISTING_SHEET_GID,
) -> list[dict[str, Any]]:
    rows = list(csv.reader(io.StringIO(csv_text)))
    if len(rows) < 3:
        return []
    headers = [cell.strip() for cell in rows[1]]
    out: list[dict[str, Any]] = []
    for raw in rows[3:]:
        if not any(cell.strip() for cell in raw):
            continue
        record = {
            header: raw[idx].strip() if idx < len(raw) else ""
            for idx, header in enumerate(headers)
            if header
        }
        row_id = record.get("Row ID", "").strip()
        address = record.get("Property Address", "").strip()
        if not row_id and not address:
            continue
        out.append(_normalize_source_row(record, sheet_id=sheet_id, gid=gid))
    return out


def upsert_listing_sheet_row(
    conn: sqlite3.Connection,
    row: Mapping[str, Any],
    *,
    province: str = "BC",
    actor: str = "sheet:google",
) -> tuple[dict[str, Any], str]:
    """Create or update one deal from a parsed source row."""
    source_key = str(row["sourceKey"])
    now = now_iso()
    existing = conn.execute("SELECT * FROM deals WHERE source_key=?", (source_key,)).fetchone()
    fields = dict(row.get("namedFields") or {})
    extra = dict(row.get("extraToggles") or {})
    detail_fields = dict(row.get("detailFields") or {})

    if existing is None:
        deal = create_deal(
            conn,
            title=str(row["title"]),
            side="listing",
            actor=actor,
            province=province.upper(),
            current_stage=int(row["currentStage"]),
            lofty_contact_id=row.get("loftyContactId"),
            listing_address=row.get("listingAddress"),
            source_key=source_key,
            source_row_id=row.get("sourceRowId"),
            source_label=row.get("sourceLabel"),
            source_synced_at=now,
            fields=fields | extra,
        )
        if detail_fields:
            deal = set_deal_fields(conn, deal["id"], actor=actor, fields=detail_fields)
        return deal, "created"

    deal_id = existing["id"]
    old_stage = int(existing["current_stage"])
    new_stage = _validate_stage(int(row["currentStage"]))
    named_sql, _ = _split_fields(fields)
    current_extra = _decode_json(existing["extra_toggles_json"]) or {}
    if not isinstance(current_extra, dict):
        current_extra = {}
    preserved_extra = {
        key: value for key, value in current_extra.items()
        if not str(key).startswith("sheet_")
    }
    merged_extra = {**preserved_extra, **extra}

    sets = [
        "title=?",
        "current_stage=?",
        "province=?",
        "listing_address=?",
        "lofty_contact_id=?",
        "extra_toggles_json=?",
        "source_row_id=?",
        "source_label=?",
        "source_synced_at=?",
        "updated_at=?",
    ]
    values: list[Any] = [
        str(row["title"]),
        new_stage,
        province.upper(),
        row.get("listingAddress"),
        row.get("loftyContactId"),
        _encode_json(merged_extra) if merged_extra else None,
        row.get("sourceRowId"),
        row.get("sourceLabel"),
        now,
        now,
    ]
    if old_stage != new_stage:
        sets.append("stage_entered_at=?")
        values.append(now)
    for field in sorted(_NAMED_FIELDS):
        if field in named_sql:
            sets.append(f"{field}=?")
            values.append(named_sql[field])
    values.append(deal_id)
    conn.execute(f"UPDATE deals SET {', '.join(sets)} WHERE id=?", values)
    if detail_fields:
        set_deal_fields(conn, deal_id, actor=actor, fields=detail_fields)
    _insert_deal_event(
        conn,
        deal_id=deal_id,
        kind="toggle_change",
        actor=actor,
        field_name="sheet_import",
        old_value={"stage": old_stage},
        new_value={"stage": new_stage, "sourceKey": source_key},
        payload={"sourceKey": source_key, "sourceRowId": row.get("sourceRowId")},
        created_at=now,
    )
    updated = get_deal(conn, deal_id)
    return updated, "updated"  # type: ignore[return-value]


def _normalize_source_row(
    record: Mapping[str, str],
    *,
    sheet_id: str,
    gid: str,
) -> dict[str, Any]:
    row_id = str(record.get("Row ID") or "").strip()
    address = str(record.get("Property Address") or "").strip()
    source_key_id = row_id or _slug(address)
    source_key = f"google_sheet:{sheet_id}:{gid}:{source_key_id}"
    stage = _parse_stage(record.get("Current Stage"))
    extra: dict[str, Any] = {}
    named: dict[str, Any] = {}
    details: dict[str, Any] = {}

    for label, raw_value in record.items():
        if raw_value == "":
            continue
        source_key_name = f"sheet_{_slug(label)}"
        extra[source_key_name] = _coerce_sheet_value(label, raw_value)

        if label in NAMED_FIELD_COLUMNS:
            named[NAMED_FIELD_COLUMNS[label]] = _coerce_named_value(
                NAMED_FIELD_COLUMNS[label],
                raw_value,
            )
        if label in DETAIL_FIELD_COLUMNS:
            detail_field = DETAIL_FIELD_COLUMNS[label]
            detail_value = _coerce_detail_value(detail_field, raw_value)
            if detail_value is not None:
                details[detail_field] = detail_value

    mls_url = str(record.get("MLS Listing URL") or "").strip()
    if mls_url and "mls_number" not in details:
        mls_number = _extract_last_number(mls_url)
        if mls_number:
            details["mls_number"] = mls_number

    return {
        "sourceKey": source_key,
        "sourceRowId": row_id or None,
        "sourceLabel": "Google Sheet Active Listings",
        "title": address or f"Listing row {row_id}",
        "listingAddress": address or None,
        "currentStage": stage,
        "loftyContactId": _extract_lofty_contact_id(record.get("Lofty Contact URL")),
        "namedFields": named,
        "detailFields": details,
        "extraToggles": extra,
        "raw": dict(record),
    }


def _parse_stage(value: str | None) -> int:
    match = _STAGE_RE.search(str(value or ""))
    if not match:
        return 0
    return _validate_stage(int(match.group(1)))


def _slug(value: str) -> str:
    text = value.strip().lower().replace("✓", "")
    text = text.replace("%", " pct ")
    text = _NON_ALNUM_RE.sub("_", text).strip("_")
    return text or "field"


def _coerce_sheet_value(label: str, value: str) -> Any:
    text = value.strip()
    bool_value = _parse_bool(text)
    if bool_value is not None:
        return bool_value
    if _DATE_RE.match(text):
        return text
    if any(token in label.lower() for token in ("price", "rate", "amount", "commission")):
        number = _parse_number(text)
        if number is not None:
            return number
    return text


def _coerce_named_value(field: str, value: str) -> Any:
    if field in _TOGGLE_FIELDS:
        bool_value = _parse_bool(value)
        return bool_value
    return value.strip() or None


def _coerce_detail_value(field: str, value: str) -> Any:
    text = value.strip()
    if field in {"list_price", "offer_price", "deposit_amount", "commission_pct", "lot_size_sqft"}:
        return _parse_number(text)
    if field == "mls_number":
        return _extract_last_number(text)
    if _DATE_RE.match(text):
        return text
    return None


def _parse_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "y", "1", "checked"}:
        return True
    if normalized in {"false", "no", "n", "0", "unchecked"}:
        return False
    return None


def _parse_number(value: str) -> float | None:
    cleaned = value.strip().replace("$", "").replace(",", "").replace("%", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_lofty_contact_id(value: str | None) -> str | None:
    text = str(value or "")
    match = _CONTACT_ID_RE.search(text)
    if match:
        return match.group(1)
    return text.strip() or None


def _extract_last_number(value: str | None) -> str | None:
    text = str(value or "")
    matches = re.findall(r"\d{5,}", text)
    return matches[-1] if matches else None


def deal_sheet_debug_json(row: Mapping[str, Any]) -> str:
    """Return a stable debug string for operator previews/tests."""
    public_row = {
        key: value for key, value in row.items()
        if key != "raw"
    }
    return json.dumps(public_row, sort_keys=True, default=str)


__all__ = [
    "DEFAULT_LISTING_SHEET_GID",
    "DEFAULT_LISTING_SHEET_ID",
    "deal_sheet_debug_json",
    "fetch_public_google_sheet_csv",
    "google_sheet_csv_url",
    "import_google_listing_sheet",
    "import_listing_sheet_csv",
    "parse_listing_sheet_csv",
    "upsert_listing_sheet_row",
]
