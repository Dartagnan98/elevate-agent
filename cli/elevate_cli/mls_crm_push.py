"""
mls_crm_push.py -- MLS lead push through the Elevate CRM write layer.

Reads a hot-leads JSON produced by an MLS scraper (Playwright/Node) and
pushes each lead into whatever CRM the agent has configured via Elevate.

Per-lead operations:
  1. crm_find_lead     -- check if already in CRM (email, then phone)
  2. crm_create_lead   -- create if not found (stage + tags + note all set in body)
  3. crm_add_note      -- write search criteria as a structured note
  4. crm_update_stage  -- merge tags + update stage (only on existing leads)

Idempotency:
  Note content is hashed and stored as a tag (`mls-hash-<short>`).
  If the lead already has the current hash, criteria are unchanged --
  skip the note add, only refresh stage if it drifted.

Usage:
  python -m elevate_cli.mls_crm_push --input /path/to/hot-leads.json
  python -m elevate_cli.mls_crm_push --input /path/to/hot-leads.json --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from elevate_cli.config import load_config
from elevate_cli.source_connectors import (
    crm_add_note,
    crm_create_lead,
    crm_find_lead,
    crm_update_stage,
)

JsonRecord = dict[str, Any]

HASH_TAG_PREFIX = "mls-hash-"


# ── Note builder ──────────────────────────────────────────────────────────────

def _build_note(lead: JsonRecord, source: str) -> str:
    """Build a structured CRM note from the lead's MLS search criteria."""
    lines = [f"MLS Active Buyer | Source: {source}"]
    lines.append(f"Last active: {lead.get('lastActivity', '?')} ({lead.get('days', '?')}d ago)")
    lines.append(f"Score: {lead.get('score', '?')}pts ({lead.get('tier', '?')})")

    profile = lead.get("profile") or {}
    search_details = [
        s for s in (profile.get("searchDetails") or [])
        if not str(s.get("title", "")).startswith("Timeline")
    ]

    for s in search_details:
        criteria = s.get("criteria") or {}
        parts = []
        areas = criteria.get("areas") or []
        if areas:
            parts.append(f"Areas: {', '.join(areas[:8])}" + (f" +{len(areas)-8} more" if len(areas) > 8 else ""))
        if criteria.get("bedsMin"):
            parts.append(f"{criteria['bedsMin']}+ beds")
        if criteria.get("bathsMin"):
            parts.append(f"{criteria['bathsMin']}+ baths")
        if criteria.get("priceMin") or criteria.get("priceMax"):
            price = f"${int(criteria['priceMin']):,}" if criteria.get("priceMin") else ""
            price += f"–${int(criteria['priceMax']):,}" if criteria.get("priceMax") else "+"
            parts.append(price)
        if criteria.get("propertyType"):
            parts.append(criteria["propertyType"])
        if parts:
            lines.append(f"{s.get('title', 'Search')}: {' · '.join(parts)}")

    return "\n".join(lines)


def _note_hash(note: str) -> str:
    return hashlib.md5(note.encode("utf-8")).hexdigest()[:10]


# ── Per-lead push ─────────────────────────────────────────────────────────────

def _push_lead(
    lead: JsonRecord,
    config: JsonRecord,
    dry_run: bool,
    source: str,
    hot_stage: str,
    hot_tags: list[str],
) -> JsonRecord:
    name = lead.get("name") or ""
    parts = name.strip().split(" ", 1)
    first = parts[0] if parts else ""
    last = parts[1] if len(parts) > 1 else ""
    email = lead.get("email") or ""
    phone = (lead.get("phone") or "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    note = _build_note(lead, source)
    hash_tag = f"{HASH_TAG_PREFIX}{_note_hash(note)}"

    result: JsonRecord = {"name": name, "email": email}

    if dry_run:
        result["action"] = "dry_run"
        result["note_preview"] = note
        result["hash_tag"] = hash_tag
        return result

    # 1. Find existing -- email first, phone fallback
    existing = None
    if email or phone:
        try:
            existing = crm_find_lead(email, config, phone=phone)
        except NotImplementedError as e:
            result["error"] = str(e)
            return result

    lead_id = existing["id"] if existing else None
    existing_tags = (existing or {}).get("tags") or []

    # Strip stale hash tags, append fresh hash + hot tags
    cleaned_existing = [t for t in existing_tags if not str(t).startswith(HASH_TAG_PREFIX)]
    merged_tags = list(dict.fromkeys(cleaned_existing + hot_tags + [hash_tag]))

    # 2. Create path -- stage, tags, note all set in create body
    if not lead_id:
        if not email and not phone:
            result["error"] = "no email or phone -- cannot dedupe, skipping"
            return result
        contact: JsonRecord = {
            "firstName": first,
            "lastName": last,
            "email": email,
            "phone": phone,
            "source": source,
            "stage": hot_stage,
            "tags": merged_tags,
            "note": note,  # Brivity bakes note into description at create
        }
        try:
            lead_id = crm_create_lead(contact, config)
        except NotImplementedError as e:
            result["error"] = str(e)
            return result
        result["action"] = "created"
        result["crm_id"] = lead_id
        if not lead_id:
            result["error"] = "no crm_id returned"
            return result
        # Lofty/FUB/Sierra need explicit note add (Brivity already has it)
        # crm_add_note returns False harmlessly for Brivity
        try:
            note_ok = crm_add_note(lead_id, note, config)
            result["note_written"] = note_ok
        except NotImplementedError:
            result["note_written"] = False
        return result

    # 3. Update path -- check hash for idempotency
    result["crm_id"] = lead_id
    has_current_hash = hash_tag in existing_tags

    if has_current_hash:
        # Criteria unchanged since last sync. Only refresh stage if drifted.
        result["action"] = "unchanged"
        if str(existing.get("stage", "")).lower() != hot_stage.lower():
            stage_ok = crm_update_stage(lead_id, hot_stage, merged_tags, config)
            result["stage_updated"] = stage_ok
        return result

    # Criteria changed. Add fresh note + update stage/tags.
    result["action"] = "updated"
    try:
        note_ok = crm_add_note(lead_id, note, config)
        result["note_written"] = note_ok
    except NotImplementedError:
        result["note_written"] = False
    stage_ok = crm_update_stage(lead_id, hot_stage, merged_tags, config)
    result["stage_updated"] = stage_ok
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Push MLS hot leads into the connected CRM.")
    parser.add_argument("--input", required=True, help="Path to hot-leads JSON from MLS scraper.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to CRM.")
    parser.add_argument("--source", default="mls-private-search", help="CRM source label (default: mls-private-search).")
    parser.add_argument("--stage", default="Hot", help="CRM stage to assign hot leads (default: Hot).")
    parser.add_argument(
        "--tags",
        default="mls-buyer,private-search",
        help="Comma-separated tags to apply (default: mls-buyer,private-search).",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(json.dumps({"error": f"Input file not found: {input_path}"}))
        sys.exit(1)

    data = json.loads(input_path.read_text())
    leads = data.get("leads") or (data if isinstance(data, list) else [])
    hot_tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    config = load_config()

    results = []
    counts = {"created": 0, "updated": 0, "unchanged": 0, "dry_run": 0, "errors": 0}

    for lead in leads:
        r = _push_lead(
            lead,
            config=config,
            dry_run=args.dry_run,
            source=args.source,
            hot_stage=args.stage,
            hot_tags=hot_tags,
        )
        results.append(r)
        if r.get("error"):
            counts["errors"] += 1
        else:
            action = r.get("action", "errors")
            if action in counts:
                counts[action] += 1

    summary = {
        "total": len(leads),
        "ok": counts["created"] + counts["updated"] + counts["unchanged"] + counts["dry_run"],
        "errors": counts["errors"],
        "created": counts["created"],
        "updated": counts["updated"],
        "unchanged": counts["unchanged"],
        "dry_run": args.dry_run,
        "results": results,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
