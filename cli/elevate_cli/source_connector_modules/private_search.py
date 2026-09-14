"""Private-search buyer helpers for source connectors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


JsonRecord = dict[str, Any]


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


def _source_dir(source_root: Path, source_id: str) -> Path:
    return _source_connectors()._source_dir(source_root, source_id)


def _read_jsonl_records(path: Path, *, limit: int = 12, tail: bool = False) -> list[JsonRecord]:
    return _source_connectors()._read_jsonl_records(path, limit=limit, tail=tail)


# Tags that mark a CRM contact as a private-client-search buyer. The PCS
# pipeline writes `xposure-pcs`; the others are common operator/CRM-native
# tags used to group buyers by saved search. Matched case-insensitively against
# the contact's `tags` array.
_PCS_BUYER_TAGS = {
    "xposure-pcs",
    "private-search",
    "mls-buyer",
    "pcs-hot-lead",
    "#pcs",
    "agent pcs",
    "agent-pcs",
}


def _is_pcs_tag(tag: str) -> bool:
    t = tag.strip().lower()
    if not t:
        return False
    if t in _PCS_BUYER_TAGS:
        return True
    # `pcs` as a token covers xposure-pcs / pcs-hot-lead / agent pcs / #pcs
    # without catching unrelated tags (no other tag contains the substring).
    return "pcs" in t or t == "private-search" or t == "mls-buyer"


def _norm_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_phone(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _pcs_tagged_crm_buyers(source_root: Path, *, limit: int) -> list[JsonRecord]:
    """Project CRM contacts carrying a PCS tag into watchlist entries.

    This is the tag-driven surface: buyers are grouped in Lofty by an
    `xposure-pcs` (or sibling) tag. They show here unscored until the PCS
    pipeline enriches them with saved-search criteria + heat scoring.
    """
    crm_dir = _source_dir(source_root, "crm")
    contacts_path = crm_dir / "contacts.jsonl"
    if not contacts_path.exists():
        return []
    out: list[JsonRecord] = []
    for record in _read_jsonl_records(contacts_path, limit=10000):
        raw_tags = record.get("tags") or []
        if isinstance(raw_tags, (list, tuple)):
            tags = [str(t) for t in raw_tags if t]
        else:
            tags = [str(raw_tags)] if raw_tags else []
        matched = [t for t in tags if _is_pcs_tag(t)]
        if not matched:
            continue
        emails_raw = record.get("emails") or record.get("email") or ""
        phones_raw = record.get("phones") or record.get("phone") or ""
        email = _norm_email(
            emails_raw.split(",")[0] if isinstance(emails_raw, str) else
            (emails_raw[0] if isinstance(emails_raw, (list, tuple)) and emails_raw else "")
        )
        phone = _norm_phone(
            phones_raw.split(",")[0] if isinstance(phones_raw, str) else
            (phones_raw[0] if isinstance(phones_raw, (list, tuple)) and phones_raw else "")
        )
        score_val = record.get("score")
        try:
            score_int = int(score_val) if score_val is not None else None
        except (TypeError, ValueError):
            score_int = None
        is_hot = any(t.strip().lower() in ("pcs-hot-lead", "#pcs") for t in tags)
        out.append({
            "id": str(record.get("contact_id") or record.get("lead_id")
                      or record.get("source_record_id") or email or phone),
            "name": record.get("display_name") or "Unnamed buyer",
            "email": email or None,
            "phone": phone or None,
            "score": score_int,
            "tier": "HOT" if is_hot else "PCS",
            "days": None,
            "lastActivity": record.get("last_seen_at") or record.get("timestamp"),
            "dateEntered": record.get("timestamp"),
            "searches": [],
            "matchingListings": [],
            "profileUrl": None,
            "source": "crm-pcs-tag",
            "sourceLabel": "PCS tag (Lofty)",
            "tags": sorted(set(matched)),
            "scrapedAt": None,
        })
    return out[: max(limit, 1)]


def _read_private_search_buyers(source_root: Path, *, limit: int = 50) -> list[JsonRecord]:
    """Project the buyer watchlist.

    Primary surface is the `xposure-pcs` tag on CRM contacts (the buyers
    are connected by tag). When the PCS pipeline has run and written
    `mls-private-search/buyers.jsonl`, its richer scored entries overlay
    the tag-derived ones (matched by email/phone) so HOT/WARM scoring,
    saved-search criteria and Xposure profile links show through.

    Sorted by score desc (None last), then by recency.
    """
    pipeline: list[JsonRecord] = []
    path = source_root / "mls-private-search" / "buyers.jsonl"
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict):
                        pipeline.append(entry)
        except OSError:
            pipeline = []

    # Index pipeline entries by email + phone for overlay matching.
    by_email: dict[str, JsonRecord] = {}
    by_phone: dict[str, JsonRecord] = {}
    for entry in pipeline:
        e = _norm_email(entry.get("email"))
        p = _norm_phone(entry.get("phone"))
        if e:
            by_email.setdefault(e, entry)
        if p:
            by_phone.setdefault(p, entry)

    tag_buyers = _pcs_tagged_crm_buyers(source_root, limit=max(limit, 50) * 4)
    matched_pipeline: set[int] = set()
    entries: list[JsonRecord] = []
    for buyer in tag_buyers:
        overlay = (
            by_email.get(_norm_email(buyer.get("email")))
            or by_phone.get(_norm_phone(buyer.get("phone")))
        )
        if isinstance(overlay, dict):
            matched_pipeline.add(id(overlay))
            for key in ("score", "tier", "days", "lastActivity",
                        "searches", "matchingListings", "profileUrl",
                        "scrapedAt"):
                val = overlay.get(key)
                if val not in (None, [], ""):
                    buyer[key] = val
            buyer["source"] = "mls-private-search"
            buyer["sourceLabel"] = "MLS private search"
        entries.append(buyer)

    # Pipeline entries with no matching tagged contact (manual adds, stale
    # tag sync) still surface so nothing scored is hidden.
    for entry in pipeline:
        if id(entry) in matched_pipeline:
            continue
        entries.append(entry)

    def _sort_key(entry: JsonRecord) -> tuple[int, int, int]:
        score = entry.get("score")
        score_val = -int(score) if isinstance(score, (int, float)) else 0
        days = entry.get("days")
        days_val = int(days) if isinstance(days, (int, float)) else 9999
        has_score = 0 if isinstance(score, (int, float)) else 1
        return (has_score, score_val, days_val)

    entries.sort(key=_sort_key)
    return entries[:max(limit, 1)]
