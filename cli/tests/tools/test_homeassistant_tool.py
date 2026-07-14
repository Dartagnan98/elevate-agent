"""Tests for the Home Assistant tool module.

Tests real logic: entity filtering, payload building, response parsing,
handler validation, and availability gating.
"""

import asyncio
import json
import sys
from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest

import tools.homeassistant_tool as ha_module
from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    authorize_effects,
)
from tools.homeassistant_tool import (
    _async_get_state,
    _async_list_entities,
    _async_list_services,
    _check_ha_available,
    _filter_and_summarize,
    _build_service_payload,
    _parse_service_response,
    _get_headers,
    _handle_get_state,
    _handle_call_service,
    _BLOCKED_DOMAINS,
    _ENTITY_ID_RE,
    _SERVICE_NAME_RE,
)
from tools.registry import registry


AUTHENTICATED_READ_TOOLS = (
    "ha_list_entities",
    "ha_get_state",
    "ha_list_services",
)


# ---------------------------------------------------------------------------
# Sample HA state data (matches real HA /api/states response shape)
# ---------------------------------------------------------------------------

SAMPLE_STATES = [
    {"entity_id": "light.bedroom", "state": "on", "attributes": {"friendly_name": "Bedroom Light", "brightness": 200}},
    {"entity_id": "light.kitchen", "state": "off", "attributes": {"friendly_name": "Kitchen Light"}},
    {"entity_id": "switch.fan", "state": "on", "attributes": {"friendly_name": "Living Room Fan"}},
    {"entity_id": "sensor.temperature", "state": "22.5", "attributes": {"friendly_name": "Kitchen Temperature", "unit_of_measurement": "C"}},
    {"entity_id": "climate.thermostat", "state": "heat", "attributes": {"friendly_name": "Main Thermostat", "current_temperature": 21}},
    {"entity_id": "binary_sensor.motion", "state": "off", "attributes": {"friendly_name": "Hallway Motion"}},
    {"entity_id": "sensor.humidity", "state": "55", "attributes": {"friendly_name": "Bedroom Humidity", "area": "bedroom"}},
]


# ---------------------------------------------------------------------------
# Entity filtering and summarization
# ---------------------------------------------------------------------------


class TestFilterAndSummarize:
    def test_no_filters_returns_all(self):
        result = _filter_and_summarize(SAMPLE_STATES)
        assert result["count"] == 7
        ids = {e["entity_id"] for e in result["entities"]}
        assert "light.bedroom" in ids
        assert "climate.thermostat" in ids

    def test_domain_filter_lights(self):
        result = _filter_and_summarize(SAMPLE_STATES, domain="light")
        assert result["count"] == 2
        for e in result["entities"]:
            assert e["entity_id"].startswith("light.")

    def test_domain_filter_sensor(self):
        result = _filter_and_summarize(SAMPLE_STATES, domain="sensor")
        assert result["count"] == 2
        ids = {e["entity_id"] for e in result["entities"]}
        assert ids == {"sensor.temperature", "sensor.humidity"}

    def test_domain_filter_no_matches(self):
        result = _filter_and_summarize(SAMPLE_STATES, domain="media_player")
        assert result["count"] == 0
        assert result["entities"] == []

    def test_area_filter_by_friendly_name(self):
        result = _filter_and_summarize(SAMPLE_STATES, area="kitchen")
        assert result["count"] == 2
        ids = {e["entity_id"] for e in result["entities"]}
        assert "light.kitchen" in ids
        assert "sensor.temperature" in ids

    def test_area_filter_by_area_attribute(self):
        result = _filter_and_summarize(SAMPLE_STATES, area="bedroom")
        ids = {e["entity_id"] for e in result["entities"]}
        # "Bedroom Light" matches via friendly_name, "Bedroom Humidity" matches via area attr
        assert "light.bedroom" in ids
        assert "sensor.humidity" in ids

    def test_area_filter_case_insensitive(self):
        result = _filter_and_summarize(SAMPLE_STATES, area="KITCHEN")
        assert result["count"] == 2

    def test_combined_domain_and_area(self):
        result = _filter_and_summarize(SAMPLE_STATES, domain="sensor", area="kitchen")
        assert result["count"] == 1
        assert result["entities"][0]["entity_id"] == "sensor.temperature"

    def test_summary_includes_friendly_name(self):
        result = _filter_and_summarize(SAMPLE_STATES, domain="climate")
        assert result["entities"][0]["friendly_name"] == "Main Thermostat"
        assert result["entities"][0]["state"] == "heat"

    def test_empty_states_list(self):
        result = _filter_and_summarize([])
        assert result["count"] == 0

    def test_missing_attributes_handled(self):
        states = [{"entity_id": "light.x", "state": "on"}]
        result = _filter_and_summarize(states)
        assert result["count"] == 1
        assert result["entities"][0]["friendly_name"] == ""


# ---------------------------------------------------------------------------
# Service payload building
# ---------------------------------------------------------------------------


class TestBuildServicePayload:
    def test_entity_id_only(self):
        payload = _build_service_payload(entity_id="light.bedroom")
        assert payload == {"entity_id": "light.bedroom"}

    def test_data_only(self):
        payload = _build_service_payload(data={"brightness": 255})
        assert payload == {"brightness": 255}

    def test_entity_id_and_data(self):
        payload = _build_service_payload(
            entity_id="light.bedroom",
            data={"brightness": 200, "color_name": "blue"},
        )
        assert payload["entity_id"] == "light.bedroom"
        assert payload["brightness"] == 200
        assert payload["color_name"] == "blue"

    def test_no_args_returns_empty(self):
        payload = _build_service_payload()
        assert payload == {}

    def test_entity_id_param_takes_precedence_over_data(self):
        payload = _build_service_payload(
            entity_id="light.a",
            data={"entity_id": "light.b"},
        )
        # explicit entity_id parameter wins over data["entity_id"]
        assert payload["entity_id"] == "light.a"


# ---------------------------------------------------------------------------
# Service response parsing
# ---------------------------------------------------------------------------


class TestParseServiceResponse:
    def test_list_response_extracts_entities(self):
        ha_response = [
            {"entity_id": "light.bedroom", "state": "on", "attributes": {}},
            {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
        ]
        result = _parse_service_response("light", "turn_on", ha_response)
        assert result["success"] is True
        assert result["service"] == "light.turn_on"
        assert len(result["affected_entities"]) == 2
        assert result["affected_entities"][0]["entity_id"] == "light.bedroom"

    def test_empty_list_response(self):
        result = _parse_service_response("scene", "turn_on", [])
        assert result["success"] is True
        assert result["affected_entities"] == []

    def test_non_list_response(self):
        # Some HA services return a dict instead of a list
        result = _parse_service_response("script", "run", {"result": "ok"})
        assert result["success"] is True
        assert result["affected_entities"] == []

    def test_none_response(self):
        result = _parse_service_response("automation", "trigger", None)
        assert result["success"] is True
        assert result["affected_entities"] == []

    def test_service_name_format(self):
        result = _parse_service_response("climate", "set_temperature", [])
        assert result["service"] == "climate.set_temperature"


# ---------------------------------------------------------------------------
# Handler validation (no mocks - these paths don't reach the network)
# ---------------------------------------------------------------------------


class TestHandlerValidation:
    def test_get_state_missing_entity_id(self):
        result = json.loads(_handle_get_state({}))
        assert "error" in result
        assert "entity_id" in result["error"]

    def test_get_state_empty_entity_id(self):
        result = json.loads(_handle_get_state({"entity_id": ""}))
        assert "error" in result

    def test_call_service_missing_domain(self):
        result = json.loads(_handle_call_service({"service": "turn_on"}))
        assert "error" in result
        assert "domain" in result["error"]

    def test_call_service_missing_service(self):
        result = json.loads(_handle_call_service({"domain": "light"}))
        assert "error" in result
        assert "service" in result["error"]

    def test_call_service_missing_both(self):
        result = json.loads(_handle_call_service({}))
        assert "error" in result

    def test_call_service_empty_strings(self):
        result = json.loads(_handle_call_service({"domain": "", "service": ""}))
        assert "error" in result


# ---------------------------------------------------------------------------
# Security: domain blocklist
# ---------------------------------------------------------------------------


class TestDomainBlocklist:
    """Verify dangerous HA service domains are blocked."""

    @pytest.mark.parametrize("domain", sorted(_BLOCKED_DOMAINS))
    def test_blocked_domain_rejected(self, domain):
        result = json.loads(_handle_call_service({
            "domain": domain, "service": "any_service"
        }))
        assert "error" in result
        assert "blocked" in result["error"].lower()

    @patch(
        "tools.homeassistant_tool._async_call_service",
        new_callable=AsyncMock,
        return_value={"success": True},
    )
    def test_safe_domain_not_blocked(self, mock_call_service):
        """Safe domains pass validation using a fully fake service transport."""
        result = json.loads(_handle_call_service({
            "domain": "light", "service": "turn_on", "entity_id": "light.test"
        }))
        assert result == {"result": {"success": True}}
        mock_call_service.assert_awaited_once_with(
            "light",
            "turn_on",
            "light.test",
            None,
        )

    def test_blocked_domains_include_shell_command(self):
        assert "shell_command" in _BLOCKED_DOMAINS

    def test_blocked_domains_include_hassio(self):
        assert "hassio" in _BLOCKED_DOMAINS

    def test_blocked_domains_include_rest_command(self):
        assert "rest_command" in _BLOCKED_DOMAINS


# ---------------------------------------------------------------------------
# Security: entity_id validation
# ---------------------------------------------------------------------------


class TestEntityIdValidation:
    """Verify entity_id format validation prevents path traversal."""

    def test_valid_entity_id_accepted(self):
        assert _ENTITY_ID_RE.match("light.bedroom")
        assert _ENTITY_ID_RE.match("sensor.temperature_1")
        assert _ENTITY_ID_RE.match("binary_sensor.motion")
        assert _ENTITY_ID_RE.match("climate.main_thermostat")

    def test_path_traversal_rejected(self):
        assert _ENTITY_ID_RE.match("../../config") is None
        assert _ENTITY_ID_RE.match("light/../../../etc/passwd") is None
        assert _ENTITY_ID_RE.match("../api/config") is None

    def test_special_chars_rejected(self):
        assert _ENTITY_ID_RE.match("light.bed room") is None  # space
        assert _ENTITY_ID_RE.match("light.bed;rm -rf") is None  # semicolon
        assert _ENTITY_ID_RE.match("light.bed/room") is None  # slash
        assert _ENTITY_ID_RE.match("LIGHT.BEDROOM") is None  # uppercase

    def test_missing_domain_rejected(self):
        assert _ENTITY_ID_RE.match(".bedroom") is None
        assert _ENTITY_ID_RE.match("bedroom") is None

    def test_get_state_rejects_invalid_entity_id(self):
        result = json.loads(_handle_get_state({"entity_id": "../../config"}))
        assert "error" in result
        assert "Invalid entity_id" in result["error"]

    def test_call_service_rejects_invalid_entity_id(self):
        result = json.loads(_handle_call_service({
            "domain": "light",
            "service": "turn_on",
            "entity_id": "../../../etc/passwd",
        }))
        assert "error" in result
        assert "Invalid entity_id" in result["error"]

    @patch(
        "tools.homeassistant_tool._async_call_service",
        new_callable=AsyncMock,
        return_value={"success": True},
    )
    def test_call_service_allows_no_entity_id(self, mock_call_service):
        """Some services omit entity_id without reaching a live transport."""
        result = json.loads(_handle_call_service({
            "domain": "scene", "service": "turn_on"
        }))
        assert result == {"result": {"success": True}}
        mock_call_service.assert_awaited_once_with(
            "scene",
            "turn_on",
            None,
            None,
        )


# ---------------------------------------------------------------------------
# String-data deserialization (XML tool calling workaround)
# ---------------------------------------------------------------------------


class TestCallServiceStringData:
    """data param may arrive as a JSON string (XML tool calling mode)."""

    @patch(
        "tools.homeassistant_tool._async_call_service",
        new_callable=AsyncMock,
        return_value={"success": True},
    )
    def test_string_data_deserialized(self, mock_call_service):
        """JSON string data is parsed into a dict before dispatch."""
        _handle_call_service({
            "domain": "climate",
            "service": "set_hvac_mode",
            "entity_id": "climate.living_room",
            "data": '{"hvac_mode": "heat"}',
        })
        mock_call_service.assert_awaited_once_with(
            "climate",
            "set_hvac_mode",
            "climate.living_room",
            {"hvac_mode": "heat"},
        )

    @patch(
        "tools.homeassistant_tool._async_call_service",
        new_callable=AsyncMock,
        return_value={"success": True},
    )
    def test_dict_data_passthrough(self, mock_call_service):
        """Dict data (JSON tool calling mode) still works unchanged."""
        _handle_call_service({
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.bedroom",
            "data": {"brightness": 255},
        })
        mock_call_service.assert_awaited_once_with(
            "light",
            "turn_on",
            "light.bedroom",
            {"brightness": 255},
        )

    def test_invalid_json_string_returns_error(self):
        """Malformed JSON string in data returns a clear error."""
        result = json.loads(_handle_call_service({
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.bedroom",
            "data": "{not valid json}",
        }))
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    @patch(
        "tools.homeassistant_tool._async_call_service",
        new_callable=AsyncMock,
        return_value={"success": True},
    )
    def test_empty_string_data_becomes_none(self, mock_call_service):
        """Empty/whitespace string data is treated as None."""
        _handle_call_service({
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.bedroom",
            "data": "   ",
        })
        mock_call_service.assert_awaited_once_with(
            "light",
            "turn_on",
            "light.bedroom",
            None,
        )


# ---------------------------------------------------------------------------
# Security: domain/service name format validation
# ---------------------------------------------------------------------------


class TestServiceNameValidation:
    """Verify domain/service format validation prevents path traversal in URL.

    The domain and service parameters are interpolated into
    /api/services/{domain}/{service}, so allowing arbitrary strings would
    enable SSRF via path traversal or blocked-domain bypass.
    """

    def test_valid_domain_names(self):
        assert _SERVICE_NAME_RE.match("light")
        assert _SERVICE_NAME_RE.match("switch")
        assert _SERVICE_NAME_RE.match("climate")
        assert _SERVICE_NAME_RE.match("shell_command")
        assert _SERVICE_NAME_RE.match("media_player")

    def test_valid_service_names(self):
        assert _SERVICE_NAME_RE.match("turn_on")
        assert _SERVICE_NAME_RE.match("turn_off")
        assert _SERVICE_NAME_RE.match("set_temperature")
        assert _SERVICE_NAME_RE.match("toggle")

    def test_path_traversal_in_domain_rejected(self):
        assert _SERVICE_NAME_RE.match("../../api/config") is None
        assert _SERVICE_NAME_RE.match("light/../../../etc") is None
        assert _SERVICE_NAME_RE.match("../config") is None

    def test_path_traversal_in_service_rejected(self):
        assert _SERVICE_NAME_RE.match("../../api/config") is None
        assert _SERVICE_NAME_RE.match("turn_on/../../config") is None

    def test_blocked_domain_bypass_via_traversal_rejected(self):
        """Ensure shell_command/../light is rejected, not just checked against blocklist."""
        assert _SERVICE_NAME_RE.match("shell_command/../light") is None
        assert _SERVICE_NAME_RE.match("python_script/../scene") is None
        assert _SERVICE_NAME_RE.match("hassio/../automation") is None

    def test_slashes_rejected(self):
        assert _SERVICE_NAME_RE.match("light/turn_on") is None
        assert _SERVICE_NAME_RE.match("a/b/c") is None

    def test_dots_rejected(self):
        assert _SERVICE_NAME_RE.match("light.turn_on") is None
        assert _SERVICE_NAME_RE.match("..") is None

    def test_uppercase_rejected(self):
        assert _SERVICE_NAME_RE.match("LIGHT") is None
        assert _SERVICE_NAME_RE.match("Turn_On") is None

    def test_special_chars_rejected(self):
        assert _SERVICE_NAME_RE.match("light;rm") is None
        assert _SERVICE_NAME_RE.match("light&cmd") is None
        assert _SERVICE_NAME_RE.match("light cmd") is None

    def test_handler_rejects_traversal_domain(self):
        """_handle_call_service must reject domain with path traversal."""
        result = json.loads(_handle_call_service({
            "domain": "../../api/config",
            "service": "turn_on",
        }))
        assert "error" in result
        assert "Invalid domain" in result["error"]

    def test_handler_rejects_traversal_service(self):
        """_handle_call_service must reject service with path traversal."""
        result = json.loads(_handle_call_service({
            "domain": "light",
            "service": "../../api/config",
        }))
        assert "error" in result
        assert "Invalid service" in result["error"]

    def test_handler_rejects_blocklist_bypass_traversal(self):
        """Blocklist bypass via shell_command/../light must be caught by format validation."""
        result = json.loads(_handle_call_service({
            "domain": "shell_command/../light",
            "service": "turn_on",
        }))
        assert "error" in result
        # Must be rejected as "Invalid domain", not slip through the blocklist
        assert "Invalid domain" in result["error"]


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------


class TestCheckAvailable:
    def test_unavailable_without_token(self, monkeypatch):
        monkeypatch.delenv("HASS_TOKEN", raising=False)
        assert _check_ha_available() is False

    def test_available_with_token(self, monkeypatch):
        monkeypatch.setenv("HASS_TOKEN", "eyJ0eXAiOiJKV1Q")
        assert _check_ha_available() is True

    def test_empty_token_is_unavailable(self, monkeypatch):
        monkeypatch.setenv("HASS_TOKEN", "")
        assert _check_ha_available() is False


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------


class TestGetHeaders:
    def test_bearer_token_format(self, monkeypatch):
        monkeypatch.setattr("tools.homeassistant_tool._HASS_TOKEN", "my-secret-token")
        headers = _get_headers()
        assert headers["Authorization"] == "Bearer my-secret-token"
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_tools_registered_in_registry(self):
        names = registry.get_all_tool_names()
        for tool in (*AUTHENTICATED_READ_TOOLS, "ha_call_service"):
            assert tool in names

    def test_tools_in_homeassistant_toolset(self):
        toolset_map = registry.get_tool_to_toolset_map()
        for tool in (*AUTHENTICATED_READ_TOOLS, "ha_call_service"):
            assert toolset_map[tool] == "homeassistant"

    def test_check_fn_gates_availability(self, monkeypatch):
        """Registry should exclude HA tools when HASS_TOKEN is not set."""
        from tools.registry import invalidate_check_fn_cache, registry

        monkeypatch.delenv("HASS_TOKEN", raising=False)
        invalidate_check_fn_cache()
        defs = registry.get_definitions({*AUTHENTICATED_READ_TOOLS, "ha_call_service"})
        assert len(defs) == 0

    def test_check_fn_includes_when_token_set(self, monkeypatch):
        """Registry should include HA tools when HASS_TOKEN is set."""
        from tools.registry import invalidate_check_fn_cache, registry

        monkeypatch.setenv("HASS_TOKEN", "test-token")
        invalidate_check_fn_cache()
        defs = registry.get_definitions({*AUTHENTICATED_READ_TOOLS, "ha_call_service"})
        assert len(defs) == 4

    def test_authenticated_reads_declare_exact_effects_and_service_call_unknown(self):
        expected = frozenset({
            Effect.parse("read:homeassistant"),
            Effect.parse("credential_access:homeassistant"),
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

        unknown = frozenset({Effect(EffectKind.UNKNOWN)})
        service_call = registry.get_entry("ha_call_service")
        assert service_call is not None
        assert service_call.effects is None
        assert service_call.effect_resolver is None
        assert registry.get_effect_metadata("ha_call_service") == {
            "declared": False,
            "effects": unknown,
            "has_resolver": False,
        }
        assert registry.resolve_effects("ha_call_service", {}) == unknown

    def test_authenticated_reads_are_denied_by_read_only_and_allowed_by_default(self):
        expected = frozenset({
            Effect.parse("read:homeassistant"),
            Effect.parse("credential_access:homeassistant"),
        })
        credential = frozenset({Effect.parse("credential_access:homeassistant")})
        read_only = ExecutionPolicy.for_mode(
            "turn-homeassistant-read-only",
            ExecutionPolicyMode.READ_ONLY,
        )
        default = ExecutionPolicy.for_mode(
            "turn-homeassistant-default",
            ExecutionPolicyMode.DEFAULT,
        )

        for name in AUTHENTICATED_READ_TOOLS:
            resolved = registry.resolve_effects(name, {})
            read_only_decision = authorize_effects(read_only, resolved)
            default_decision = authorize_effects(default, resolved)

            assert resolved == expected
            assert read_only_decision.allowed is False
            assert read_only_decision.denied_effects == credential
            assert read_only_decision.reason == "effect_not_allowed"
            assert default_decision.allowed is True
            assert default_decision.denied_effects == frozenset()
            assert default_decision.reason == "allowed"

        unknown_decision = authorize_effects(
            default,
            registry.resolve_effects("ha_call_service", {}),
        )
        assert unknown_decision.allowed is False
        assert unknown_decision.reason == "unknown_effect"


def test_authenticated_reads_use_get_only_fake_transport_without_filesystem_mutation(
    tmp_path,
    monkeypatch,
):
    calls = []
    state = {
        "entity_id": "light.bedroom",
        "state": "on",
        "attributes": {"friendly_name": "Bedroom Light"},
        "last_changed": "2026-07-14T12:00:00Z",
        "last_updated": "2026-07-14T12:00:00Z",
    }
    services = [{
        "domain": "light",
        "services": {
            "turn_on": {
                "description": "Turn on a light",
                "fields": {},
            },
        },
    }]

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        def raise_for_status(self):
            return None

        async def json(self):
            return self.payload

    class FakeClientSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        def get(self, url, **kwargs):
            calls.append({"method": "GET", "url": url, **kwargs})
            if url.endswith("/api/states/light.bedroom"):
                return FakeResponse(state)
            if url.endswith("/api/states"):
                return FakeResponse(SAMPLE_STATES)
            if url.endswith("/api/services"):
                return FakeResponse(services)
            raise AssertionError(f"unexpected fake Home Assistant URL: {url}")

        def post(self, url, **kwargs):
            calls.append({"method": "POST", "url": url, **kwargs})
            raise AssertionError("authenticated Home Assistant read attempted POST")

    fake_aiohttp = ModuleType("aiohttp")
    fake_aiohttp.ClientSession = FakeClientSession
    fake_aiohttp.ClientTimeout = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    monkeypatch.setattr(
        ha_module,
        "_get_config",
        lambda: ("https://homeassistant.invalid", "fake-test-token"),
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    before = set(tmp_path.rglob("*"))

    async def exercise_reads():
        return (
            await _async_list_entities(domain="light"),
            await _async_get_state("light.bedroom"),
            await _async_list_services(domain="light"),
        )

    entities_result, state_result, services_result = asyncio.run(exercise_reads())

    assert entities_result["count"] == 2
    assert state_result["entity_id"] == "light.bedroom"
    assert services_result["count"] == 1
    assert len(calls) == 3
    assert {call["method"] for call in calls} == {"GET"}
    assert not any(call["method"] == "POST" for call in calls)
    assert {call["url"] for call in calls} == {
        "https://homeassistant.invalid/api/states",
        "https://homeassistant.invalid/api/states/light.bedroom",
        "https://homeassistant.invalid/api/services",
    }
    for call in calls:
        assert call["headers"] == {
            "Authorization": "Bearer fake-test-token",
            "Content-Type": "application/json",
        }
    assert set(tmp_path.rglob("*")) == before
