"""Agent dashboard status: untouched Telegram lanes are healthy.

Defaults ship "telegram" in platforms for every customer-facing agent, so
after an update the reconcile unions it into existing rosters. The old rule
flagged ANY agent without a fully-configured dedicated bot as
needs_telegram — painting whole rosters as "disconnected" (Justin's box,
2026-06-11) with nothing actually broken. Only a half-configured or
conflicting lane is a problem state.

Also covers the retired-agent bot-token migration: consolidation tombstones
an agent def, but its dedicated bot must keep answering as the absorber.
"""

from __future__ import annotations

from unittest.mock import patch

import elevate_cli.agent_hub as ah


class TestLaneNeedsAttention:
    def _lane(self, **kw):
        base = {
            "configured": False,
            "tokenConfigured": False,
            "targetConfigured": False,
            "usesSharedBot": False,
            "duplicateSharedBot": False,
        }
        base.update(kw)
        return base

    def test_untouched_lane_is_fine(self):
        assert ah._telegram_lane_needs_attention(self._lane()) is False

    def test_fully_configured_is_fine(self):
        assert ah._telegram_lane_needs_attention(
            self._lane(configured=True, tokenConfigured=True, targetConfigured=True)
        ) is False

    def test_token_without_target_flags(self):
        assert ah._telegram_lane_needs_attention(
            self._lane(tokenConfigured=True)
        ) is True

    def test_target_without_token_flags(self):
        assert ah._telegram_lane_needs_attention(
            self._lane(targetConfigured=True)
        ) is True

    def test_shared_bot_rider_is_fine(self):
        # Riding the shared bot intentionally (no dedicated token) — not a
        # problem state even with a target set.
        assert ah._telegram_lane_needs_attention(
            self._lane(usesSharedBot=True, targetConfigured=True)
        ) is False

    def test_duplicate_shared_bot_always_flags(self):
        # A specialist reusing the SHARED bot token = two pollers on one
        # bot — real conflict, surfaced even though usesSharedBot is True.
        assert ah._telegram_lane_needs_attention(
            self._lane(
                usesSharedBot=True,
                duplicateSharedBot=True,
                tokenConfigured=True,
                targetConfigured=True,
            )
        ) is True


class TestRetiredAgentBotMigration:
    def test_token_migrates_to_absorber(self):
        env = {"ELEVATE_AGENT_TRANSACTION_COORDINATOR_TELEGRAM_BOT_TOKEN": "123:abc"}
        saved = {}
        with patch("elevate_cli.config.load_env", return_value=env), patch(
            "elevate_cli.config.save_env_value",
            side_effect=lambda k, v: saved.__setitem__(k, v),
        ):
            assert ah._migrate_retired_agent_bot_token(
                "transaction-coordinator", "admin"
            ) is True
        assert saved == {"ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN": "123:abc"}

    def test_absorber_keeps_its_own_bot(self):
        env = {
            "ELEVATE_AGENT_ADS_TELEGRAM_BOT_TOKEN": "old:token",
            "ELEVATE_AGENT_MARKETING_TELEGRAM_BOT_TOKEN": "own:token",
        }
        saved = {}
        with patch("elevate_cli.config.load_env", return_value=env), patch(
            "elevate_cli.config.save_env_value",
            side_effect=lambda k, v: saved.__setitem__(k, v),
        ):
            assert ah._migrate_retired_agent_bot_token("ads", "marketing") is False
        assert saved == {}

    def test_no_token_is_noop(self):
        with patch("elevate_cli.config.load_env", return_value={}):
            assert ah._migrate_retired_agent_bot_token("ads", "marketing") is False

    def test_every_retired_id_has_an_absorber(self):
        assert set(ah._RETIRED_AGENT_IDS) == set(ah._RETIRED_AGENT_ABSORBERS)
        for absorber in ah._RETIRED_AGENT_ABSORBERS.values():
            assert any(d.get("id") == absorber for d in ah.DEFAULT_AGENT_DEFS)
