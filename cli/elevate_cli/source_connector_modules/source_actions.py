"""Source inbox profile state actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from elevate_cli.source_connector_modules.integration_settings import _as_dict
from elevate_cli.source_connector_modules.source_io import (
    PROFILE_STATUS_VALUES,
    _read_profile_state,
    _write_profile_state,
)


JsonRecord = dict[str, Any]


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


def update_profile_state(
    profile_id: str,
    status: str | None,
    config: dict[str, Any] | None = None,
    *,
    return_inbox: bool = True,
) -> JsonRecord:
    """Persist the operator-set pipeline status for a profile.

    Writes ``contacts.pipeline_status`` in the operational DB via
    :func:`set_pipeline_status` (migration 0014). Picking
    ``closed_seller`` / ``closed_buyer`` from the dropdown also calls
    :func:`close_to_admin` so the contact lands on /admin in the same
    transaction. By default returns the refreshed /leads response so legacy
    callers can rerender without a second fetch; HTTP routes pass
    ``return_inbox=False`` and build the DB-primary response once.

    Falls back to the legacy ``profile-state.json`` writer when the
    profile is not a contact UUID (e.g. composio thread-derived profiles
    that don't have a contacts row yet); the AI sweep eventually merges
    them, at which point the SQLite path takes over.
    """
    pid = str(profile_id or "").strip()
    if not pid:
        raise ValueError("profileId is required")
    normalized = str(status or "").strip().lower()
    if normalized == "none":
        normalized = ""
    if normalized and normalized not in PROFILE_STATUS_VALUES:
        raise ValueError(f"Unsupported profile status: {status}")

    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()

    # Primary path: write to contacts.pipeline_status in SQLite. The UI
    # passes the source-inbox profile id (e.g. "email:foo@bar.com" or
    # "phone:+15551234567") so we resolve to a contacts row by either UUID
    # or verifier match.
    try:
        from elevate_cli.data import connect, get_contact, set_pipeline_status
        with connect() as conn:
            contact_id: str | None = None
            if get_contact(conn, pid) is not None:
                contact_id = pid
            elif ":" in pid:
                kind, _, value = pid.partition(":")
                kind = kind.strip().lower()
                value = value.strip()
                if value:
                    if kind == "email":
                        row = conn.execute(
                            "SELECT id FROM contacts WHERE LOWER(primary_email) = LOWER(?) LIMIT 1",
                            (value,),
                        ).fetchone()
                    elif kind == "phone":
                        row = conn.execute(
                            "SELECT id FROM contacts WHERE primary_phone = ? LIMIT 1",
                            (value,),
                        ).fetchone()
                    else:
                        row = None
                    if row is not None:
                        contact_id = row["id"]
            if contact_id:
                set_pipeline_status(
                    conn,
                    contact_id,
                    status=normalized or None,
                    actor="operator:leads-ui",
                    set_by="operator",
                )
                return source_connectors.build_source_inbox_response(config) if return_inbox else {"ok": True}
    except ValueError:
        raise
    except Exception:
        # Fall through to the legacy JSON writer if the data module can't
        # accept this profile_id (e.g. composio thread profile without a
        # contacts row yet).
        pass

    info = source_connectors.get_source_root_info(config)
    source_root = Path(info["sourceRoot"])
    state = _read_profile_state(source_root)
    profiles = _as_dict(state.get("profiles"))
    if not normalized:
        profiles.pop(pid, None)
    else:
        profiles[pid] = {"status": normalized, "updated_at": source_connectors._now()}
    state["profiles"] = profiles
    _write_profile_state(source_root, state)
    return source_connectors.build_source_inbox_response(config) if return_inbox else {"ok": True}


def update_profile_favorite(
    profile_id: str,
    *,
    favorite: bool,
    contact_id: str | None = None,
    config: dict[str, Any] | None = None,
    return_inbox: bool = True,
) -> JsonRecord:
    """Persist the operator-set /leads favorite flag for a profile."""
    pid = str(profile_id or "").strip()
    if not pid:
        raise ValueError("profileId is required")

    from elevate_cli.data import connect, set_lead_profile_favorite

    with connect() as conn:
        set_lead_profile_favorite(
            conn,
            pid,
            favorite=bool(favorite),
            contact_id=contact_id,
            actor="operator:leads-ui",
        )
    source_connectors = _source_connectors()
    config = config or source_connectors.load_config()
    return source_connectors.build_source_inbox_response(config) if return_inbox else {"ok": True}
