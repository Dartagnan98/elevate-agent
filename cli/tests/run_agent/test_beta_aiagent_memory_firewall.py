"""Realtor Beta rejects automatic memory inference before agent side effects."""

from __future__ import annotations

import subprocess
import threading
from unittest.mock import MagicMock

import pytest

import run_agent
from elevate_cli.beta_provider_policy import BetaProviderPolicyError


@pytest.mark.parametrize(
    ("memory_yaml", "code"),
    [
        (
            "memory:\n  provider: hindsight\n",
            "beta_memory_provider_not_allowed",
        ),
        (
            "memory:\n  provider: holographic\n"
            "plugins:\n"
            "  elevate-memory-store:\n"
            "    embedding_enabled: true\n",
            "beta_memory_embeddings_not_allowed",
        ),
    ],
)
def test_beta_stale_memory_config_fails_before_provider_or_runtime_side_effects(
    tmp_path,
    monkeypatch,
    memory_yaml,
    code,
):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "model:\n"
        "  provider: openai-codex\n"
        "  default: gpt-5.5\n"
        + memory_yaml,
        encoding="utf-8",
    )

    runtime_resolver = MagicMock()
    stdio_installer = MagicMock()
    tool_loader = MagicMock()
    memory_loader = MagicMock()
    primary_client = MagicMock()
    thread_constructor = MagicMock()
    process_constructor = MagicMock()
    process_runner = MagicMock()

    monkeypatch.setattr(
        "elevate_cli.runtime_provider.resolve_runtime_provider",
        runtime_resolver,
    )
    monkeypatch.setattr(run_agent, "_install_safe_stdio", stdio_installer)
    monkeypatch.setattr(run_agent, "get_tool_definitions", tool_loader)
    monkeypatch.setattr(run_agent, "OpenAI", primary_client)
    monkeypatch.setattr("plugins.memory.load_memory_provider", memory_loader)
    monkeypatch.setattr(threading, "Thread", thread_constructor)
    monkeypatch.setattr(subprocess, "Popen", process_constructor)
    monkeypatch.setattr(subprocess, "run", process_runner)

    with pytest.raises(BetaProviderPolicyError) as exc:
        run_agent.AIAgent(
            model="gpt-5.5",
            provider="openai-codex",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=False,
            persist_session=False,
        )

    assert exc.value.code == code
    runtime_resolver.assert_not_called()
    stdio_installer.assert_not_called()
    tool_loader.assert_not_called()
    memory_loader.assert_not_called()
    primary_client.assert_not_called()
    thread_constructor.assert_not_called()
    process_constructor.assert_not_called()
    process_runner.assert_not_called()
