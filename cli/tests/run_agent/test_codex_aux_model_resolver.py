"""The codex auxiliary model must track the user's active model, not a stale const.

A hardcoded _CODEX_AUX_MODEL ('gpt-5.2-codex') went stale against the rotating
ChatGPT-account allow-list and silently broke compaction (summary 400'd ->
context ballooned -> burned the plan quota). The resolver adopts the active
codex model so it can't drift out of the allow-list.
"""
from unittest.mock import patch

import agent.auxiliary_client as ac


def _cfg(provider, default):
    return {"model": {"provider": provider, "default": default}}


def test_adopts_active_model_when_primary_is_codex():
    with patch("elevate_cli.config.load_config", return_value=_cfg("openai-codex", "gpt-5.5")):
        assert ac._resolve_codex_aux_model() == "gpt-5.5"


def test_keeps_constant_when_primary_is_not_codex():
    # A non-codex primary model must NOT be sent to the codex endpoint.
    with patch("elevate_cli.config.load_config", return_value=_cfg("anthropic", "claude-opus-4")):
        assert ac._resolve_codex_aux_model() == ac._CODEX_AUX_MODEL


def test_falls_back_on_empty_or_broken_config():
    with patch("elevate_cli.config.load_config", return_value={}):
        assert ac._resolve_codex_aux_model() == ac._CODEX_AUX_MODEL
    with patch("elevate_cli.config.load_config", side_effect=RuntimeError("boom")):
        assert ac._resolve_codex_aux_model() == ac._CODEX_AUX_MODEL
