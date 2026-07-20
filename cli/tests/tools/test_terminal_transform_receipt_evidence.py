"""Terminal transform_terminal_output containment under durable receipts.

``0bbb80997``'s noted gap: the transform hook rewrites model-visible output
AFTER the terminal receipt bound its result identity.  Under an exact-Beta
approval-effect claim a rewrite now reaches the model only once its
pre/post digests are evidenced on the receipt
(``bind_approved_effect_transform``); an unevidenced rewrite is withheld
and the receipt-anchored original output is kept.  Without a claim
(Stable), the seam is byte-identical to the legacy behavior.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import elevate_cli.plugins as plugins_module
import tools.terminal_tool as terminal_module
from tools import approval


_COMMAND = "rm -rf /tmp/elevate-transform-test"


def _config(tmp_path):
    return {
        "env_type": "local",
        "timeout": 30,
        "cwd": str(tmp_path),
        "host_cwd": None,
        "modal_mode": "auto",
        "docker_image": "",
        "singularity_image": "",
        "modal_image": "",
        "daytona_image": "",
    }


class _RecordingTransformStore:
    def __init__(self, *, result: int):
        self._result = result
        self.calls = []

    def record_approval_effect_result_transform(self, **kwargs):
        self.calls.append(kwargs)
        return self._result


def _make_claim(store, effect_context):
    return approval.ApprovalEffectClaim(
        request_id="f" * 32,
        claim_id="e" * 32,
        boot_id="d" * 32,
        context=effect_context,
        store=store,
    )


def _effect_context(tool_args):
    policy = approval.ExecutionPolicy.for_mode("turn-transform", "default")
    return approval.ApprovalEffectContext(
        session_id="session-transform",
        invocation_id="call-transform",
        tool_name="terminal",
        canonical_args_digest=approval._approval_sha256(tool_args),
        accepted_policy=policy,
        policy_revision=0,
        declared_effects={"destructive"},
    )


def _install_beta_claimed_path(monkeypatch, tmp_path, store):
    tool_args = {"command": _COMMAND}
    effect_context = _effect_context(tool_args)
    claim = _make_claim(store, effect_context)
    env = SimpleNamespace(
        execute=lambda *_a, **_k: {"output": "real output", "returncode": 0},
        env={},
    )
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setattr(
        terminal_module, "_get_env_config", lambda: _config(tmp_path)
    )
    monkeypatch.setattr(terminal_module, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(
        terminal_module,
        "_check_all_guards",
        lambda *_args, **_kwargs: {
            "approved": True,
            "user_approved": True,
            "description": "dangerous test command",
            "_approval_effect_entry": object(),
        },
    )
    monkeypatch.setattr(
        approval, "claim_approved_effect", lambda *_a, **_k: claim
    )
    monkeypatch.setattr(
        approval, "complete_approved_effect_claim", lambda *_a, **_k: True
    )
    monkeypatch.setitem(terminal_module._active_environments, "default", env)
    monkeypatch.setitem(terminal_module._last_activity, "default", 0.0)
    return tool_args, effect_context


def _rewriting_hook(monkeypatch, rewritten: str):
    def fake_invoke_hook(hook_name, **kwargs):
        if hook_name == "transform_terminal_output":
            return [rewritten]
        return []

    monkeypatch.setattr(plugins_module, "invoke_hook", fake_invoke_hook)


def _invoke(tool_args, effect_context):
    return json.loads(
        terminal_module.terminal_tool(
            command=_COMMAND,
            _approval_effect_context=effect_context,
            _approval_tool_args=tool_args,
        )
    )


def test_evidenced_rewrite_reaches_the_model(monkeypatch, tmp_path):
    store = _RecordingTransformStore(result=1)
    tool_args, effect_context = _install_beta_claimed_path(
        monkeypatch, tmp_path, store
    )
    _rewriting_hook(monkeypatch, "rewritten output")

    result = _invoke(tool_args, effect_context)

    assert result["output"] == "rewritten output"
    assert result["exit_code"] == 0
    assert len(store.calls) == 1
    call = store.calls[0]
    assert call["claim_id"] == "e" * 32
    assert call["request_id"] == "f" * 32
    assert call["boot_id"] == "d" * 32
    assert call["transform_pre_digest"] == approval._approval_sha256(
        {"output": "real output"}
    )
    assert call["transform_post_digest"] == approval._approval_sha256(
        {"output": "rewritten output"}
    )


def test_unevidenced_rewrite_is_withheld(monkeypatch, tmp_path):
    store = _RecordingTransformStore(result=0)
    tool_args, effect_context = _install_beta_claimed_path(
        monkeypatch, tmp_path, store
    )
    _rewriting_hook(monkeypatch, "tampered output")

    result = _invoke(tool_args, effect_context)

    # The rewrite could not be bound to the receipt: the receipt-anchored
    # original output is kept and the recorded outcome stands.
    assert result["output"] == "real output"
    assert result["exit_code"] == 0
    assert len(store.calls) == 1


def test_identical_hook_output_needs_no_evidence(monkeypatch, tmp_path):
    store = _RecordingTransformStore(result=1)
    tool_args, effect_context = _install_beta_claimed_path(
        monkeypatch, tmp_path, store
    )
    _rewriting_hook(monkeypatch, "real output")

    result = _invoke(tool_args, effect_context)

    assert result["output"] == "real output"
    assert store.calls == []


def test_stable_seam_is_byte_identical_without_a_claim(monkeypatch, tmp_path):
    """Outside Beta (no claim) the legacy transform behavior is preserved
    exactly: the rewrite applies and no evidence store is consulted."""
    env = SimpleNamespace(
        execute=lambda *_a, **_k: {"output": "real output", "returncode": 0},
        env={},
    )
    monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    monkeypatch.setattr(
        terminal_module, "_get_env_config", lambda: _config(tmp_path)
    )
    monkeypatch.setattr(terminal_module, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(
        terminal_module,
        "_check_all_guards",
        lambda *_args, **_kwargs: {"approved": True},
    )
    monkeypatch.setitem(terminal_module._active_environments, "default", env)
    monkeypatch.setitem(terminal_module._last_activity, "default", 0.0)
    _rewriting_hook(monkeypatch, "rewritten output")

    result = json.loads(terminal_module.terminal_tool(command="echo hello"))

    assert result["output"] == "rewritten output"
    assert result["exit_code"] == 0
