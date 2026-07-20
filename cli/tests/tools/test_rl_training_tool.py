"""Tests for rl_training_tool.py effects, read-only inspection, and cleanup.

Verifies that _stop_training_run properly closes log file handles,
terminates processes, and handles edge cases on failure paths.
Inspired by PR #715 (0xbyt4).
"""

import asyncio
import json
import socket
from unittest.mock import MagicMock

import tools.rl_training_tool as rl_module
from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.registry import registry
from tools.rl_training_tool import RunState, _stop_training_run


PURE_RL_INSPECTORS = (
    "rl_list_environments",
    "rl_get_current_config",
    "rl_list_runs",
)

UNDECLARED_RL_TOOLS = (
    "rl_select_environment",
    "rl_edit_config",
    "rl_start_training",
    "rl_check_status",
    "rl_stop_training",
    "rl_test_inference",
)


def _tree_snapshot(root):
    return {
        str(path.relative_to(root)): (
            "directory" if path.is_dir() else "file",
            None if path.is_dir() else path.read_bytes(),
        )
        for path in sorted(root.rglob("*"))
    }


def test_pure_rl_inspectors_declare_exact_read_rl_effect():
    expected = frozenset({Effect.parse("read:rl")})

    for name in PURE_RL_INSPECTORS:
        entry = registry.get_entry(name)
        assert entry is not None
        assert entry.effects == expected
        assert entry.effect_resolver is None
        assert registry.get_effect_metadata(name) == {
            "declared": True,
            "effects": expected,
            "has_resolver": False,
        }
        assert registry.resolve_effects(name, {}) == expected


def test_pure_rl_inspectors_are_allowed_by_read_only_policy():
    expected = frozenset({Effect.parse("read:rl")})

    for name in PURE_RL_INSPECTORS:
        resolved = registry.resolve_effects(name, {})
        decision = authorize_effects(
            ExecutionPolicy.for_mode(
                f"turn-{name}",
                ExecutionPolicyMode.READ_ONLY,
            ),
            resolved,
        )

        assert resolved == expected
        assert decision.allowed is True
        assert decision.requested_effects == expected
        assert decision.denied_effects == frozenset()
        assert decision.reason == "allowed"


def test_pure_rl_inspectors_do_not_require_provider_keys(monkeypatch):
    monkeypatch.delenv("TINKER_API_KEY", raising=False)
    monkeypatch.delenv("WANDB_API_KEY", raising=False)

    for name in PURE_RL_INSPECTORS:
        entry = registry.get_entry(name)
        assert entry is not None
        assert entry.check_fn is rl_module.check_rl_python_version
        assert entry.requires_env == []
        assert entry.check_fn() == rl_module.check_rl_python_version()


def test_rl_list_environments_only_populates_ephemeral_cache(tmp_path, monkeypatch):
    environments_dir = tmp_path / "environments"
    environments_dir.mkdir()
    (environments_dir / "sample.py").write_text(
        "class BaseEnv:\n"
        "    pass\n\n"
        "class SampleEnv(BaseEnv):\n"
        "    \"\"\"Read-only sample environment.\"\"\"\n"
        "    name = \"sample\"\n",
        encoding="utf-8",
    )
    logs_dir = tmp_path / "logs" / "rl_training"
    before = _tree_snapshot(tmp_path)

    def unexpected_effect(*_args, **_kwargs):
        raise AssertionError("pure RL discovery attempted a non-read effect")

    monkeypatch.setattr(rl_module, "ENVIRONMENTS_DIR", environments_dir)
    monkeypatch.setattr(rl_module, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(rl_module, "_environments", [])
    monkeypatch.setattr(
        rl_module.importlib.util,
        "spec_from_file_location",
        unexpected_effect,
    )
    monkeypatch.setattr(rl_module.subprocess, "Popen", unexpected_effect)
    monkeypatch.setattr(socket, "create_connection", unexpected_effect)
    monkeypatch.setattr(socket.socket, "connect", unexpected_effect)

    result = json.loads(asyncio.run(rl_module.rl_list_environments()))

    assert result["count"] == 1
    assert result["environments"][0]["name"] == "sample"
    assert [environment.name for environment in rl_module._environments] == ["sample"]
    assert not logs_dir.exists()
    assert _tree_snapshot(tmp_path) == before


def test_networked_and_mutating_rl_inspectors_remain_unknown():
    unknown = frozenset({Effect(EffectKind.UNKNOWN)})

    for name in UNDECLARED_RL_TOOLS:
        entry = registry.get_entry(name)
        assert entry is not None
        assert entry.effects is None
        assert entry.effect_resolver is None
        assert registry.get_effect_metadata(name) == {
            "declared": False,
            "effects": unknown,
            "has_resolver": False,
        }

        resolved = registry.resolve_effects(name, {})
        decision = authorize_effects(
            ExecutionPolicy.for_mode(
                f"turn-{name}",
                ExecutionPolicyMode.READ_ONLY,
            ),
            resolved,
        )

        assert resolved == unknown
        assert decision.allowed is False
        assert decision.denied_effects == unknown
        assert decision.reason == "unknown_effect"


def test_rl_get_results_is_declared_via_resolver_only():
    entry = registry.get_entry("rl_get_results")
    assert entry is not None
    assert entry.effects is None
    assert entry.effect_resolver is rl_module._rl_get_results_effect_resolver
    assert registry.get_effect_metadata("rl_get_results") == {
        "declared": True,
        "effects": frozenset(),
        "has_resolver": True,
    }


def test_rl_get_results_resolves_to_read_rl_without_wandb_sdk(monkeypatch):
    monkeypatch.setattr(rl_module, "_WANDB_SDK_AVAILABLE", False)
    expected = frozenset({Effect.parse("read:rl")})

    resolved = registry.resolve_effects("rl_get_results", {"run_id": "any"})
    decision = authorize_effects(
        ExecutionPolicy.for_mode(
            "turn-rl_get_results",
            ExecutionPolicyMode.READ_ONLY,
        ),
        resolved,
    )

    assert resolved == expected
    assert decision.allowed is True
    assert decision.denied_effects == frozenset()
    assert decision.reason == "allowed"


def test_rl_get_results_fails_closed_to_unknown_with_wandb_sdk(monkeypatch):
    monkeypatch.setattr(rl_module, "_WANDB_SDK_AVAILABLE", True)
    unknown = frozenset({Effect(EffectKind.UNKNOWN)})

    resolved = registry.resolve_effects("rl_get_results", {"run_id": "any"})
    decision = authorize_effects(
        ExecutionPolicy.for_mode(
            "turn-rl_get_results",
            ExecutionPolicyMode.READ_ONLY,
        ),
        resolved,
    )

    assert resolved == unknown
    assert decision.allowed is False
    assert decision.denied_effects == unknown
    assert decision.reason == "unknown_effect"


def test_wandb_probe_is_process_stable(monkeypatch):
    monkeypatch.setattr(rl_module, "_WANDB_SDK_AVAILABLE", None)
    monkeypatch.setattr(
        rl_module.importlib.util, "find_spec", lambda _name: None
    )
    assert rl_module._wandb_sdk_available() is False

    # A later install (find_spec now succeeding) must NOT flip the snapshot:
    # the resolver classified calls with the first probe.
    monkeypatch.setattr(
        rl_module.importlib.util, "find_spec", lambda _name: object()
    )
    assert rl_module._wandb_sdk_available() is False
    assert registry.resolve_effects("rl_get_results", {"run_id": "r"}) == frozenset(
        {Effect.parse("read:rl")}
    )


def test_wandb_probe_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(rl_module, "_WANDB_SDK_AVAILABLE", None)

    def _boom(_name):
        raise RuntimeError("probe failure")

    monkeypatch.setattr(rl_module.importlib.util, "find_spec", _boom)
    assert rl_module._wandb_sdk_available() is True
    assert registry.resolve_effects("rl_get_results", {"run_id": "r"}) == frozenset(
        {Effect(EffectKind.UNKNOWN)}
    )


def test_rl_get_results_declared_read_never_reaches_wandb(
    tmp_path, monkeypatch
):
    """Adversarial: even with an importable wandb module at execute time, a
    call whose effects resolved to a pure read must never construct the SDK
    client, touch the network, or write the filesystem."""
    import sys
    import types

    monkeypatch.setattr(rl_module, "_WANDB_SDK_AVAILABLE", False)

    def unexpected_effect(*_args, **_kwargs):
        raise AssertionError("declared-read rl_get_results reached the W&B SDK")

    fake_wandb = types.ModuleType("wandb")
    fake_wandb.Api = unexpected_effect
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setattr(socket, "create_connection", unexpected_effect)
    monkeypatch.setattr(socket.socket, "connect", unexpected_effect)

    run_state = _make_run_state(run_id="declared-read-run")
    run_state.status = "completed"
    monkeypatch.setattr(
        rl_module, "_active_runs", {"declared-read-run": run_state}
    )

    before = _tree_snapshot(tmp_path)
    result = json.loads(
        asyncio.run(rl_module.rl_get_results(run_id="declared-read-run"))
    )

    assert result["run_id"] == "declared-read-run"
    assert result["status"] == "completed"
    assert result["wandb_error"] == "wandb SDK is not installed"
    assert "final_metrics" not in result
    assert _tree_snapshot(tmp_path) == before


def test_rl_get_results_missing_run_is_a_pure_error(monkeypatch):
    monkeypatch.setattr(rl_module, "_WANDB_SDK_AVAILABLE", False)
    monkeypatch.setattr(rl_module, "_active_runs", {})

    result = json.loads(asyncio.run(rl_module.rl_get_results(run_id="nope")))

    assert result["error"] == "Run 'nope' not found"


def _make_run_state(**overrides) -> RunState:
    """Create a minimal RunState for testing."""
    defaults = {
        "run_id": "test-run-001",
        "environment": "test_env",
        "config": {},
    }
    defaults.update(overrides)
    return RunState(**defaults)


class TestStopTrainingRunFileHandles:
    """Verify that _stop_training_run closes log file handles stored as attributes."""

    def test_closes_all_log_file_handles(self):
        state = _make_run_state()
        files = {}
        for attr in ("api_log_file", "trainer_log_file", "env_log_file"):
            fh = MagicMock()
            setattr(state, attr, fh)
            files[attr] = fh

        _stop_training_run(state)

        for attr, fh in files.items():
            fh.close.assert_called_once()
            assert getattr(state, attr) is None

    def test_clears_file_attrs_to_none(self):
        state = _make_run_state()
        state.api_log_file = MagicMock()

        _stop_training_run(state)

        assert state.api_log_file is None

    def test_close_exception_does_not_propagate(self):
        """If a file handle .close() raises, it must not crash."""
        state = _make_run_state()
        bad_fh = MagicMock()
        bad_fh.close.side_effect = OSError("already closed")
        good_fh = MagicMock()
        state.api_log_file = bad_fh
        state.trainer_log_file = good_fh

        _stop_training_run(state)  # should not raise

        bad_fh.close.assert_called_once()
        good_fh.close.assert_called_once()

    def test_handles_missing_file_attrs(self):
        """RunState without log file attrs should not crash."""
        state = _make_run_state()
        # No log file attrs set at all — getattr(..., None) should handle it
        _stop_training_run(state)  # should not raise


class TestStopTrainingRunProcesses:
    """Verify that _stop_training_run terminates processes correctly."""

    def test_terminates_running_processes(self):
        state = _make_run_state()
        for attr in ("api_process", "trainer_process", "env_process"):
            proc = MagicMock()
            proc.poll.return_value = None  # still running
            setattr(state, attr, proc)

        _stop_training_run(state)

        for attr in ("api_process", "trainer_process", "env_process"):
            getattr(state, attr).terminate.assert_called_once()

    def test_does_not_terminate_exited_processes(self):
        state = _make_run_state()
        proc = MagicMock()
        proc.poll.return_value = 0  # already exited
        state.api_process = proc

        _stop_training_run(state)

        proc.terminate.assert_not_called()

    def test_handles_none_processes(self):
        state = _make_run_state()
        # All process attrs are None by default
        _stop_training_run(state)  # should not raise

    def test_handles_mixed_running_and_exited_processes(self):
        state = _make_run_state()
        # api still running
        api = MagicMock()
        api.poll.return_value = None
        state.api_process = api
        # trainer already exited
        trainer = MagicMock()
        trainer.poll.return_value = 0
        state.trainer_process = trainer
        # env is None
        state.env_process = None

        _stop_training_run(state)

        api.terminate.assert_called_once()
        trainer.terminate.assert_not_called()


class TestStopTrainingRunStatus:
    """Verify status transitions in _stop_training_run."""

    def test_sets_status_to_stopped_when_running(self):
        state = _make_run_state(status="running")
        _stop_training_run(state)
        assert state.status == "stopped"

    def test_does_not_change_status_when_failed(self):
        state = _make_run_state(status="failed")
        _stop_training_run(state)
        assert state.status == "failed"

    def test_does_not_change_status_when_pending(self):
        state = _make_run_state(status="pending")
        _stop_training_run(state)
        assert state.status == "pending"

    def test_no_crash_with_no_processes_and_no_files(self):
        state = _make_run_state()
        _stop_training_run(state)  # should not raise
        assert state.status == "pending"
