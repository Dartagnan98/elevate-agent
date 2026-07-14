import json
import sqlite3

from elevate_cli.access import ENTITLEMENT_CORE
from elevate_cli.data.pack_onboarding import _ensure_seeded


def _contract_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE pack_onboarding_profiles (
            pack_id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            entitlement TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'missing',
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE pack_onboarding_items (
            pack_id TEXT NOT NULL,
            key TEXT NOT NULL,
            category TEXT NOT NULL,
            label TEXT NOT NULL,
            description TEXT,
            required INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'missing',
            provider TEXT,
            env_keys_json TEXT,
            value_json TEXT,
            notes TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (pack_id, key)
        );
        """
    )
    return conn


def test_pack_contract_refreshes_metadata_without_erasing_user_state():
    conn = _contract_db()
    _ensure_seeded(conn)
    conn.execute(
        """
        UPDATE pack_onboarding_items
        SET env_keys_json=?, status=?, provider=?, value_json=?, notes=?, updated_at=?
        WHERE pack_id=? AND key=?
        """,
        (
            '["TELEGRAM_BOT_TOKEN"]',
            "configured",
            "Telegram",
            '{"approved":true}',
            "kept user note",
            "2026-01-01T00:00:00Z",
            ENTITLEMENT_CORE,
            "messaging_gateway",
        ),
    )
    conn.execute(
        """
        INSERT INTO pack_onboarding_items(
            pack_id, key, category, label, description, required, status,
            provider, env_keys_json, value_json, notes, sort_order, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ENTITLEMENT_CORE,
            "retired_provider_picker",
            "model",
            "Retired provider picker",
            "No longer shipped.",
            0,
            "configured",
            "attacker-provider",
            '["ATTACKER_API_KEY"]',
            '{}',
            "stale contract row",
            999,
            "2026-01-01T00:00:00Z",
        ),
    )

    _ensure_seeded(conn)

    row = conn.execute(
        """
        SELECT env_keys_json, status, provider, value_json, notes, updated_at
        FROM pack_onboarding_items
        WHERE pack_id=? AND key=?
        """,
        (ENTITLEMENT_CORE, "messaging_gateway"),
    ).fetchone()
    assert row is not None
    env_keys = set(json.loads(row[0]))
    assert "TELEGRAM_BOT_TOKEN" in env_keys
    assert "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_BOT_TOKEN" in env_keys
    assert "ELEVATE_AGENT_EXECUTIVE_ASSISTANT_TELEGRAM_CHANNEL" in env_keys
    assert row[1:] == (
        "configured",
        "Telegram",
        '{"approved":true}',
        "kept user note",
        "2026-01-01T00:00:00Z",
    )
    assert conn.execute(
        "SELECT 1 FROM pack_onboarding_items WHERE pack_id=? AND key=?",
        (ENTITLEMENT_CORE, "retired_provider_picker"),
    ).fetchone() is None
