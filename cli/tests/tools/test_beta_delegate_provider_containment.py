"""Exact Realtor Beta provider containment for delegated children.

All provider/auth boundaries are faked.  These tests never read a real profile,
refresh a live token, construct a network client, or call a provider.
"""

from __future__ import annotations

import json
import os
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from elevate_cli.beta_provider_policy import (
    BETA_ALLOWED_PROVIDER,
    BETA_CODEX_BASE_URL,
    canonical_beta_provider,
)
from tools import delegate_tool as delegate


def _parent() -> SimpleNamespace:
    return SimpleNamespace(
        provider=BETA_ALLOWED_PROVIDER,
        model="gpt-5.5",
        base_url=BETA_CODEX_BASE_URL,
        api_mode="codex_responses",
        # Hostile cached credentials/pool must never reach a Beta child.
        api_key="cached-parent-token",
        _client_kwargs={"api_key": "cached-client-token"},
        _credential_pool=object(),
        _fallback_chain=[],
        _fallback_model=None,
        providers_allowed=None,
        providers_ignored=None,
        providers_order=None,
        provider_sort=None,
        openrouter_min_coding_score=None,
        acp_command=None,
        acp_args=[],
        reasoning_config=None,
        prefill_messages=None,
        max_tokens=None,
        enabled_toolsets=[],
        valid_tool_names=set(),
        platform="cli",
        _session_db=None,
        session_id="parent-session",
        _delegate_depth=0,
        _active_children=[],
        _active_children_lock=threading.Lock(),
        _print_fn=None,
        clarify_callback=None,
        tool_progress_callback=None,
        _async_delegate_sink=None,
        _current_task_id=None,
        _interrupt_requested=False,
    )


def _install_fake_agent(monkeypatch, *, result=None):
    import run_agent

    calls = []
    children = []

    def _factory(**kwargs):
        child = MagicMock()
        child.provider = kwargs["provider"]
        child.model = kwargs["model"]
        child.base_url = kwargs["base_url"]
        child.api_mode = kwargs["api_mode"]
        child.api_key = kwargs["api_key"]
        child.acp_command = kwargs["acp_command"]
        child.acp_args = list(kwargs["acp_args"] or [])
        child._fallback_chain = list(kwargs["fallback_model"] or [])
        child._fallback_model = None
        child._credential_pool = None
        child.session_id = f"child-{len(children)}"
        child.session_estimated_cost_usd = 0.0
        child.session_prompt_tokens = 0
        child.session_completion_tokens = 0
        child.session_reasoning_tokens = 0
        child.tool_progress_callback = kwargs.get("tool_progress_callback")
        child.run_conversation.return_value = result or {
            "final_response": "done",
            "completed": True,
            "api_calls": 1,
            "messages": [],
        }
        child.get_activity_summary.return_value = {
            "api_call_count": 1,
            "current_tool": None,
            "max_iterations": 10,
        }
        calls.append(kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(run_agent, "AIAgent", _factory)
    return calls, children


def _install_beta_boundary(
    monkeypatch,
    tmp_path,
    *,
    config=None,
    delegation_config=None,
    auth_reader=None,
    runtime_resolver=None,
):
    from elevate_cli import beta_provider_policy, config as config_module
    from elevate_cli import runtime_provider

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    for key in (
        "ELEVATE_INFERENCE_PROVIDER",
        "ELEVATE_MODEL",
        "ELEVATE_CODEX_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    current_config = config or {
        "model": {
            "provider": BETA_ALLOWED_PROVIDER,
            "default": "gpt-5.5",
            "base_url": BETA_CODEX_BASE_URL,
            "api_mode": "codex_responses",
        }
    }
    monkeypatch.setattr(config_module, "load_config", lambda: current_config)
    monkeypatch.setattr(config_module, "get_elevate_home", lambda: tmp_path)
    monkeypatch.setattr(
        delegate,
        "_load_config",
        lambda: delegation_config or {},
    )

    if auth_reader is None:
        def auth_reader(_home):
            return {
                "logged_in": True,
                "source": "provider_state",
                "reason": None,
            }
    monkeypatch.setattr(
        beta_provider_policy,
        "read_beta_codex_auth_status",
        auth_reader,
    )

    calls = []
    if runtime_resolver is None:

        def runtime_resolver(**kwargs):
            calls.append(dict(kwargs))
            token = f"fresh-child-token-{len(calls)}"
            return {
                "provider": BETA_ALLOWED_PROVIDER,
                "requested_provider": BETA_ALLOWED_PROVIDER,
                "api_mode": "codex_responses",
                "base_url": BETA_CODEX_BASE_URL,
                "api_key": token,
                "source": "elevate-auth-store",
                "auth_store": str(tmp_path / "auth.json"),
            }

    else:
        supplied = runtime_resolver

        def runtime_resolver(**kwargs):
            calls.append(dict(kwargs))
            return supplied(**kwargs)

    monkeypatch.setattr(
        runtime_provider,
        "resolve_runtime_provider",
        runtime_resolver,
    )
    return calls


def test_parallel_beta_children_each_fresh_resolve_and_never_share_cached_auth(
    monkeypatch, tmp_path
):
    resolver_calls = _install_beta_boundary(monkeypatch, tmp_path)
    agent_calls, children = _install_fake_agent(monkeypatch)
    captured = {}

    def _capture(children_arg, *_args, **_kwargs):
        captured["children"] = list(children_arg)
        return {"results": [], "total_duration_seconds": 0.0}

    monkeypatch.setattr(delegate, "_execute_and_finalize_delegation", _capture)
    parent = _parent()

    payload = json.loads(
        delegate.delegate_task(
            tasks=[{"goal": "one"}, {"goal": "two"}],
            parent_agent=parent,
        )
    )

    assert payload == {"results": [], "total_duration_seconds": 0.0}
    assert len(resolver_calls) == 2
    assert [call["target_model"] for call in resolver_calls] == [
        "gpt-5.5",
        "gpt-5.5",
    ]
    assert [call["api_key"] for call in agent_calls] == [
        "fresh-child-token-1",
        "fresh-child-token-2",
    ]
    assert all(call["provider"] == BETA_ALLOWED_PROVIDER for call in agent_calls)
    assert all(call["base_url"] == BETA_CODEX_BASE_URL for call in agent_calls)
    assert all(call["api_mode"] == "codex_responses" for call in agent_calls)
    assert all(call["fallback_model"] is None for call in agent_calls)
    assert all(call["acp_command"] is None for call in agent_calls)
    assert all(call["acp_args"] == [] for call in agent_calls)
    assert all(call["providers_allowed"] is None for call in agent_calls)
    assert all(child._credential_pool is None for child in children)
    assert all(child._credential_pool is not parent._credential_pool for child in children)


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda parent, _config: setattr(parent, "provider", "anthropic"),
            "beta_provider_not_allowed",
        ),
        (
            lambda _parent, config: config.update(
                fallback_model={"provider": "anthropic", "model": "claude"}
            ),
            "beta_fallback_not_allowed",
        ),
        (
            lambda parent, _config: setattr(
                parent,
                "_fallback_chain",
                [{"provider": "openrouter", "model": "gpt-4o"}],
            ),
            "beta_delegate_fallback_not_allowed",
        ),
    ],
)
def test_hostile_parent_and_profile_surfaces_fail_before_child_client(
    monkeypatch, tmp_path, mutate, expected_code
):
    config = {
        "model": {
            "provider": BETA_ALLOWED_PROVIDER,
            "default": "gpt-5.5",
            "base_url": BETA_CODEX_BASE_URL,
            "api_mode": "codex_responses",
        }
    }
    resolver_calls = _install_beta_boundary(monkeypatch, tmp_path, config=config)
    agent_calls, _children = _install_fake_agent(monkeypatch)
    parent = _parent()
    mutate(parent, config)

    result = json.loads(delegate.delegate_task(goal="blocked", parent_agent=parent))

    assert result["code"] == expected_code
    assert f"[{expected_code}]" in result["error"]
    assert agent_calls == []
    if expected_code.startswith("beta_delegate"):
        assert resolver_calls == []


@pytest.mark.parametrize(
    ("task_override", "expected_code"),
    [
        ({"base_url": "https://evil.example/v1"}, "beta_delegate_custom_endpoint_not_allowed"),
        ({"api_key": "stolen-key"}, "beta_delegate_api_key_not_allowed"),
        ({"api_mode": "chat_completions"}, "beta_delegate_api_mode_not_allowed"),
        ({"custom_providers": [{"name": "evil"}]}, "beta_delegate_custom_provider_not_allowed"),
        ({"acp_command": "claude"}, "beta_delegate_transport_override_not_allowed"),
        ({"runtime_type": "acp"}, "beta_delegate_transport_override_not_allowed"),
        ({"role": "provider:anthropic"}, "beta_delegate_role_not_allowed"),
    ],
)
def test_task_provider_escape_fields_fail_before_resolution(
    monkeypatch, tmp_path, task_override, expected_code
):
    resolver_calls = _install_beta_boundary(monkeypatch, tmp_path)
    agent_calls, _children = _install_fake_agent(monkeypatch)
    task = {"goal": "blocked", **task_override}

    result = json.loads(delegate.delegate_task(tasks=[task], parent_agent=_parent()))

    assert result["code"] == expected_code
    assert resolver_calls == []
    assert agent_calls == []


def test_hostile_env_is_rejected_by_canonical_runtime_boundary(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "anthropic")

    def _resolver(**_kwargs):
        canonical_beta_provider(
            os.environ.get("ELEVATE_INFERENCE_PROVIDER"),
            source="ELEVATE_INFERENCE_PROVIDER",
        )
        raise AssertionError("hostile env should have been rejected")

    resolver_calls = _install_beta_boundary(
        monkeypatch,
        tmp_path,
        runtime_resolver=_resolver,
    )
    # _install_beta_boundary clears provider env by design; restore the hostile
    # value after the isolated boundary is installed.
    monkeypatch.setenv("ELEVATE_INFERENCE_PROVIDER", "anthropic")
    agent_calls, _children = _install_fake_agent(monkeypatch)

    result = json.loads(delegate.delegate_task(goal="blocked", parent_agent=_parent()))

    assert result["code"] == "beta_provider_not_allowed"
    assert len(resolver_calls) == 1
    assert agent_calls == []


def test_hostile_specialist_runtime_is_rejected(monkeypatch, tmp_path):
    from elevate_cli import agent_hub

    resolver_calls = _install_beta_boundary(monkeypatch, tmp_path)
    agent_calls, _children = _install_fake_agent(monkeypatch)
    monkeypatch.setattr(
        agent_hub,
        "get_agent_def",
        lambda _agent: {
            "id": "admin",
            "enabled": True,
            "toolsets": [],
            "runtime": {"provider": "anthropic", "model": "claude-opus"},
        },
    )

    result = json.loads(
        delegate.delegate_task(
            goal="admin work",
            agent="admin",
            parent_agent=_parent(),
        )
    )

    assert result["code"] == "beta_provider_not_allowed"
    assert resolver_calls == []
    assert agent_calls == []


def test_final_auth_race_fails_before_child_construction(monkeypatch, tmp_path):
    reads = iter(
        [
            {"logged_in": True, "source": "provider_state", "reason": None},
            {
                "logged_in": False,
                "source": None,
                "reason": "codex_auth_missing_or_expired",
            },
        ]
    )
    resolver_calls = _install_beta_boundary(
        monkeypatch,
        tmp_path,
        auth_reader=lambda _home: next(reads),
    )
    agent_calls, _children = _install_fake_agent(monkeypatch)

    result = json.loads(delegate.delegate_task(goal="race", parent_agent=_parent()))

    assert result["code"] == "beta_codex_auth_required"
    assert len(resolver_calls) == 1
    assert agent_calls == []


class _ProviderFailure(RuntimeError):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code} provider failure")


def _confined_run_child(*, result=None, side_effect=None):
    child = MagicMock()
    child._beta_delegate_provider_confined = True
    child.provider = BETA_ALLOWED_PROVIDER
    child.model = "gpt-5.5"
    child.base_url = BETA_CODEX_BASE_URL
    child.api_mode = "codex_responses"
    child.api_key = "fresh-token"
    child._fallback_chain = []
    child._credential_pool = None
    child.acp_command = None
    child.acp_args = []
    child._delegate_role = "leaf"
    child._subagent_id = "sa-test"
    child._parent_subagent_id = None
    child._parent_session_id = "parent"
    child._async_task_id = None
    child.session_id = "child-session"
    child.session_prompt_tokens = 0
    child.session_completion_tokens = 0
    child.session_reasoning_tokens = 0
    child.session_estimated_cost_usd = 0.0
    child.tool_progress_callback = None
    child._session_db = None
    child.get_activity_summary.return_value = {
        "api_call_count": 1,
        "current_tool": None,
        "max_iterations": 10,
    }
    if side_effect is not None:
        child.run_conversation.side_effect = side_effect
    else:
        child.run_conversation.return_value = result
    return child


@pytest.mark.parametrize("status_code", [401, 429])
def test_beta_provider_http_failures_are_visible_failed_states(
    monkeypatch, status_code
):
    child = _confined_run_child(side_effect=_ProviderFailure(status_code))
    monkeypatch.setattr(delegate, "_get_child_timeout", lambda: 1.0)

    entry = delegate._run_single_child(
        task_index=0,
        goal="provider failure",
        child=child,
        parent_agent=_parent(),
    )

    assert entry["status"] == "failed"
    assert "[beta_delegate_provider_failed]" in entry["error"]
    assert f"HTTP {status_code}" in entry["error"]
    assert child.provider == BETA_ALLOWED_PROVIDER
    assert child._fallback_chain == []
    assert child._credential_pool is None


def test_beta_timeout_and_empty_response_cannot_report_completed(monkeypatch):
    monkeypatch.setattr(delegate, "_get_child_timeout", lambda: 0.2)
    monkeypatch.setattr(
        delegate,
        "_dump_subagent_timeout_diagnostic",
        lambda **_kwargs: None,
    )
    timeout_child = _confined_run_child(side_effect=TimeoutError("socket timed out"))
    timeout_entry = delegate._run_single_child(
        task_index=0,
        goal="timeout",
        child=timeout_child,
        parent_agent=_parent(),
    )

    empty_child = _confined_run_child(
        result={"completed": True, "final_response": "", "api_calls": 1, "messages": []}
    )
    empty_entry = delegate._run_single_child(
        task_index=1,
        goal="empty",
        child=empty_child,
        parent_agent=_parent(),
    )

    assert timeout_entry["status"] == "failed"
    assert timeout_entry["exit_reason"] == "timeout"
    assert "[beta_delegate_timeout]" in timeout_entry["error"]
    assert empty_entry["status"] == "failed"
    assert empty_entry["exit_reason"] != "completed"
    assert "did not produce a response" in empty_entry["error"].lower()


def test_in_run_provider_drift_is_failed_even_with_done_text(monkeypatch):
    child = _confined_run_child()

    def _switch_provider(**_kwargs):
        child.provider = "anthropic"
        child.base_url = "https://api.anthropic.com"
        return {
            "completed": True,
            "final_response": "Everything completed successfully.",
            "api_calls": 1,
            "messages": [],
        }

    child.run_conversation.side_effect = _switch_provider
    monkeypatch.setattr(delegate, "_get_child_timeout", lambda: 1.0)

    entry = delegate._run_single_child(
        task_index=0,
        goal="drift",
        child=child,
        parent_agent=_parent(),
    )

    assert entry["status"] == "failed"
    assert entry["exit_reason"] != "completed"
    assert "[beta_delegate_runtime_drift]" in entry["error"]


def test_async_beta_failure_is_delivered_as_failed_not_completed(
    monkeypatch, tmp_path
):
    resolver_calls = _install_beta_boundary(monkeypatch, tmp_path)
    _agent_calls, _children = _install_fake_agent(monkeypatch)
    delivered = []
    done = threading.Event()
    parent = _parent()

    def _sink(payload):
        delivered.append(payload)
        done.set()

    parent._async_delegate_sink = _sink
    monkeypatch.setattr(delegate, "_get_async_delegation_enabled", lambda _cfg: True)
    monkeypatch.setattr(
        delegate,
        "_run_single_child",
        lambda *_args, **_kwargs: {
            "task_index": 0,
            "status": "failed",
            "summary": None,
            "error": "Error [beta_delegate_provider_failed]: HTTP 429",
            "api_calls": 1,
            "duration_seconds": 0.0,
        },
    )

    dispatch = json.loads(delegate.delegate_task(goal="async", parent_agent=parent))

    assert dispatch["status"] == "dispatched"
    assert done.wait(timeout=2.0)
    assert len(resolver_calls) == 1
    result = delivered[0]["results"][0]
    assert result["status"] == "failed"
    assert result["status"] != "completed"
    assert "HTTP 429" in result["error"]


def test_only_exact_lowercase_beta_changes_stable_delegate_behavior(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "Beta")
    monkeypatch.setattr(delegate, "_load_config", lambda: {})
    parent = _parent()
    parent.provider = "openrouter"
    parent.model = "anthropic/claude-sonnet-4"
    parent.base_url = "https://openrouter.ai/api/v1"
    parent.api_mode = "chat_completions"
    parent.api_key = "stable-parent-key"
    fallback = {"provider": "anthropic", "model": "claude-sonnet"}
    parent._fallback_chain = [fallback]
    stable_pool = object()
    parent._credential_pool = stable_pool
    agent_calls, children = _install_fake_agent(monkeypatch)

    delegate._build_child_agent(
        task_index=0,
        goal="stable",
        context=None,
        toolsets=None,
        model=None,
        max_iterations=10,
        task_count=1,
        parent_agent=parent,
    )

    call = agent_calls[0]
    assert call["provider"] == "openrouter"
    assert call["model"] == "anthropic/claude-sonnet-4"
    assert call["api_key"] == "stable-parent-key"
    assert call["fallback_model"] == [fallback]
    assert children[0]._credential_pool is stable_pool
