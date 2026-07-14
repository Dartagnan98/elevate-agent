"""Regression tests for dashboard Telegram alias state."""

from importlib import reload

from elevate_cli import config as config_module
import elevate_cli.web_telegram_aliases as telegram_aliases


def test_duplicate_reader_recovers_after_import_under_temporary_env_patch(monkeypatch):
    """A setup probe must not freeze its temporary env reader into web routes."""
    token = "444444444:ADMINdddddddddddddddddddddd"
    key = "ELEVATE_AGENT_ADMIN_TELEGRAM_BOT_TOKEN"

    with monkeypatch.context() as temporary_patch:
        temporary_patch.setattr(
            config_module,
            "load_env",
            lambda: {"TELEGRAM_BOT_TOKEN": "123456:ABCDEFGHIJKLMNOPQRSTUVWX"},
        )
        aliases_imported_during_probe = reload(telegram_aliases)
        assert aliases_imported_during_probe._non_executive_duplicate_agent_token(token) == ""

    config_module.save_env_value(key, token)

    assert aliases_imported_during_probe._non_executive_duplicate_agent_token(token) == key
