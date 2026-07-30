"""The connector view must not call a populated source empty.

`connector_view` derived everything from JSONL on disk. Once
`_walk_jsonl_into_pg` migrates rows into Postgres the directory is emptied (or
never existed), so the Sources page read "NOT CONFIGURED · 0 RECORDS" for
apple-messages while the store held 1,190 conversations — and offered
"Initialize this source", which over real data is worse than merely wrong.
"""

from pathlib import Path

import pytest

from elevate_cli.data import connect, get_or_create_conversation, upsert_contact
from elevate_cli.data.connection import _reset_schema_cache
from elevate_cli.source_connector_modules import connector_views


@pytest.fixture(autouse=True)
def _fresh(_hermetic_environment):
    _reset_schema_cache()
    connector_views.reset_db_source_count_cache()
    yield
    connector_views.reset_db_source_count_cache()
    _reset_schema_cache()


def seed(source_id: str, n: int) -> None:
    with connect() as conn:
        for i in range(n):
            contact = upsert_contact(
                conn,
                display_name=f"Lead {source_id} {i}",
                source_key=f"{source_id}:seed-{i}",
            )
            get_or_create_conversation(
                conn,
                contact_id=contact["id"],
                source_id=source_id,
                channel="email",
                thread_key=f"{source_id}-thread-{i}",
            )


def test_blueprint_source_with_db_rows_and_no_disk_reads_connected(tmp_path: Path):
    seed("apple-messages", 3)
    connector_views.reset_db_source_count_cache()

    # No source dir at all — the harshest version of what was on the real box.
    view = connector_views.connector_view(tmp_path, "apple-messages")

    assert view is not None
    assert view["state"] == "connected", "a source with rows is configured"
    assert sum(view["recordCounts"].values()) >= 3


def test_composio_view_survives_an_emptied_directory(tmp_path: Path):
    seed("composio-gmail", 4)
    connector_views.reset_db_source_count_cache()

    view = connector_views._composio_connector_view(tmp_path, "composio-gmail")

    assert view is not None, "returning None here is what 404'd 639 threads"
    assert view["recordCounts"].get("conversations") == 4


def test_genuinely_empty_source_still_reads_not_configured(tmp_path: Path):
    connector_views.reset_db_source_count_cache()

    view = connector_views.connector_view(tmp_path, "sms-provider")

    assert view is not None
    assert view["state"] == "not_configured"
    assert sum(view["recordCounts"].values()) == 0


def test_disk_and_db_reconcile_to_the_larger_count(tmp_path: Path):
    """A stale directory must not shadow the store, nor vice versa."""
    seed("composio-instagram", 9)
    src = tmp_path / "composio-instagram"
    src.mkdir(parents=True)
    (src / "conversations.jsonl").write_text(
        "\n".join('{"id": "c%d"}' % i for i in range(2)) + "\n", encoding="utf-8"
    )
    connector_views.reset_db_source_count_cache()

    view = connector_views._composio_connector_view(tmp_path, "composio-instagram")

    assert view is not None
    assert view["recordCounts"]["conversations"] == 9, "9 in the DB beats 2 on disk"
