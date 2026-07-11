"""Regression tests for truthful RL CLI terminal outcomes."""

import importlib

import pytest


def _configure_cli(monkeypatch, result):
    rl_cli = importlib.import_module("rl_cli")
    monkeypatch.setattr(
        rl_cli,
        "load_elevate_config",
        lambda: {"model": "test/model", "base_url": "https://example.test"},
    )
    monkeypatch.setattr(rl_cli, "check_requirements", lambda: True)

    class FakeAgent:
        def __init__(self, **_kwargs):
            pass

        def run_conversation(self, _task):
            if isinstance(result, BaseException):
                raise result
            return result

    monkeypatch.setattr(rl_cli, "AIAgent", FakeAgent)
    return rl_cli


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"final_response": "draft", "failed": True, "error": "model failed"}, "draft"),
        ({"final_response": "partial draft", "partial": True}, "partial draft"),
        ({"final_response": "partial draft", "interrupted": True}, "partial draft"),
        ({"final_response": "draft", "error": "provider timeout"}, "provider timeout"),
        ({"final_response": "draft", "completed": False}, "draft"),
    ],
)
def test_single_task_failure_exits_nonzero_without_success_banner(
    monkeypatch, capsys, result, expected,
):
    rl_cli = _configure_cli(monkeypatch, result)

    with pytest.raises(SystemExit) as exc_info:
        rl_cli.main(task="train", api_key="test-key")

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert "❌ Task failed" in output
    assert expected in output
    assert "✅ Task completed" not in output


def test_keyboard_interrupt_exits_130(monkeypatch, capsys):
    rl_cli = _configure_cli(monkeypatch, KeyboardInterrupt())

    with pytest.raises(SystemExit) as exc_info:
        rl_cli.main(task="train", api_key="test-key")

    assert exc_info.value.code == 130
    assert "Interrupted by user" in capsys.readouterr().out
