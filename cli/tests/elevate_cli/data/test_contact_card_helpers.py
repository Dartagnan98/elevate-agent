"""Data-module helpers behind the CRM contact card.

``set_contact_segments`` and ``update_contact_card_details`` exist so the
card's routes never hand-write the central ``contacts`` table (the
invariant pinned by ``test_data_module_isolation.py``). Postgres is the
primary read path, so a route-level UPDATE skips the data module and a
card edit can land inconsistently.
"""

from __future__ import annotations

import json

import pytest

from elevate_cli.data import connect, get_contact, upsert_contact
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.data.contacts import (
    set_contact_segments,
    update_contact_card_details,
)


@pytest.fixture(autouse=True)
def _fresh_schema_cache():
    _reset_schema_cache()
    yield
    _reset_schema_cache()


def _seed(conn, **overrides):
    return upsert_contact(
        conn,
        display_name=overrides.get("display_name", "Helper Lead"),
        primary_email=overrides.get("primary_email", "helper@example.com"),
        primary_phone=overrides.get("primary_phone", "+16045550200"),
        source_key=overrides.get("source_key", "lofty-default:helper-1"),
    )


# ─── set_contact_segments ──────────────────────────────────────────────


def test_set_contact_segments_writes_sorted_unique_stripped():
    with connect() as conn:
        contact = _seed(conn)
        result = set_contact_segments(
            conn, contact["id"], [" vip ", "past-client", "vip", "  ", ""]
        )
        assert result == ["past-client", "vip"]
        stored = get_contact(conn, contact["id"])
        assert json.loads(stored["segmentsJson"]) == ["past-client", "vip"]


def test_set_contact_segments_replaces_and_can_empty():
    with connect() as conn:
        contact = _seed(conn)
        set_contact_segments(conn, contact["id"], ["a", "b"])
        assert set_contact_segments(conn, contact["id"], []) == []
        stored = get_contact(conn, contact["id"])
        assert json.loads(stored["segmentsJson"]) == []


def test_set_contact_segments_bumps_updated_at():
    with connect() as conn:
        contact = _seed(conn)
        set_contact_segments(conn, contact["id"], ["a"])
        assert get_contact(conn, contact["id"])["updatedAt"] >= contact["updatedAt"]


def test_set_contact_segments_unknown_contact_raises():
    with connect() as conn:
        with pytest.raises(ValueError, match="not found"):
            set_contact_segments(conn, "nope", ["a"])


def test_set_contact_segments_leaves_tags_alone():
    with connect() as conn:
        contact = _seed(conn)
        from elevate_cli.data import set_contact_tags

        set_contact_tags(conn, contact["id"], ["keep-me"])
        set_contact_segments(conn, contact["id"], ["vip"])
        stored = get_contact(conn, contact["id"])
        assert json.loads(stored["tagsJson"]) == ["keep-me"]
        assert json.loads(stored["segmentsJson"]) == ["vip"]


# ─── update_contact_card_details ───────────────────────────────────────


def test_update_contact_card_details_writes_provided_columns():
    with connect() as conn:
        contact = _seed(conn, display_name="Before")
        out = update_contact_card_details(
            conn,
            contact["id"],
            {"display_name": "After", "buying_time_frame": "3-6 months"},
        )
        assert out["displayName"] == "After"
        assert out["buyingTimeFrame"] == "3-6 months"
        # Not provided => untouched.
        assert out["primaryEmail"] == contact["primaryEmail"]


def test_update_contact_card_details_writes_values_verbatim():
    """No strip/blank coercion — the card sends exactly what it wants stored."""
    with connect() as conn:
        contact = _seed(conn)
        out = update_contact_card_details(
            conn, contact["id"], {"display_name": "  Padded  "}
        )
        assert out["displayName"] == "  Padded  "


def test_update_contact_card_details_none_clears_the_column():
    with connect() as conn:
        contact = _seed(conn)
        update_contact_card_details(
            conn, contact["id"], {"pre_qual_status": "pre-approved"}
        )
        out = update_contact_card_details(
            conn, contact["id"], {"pre_qual_status": None}
        )
        assert out["preQualStatus"] is None


def test_update_contact_card_details_drops_unknown_columns():
    with connect() as conn:
        contact = _seed(conn)
        out = update_contact_card_details(
            conn,
            contact["id"],
            {"display_name": "Kept", "stage": "closed", "nonsense": 1},
        )
        assert out["displayName"] == "Kept"
        assert out["stage"] == contact["stage"]


def test_update_contact_card_details_empty_patch_is_a_noop():
    with connect() as conn:
        contact = _seed(conn)
        out = update_contact_card_details(conn, contact["id"], {})
        assert out == contact
        assert get_contact(conn, contact["id"])["updatedAt"] == contact["updatedAt"]


def test_update_contact_card_details_unknown_contact_raises():
    with connect() as conn:
        with pytest.raises(ValueError, match="not found"):
            update_contact_card_details(conn, "nope", {"display_name": "x"})
