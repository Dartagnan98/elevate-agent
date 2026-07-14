"""Tests for Feishu tool registration, effects, and isolated request paths."""

import importlib
import json
import socket
import sys
import unittest
from types import ModuleType, SimpleNamespace

import pytest

from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.registry import registry

# Trigger tool discovery so feishu tools get registered
feishu_doc_tool = importlib.import_module("tools.feishu_doc_tool")
feishu_drive_tool = importlib.import_module("tools.feishu_drive_tool")


AUTHENTICATED_READ_TOOLS = (
    "feishu_doc_read",
    "feishu_drive_list_comments",
    "feishu_drive_list_comment_replies",
)
COMMENT_WRITE_TOOLS = (
    "feishu_drive_reply_comment",
    "feishu_drive_add_comment",
)


@pytest.fixture(autouse=True)
def _clear_injected_clients():
    modules = (feishu_doc_tool, feishu_drive_tool)
    for module in modules:
        if hasattr(module._local, "client"):
            del module._local.client
    yield
    for module in modules:
        if hasattr(module._local, "client"):
            del module._local.client


class _FakeRequestBuilder:
    def __init__(self):
        self._fields = {
            "http_method": None,
            "uri": None,
            "token_types": set(),
            "paths": {},
            "queries": [],
            "body": None,
        }

    def http_method(self, value):
        self._fields["http_method"] = value
        return self

    def uri(self, value):
        self._fields["uri"] = value
        return self

    def token_types(self, value):
        self._fields["token_types"] = set(value)
        return self

    def paths(self, value):
        self._fields["paths"] = dict(value)
        return self

    def queries(self, value):
        self._fields["queries"] = list(value)
        return self

    def body(self, value):
        self._fields["body"] = value
        return self

    def build(self):
        return SimpleNamespace(**self._fields)


class _FakeBaseRequest:
    @classmethod
    def builder(cls):
        return _FakeRequestBuilder()


def _install_fake_lark_sdk(monkeypatch):
    lark_module = ModuleType("lark_oapi")
    core_module = ModuleType("lark_oapi.core")
    enum_module = ModuleType("lark_oapi.core.enum")
    model_module = ModuleType("lark_oapi.core.model")
    request_module = ModuleType("lark_oapi.core.model.base_request")

    lark_module.__path__ = []
    core_module.__path__ = []
    model_module.__path__ = []
    lark_module.AccessTokenType = SimpleNamespace(TENANT="TENANT")
    enum_module.HttpMethod = SimpleNamespace(GET="GET", POST="POST")
    request_module.BaseRequest = _FakeBaseRequest
    lark_module.core = core_module
    core_module.enum = enum_module
    core_module.model = model_module
    model_module.base_request = request_module

    for name, module in (
        ("lark_oapi", lark_module),
        ("lark_oapi.core", core_module),
        ("lark_oapi.core.enum", enum_module),
        ("lark_oapi.core.model", model_module),
        ("lark_oapi.core.model.base_request", request_module),
    ):
        monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
def fake_feishu_runtime(monkeypatch):
    _install_fake_lark_sdk(monkeypatch)

    class FakeTenantTokenManager:
        def __init__(self):
            self.cache = {}
            self.lookups = 0
            self.cache_misses = 0
            self.cache_hits = 0
            self.credential_reads = []

        def tenant_token(self, client):
            self.lookups += 1
            token = self.cache.get("tenant")
            if token is None:
                self.cache_misses += 1
                self.credential_reads.append((client.app_id, client.app_secret))
                token = "fake-tenant-token"
                self.cache["tenant"] = token
            else:
                self.cache_hits += 1
            return token

    class FakeTransport:
        def __init__(self):
            self.calls = []

        def send(self, request, token):
            if request.http_method != "GET":
                raise AssertionError(
                    f"Feishu read attempted {request.http_method}"
                )
            self.calls.append(SimpleNamespace(request=request, token=token))
            payloads = {
                feishu_doc_tool._RAW_CONTENT_URI: {
                    "content": "Fake document content",
                },
                feishu_drive_tool._LIST_COMMENTS_URI: {
                    "items": [{"comment_id": "comment-1"}],
                    "has_more": False,
                },
                feishu_drive_tool._LIST_REPLIES_URI: {
                    "items": [{"reply_id": "reply-1"}],
                    "has_more": False,
                },
            }
            if request.uri not in payloads:
                raise AssertionError(f"unexpected fake Feishu URI: {request.uri}")
            return SimpleNamespace(
                code=0,
                msg="",
                raw=SimpleNamespace(
                    content=json.dumps({"data": payloads[request.uri]})
                ),
                data=None,
            )

    class FakeInjectedClient:
        app_id = "fake-app-id"
        app_secret = "fake-app-secret"

        def __init__(self, token_manager, transport):
            self.token_manager = token_manager
            self.transport = transport

        def request(self, request):
            token = self.token_manager.tenant_token(self)
            return self.transport.send(request, token)

    token_manager = FakeTenantTokenManager()
    transport = FakeTransport()
    client = FakeInjectedClient(token_manager, transport)
    feishu_doc_tool.set_client(client)
    feishu_drive_tool.set_client(client)
    return SimpleNamespace(
        client=client,
        token_manager=token_manager,
        transport=transport,
    )


class TestFeishuToolRegistration(unittest.TestCase):
    """Verify feishu tools are registered and have valid schemas."""

    EXPECTED_TOOLS = {
        "feishu_doc_read": "feishu_doc",
        "feishu_drive_list_comments": "feishu_drive",
        "feishu_drive_list_comment_replies": "feishu_drive",
        "feishu_drive_reply_comment": "feishu_drive",
        "feishu_drive_add_comment": "feishu_drive",
    }

    def test_all_tools_registered(self):
        for tool_name, toolset in self.EXPECTED_TOOLS.items():
            entry = registry.get_entry(tool_name)
            self.assertIsNotNone(entry, f"{tool_name} not registered")
            self.assertEqual(entry.toolset, toolset)

    def test_schemas_have_required_fields(self):
        for tool_name in self.EXPECTED_TOOLS:
            entry = registry.get_entry(tool_name)
            schema = entry.schema
            self.assertIn("name", schema)
            self.assertEqual(schema["name"], tool_name)
            self.assertIn("description", schema)
            self.assertIn("parameters", schema)
            self.assertIn("type", schema["parameters"])
            self.assertEqual(schema["parameters"]["type"], "object")

    def test_handlers_are_callable(self):
        for tool_name in self.EXPECTED_TOOLS:
            entry = registry.get_entry(tool_name)
            self.assertTrue(callable(entry.handler))

    def test_doc_read_schema_params(self):
        entry = registry.get_entry("feishu_doc_read")
        props = entry.schema["parameters"].get("properties", {})
        self.assertIn("doc_token", props)

    def test_drive_tools_require_file_token(self):
        for tool_name in self.EXPECTED_TOOLS:
            if tool_name == "feishu_doc_read":
                continue
            entry = registry.get_entry(tool_name)
            props = entry.schema["parameters"].get("properties", {})
            self.assertIn("file_token", props, f"{tool_name} missing file_token param")
            self.assertIn("file_type", props, f"{tool_name} missing file_type param")


def test_feishu_read_tools_declare_exact_effects():
    expected = frozenset({
        Effect.parse("read:feishu"),
        Effect.parse("credential_access:feishu"),
    })

    for name in AUTHENTICATED_READ_TOOLS:
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


def test_feishu_reads_are_denied_without_credential_capability():
    read_only = ExecutionPolicy.for_mode(
        "turn-feishu-read-only",
        ExecutionPolicyMode.READ_ONLY,
    )
    credential = frozenset({Effect.parse("credential_access:feishu")})

    for name in AUTHENTICATED_READ_TOOLS:
        decision = authorize_effects(
            read_only,
            registry.resolve_effects(name, {}),
        )
        assert decision.allowed is False
        assert decision.denied_effects == credential
        assert decision.reason == "effect_not_allowed"


def test_feishu_reads_are_allowed_by_default_policy():
    default = ExecutionPolicy.for_mode(
        "turn-feishu-default",
        ExecutionPolicyMode.DEFAULT,
    )

    for name in AUTHENTICATED_READ_TOOLS:
        decision = authorize_effects(
            default,
            registry.resolve_effects(name, {}),
        )
        assert decision.allowed is True
        assert decision.denied_effects == frozenset()
        assert decision.reason == "allowed"


def test_feishu_read_tools_build_get_requests_only_without_disk_or_network(
    fake_feishu_runtime,
    tmp_path,
    monkeypatch,
):
    def unexpected_disk(*_args, **_kwargs):
        raise AssertionError("Feishu read attempted direct disk access")

    def unexpected_network(*_args, **_kwargs):
        raise AssertionError("Feishu read bypassed the fake transport")

    for key in (
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "LARK_APP_ID",
        "LARK_APP_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("builtins.open", unexpected_disk)
    monkeypatch.setattr(socket, "create_connection", unexpected_network)
    before = set(tmp_path.rglob("*"))

    doc = json.loads(
        feishu_doc_tool._handle_feishu_doc_read({"doc_token": "doc-1"})
    )
    comments = json.loads(
        feishu_drive_tool._handle_list_comments({"file_token": "doc-1"})
    )
    replies = json.loads(
        feishu_drive_tool._handle_list_replies({
            "file_token": "doc-1",
            "comment_id": "comment-1",
        })
    )

    assert doc == {"success": True, "content": "Fake document content"}
    assert comments["items"] == [{"comment_id": "comment-1"}]
    assert replies["items"] == [{"reply_id": "reply-1"}]
    assert set(tmp_path.rglob("*")) == before

    calls = fake_feishu_runtime.transport.calls
    assert len(calls) == 3
    assert {call.request.http_method for call in calls} == {"GET"}
    assert all(call.request.body is None for call in calls)
    assert all(call.request.token_types == {"TENANT"} for call in calls)
    assert all(call.token == "fake-tenant-token" for call in calls)
    assert {call.request.uri for call in calls} == {
        feishu_doc_tool._RAW_CONTENT_URI,
        feishu_drive_tool._LIST_COMMENTS_URI,
        feishu_drive_tool._LIST_REPLIES_URI,
    }
    assert [call.request.paths for call in calls] == [
        {"document_id": "doc-1"},
        {"file_token": "doc-1"},
        {"file_token": "doc-1", "comment_id": "comment-1"},
    ]


def test_feishu_tenant_token_cache_miss_is_covered_by_credential_effect(
    fake_feishu_runtime,
):
    first = json.loads(
        feishu_doc_tool._handle_feishu_doc_read({"doc_token": "doc-1"})
    )
    second = json.loads(
        feishu_doc_tool._handle_feishu_doc_read({"doc_token": "doc-2"})
    )

    assert first["success"] is True
    assert second["success"] is True
    manager = fake_feishu_runtime.token_manager
    assert manager.lookups == 2
    assert manager.cache_misses == 1
    assert manager.cache_hits == 1
    assert manager.credential_reads == [("fake-app-id", "fake-app-secret")]
    assert manager.cache == {"tenant": "fake-tenant-token"}
    assert Effect.parse("credential_access:feishu") in registry.resolve_effects(
        "feishu_doc_read",
        {"doc_token": "doc-1"},
    )


def test_feishu_comment_writes_remain_unknown():
    unknown = frozenset({Effect(EffectKind.UNKNOWN)})
    default = ExecutionPolicy.for_mode(
        "turn-feishu-write-default",
        ExecutionPolicyMode.DEFAULT,
    )

    for name in COMMENT_WRITE_TOOLS:
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
        assert resolved == unknown
        decision = authorize_effects(default, resolved)
        assert decision.allowed is False
        assert decision.reason == "unknown_effect"


if __name__ == "__main__":
    unittest.main()
