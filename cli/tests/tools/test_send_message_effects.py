"""Effect-resolver and hidden-write tests for the send_message tool.

``send_message`` has exactly two surfaces: ``list`` formats the on-disk channel
directory (a pure local read) and every other action sends a message to an
external platform. These tests pin the repaired contract:

- ``list`` resolves to an exact ``read:channels`` and is allowed under a
  read-only policy;
- the send path (and every unrecognized action, and a missing action which the
  handler defaults to ``send``) stays unknown and is denied under read-only;
- the resolver's branch matches the handler's dispatch byte-for-byte, so the
  declared surface can never advertise coverage the handler does not honor;
- the ``list`` read never creates or mutates a file.
"""

from __future__ import annotations

import json

import pytest

from gateway import channel_directory
from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.registry import registry
from tools import send_message_tool as send_message_module
from tools.send_message_tool import (
    _send_message_effect_resolver,
    send_message_tool,
)

READ_CHANNELS = frozenset({Effect.parse("read:channels")})
UNKNOWN = frozenset({Effect(EffectKind.UNKNOWN)})


def _read_only():
    return ExecutionPolicy.for_mode(
        "turn-send-message-read", ExecutionPolicyMode.READ_ONLY
    )


def test_send_message_registers_a_resolver_not_static_effects():
    entry = registry.get_entry("send_message")
    assert entry is not None
    assert entry.effects is None
    assert entry.effect_resolver is not None
    assert registry.get_effect_metadata("send_message") == {
        "declared": True,
        "effects": frozenset(),
        "has_resolver": True,
    }


def test_list_resolves_to_read_channels_and_is_read_only_allowed():
    resolved = registry.resolve_effects("send_message", {"action": "list"})
    assert resolved == READ_CHANNELS

    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is True
    assert decision.denied_effects == frozenset()
    assert decision.reason == "allowed"


@pytest.mark.parametrize(
    "args",
    [
        {"action": "send", "target": "x", "message": "y"},
        {"target": "x", "message": "y"},  # missing action -> handler defaults to send
        {},
        None,
        {"action": "List"},   # case-sensitive: handler compares == "list"
        {"action": " list "},  # not stripped by the handler
        {"action": "broadcast"},
    ],
)
def test_send_and_unknown_actions_stay_unknown_and_denied(args):
    resolved = registry.resolve_effects("send_message", args)
    assert resolved == UNKNOWN

    decision = authorize_effects(_read_only(), resolved)
    assert decision.allowed is False
    assert decision.reason == "unknown_effect"


@pytest.mark.parametrize(
    "args",
    [
        {"action": "list"},
        {"action": "send", "target": "t", "message": "m"},
        {"target": "t", "message": "m"},
        {},
        {"action": "List"},
        {"action": " list "},
        {"action": "nonsense"},
    ],
)
def test_resolver_matches_handler_dispatch_exactly(monkeypatch, args):
    """Adversarial: the resolved effect must agree with the branch the handler
    actually takes. We replace the two handler branches with sentinels and
    check that the handler routes to ``list`` IFF the resolver declared the
    pure read."""
    routed = {"branch": None}

    monkeypatch.setattr(
        send_message_module,
        "_handle_list",
        lambda: routed.__setitem__("branch", "list") or "{}",
    )
    monkeypatch.setattr(
        send_message_module,
        "_handle_send",
        lambda _a: routed.__setitem__("branch", "send") or "{}",
    )

    send_message_tool(args if isinstance(args, dict) else {})
    resolved = registry.resolve_effects("send_message", args)

    took_list_branch = routed["branch"] == "list"
    declared_pure_read = resolved == READ_CHANNELS
    assert took_list_branch == declared_pure_read


def test_list_read_creates_no_file_when_directory_absent(monkeypatch, tmp_path):
    # A dedicated subtree the harness's ELEVATE_HOME fixture never touches, so
    # anything appearing here was written by the tool under test.
    subdir = tmp_path / "chdir"
    missing = subdir / "channel_directory.json"
    monkeypatch.setattr(channel_directory, "DIRECTORY_PATH", missing)

    out = json.loads(send_message_tool({"action": "list"}))

    assert "targets" in out
    assert not missing.exists()
    assert not subdir.exists()  # the read never created the directory tree


def test_list_read_does_not_mutate_existing_directory_file(monkeypatch, tmp_path):
    subdir = tmp_path / "chdir"
    subdir.mkdir()
    path = subdir / "channel_directory.json"
    payload = {
        "updated_at": "2026-07-17T00:00:00Z",
        "platforms": {"slack": [{"id": "C1", "name": "general", "type": "channel"}]},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    monkeypatch.setattr(channel_directory, "DIRECTORY_PATH", path)

    out = json.loads(send_message_tool({"action": "list"}))

    assert "general" in out["targets"]
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime
    # No sibling temp/backup files were created in the isolated subtree.
    assert [p.name for p in subdir.iterdir()] == ["channel_directory.json"]


def test_resolver_function_is_pure_and_import_light():
    # The resolver must not need any heavy runtime; a direct call classifies
    # from the argument alone.
    assert _send_message_effect_resolver({"action": "list"}) == {"read:channels"}
    assert _send_message_effect_resolver({"action": "send"}) == {EffectKind.UNKNOWN}
    assert _send_message_effect_resolver(None) == {EffectKind.UNKNOWN}
