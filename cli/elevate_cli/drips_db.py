"""Drip campaign store + engine.

Backs the dashboard's Drips section. Everything lives in the per-account
operational Postgres store (migration ``0035_drip_campaigns.sql``) through
the ``elevate_cli.data.connection`` shim, so the SQL below keeps the
sqlite-style ``?`` placeholders the rest of the data layer uses.

Three layers:

* **Library** — the Elevation templates in :mod:`elevate_cli.drip_templates`
  are seeded on first use (segments, campaigns + steps, the video script
  library, engine settings). They become ordinary editable rows; the
  template library stays available to re-install or reset from.
* **Store** — CRUD for segments, campaigns, steps, videos and settings,
  plus enrollments (a contact running through a campaign) and touches
  (the materialised day-by-day schedule for one enrollment).
* **Engine** — ``set_contact_segment`` applies the layering rules (one
  nurture campaign at a time, the segment move ends the old one and
  starts the new one the same day, courses layer by buying/selling flag on
  pre-set days that never clash), ``due_board`` lists what goes out today,
  and ``run_engine`` executes the automatic tag moves, completes finished
  runs and turns call touches into tasks.
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator

from elevate_cli import drip_templates as _templates
from elevate_cli.data import connection as _data_connection
from elevate_cli.data._util import new_id, now_iso

_LOG = logging.getLogger(__name__)

ACTOR_WEB = "human:web"
ACTOR_AUTO = "drips:auto"

CHANNELS = ("text", "email", "call", "task", "tag")
KINDS = ("nurture", "course", "playbook", "custom")
ROLES = ("primary", "layer")
LAYER_FLAGS = ("buying", "selling")
LIVE_ENROLLMENT_STATUSES = ("active", "paused")
ROUTE_SPECIALS = ("done", "restart")

SEED_KEY = "seed_template_version"

DEFAULT_SETTINGS: dict[str, Any] = {
    # Put brand-new buyer/seller leads straight into the New segment (which
    # starts The First 14 Days). Off by default so an install chooses when
    # to switch it on; the existing book is never swept automatically.
    "autoEnrollNewLeads": False,
    "autoEnrollSince": None,
    # Let day-15 / day-92 / day-187 / day-101 / day-367 tag steps move the
    # segment on their own (with a note on the contact card).
    "autoTagMoves": True,
    "sendWindowStart": "08:00",
    "sendWindowEnd": "20:30",
    # Call touches become tasks on the Tasks board the day they are due.
    "callsAsTasks": True,
    # AI first-touch drafts stay paused for anyone running through a campaign.
    "pauseAiDraftsInCampaigns": True,
    "newsletterTool": "Mailjet",
}

_VIDEO_SLOT_RE = re.compile(r"\[Insert video:\s*([^\]]+)\]", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r"\[[^\[\]\n]{1,60}\]")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ─── Connection + seeding ──────────────────────────────────────────────


@contextmanager
def connect() -> Iterator[Any]:
    """Pooled operational-store connection with the Elevation seed applied."""
    with _data_connection.connect() as conn:
        maybe_seed(conn)
        yield conn


def _today() -> date:
    return date.today()


def _as_date(value: Any, fallback: date | None = None) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value.strip():
        return date.fromisoformat(value.strip()[:10])
    if fallback is not None:
        return fallback
    return _today()


def slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", (value or "").strip().lower()).strip("-")
    return slug or "campaign"


def _read_setting(conn, key: str) -> Any:
    row = conn.execute("SELECT value_json FROM drip_settings WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["value_json"])
    except Exception:
        return None


def _write_setting(conn, key: str, value: Any) -> None:
    conn.execute(
        """
        INSERT INTO drip_settings (key, value_json, updated_at) VALUES (?, ?, ?)
        ON CONFLICT (key) DO UPDATE SET value_json=EXCLUDED.value_json, updated_at=EXCLUDED.updated_at
        """,
        (key, json.dumps(value), now_iso()),
    )


def maybe_seed(conn) -> bool:
    """Seed the Elevation library once per account database. Returns True when it ran."""
    if _read_setting(conn, SEED_KEY) is not None:
        return False
    seed_elevation_defaults(conn)
    return True


def seed_elevation_defaults(conn) -> dict[str, int]:
    """Insert the Elevation segments, campaigns, videos and settings.

    Idempotent per row: segments and videos upsert on their key, campaigns
    are only inserted when no row carries that ``template_slug`` yet, and
    settings keep whatever the install already changed.
    """
    now = now_iso()
    counts = {"segments": 0, "campaigns": 0, "videos": 0}
    for order, seg in enumerate(_templates.SEGMENTS):
        conn.execute(
            """
            INSERT INTO drip_segments (key, label, description, window_label, color, sort_order, builtin, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
            ON CONFLICT (key) DO NOTHING
            """,
            (seg["key"], seg["label"], seg.get("description"), seg.get("window_label"), seg.get("color"), order * 10, now, now),
        )
        counts["segments"] += 1
    for order, video in enumerate(_templates.VIDEOS):
        conn.execute(
            """
            INSERT INTO drip_videos (slug, name, length_label, script, used_in, link, recorded_at, sort_order, builtin, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, 1, ?, ?)
            ON CONFLICT (slug) DO NOTHING
            """,
            (video["slug"], video["name"], video.get("length_label"), video.get("script"), video.get("used_in"), order * 10, now, now),
        )
        counts["videos"] += 1
    for template in _templates.CAMPAIGNS:
        exists = conn.execute(
            "SELECT id FROM drip_campaigns WHERE template_slug=? LIMIT 1", (template["slug"],)
        ).fetchone()
        if exists:
            continue
        _insert_campaign_from_template(conn, template, slug=template["slug"])
        counts["campaigns"] += 1
    for key, value in DEFAULT_SETTINGS.items():
        if _read_setting(conn, key) is None and conn.execute(
            "SELECT 1 FROM drip_settings WHERE key=?", (key,)
        ).fetchone() is None:
            _write_setting(conn, key, value)
    _write_setting(conn, SEED_KEY, _templates.TEMPLATE_VERSION)
    return counts


def _unique_slug(conn, base: str) -> str:
    slug = slugify(base)
    candidate = slug
    n = 2
    while conn.execute("SELECT 1 FROM drip_campaigns WHERE slug=?", (candidate,)).fetchone():
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


def _insert_campaign_from_template(conn, template: dict[str, Any], *, slug: str, name: str | None = None) -> str:
    now = now_iso()
    campaign_id = new_id()
    conn.execute(
        """
        INSERT INTO drip_campaigns
            (id, slug, name, description, kind, role, trigger_segment, layer_flag, defer_layers,
             run_once, enabled, template_slug, source_url, exit_day, exit_rule, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            campaign_id,
            slug,
            name or template["name"],
            template.get("description"),
            template.get("kind", "nurture"),
            template.get("role", "primary"),
            template.get("trigger_segment"),
            template.get("layer_flag"),
            1 if template.get("defer_layers") else 0,
            1 if template.get("run_once") else 0,
            template["slug"],
            template.get("source_url"),
            template.get("exit_day"),
            template.get("exit_rule"),
            template.get("notes"),
            now,
            now,
        ),
    )
    for order, step in enumerate(template.get("steps", [])):
        conn.execute(
            """
            INSERT INTO drip_steps (id, campaign_id, day, sort_order, channel, title, subject, body, video_slot, notes, route_to, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(), campaign_id, int(step["day"]), order * 10, step["channel"], step["title"],
                step.get("subject"), step.get("body"), step.get("video"), step.get("notes"), step.get("route_to"),
                now, now,
            ),
        )
    return campaign_id


# ─── Row shaping ───────────────────────────────────────────────────────


def _row_segment(row) -> dict[str, Any]:
    return {
        "key": row["key"],
        "label": row["label"],
        "description": row["description"],
        "windowLabel": row["window_label"],
        "color": row["color"],
        "sortOrder": int(row["sort_order"] or 0),
        "builtin": bool(row["builtin"]),
        "enabled": bool(row["enabled"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _row_campaign(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "name": row["name"],
        "description": row["description"],
        "kind": row["kind"],
        "role": row["role"],
        "triggerSegment": row["trigger_segment"],
        "layerFlag": row["layer_flag"],
        "deferLayers": bool(row["defer_layers"]),
        "runOnce": bool(row["run_once"]),
        "enabled": bool(row["enabled"]),
        "templateSlug": row["template_slug"],
        "sourceUrl": row["source_url"],
        "exitDay": row["exit_day"],
        "exitRule": row["exit_rule"],
        "notes": row["notes"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _row_step(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "campaignId": row["campaign_id"],
        "day": int(row["day"]),
        "sortOrder": int(row["sort_order"] or 0),
        "channel": row["channel"],
        "title": row["title"],
        "subject": row["subject"],
        "body": row["body"],
        "video": row["video_slot"],
        "notes": row["notes"],
        "routeTo": row["route_to"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _row_enrollment(row) -> dict[str, Any]:
    keys = row.keys() if hasattr(row, "keys") else []
    out = {
        "id": row["id"],
        "campaignId": row["campaign_id"],
        "contactId": row["contact_id"],
        "startDate": row["start_date"],
        "status": row["status"],
        "stopReason": row["stop_reason"],
        "enrolledBy": row["enrolled_by"],
        "completedAt": row["completed_at"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    if "campaign_name" in keys:
        out["campaignName"] = row["campaign_name"]
    if "display_name" in keys:
        out["contactName"] = row["display_name"]
    if "scheduled_count" in keys:
        out["scheduledCount"] = int(row["scheduled_count"] or 0)
    if "done_count" in keys:
        out["doneCount"] = int(row["done_count"] or 0)
    if "next_due" in keys:
        out["nextDue"] = row["next_due"]
    return out


def _row_video(row) -> dict[str, Any]:
    return {
        "slug": row["slug"],
        "name": row["name"],
        "lengthLabel": row["length_label"],
        "script": row["script"],
        "usedIn": row["used_in"],
        "link": row["link"],
        "recordedAt": row["recorded_at"],
        "sortOrder": int(row["sort_order"] or 0),
        "builtin": bool(row["builtin"]),
    }


def _row_contact(row) -> dict[str, Any]:
    keys = row.keys() if hasattr(row, "keys") else []

    def _get(name: str, default: Any = None) -> Any:
        return row[name] if name in keys else default

    return {
        "id": row["id"],
        "name": _get("display_name") or "(no name)",
        "email": _get("primary_email"),
        "phone": _get("primary_phone"),
        "type": _get("type"),
        "createdAt": _get("created_at"),
        "leadSource": _get("lead_source"),
        "hidden": bool(_get("hidden", 0) or 0),
        "unsubscribed": bool(_get("unsubscribed", 0) or 0),
    }


# ─── Settings ──────────────────────────────────────────────────────────


def get_settings(conn) -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    rows = conn.execute("SELECT key, value_json FROM drip_settings").fetchall()
    for row in rows:
        key = row["key"]
        if key not in DEFAULT_SETTINGS:
            continue
        try:
            out[key] = json.loads(row["value_json"])
        except Exception:
            continue
    return out


def update_settings(conn, patch: dict[str, Any]) -> dict[str, Any]:
    current = get_settings(conn)
    for key, value in (patch or {}).items():
        if key not in DEFAULT_SETTINGS:
            raise ValueError(f"unknown setting {key!r}")
        if key == "autoEnrollNewLeads":
            value = bool(value)
            if value and not current.get("autoEnrollSince"):
                _write_setting(conn, "autoEnrollSince", now_iso())
        elif key in ("autoTagMoves", "callsAsTasks", "pauseAiDraftsInCampaigns"):
            value = bool(value)
        elif key in ("sendWindowStart", "sendWindowEnd"):
            value = _validate_clock(value)
        elif key == "newsletterTool":
            value = (str(value or "")).strip() or None
        elif key == "autoEnrollSince":
            value = (str(value or "")).strip() or None
        _write_setting(conn, key, value)
    return get_settings(conn)


def _validate_clock(value: Any) -> str:
    text = str(value or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"invalid time {value!r}; use HH:MM")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


# ─── Segments ──────────────────────────────────────────────────────────


def list_segments(conn, *, include_counts: bool = True) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM drip_segments ORDER BY sort_order, label").fetchall()
    segments = [_row_segment(r) for r in rows]
    if include_counts:
        counts: dict[str, int] = {}
        for row in conn.execute(
            "SELECT segment_key, COUNT(*) AS n FROM drip_contact_segments GROUP BY segment_key"
        ).fetchall():
            counts[row["segment_key"]] = int(row["n"] or 0)
        triggers: dict[str, list[str]] = {}
        for row in conn.execute(
            "SELECT trigger_segment, name FROM drip_campaigns WHERE trigger_segment IS NOT NULL ORDER BY name"
        ).fetchall():
            triggers.setdefault(row["trigger_segment"], []).append(row["name"])
        for seg in segments:
            seg["contactCount"] = counts.get(seg["key"], 0)
            seg["campaigns"] = triggers.get(seg["key"], [])
    return segments


def get_segment(conn, key: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM drip_segments WHERE key=?", (key,)).fetchone()
    return _row_segment(row) if row else None


def create_segment(
    conn,
    *,
    label: str,
    key: str | None = None,
    description: str | None = None,
    window_label: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    label = (label or "").strip()
    if not label:
        raise ValueError("segment label cannot be empty")
    seg_key = slugify(key or label).replace("-", "_")
    if conn.execute("SELECT 1 FROM drip_segments WHERE key=?", (seg_key,)).fetchone():
        raise ValueError(f"segment {seg_key!r} already exists")
    row = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS m FROM drip_segments").fetchone()
    now = now_iso()
    conn.execute(
        """
        INSERT INTO drip_segments (key, label, description, window_label, color, sort_order, builtin, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?, ?)
        """,
        (seg_key, label, description, window_label, color, int(row["m"] or 0) + 10, now, now),
    )
    return get_segment(conn, seg_key)  # type: ignore[return-value]


def update_segment(conn, key: str, **fields: Any) -> dict[str, Any]:
    if get_segment(conn, key) is None:
        raise ValueError(f"segment {key!r} not found")
    columns = {
        "label": "label",
        "description": "description",
        "window_label": "window_label",
        "windowLabel": "window_label",
        "color": "color",
        "enabled": "enabled",
        "sort_order": "sort_order",
        "sortOrder": "sort_order",
    }
    sets: list[str] = []
    params: list[Any] = []
    for name, value in fields.items():
        if value is None or name not in columns:
            continue
        column = columns[name]
        if column == "label":
            value = str(value).strip()
            if not value:
                raise ValueError("segment label cannot be empty")
        elif column == "enabled":
            value = 1 if value else 0
        elif column == "sort_order":
            value = int(value)
        sets.append(f"{column}=?")
        params.append(value)
    if sets:
        sets.append("updated_at=?")
        params.append(now_iso())
        params.append(key)
        conn.execute(f"UPDATE drip_segments SET {', '.join(sets)} WHERE key=?", params)
    return get_segment(conn, key)  # type: ignore[return-value]


def delete_segment(conn, key: str) -> bool:
    if get_segment(conn, key) is None:
        return False
    in_use = conn.execute(
        "SELECT COUNT(*) AS n FROM drip_contact_segments WHERE segment_key=?", (key,)
    ).fetchone()
    if int(in_use["n"] or 0):
        raise ValueError("move the contacts out of this segment before deleting it")
    triggers = conn.execute(
        "SELECT name FROM drip_campaigns WHERE trigger_segment=?", (key,)
    ).fetchall()
    if triggers:
        names = ", ".join(r["name"] for r in triggers)
        raise ValueError(f"{names} start from this segment; change their trigger first")
    conn.execute("DELETE FROM drip_segments WHERE key=?", (key,))
    return True


def reorder_segments(conn, keys: list[str]) -> list[dict[str, Any]]:
    now = now_iso()
    for index, key in enumerate(keys):
        conn.execute(
            "UPDATE drip_segments SET sort_order=?, updated_at=? WHERE key=?",
            (index * 10, now, key),
        )
    return list_segments(conn)


# ─── Campaigns + steps ─────────────────────────────────────────────────


def _campaign_row(conn, campaign_id: str):
    return conn.execute("SELECT * FROM drip_campaigns WHERE id=?", (campaign_id,)).fetchone()


def _campaign_stats(conn) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for row in conn.execute(
        "SELECT campaign_id, COUNT(*) AS n FROM drip_steps GROUP BY campaign_id"
    ).fetchall():
        stats.setdefault(row["campaign_id"], {})["steps"] = int(row["n"] or 0)
    for row in conn.execute(
        "SELECT campaign_id, day FROM drip_steps WHERE channel <> 'tag' GROUP BY campaign_id, day ORDER BY campaign_id, day"
    ).fetchall():
        stats.setdefault(row["campaign_id"], {}).setdefault("days", []).append(int(row["day"]))
    for row in conn.execute(
        """
        SELECT campaign_id,
               SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active_n,
               SUM(CASE WHEN status='paused' THEN 1 ELSE 0 END) AS paused_n,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed_n
        FROM drip_enrollments GROUP BY campaign_id
        """
    ).fetchall():
        entry = stats.setdefault(row["campaign_id"], {})
        entry["active"] = int(row["active_n"] or 0)
        entry["paused"] = int(row["paused_n"] or 0)
        entry["completed"] = int(row["completed_n"] or 0)
    return stats


def list_campaigns(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM drip_campaigns ORDER BY CASE role WHEN 'primary' THEN 0 ELSE 1 END, kind, name"
    ).fetchall()
    stats = _campaign_stats(conn)
    out = []
    for row in rows:
        campaign = _row_campaign(row)
        entry = stats.get(campaign["id"], {})
        campaign["stepCount"] = entry.get("steps", 0)
        campaign["days"] = entry.get("days", [])
        campaign["activeEnrollments"] = entry.get("active", 0)
        campaign["pausedEnrollments"] = entry.get("paused", 0)
        campaign["completedEnrollments"] = entry.get("completed", 0)
        out.append(campaign)
    return out


def list_steps(conn, campaign_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM drip_steps WHERE campaign_id=? ORDER BY day, sort_order, created_at",
        (campaign_id,),
    ).fetchall()
    return [_row_step(r) for r in rows]


def get_campaign(conn, campaign_id: str) -> dict[str, Any] | None:
    row = _campaign_row(conn, campaign_id)
    if not row:
        return None
    campaign = _row_campaign(row)
    campaign["steps"] = list_steps(conn, campaign_id)
    campaign["enrollments"] = list_enrollments(conn, campaign_id=campaign_id)
    stats = _campaign_stats(conn).get(campaign_id, {})
    campaign["stepCount"] = len(campaign["steps"])
    campaign["days"] = sorted({s["day"] for s in campaign["steps"] if s["channel"] != "tag"})
    campaign["activeEnrollments"] = stats.get("active", 0)
    campaign["pausedEnrollments"] = stats.get("paused", 0)
    campaign["completedEnrollments"] = stats.get("completed", 0)
    return campaign


def create_campaign(
    conn,
    *,
    name: str,
    description: str | None = None,
    kind: str = "custom",
    role: str = "primary",
    trigger_segment: str | None = None,
    layer_flag: str | None = None,
    defer_layers: bool = False,
    run_once: bool = False,
    enabled: bool = True,
    exit_day: int | None = None,
    exit_rule: str | None = None,
    notes: str | None = None,
    source_url: str | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("campaign name cannot be empty")
    _validate_campaign_fields(conn, kind=kind, role=role, trigger_segment=trigger_segment, layer_flag=layer_flag)
    template = {
        "slug": None,
        "name": name,
        "description": description,
        "kind": kind,
        "role": role,
        "trigger_segment": trigger_segment or None,
        "layer_flag": layer_flag or None,
        "defer_layers": defer_layers,
        "run_once": run_once,
        "exit_day": exit_day,
        "exit_rule": exit_rule,
        "notes": notes,
        "source_url": source_url,
        "steps": [],
    }
    campaign_id = _insert_campaign_from_template(conn, template, slug=_unique_slug(conn, name))
    # _insert_campaign_from_template records template_slug=None for custom builds.
    conn.execute("UPDATE drip_campaigns SET template_slug=NULL, enabled=? WHERE id=?", (1 if enabled else 0, campaign_id))
    for step in steps or []:
        add_step(conn, campaign_id, **step)
    return get_campaign(conn, campaign_id)  # type: ignore[return-value]


def _validate_campaign_fields(conn, *, kind: str, role: str, trigger_segment: str | None, layer_flag: str | None) -> None:
    if kind not in KINDS:
        raise ValueError(f"invalid kind {kind!r}")
    if role not in ROLES:
        raise ValueError(f"invalid role {role!r}")
    if layer_flag and layer_flag not in LAYER_FLAGS:
        raise ValueError(f"invalid layer flag {layer_flag!r}")
    if trigger_segment and get_segment(conn, trigger_segment) is None:
        raise ValueError(f"segment {trigger_segment!r} not found")


def update_campaign(conn, campaign_id: str, **fields: Any) -> dict[str, Any]:
    row = _campaign_row(conn, campaign_id)
    if not row:
        raise ValueError(f"campaign {campaign_id!r} not found")
    columns = {
        "name": "name",
        "description": "description",
        "kind": "kind",
        "role": "role",
        "triggerSegment": "trigger_segment",
        "trigger_segment": "trigger_segment",
        "layerFlag": "layer_flag",
        "layer_flag": "layer_flag",
        "deferLayers": "defer_layers",
        "defer_layers": "defer_layers",
        "runOnce": "run_once",
        "run_once": "run_once",
        "enabled": "enabled",
        "exitDay": "exit_day",
        "exit_day": "exit_day",
        "exitRule": "exit_rule",
        "exit_rule": "exit_rule",
        "notes": "notes",
        "sourceUrl": "source_url",
        "source_url": "source_url",
    }
    merged = {
        "kind": row["kind"],
        "role": row["role"],
        "trigger_segment": row["trigger_segment"],
        "layer_flag": row["layer_flag"],
    }
    sets: list[str] = []
    params: list[Any] = []
    # Nullable text columns accept an explicit empty string to clear them.
    clearable = {"trigger_segment", "layer_flag", "exit_day", "exit_rule", "description", "notes", "source_url"}
    for name, value in fields.items():
        if name not in columns:
            continue
        column = columns[name]
        if value is None and column not in clearable:
            continue
        if column == "name":
            value = str(value).strip()
            if not value:
                raise ValueError("campaign name cannot be empty")
        elif column in ("defer_layers", "run_once", "enabled"):
            value = 1 if value else 0
        elif column == "exit_day":
            value = int(value) if value not in (None, "") else None
        elif column in ("trigger_segment", "layer_flag"):
            value = (str(value).strip() or None) if value is not None else None
            merged[column] = value
        elif column in ("kind", "role"):
            value = str(value)
            merged[column] = value
        elif column in clearable and isinstance(value, str) and not value.strip():
            value = None
        sets.append(f"{column}=?")
        params.append(value)
    _validate_campaign_fields(conn, **merged)
    if sets:
        sets.append("updated_at=?")
        params.append(now_iso())
        params.append(campaign_id)
        conn.execute(f"UPDATE drip_campaigns SET {', '.join(sets)} WHERE id=?", params)
    return get_campaign(conn, campaign_id)  # type: ignore[return-value]


def set_campaign_enabled(conn, campaign_id: str, enabled: bool) -> dict[str, Any]:
    return update_campaign(conn, campaign_id, enabled=enabled)


def delete_campaign(conn, campaign_id: str, *, force: bool = False) -> bool:
    row = _campaign_row(conn, campaign_id)
    if not row:
        return False
    live = conn.execute(
        "SELECT COUNT(*) AS n FROM drip_enrollments WHERE campaign_id=? AND status IN ('active','paused')",
        (campaign_id,),
    ).fetchone()
    if int(live["n"] or 0) and not force:
        raise ValueError("this campaign still has contacts running through it; stop them first or switch it off")
    conn.execute("DELETE FROM drip_campaigns WHERE id=?", (campaign_id,))
    return True


def duplicate_campaign(conn, campaign_id: str, *, name: str | None = None) -> dict[str, Any]:
    source = get_campaign(conn, campaign_id)
    if source is None:
        raise ValueError(f"campaign {campaign_id!r} not found")
    new_name = (name or f"{source['name']} (copy)").strip()
    template = {
        "slug": None,
        "name": new_name,
        "description": source["description"],
        "kind": source["kind"] if source["kind"] != "playbook" else "playbook",
        "role": source["role"],
        "trigger_segment": None,  # a copy never auto-starts until the user says so
        "layer_flag": None,
        "defer_layers": source["deferLayers"],
        "run_once": source["runOnce"],
        "exit_day": source["exitDay"],
        "exit_rule": source["exitRule"],
        "notes": source["notes"],
        "source_url": source["sourceUrl"],
        "steps": [
            {
                "day": s["day"], "channel": s["channel"], "title": s["title"], "subject": s["subject"],
                "body": s["body"], "video": s["video"], "notes": s["notes"], "route_to": s["routeTo"],
            }
            for s in source["steps"]
        ],
    }
    new_id_ = _insert_campaign_from_template(conn, template, slug=_unique_slug(conn, new_name))
    conn.execute("UPDATE drip_campaigns SET template_slug=NULL, enabled=0 WHERE id=?", (new_id_,))
    return get_campaign(conn, new_id_)  # type: ignore[return-value]


def add_step(
    conn,
    campaign_id: str,
    *,
    day: int,
    channel: str,
    title: str,
    subject: str | None = None,
    body: str | None = None,
    video: str | None = None,
    notes: str | None = None,
    route_to: str | None = None,
    sort_order: int | None = None,
) -> dict[str, Any]:
    if _campaign_row(conn, campaign_id) is None:
        raise ValueError(f"campaign {campaign_id!r} not found")
    day = int(day)
    if day < 1:
        raise ValueError("day must be 1 or later (day 1 is the day the segment goes on)")
    if channel not in CHANNELS:
        raise ValueError(f"invalid channel {channel!r}")
    title = (title or "").strip()
    if not title:
        raise ValueError("step title cannot be empty")
    route_to = _validate_route(conn, channel, route_to)
    video = _validate_video(conn, video)
    if sort_order is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM drip_steps WHERE campaign_id=? AND day=?",
            (campaign_id, day),
        ).fetchone()
        sort_order = int(row["m"] or 0) + 10
    now = now_iso()
    step_id = new_id()
    conn.execute(
        """
        INSERT INTO drip_steps (id, campaign_id, day, sort_order, channel, title, subject, body, video_slot, notes, route_to, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (step_id, campaign_id, day, int(sort_order), channel, title, subject, body, video, notes, route_to, now, now),
    )
    _materialize_step_for_live_enrollments(conn, campaign_id, step_id, day)
    return _row_step(conn.execute("SELECT * FROM drip_steps WHERE id=?", (step_id,)).fetchone())


def _validate_route(conn, channel: str, route_to: str | None) -> str | None:
    if channel != "tag":
        return None
    route = (route_to or "").strip() or None
    if route and route not in ROUTE_SPECIALS and get_segment(conn, route) is None:
        raise ValueError(f"segment {route!r} not found")
    return route


def _validate_video(conn, video: str | None) -> str | None:
    slug = (video or "").strip() or None
    if slug and conn.execute("SELECT 1 FROM drip_videos WHERE slug=?", (slug,)).fetchone() is None:
        raise ValueError(f"video {slug!r} not found")
    return slug


def update_step(conn, step_id: str, **fields: Any) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM drip_steps WHERE id=?", (step_id,)).fetchone()
    if not row:
        raise ValueError(f"step {step_id!r} not found")
    channel = fields.get("channel") or row["channel"]
    if channel not in CHANNELS:
        raise ValueError(f"invalid channel {channel!r}")
    columns = {
        "day": "day",
        "channel": "channel",
        "title": "title",
        "subject": "subject",
        "body": "body",
        "video": "video_slot",
        "notes": "notes",
        "routeTo": "route_to",
        "route_to": "route_to",
        "sortOrder": "sort_order",
        "sort_order": "sort_order",
    }
    sets: list[str] = []
    params: list[Any] = []
    new_day: int | None = None
    for name, value in fields.items():
        if name not in columns:
            continue
        column = columns[name]
        if column == "day":
            new_day = int(value)
            if new_day < 1:
                raise ValueError("day must be 1 or later")
            value = new_day
        elif column == "title":
            value = (str(value or "")).strip()
            if not value:
                raise ValueError("step title cannot be empty")
        elif column == "route_to":
            value = _validate_route(conn, channel, value)
        elif column == "video_slot":
            value = _validate_video(conn, value)
        elif column == "sort_order":
            value = int(value)
        elif column in ("subject", "body", "notes") and isinstance(value, str) and not value.strip():
            value = None
        sets.append(f"{column}=?")
        params.append(value)
    if "channel" in fields and channel != "tag":
        sets.append("route_to=?")
        params.append(None)
    if sets:
        sets.append("updated_at=?")
        params.append(now_iso())
        params.append(step_id)
        conn.execute(f"UPDATE drip_steps SET {', '.join(sets)} WHERE id=?", params)
    if new_day is not None and new_day != int(row["day"]):
        _reschedule_step_touches(conn, step_id, new_day)
    return _row_step(conn.execute("SELECT * FROM drip_steps WHERE id=?", (step_id,)).fetchone())


def delete_step(conn, step_id: str) -> bool:
    row = conn.execute("SELECT id FROM drip_steps WHERE id=?", (step_id,)).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM drip_steps WHERE id=?", (step_id,))
    return True


def _materialize_step_for_live_enrollments(conn, campaign_id: str, step_id: str, day: int) -> int:
    """A step added to a running campaign gets scheduled for everyone still
    in it, as long as its day has not already passed for that person."""
    today = _today()
    created = 0
    now = now_iso()
    for enrollment in conn.execute(
        "SELECT id, start_date FROM drip_enrollments WHERE campaign_id=? AND status IN ('active','paused')",
        (campaign_id,),
    ).fetchall():
        due = _as_date(enrollment["start_date"]) + timedelta(days=day - 1)
        if due < today:
            continue
        conn.execute(
            """
            INSERT INTO drip_touches (id, enrollment_id, step_id, due_date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'scheduled', ?, ?)
            """,
            (new_id(), enrollment["id"], step_id, due.isoformat(), now, now),
        )
        created += 1
    return created


def _reschedule_step_touches(conn, step_id: str, day: int) -> int:
    now = now_iso()
    moved = 0
    for touch in conn.execute(
        """
        SELECT t.id, e.start_date FROM drip_touches t
        JOIN drip_enrollments e ON e.id = t.enrollment_id
        WHERE t.step_id=? AND t.status='scheduled'
        """,
        (step_id,),
    ).fetchall():
        due = _as_date(touch["start_date"]) + timedelta(days=day - 1)
        conn.execute(
            "UPDATE drip_touches SET due_date=?, updated_at=? WHERE id=?",
            (due.isoformat(), now, touch["id"]),
        )
        moved += 1
    return moved


# ─── Template library ──────────────────────────────────────────────────


def list_templates(conn) -> list[dict[str, Any]]:
    installed: dict[str, list[dict[str, Any]]] = {}
    for row in conn.execute(
        "SELECT id, name, enabled, template_slug FROM drip_campaigns WHERE template_slug IS NOT NULL"
    ).fetchall():
        installed.setdefault(row["template_slug"], []).append(
            {"id": row["id"], "name": row["name"], "enabled": bool(row["enabled"])}
        )
    out = []
    for template in _templates.CAMPAIGNS:
        steps = template.get("steps", [])
        out.append(
            {
                "slug": template["slug"],
                "name": template["name"],
                "description": template.get("description"),
                "kind": template.get("kind", "nurture"),
                "role": template.get("role", "primary"),
                "triggerSegment": template.get("trigger_segment"),
                "layerFlag": template.get("layer_flag"),
                "runOnce": bool(template.get("run_once")),
                "exitDay": template.get("exit_day"),
                "exitRule": template.get("exit_rule"),
                "sourceUrl": template.get("source_url"),
                "stepCount": len(steps),
                "days": sorted({int(s["day"]) for s in steps}),
                "channels": sorted({s["channel"] for s in steps}),
                "installed": installed.get(template["slug"], []),
            }
        )
    return out


def install_template(conn, slug: str, *, as_copy: bool = False) -> dict[str, Any]:
    template = _templates.campaign_by_slug(slug)
    if template is None:
        raise ValueError(f"template {slug!r} not found")
    existing = conn.execute(
        "SELECT id FROM drip_campaigns WHERE template_slug=? ORDER BY created_at LIMIT 1", (slug,)
    ).fetchone()
    if existing and not as_copy:
        return get_campaign(conn, existing["id"])  # type: ignore[return-value]
    name = template["name"] if not existing else f"{template['name']} (Elevation copy)"
    campaign_id = _insert_campaign_from_template(conn, template, slug=_unique_slug(conn, template["slug"]), name=name)
    if existing:
        # A second copy must not auto-start from the same segment as the first.
        conn.execute(
            "UPDATE drip_campaigns SET trigger_segment=NULL, layer_flag=NULL, enabled=0, template_slug=NULL WHERE id=?",
            (campaign_id,),
        )
    return get_campaign(conn, campaign_id)  # type: ignore[return-value]


def reset_campaign_to_template(conn, campaign_id: str) -> dict[str, Any]:
    """Put a campaign's copy, timing and settings back to the Elevation original.

    Live enrollments keep running: their remaining schedule is rebuilt from
    the reset steps (touches whose day already passed are left alone).
    """
    row = _campaign_row(conn, campaign_id)
    if not row:
        raise ValueError(f"campaign {campaign_id!r} not found")
    template = _templates.campaign_by_slug(row["template_slug"] or "")
    if template is None:
        raise ValueError("this campaign was not built from an Elevation template")
    now = now_iso()
    conn.execute(
        """
        UPDATE drip_campaigns SET name=?, description=?, kind=?, role=?, trigger_segment=?, layer_flag=?,
            defer_layers=?, run_once=?, source_url=?, exit_day=?, exit_rule=?, notes=?, updated_at=?
        WHERE id=?
        """,
        (
            template["name"], template.get("description"), template.get("kind", "nurture"), template.get("role", "primary"),
            template.get("trigger_segment"), template.get("layer_flag"), 1 if template.get("defer_layers") else 0,
            1 if template.get("run_once") else 0, template.get("source_url"), template.get("exit_day"),
            template.get("exit_rule"), template.get("notes"), now, campaign_id,
        ),
    )
    conn.execute("DELETE FROM drip_steps WHERE campaign_id=?", (campaign_id,))
    for order, step in enumerate(template.get("steps", [])):
        step_id = new_id()
        conn.execute(
            """
            INSERT INTO drip_steps (id, campaign_id, day, sort_order, channel, title, subject, body, video_slot, notes, route_to, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                step_id, campaign_id, int(step["day"]), order * 10, step["channel"], step["title"], step.get("subject"),
                step.get("body"), step.get("video"), step.get("notes"), step.get("route_to"), now, now,
            ),
        )
        _materialize_step_for_live_enrollments(conn, campaign_id, step_id, int(step["day"]))
    return get_campaign(conn, campaign_id)  # type: ignore[return-value]


# ─── Videos ────────────────────────────────────────────────────────────


def list_videos(conn) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM drip_videos ORDER BY sort_order, name").fetchall()
    return [_row_video(r) for r in rows]


def get_video(conn, slug: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM drip_videos WHERE slug=?", (slug,)).fetchone()
    return _row_video(row) if row else None


def create_video(conn, *, name: str, script: str | None = None, length_label: str | None = None, used_in: str | None = None) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("video name cannot be empty")
    base = slugify(name)
    slug = base
    n = 2
    while conn.execute("SELECT 1 FROM drip_videos WHERE slug=?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    row = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS m FROM drip_videos").fetchone()
    now = now_iso()
    conn.execute(
        """
        INSERT INTO drip_videos (slug, name, length_label, script, used_in, link, recorded_at, sort_order, builtin, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, 0, ?, ?)
        """,
        (slug, name, length_label, script, used_in, int(row["m"] or 0) + 10, now, now),
    )
    return get_video(conn, slug)  # type: ignore[return-value]


def update_video(conn, slug: str, **fields: Any) -> dict[str, Any]:
    if get_video(conn, slug) is None:
        raise ValueError(f"video {slug!r} not found")
    columns = {"name": "name", "script": "script", "lengthLabel": "length_label", "length_label": "length_label",
               "usedIn": "used_in", "used_in": "used_in", "link": "link", "recordedAt": "recorded_at", "recorded_at": "recorded_at"}
    sets: list[str] = []
    params: list[Any] = []
    for name, value in fields.items():
        if name not in columns:
            continue
        column = columns[name]
        if column == "name":
            if value is None:
                continue
            value = str(value).strip()
            if not value:
                raise ValueError("video name cannot be empty")
        elif isinstance(value, str) and not value.strip():
            value = None
        if column == "link" and value and not re.match(r"^https?://", value, re.IGNORECASE):
            raise ValueError("video link must start with http:// or https://")
        sets.append(f"{column}=?")
        params.append(value)
    if "link" in fields and fields.get("link") and "recordedAt" not in fields and "recorded_at" not in fields:
        sets.append("recorded_at=COALESCE(recorded_at, ?)")
        params.append(now_iso()[:10])
    if sets:
        sets.append("updated_at=?")
        params.append(now_iso())
        params.append(slug)
        conn.execute(f"UPDATE drip_videos SET {', '.join(sets)} WHERE slug=?", params)
    return get_video(conn, slug)  # type: ignore[return-value]


def delete_video(conn, slug: str) -> bool:
    row = conn.execute("SELECT builtin FROM drip_videos WHERE slug=?", (slug,)).fetchone()
    if not row:
        return False
    conn.execute("UPDATE drip_steps SET video_slot=NULL WHERE video_slot=?", (slug,))
    conn.execute("DELETE FROM drip_videos WHERE slug=?", (slug,))
    return True


# ─── Contacts ──────────────────────────────────────────────────────────


def _contact_row(conn, contact_id: str):
    return conn.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()


def search_contacts(conn, query: str | None = None, *, limit: int = 25, segment: str | None = None) -> list[dict[str, Any]]:
    q = (query or "").strip()
    sql = "SELECT c.*, s.segment_key, s.buying AS seg_buying, s.selling AS seg_selling FROM contacts c LEFT JOIN drip_contact_segments s ON s.contact_id = c.id WHERE 1=1"
    params: list[Any] = []
    if q:
        like = f"%{q}%"
        sql += " AND (c.display_name ILIKE ? OR c.primary_email ILIKE ? OR c.primary_phone ILIKE ?)"
        params.extend([like, like, like])
    if segment:
        sql += " AND s.segment_key = ?"
        params.append(segment)
    sql += " ORDER BY c.display_name NULLS LAST, c.created_at DESC LIMIT ?"
    params.append(max(1, min(200, int(limit))))
    out = []
    for row in conn.execute(sql, params).fetchall():
        contact = _row_contact(row)
        if contact["hidden"]:
            continue
        contact["segment"] = row["segment_key"]
        contact["buying"] = bool(row["seg_buying"] or 0)
        contact["selling"] = bool(row["seg_selling"] or 0)
        out.append(contact)
    return out


def contact_drip_state(conn, contact_id: str) -> dict[str, Any] | None:
    row = _contact_row(conn, contact_id)
    if not row:
        return None
    contact = _row_contact(row)
    seg = conn.execute("SELECT * FROM drip_contact_segments WHERE contact_id=?", (contact_id,)).fetchone()
    contact["segment"] = seg["segment_key"] if seg else None
    contact["segmentSetAt"] = seg["set_at"] if seg else None
    contact["segmentSetBy"] = seg["set_by"] if seg else None
    contact["segmentNote"] = seg["note"] if seg else None
    contact["buying"] = bool(seg["buying"]) if seg else False
    contact["selling"] = bool(seg["selling"]) if seg else False
    contact["enrollments"] = list_enrollments(conn, contact_id=contact_id)
    return contact


def set_contact_segment(
    conn,
    contact_id: str,
    segment_key: str | None,
    *,
    actor: str,
    note: str | None = None,
    buying: bool | None = None,
    selling: bool | None = None,
    start_date: date | str | None = None,
) -> dict[str, Any]:
    """Move a contact into a segment and apply the layering rules.

    * The segment move ends every live primary campaign that does not start
      from the new segment, then starts the enabled primary campaign(s) that
      do, the same day.
    * Buying / selling flags layer the courses (run once per person) unless
      the segment's primary campaign defers layers (The First 14 Days).
    * ``segment_key=None`` clears the segment and stops every live campaign.
    """
    if _contact_row(conn, contact_id) is None:
        raise ValueError(f"contact {contact_id!r} not found")
    today = _as_date(start_date)
    prev = conn.execute("SELECT * FROM drip_contact_segments WHERE contact_id=?", (contact_id,)).fetchone()
    now = now_iso()
    result: dict[str, Any] = {"stopped": [], "started": [], "skipped": []}

    if segment_key is None:
        conn.execute("DELETE FROM drip_contact_segments WHERE contact_id=?", (contact_id,))
        for enrollment in conn.execute(
            "SELECT id FROM drip_enrollments WHERE contact_id=? AND status IN ('active','paused')", (contact_id,)
        ).fetchall():
            _finish_enrollment(conn, enrollment["id"], status="stopped", reason="segment cleared")
            result["stopped"].append(enrollment["id"])
        _note_contact(conn, contact_id, "Drips: removed from every campaign" + (f" ({note})" if note else ""), actor=actor)
        state = contact_drip_state(conn, contact_id) or {}
        state.update(result)
        return state

    segment = get_segment(conn, segment_key)
    if segment is None:
        raise ValueError(f"segment {segment_key!r} not found")
    if not segment["enabled"]:
        raise ValueError(f"segment {segment['label']!r} is switched off")

    buying_flag = (bool(prev["buying"]) if prev else False) if buying is None else bool(buying)
    selling_flag = (bool(prev["selling"]) if prev else False) if selling is None else bool(selling)
    changed = prev is None or prev["segment_key"] != segment_key

    conn.execute(
        """
        INSERT INTO drip_contact_segments (contact_id, segment_key, set_at, set_by, note, buying, selling)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (contact_id) DO UPDATE SET segment_key=EXCLUDED.segment_key, set_at=EXCLUDED.set_at,
            set_by=EXCLUDED.set_by, note=EXCLUDED.note, buying=EXCLUDED.buying, selling=EXCLUDED.selling
        """,
        (contact_id, segment_key, now, actor, note, 1 if buying_flag else 0, 1 if selling_flag else 0),
    )

    if changed:
        for enrollment in conn.execute(
            """
            SELECT e.id, c.trigger_segment FROM drip_enrollments e
            JOIN drip_campaigns c ON c.id = e.campaign_id
            WHERE e.contact_id=? AND e.status IN ('active','paused') AND c.role='primary'
            """,
            (contact_id,),
        ).fetchall():
            if enrollment["trigger_segment"] != segment_key:
                _finish_enrollment(conn, enrollment["id"], status="stopped", reason=f"moved to {segment['label']}")
                result["stopped"].append(enrollment["id"])
        for campaign in conn.execute(
            "SELECT id, name FROM drip_campaigns WHERE trigger_segment=? AND enabled=1 AND role='primary' ORDER BY name",
            (segment_key,),
        ).fetchall():
            enrollment = _enroll(conn, campaign["id"], contact_id, start=today, actor=actor)
            if enrollment.get("created"):
                result["started"].append({"campaignId": campaign["id"], "campaignName": campaign["name"], "enrollmentId": enrollment["id"]})

    defer = conn.execute(
        "SELECT 1 FROM drip_campaigns WHERE trigger_segment=? AND enabled=1 AND role='primary' AND defer_layers=1 LIMIT 1",
        (segment_key,),
    ).fetchone()
    if not defer:
        for flag, on in (("buying", buying_flag), ("selling", selling_flag)):
            if not on:
                continue
            for campaign in conn.execute(
                "SELECT id, name FROM drip_campaigns WHERE layer_flag=? AND enabled=1 AND role='layer' ORDER BY name",
                (flag,),
            ).fetchall():
                try:
                    enrollment = _enroll(conn, campaign["id"], contact_id, start=today, actor=actor)
                except ValueError as exc:
                    result["skipped"].append({"campaignName": campaign["name"], "reason": str(exc)})
                    continue
                if enrollment.get("created"):
                    result["started"].append({"campaignId": campaign["id"], "campaignName": campaign["name"], "enrollmentId": enrollment["id"]})

    if changed:
        label = segment["label"]
        text = f"Drips: moved to {label}"
        if note:
            text += f" ({note})"
        if result["started"]:
            text += ". Started " + ", ".join(s["campaignName"] for s in result["started"])
        _note_contact(conn, contact_id, text, actor=actor)
    elif result["started"]:
        _note_contact(conn, contact_id, "Drips: started " + ", ".join(s["campaignName"] for s in result["started"]), actor=actor)

    state = contact_drip_state(conn, contact_id) or {}
    state.update(result)
    return state


def _note_contact(conn, contact_id: str, text: str, *, actor: str) -> None:
    try:
        from elevate_cli.data.contacts import add_contact_note

        add_contact_note(conn, contact_id, text, actor=actor)
    except Exception:  # pragma: no cover - notes are best-effort
        _LOG.debug("drips: could not add contact note", exc_info=True)


# ─── Enrollments + touches ─────────────────────────────────────────────


def list_enrollments(conn, *, campaign_id: str | None = None, contact_id: str | None = None, live_only: bool = False) -> list[dict[str, Any]]:
    sql = """
        SELECT e.*, c.name AS campaign_name, co.display_name,
               (SELECT COUNT(*) FROM drip_touches t WHERE t.enrollment_id = e.id AND t.status='scheduled') AS scheduled_count,
               (SELECT COUNT(*) FROM drip_touches t WHERE t.enrollment_id = e.id AND t.status='done') AS done_count,
               (SELECT MIN(t.due_date) FROM drip_touches t WHERE t.enrollment_id = e.id AND t.status='scheduled') AS next_due
        FROM drip_enrollments e
        JOIN drip_campaigns c ON c.id = e.campaign_id
        LEFT JOIN contacts co ON co.id = e.contact_id
        WHERE 1=1
    """
    params: list[Any] = []
    if campaign_id:
        sql += " AND e.campaign_id=?"
        params.append(campaign_id)
    if contact_id:
        sql += " AND e.contact_id=?"
        params.append(contact_id)
    if live_only:
        sql += " AND e.status IN ('active','paused')"
    sql += " ORDER BY CASE e.status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END, e.created_at DESC LIMIT 500"
    return [_row_enrollment(r) for r in conn.execute(sql, params).fetchall()]


def get_enrollment(conn, enrollment_id: str) -> dict[str, Any] | None:
    rows = conn.execute(
        """
        SELECT e.*, c.name AS campaign_name, co.display_name
        FROM drip_enrollments e JOIN drip_campaigns c ON c.id=e.campaign_id
        LEFT JOIN contacts co ON co.id = e.contact_id WHERE e.id=?
        """,
        (enrollment_id,),
    ).fetchone()
    if not rows:
        return None
    enrollment = _row_enrollment(rows)
    enrollment["touches"] = [
        _touch_summary(r)
        for r in conn.execute(
            """
            SELECT t.*, s.day, s.channel, s.title FROM drip_touches t JOIN drip_steps s ON s.id=t.step_id
            WHERE t.enrollment_id=? ORDER BY t.due_date, s.sort_order
            """,
            (enrollment_id,),
        ).fetchall()
    ]
    return enrollment


def _touch_summary(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "stepId": row["step_id"],
        "day": int(row["day"]),
        "channel": row["channel"],
        "title": row["title"],
        "dueDate": row["due_date"],
        "status": row["status"],
        "doneAt": row["done_at"],
        "note": row["note"],
        "taskId": row["task_id"],
    }


def enroll_contact(conn, campaign_id: str, contact_id: str, *, actor: str, start_date: date | str | None = None) -> dict[str, Any]:
    """Manually put a contact on a campaign (the segment is left as is)."""
    if _contact_row(conn, contact_id) is None:
        raise ValueError(f"contact {contact_id!r} not found")
    return _enroll(conn, campaign_id, contact_id, start=_as_date(start_date), actor=actor)


def _enroll(conn, campaign_id: str, contact_id: str, *, start: date, actor: str) -> dict[str, Any]:
    campaign = _campaign_row(conn, campaign_id)
    if campaign is None:
        raise ValueError(f"campaign {campaign_id!r} not found")
    if not campaign["enabled"]:
        raise ValueError(f"{campaign['name']} is switched off")
    live = conn.execute(
        "SELECT id FROM drip_enrollments WHERE campaign_id=? AND contact_id=? AND status IN ('active','paused')",
        (campaign_id, contact_id),
    ).fetchone()
    if live:
        existing = get_enrollment(conn, live["id"]) or {}
        existing["created"] = False
        return existing
    if campaign["run_once"]:
        done = conn.execute(
            "SELECT 1 FROM drip_enrollments WHERE campaign_id=? AND contact_id=? AND status='completed' LIMIT 1",
            (campaign_id, contact_id),
        ).fetchone()
        if done:
            raise ValueError(f"{campaign['name']} already ran for this contact (it runs once per person)")
    if campaign["role"] == "primary":
        # One nurture campaign at a time.
        for other in conn.execute(
            """
            SELECT e.id FROM drip_enrollments e JOIN drip_campaigns c ON c.id=e.campaign_id
            WHERE e.contact_id=? AND e.status IN ('active','paused') AND c.role='primary' AND e.campaign_id<>?
            """,
            (contact_id, campaign_id),
        ).fetchall():
            _finish_enrollment(conn, other["id"], status="stopped", reason=f"replaced by {campaign['name']}")
    now = now_iso()
    enrollment_id = new_id()
    conn.execute(
        """
        INSERT INTO drip_enrollments (id, campaign_id, contact_id, start_date, status, enrolled_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (enrollment_id, campaign_id, contact_id, start.isoformat(), actor, now, now),
    )
    _materialize(conn, enrollment_id, campaign_id, contact_id, start, avoid_clashes=campaign["role"] == "layer")
    enrollment = get_enrollment(conn, enrollment_id) or {}
    enrollment["created"] = True
    return enrollment


def _materialize(conn, enrollment_id: str, campaign_id: str, contact_id: str, start: date, *, avoid_clashes: bool) -> int:
    taken: set[str] = set()
    if avoid_clashes:
        for row in conn.execute(
            """
            SELECT t.due_date FROM drip_touches t
            JOIN drip_enrollments e ON e.id=t.enrollment_id
            JOIN drip_steps s ON s.id=t.step_id
            WHERE e.contact_id=? AND e.status IN ('active','paused') AND t.status='scheduled'
              AND s.channel IN ('text','email')
            """,
            (contact_id,),
        ).fetchall():
            taken.add(str(row["due_date"])[:10])
    now = now_iso()
    created = 0
    for step in conn.execute(
        "SELECT id, day, channel FROM drip_steps WHERE campaign_id=? ORDER BY day, sort_order", (campaign_id,)
    ).fetchall():
        due = start + timedelta(days=int(step["day"]) - 1)
        if avoid_clashes and step["channel"] in ("text", "email"):
            shifts = 0
            while due.isoformat() in taken and shifts < 7:
                due += timedelta(days=1)
                shifts += 1
            taken.add(due.isoformat())
        conn.execute(
            """
            INSERT INTO drip_touches (id, enrollment_id, step_id, due_date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'scheduled', ?, ?)
            """,
            (new_id(), enrollment_id, step["id"], due.isoformat(), now, now),
        )
        created += 1
    return created


def _finish_enrollment(conn, enrollment_id: str, *, status: str, reason: str | None = None) -> None:
    now = now_iso()
    conn.execute(
        "UPDATE drip_enrollments SET status=?, stop_reason=?, completed_at=?, updated_at=? WHERE id=?",
        (status, reason, now if status in ("completed", "stopped") else None, now, enrollment_id),
    )
    conn.execute(
        "UPDATE drip_touches SET status='cancelled', updated_at=? WHERE enrollment_id=? AND status='scheduled'",
        (now, enrollment_id),
    )


def pause_enrollment(conn, enrollment_id: str) -> dict[str, Any]:
    return _set_enrollment_status(conn, enrollment_id, "paused")


def resume_enrollment(conn, enrollment_id: str) -> dict[str, Any]:
    return _set_enrollment_status(conn, enrollment_id, "active")


def stop_enrollment(conn, enrollment_id: str, *, reason: str | None = None) -> dict[str, Any]:
    if get_enrollment(conn, enrollment_id) is None:
        raise ValueError(f"enrollment {enrollment_id!r} not found")
    _finish_enrollment(conn, enrollment_id, status="stopped", reason=reason or "stopped by hand")
    return get_enrollment(conn, enrollment_id)  # type: ignore[return-value]


def _set_enrollment_status(conn, enrollment_id: str, status: str) -> dict[str, Any]:
    current = get_enrollment(conn, enrollment_id)
    if current is None:
        raise ValueError(f"enrollment {enrollment_id!r} not found")
    if current["status"] not in LIVE_ENROLLMENT_STATUSES:
        raise ValueError("this run has already finished")
    conn.execute(
        "UPDATE drip_enrollments SET status=?, updated_at=? WHERE id=?", (status, now_iso(), enrollment_id)
    )
    return get_enrollment(conn, enrollment_id)  # type: ignore[return-value]


def complete_touch(conn, touch_id: str, *, status: str = "done", note: str | None = None) -> dict[str, Any]:
    if status not in ("done", "skipped"):
        raise ValueError("status must be done or skipped")
    row = conn.execute("SELECT * FROM drip_touches WHERE id=?", (touch_id,)).fetchone()
    if not row:
        raise ValueError(f"touch {touch_id!r} not found")
    now = now_iso()
    conn.execute(
        "UPDATE drip_touches SET status=?, done_at=?, note=?, updated_at=? WHERE id=?",
        (status, now, note, now, touch_id),
    )
    _complete_finished_enrollment(conn, row["enrollment_id"])
    full = conn.execute(
        "SELECT t.*, s.day, s.channel, s.title FROM drip_touches t JOIN drip_steps s ON s.id=t.step_id WHERE t.id=?",
        (touch_id,),
    ).fetchone()
    return _touch_summary(full)


def _complete_finished_enrollment(conn, enrollment_id: str) -> bool:
    remaining = conn.execute(
        "SELECT COUNT(*) AS n FROM drip_touches WHERE enrollment_id=? AND status='scheduled'", (enrollment_id,)
    ).fetchone()
    if int(remaining["n"] or 0):
        return False
    row = conn.execute("SELECT status FROM drip_enrollments WHERE id=?", (enrollment_id,)).fetchone()
    if not row or row["status"] not in LIVE_ENROLLMENT_STATUSES:
        return False
    now = now_iso()
    conn.execute(
        "UPDATE drip_enrollments SET status='completed', completed_at=?, updated_at=? WHERE id=?",
        (now, now, enrollment_id),
    )
    return True


# ─── Rendering ─────────────────────────────────────────────────────────


def _identity(conn) -> dict[str, str]:
    try:
        from elevate_cli.outreach_db import _realtor_identity

        return _realtor_identity(conn)
    except Exception:
        return {"agent_name": "", "brokerage": ""}


def render_text(
    text: str | None,
    *,
    first_name: str | None = None,
    agent_name: str | None = None,
    brokerage: str | None = None,
    phone: str | None = None,
    video_link: str | None = None,
) -> dict[str, Any]:
    """Fill the placeholders the system knows and report the ones left over."""
    body = text or ""
    if first_name:
        body = re.sub(r"\[First Name\]", first_name, body, flags=re.IGNORECASE)
    if agent_name:
        body = re.sub(r"\[Your Name\]", agent_name, body, flags=re.IGNORECASE)
    if brokerage:
        body = re.sub(r"\[Brokerage\]", brokerage, body, flags=re.IGNORECASE)
    if phone:
        body = re.sub(r"\[Phone Number\]", phone, body, flags=re.IGNORECASE)
    video_missing = False
    if _VIDEO_SLOT_RE.search(body):
        if video_link:
            body = _VIDEO_SLOT_RE.sub(video_link, body)
        else:
            video_missing = True
    placeholders = sorted({m.group(0) for m in _PLACEHOLDER_RE.finditer(body) if not m.group(0).lower().startswith("[insert video")})
    return {"text": body, "placeholders": placeholders, "videoMissing": video_missing}


def _first_name(display_name: str | None) -> str | None:
    name = (display_name or "").strip()
    if not name:
        return None
    first = name.split()[0]
    return first.strip(",;:") or None


# ─── Due board ─────────────────────────────────────────────────────────


def due_board(conn, *, today: date | str | None = None, horizon_days: int = 7) -> dict[str, Any]:
    day = _as_date(today)
    horizon = day + timedelta(days=max(0, int(horizon_days)))
    identity = _identity(conn)
    videos = {v["slug"]: v for v in list_videos(conn)}
    rows = conn.execute(
        """
        SELECT t.id AS touch_id, t.due_date, t.status AS touch_status, t.task_id,
               s.id AS step_id, s.day, s.channel, s.title, s.subject, s.body, s.video_slot, s.notes AS step_notes, s.route_to,
               e.id AS enrollment_id, e.contact_id, e.start_date,
               c.id AS campaign_id, c.name AS campaign_name, c.kind, c.trigger_segment,
               co.display_name, co.primary_email, co.primary_phone,
               seg.segment_key
        FROM drip_touches t
        JOIN drip_steps s ON s.id = t.step_id
        JOIN drip_enrollments e ON e.id = t.enrollment_id
        JOIN drip_campaigns c ON c.id = e.campaign_id
        LEFT JOIN contacts co ON co.id = e.contact_id
        LEFT JOIN drip_contact_segments seg ON seg.contact_id = e.contact_id
        WHERE t.status='scheduled' AND e.status='active' AND c.enabled=1 AND t.due_date <= ?
        ORDER BY t.due_date, s.day, s.sort_order, co.display_name
        """,
        (horizon.isoformat(),),
    ).fetchall()
    overdue: list[dict[str, Any]] = []
    today_items: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    for row in rows:
        due = _as_date(row["due_date"])
        video = videos.get(row["video_slot"]) if row["video_slot"] else None
        link = video["link"] if video else None
        first = _first_name(row["display_name"])
        rendered_body = render_text(
            row["body"], first_name=first, agent_name=identity.get("agent_name"), brokerage=identity.get("brokerage"),
            phone=row["primary_phone"], video_link=link,
        )
        rendered_subject = render_text(
            row["subject"], first_name=first, agent_name=identity.get("agent_name"), brokerage=identity.get("brokerage"),
        )
        item = {
            "id": row["touch_id"],
            "dueDate": due.isoformat(),
            "daysLate": (day - due).days,
            "day": int(row["day"]),
            "channel": row["channel"],
            "title": row["title"],
            "subject": rendered_subject["text"] or None,
            "body": rendered_body["text"],
            "placeholders": sorted(set(rendered_body["placeholders"]) | set(rendered_subject["placeholders"])),
            "video": {"slug": video["slug"], "name": video["name"], "link": link} if video else None,
            "videoMissing": rendered_body["videoMissing"],
            "notes": row["step_notes"],
            "routeTo": row["route_to"],
            "taskId": row["task_id"],
            "stepId": row["step_id"],
            "enrollmentId": row["enrollment_id"],
            "campaignId": row["campaign_id"],
            "campaignName": row["campaign_name"],
            "campaignKind": row["kind"],
            "contact": {
                "id": row["contact_id"],
                "name": row["display_name"] or "(no name)",
                "firstName": first,
                "email": row["primary_email"],
                "phone": row["primary_phone"],
                "segment": row["segment_key"],
            },
        }
        if due < day:
            overdue.append(item)
        elif due == day:
            today_items.append(item)
        else:
            upcoming.append(item)
    return {
        "date": day.isoformat(),
        "overdue": overdue,
        "today": today_items,
        "upcoming": upcoming,
        "counts": {"overdue": len(overdue), "today": len(today_items), "upcoming": len(upcoming)},
    }


# ─── Engine ────────────────────────────────────────────────────────────


def run_engine(conn, *, today: date | str | None = None, actor: str = ACTOR_AUTO) -> dict[str, Any]:
    """Advance every live run: automatic tag moves, finished runs, call tasks, auto-enrolment."""
    day = _as_date(today)
    settings = get_settings(conn)
    summary: dict[str, Any] = {"date": day.isoformat(), "autoEnrolled": 0, "routed": [], "restarted": 0, "completed": 0, "tasksCreated": 0, "errors": []}

    if settings.get("autoEnrollNewLeads"):
        summary["autoEnrolled"] = _auto_enroll_new_leads(conn, settings, day, actor=actor)

    rows = conn.execute(
        """
        SELECT t.id AS touch_id, t.enrollment_id, e.contact_id, e.campaign_id, s.route_to, s.day, s.title,
               c.trigger_segment, c.name AS campaign_name, seg.segment_key
        FROM drip_touches t
        JOIN drip_steps s ON s.id = t.step_id
        JOIN drip_enrollments e ON e.id = t.enrollment_id
        JOIN drip_campaigns c ON c.id = e.campaign_id
        LEFT JOIN drip_contact_segments seg ON seg.contact_id = e.contact_id
        WHERE t.status='scheduled' AND s.channel='tag' AND e.status='active' AND c.enabled=1 AND t.due_date <= ?
        ORDER BY t.due_date
        """,
        (day.isoformat(),),
    ).fetchall()
    now = now_iso()
    for row in rows:
        route = row["route_to"]
        touch_id = row["touch_id"]
        try:
            if route == "done":
                conn.execute("UPDATE drip_touches SET status='done', done_at=?, updated_at=? WHERE id=?", (now, now, touch_id))
                _finish_enrollment(conn, row["enrollment_id"], status="completed", reason="course finished")
                summary["completed"] += 1
            elif route == "restart":
                conn.execute("UPDATE drip_touches SET status='done', done_at=?, updated_at=? WHERE id=?", (now, now, touch_id))
                _finish_enrollment(conn, row["enrollment_id"], status="completed", reason="rhythm finished, restarting")
                still_there = row["trigger_segment"] is None or row["segment_key"] == row["trigger_segment"]
                if still_there:
                    _enroll(conn, row["campaign_id"], row["contact_id"], start=day, actor=actor)
                    summary["restarted"] += 1
            elif route and settings.get("autoTagMoves"):
                if row["segment_key"] == row["trigger_segment"] or row["trigger_segment"] is None:
                    conn.execute("UPDATE drip_touches SET status='done', done_at=?, updated_at=? WHERE id=?", (now, now, touch_id))
                    label = (get_segment(conn, route) or {}).get("label", route)
                    set_contact_segment(
                        conn, row["contact_id"], route, actor=actor, start_date=day,
                        note=f"{row['campaign_name']} day {row['day']}: automatic move",
                    )
                    summary["routed"].append({"contactId": row["contact_id"], "to": route, "toLabel": label, "campaignName": row["campaign_name"]})
                else:
                    conn.execute(
                        "UPDATE drip_touches SET status='skipped', done_at=?, note=?, updated_at=? WHERE id=?",
                        (now, "contact had already moved segment", now, touch_id),
                    )
            # route without autoTagMoves: leave the touch on the board for a manual decision.
        except Exception as exc:  # keep the loop going; report per touch
            summary["errors"].append({"touchId": touch_id, "error": str(exc)})
            _LOG.exception("drips: engine step failed for touch %s", touch_id)

    for enrollment in conn.execute(
        """
        SELECT e.id FROM drip_enrollments e
        WHERE e.status='active'
          AND NOT EXISTS (SELECT 1 FROM drip_touches t WHERE t.enrollment_id=e.id AND t.status='scheduled')
          AND EXISTS (SELECT 1 FROM drip_touches t WHERE t.enrollment_id=e.id)
        """
    ).fetchall():
        if _complete_finished_enrollment(conn, enrollment["id"]):
            summary["completed"] += 1

    if settings.get("callsAsTasks"):
        summary["tasksCreated"] = _calls_to_tasks(conn, day, actor=actor)
    return summary


def _auto_enroll_new_leads(conn, settings: dict[str, Any], day: date, *, actor: str) -> int:
    since = settings.get("autoEnrollSince")
    if not since:
        return 0
    rows = conn.execute(
        """
        SELECT c.* FROM contacts c
        LEFT JOIN drip_contact_segments s ON s.contact_id = c.id
        WHERE s.contact_id IS NULL AND c.created_at >= ? AND c.type IN ('buyer','listing')
        ORDER BY c.created_at LIMIT 200
        """,
        (since,),
    ).fetchall()
    count = 0
    for row in rows:
        contact = _row_contact(row)
        if contact["hidden"] or contact["unsubscribed"]:
            continue
        try:
            set_contact_segment(
                conn, contact["id"], "new", actor=actor, start_date=day, note="new lead, auto-enrolled",
                buying=contact["type"] == "buyer", selling=contact["type"] == "listing",
            )
            count += 1
        except ValueError:
            continue
    return count


def _calls_to_tasks(conn, day: date, *, actor: str) -> int:
    try:
        from elevate_cli.data.surface_tasks import create_task
    except Exception:  # pragma: no cover - tasks module missing in a trimmed install
        return 0
    rows = conn.execute(
        """
        SELECT t.id AS touch_id, s.title, s.body, s.day, c.name AS campaign_name, co.display_name, co.primary_phone
        FROM drip_touches t
        JOIN drip_steps s ON s.id = t.step_id
        JOIN drip_enrollments e ON e.id = t.enrollment_id
        JOIN drip_campaigns c ON c.id = e.campaign_id
        LEFT JOIN contacts co ON co.id = e.contact_id
        WHERE t.status='scheduled' AND t.task_id IS NULL AND s.channel IN ('call','task')
          AND e.status='active' AND c.enabled=1 AND t.due_date <= ?
        """,
        (day.isoformat(),),
    ).fetchall()
    created = 0
    for row in rows:
        name = row["display_name"] or "(no name)"
        phone = f" · {row['primary_phone']}" if row["primary_phone"] else ""
        title = f"{row['title']}: {name}{phone}"
        description = f"{row['campaign_name']} · day {row['day']}\n\n{row['body'] or ''}".strip()
        try:
            task = create_task(
                conn,
                title=title[:200],
                description=description,
                type="human",
                priority="normal",
                project="drips",
                due_date=day.isoformat(),
                created_by=actor,
                # The schedule is the realtor's own; file the reminder as a human
                # action so the agent safety policy does not treat it as an agent run.
                actor=ACTOR_WEB,
                policy_action="drip_call_task",
                policy_category="task",
            )
        except Exception:
            _LOG.debug("drips: could not create call task", exc_info=True)
            continue
        conn.execute(
            "UPDATE drip_touches SET task_id=?, updated_at=? WHERE id=?",
            (task.get("id"), now_iso(), row["touch_id"]),
        )
        created += 1
    return created


# ─── Overview ──────────────────────────────────────────────────────────


def overview(conn, *, today: date | str | None = None) -> dict[str, Any]:
    day = _as_date(today)
    board = due_board(conn, today=day, horizon_days=7)
    videos = list_videos(conn)
    live = conn.execute(
        "SELECT COUNT(*) AS n FROM drip_enrollments WHERE status IN ('active','paused')"
    ).fetchone()
    contacts_in = conn.execute("SELECT COUNT(*) AS n FROM drip_contact_segments").fetchone()
    return {
        "date": day.isoformat(),
        "segments": list_segments(conn),
        "campaigns": list_campaigns(conn),
        "settings": get_settings(conn),
        "counts": {
            "dueToday": board["counts"]["today"],
            "overdue": board["counts"]["overdue"],
            "upcoming": board["counts"]["upcoming"],
            "liveEnrollments": int(live["n"] or 0),
            "contactsInSegments": int(contacts_in["n"] or 0),
            "videosRecorded": sum(1 for v in videos if v["link"]),
            "videosTotal": len(videos),
        },
    }


__all__ = [
    "ACTOR_AUTO",
    "ACTOR_WEB",
    "CHANNELS",
    "DEFAULT_SETTINGS",
    "KINDS",
    "ROLES",
    "add_step",
    "complete_touch",
    "connect",
    "contact_drip_state",
    "create_campaign",
    "create_segment",
    "create_video",
    "delete_campaign",
    "delete_segment",
    "delete_step",
    "delete_video",
    "due_board",
    "duplicate_campaign",
    "enroll_contact",
    "get_campaign",
    "get_enrollment",
    "get_segment",
    "get_settings",
    "get_video",
    "install_template",
    "list_campaigns",
    "list_enrollments",
    "list_segments",
    "list_steps",
    "list_templates",
    "list_videos",
    "maybe_seed",
    "overview",
    "pause_enrollment",
    "render_text",
    "reorder_segments",
    "reset_campaign_to_template",
    "resume_enrollment",
    "run_engine",
    "search_contacts",
    "seed_elevation_defaults",
    "set_campaign_enabled",
    "set_contact_segment",
    "slugify",
    "stop_enrollment",
    "update_campaign",
    "update_segment",
    "update_settings",
    "update_step",
    "update_video",
]
