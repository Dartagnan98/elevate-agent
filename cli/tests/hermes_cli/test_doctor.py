"""Tests for elevate_cli.doctor."""

import os
import sys
import types
import io
import contextlib
from argparse import Namespace
from types import SimpleNamespace

import pytest

import elevate_cli.doctor as doctor
import elevate_cli.gateway as gateway_cli
from elevate_cli import doctor as doctor_mod
from elevate_cli.doctor import _has_provider_env_config


class TestDoctorPlatformHints:
    def test_termux_package_hint(self, monkeypatch):
        monkeypatch.setenv("TERMUX_VERSION", "0.118.3")
        monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
        assert doctor._is_termux() is True
        assert doctor._python_install_cmd() == "python -m pip install"
        assert doctor._system_package_install_cmd("ripgrep") == "pkg install ripgrep"

    def test_non_termux_package_hint_defaults_to_apt(self, monkeypatch):
        monkeypatch.delenv("TERMUX_VERSION", raising=False)
        monkeypatch.setenv("PREFIX", "/usr")
        monkeypatch.setattr(sys, "platform", "linux")
        assert doctor._is_termux() is False
        assert doctor._python_install_cmd() == "uv pip install"
        assert doctor._system_package_install_cmd("ripgrep") == "sudo apt install ripgrep"


class TestProviderEnvDetection:
    def test_detects_openai_api_key(self):
        content = "OPENAI_BASE_URL=http://localhost:1234/v1\nOPENAI_API_KEY=***"
        assert _has_provider_env_config(content)

    def test_detects_custom_endpoint_without_openrouter_key(self):
        content = "OPENAI_BASE_URL=http://localhost:8080/v1\n"
        assert _has_provider_env_config(content)

    def test_detects_kimi_cn_api_key(self):
        content = "KIMI_CN_API_KEY=sk-test\n"
        assert _has_provider_env_config(content)

    def test_returns_false_when_no_provider_settings(self):
        content = "TERMINAL_ENV=local\n"
        assert not _has_provider_env_config(content)


class TestDoctorToolAvailabilityOverrides:
    def test_marks_honcho_available_when_configured(self, monkeypatch):
        monkeypatch.setattr(doctor, "_honcho_is_configured_for_doctor", lambda: True)

        available, unavailable = doctor._apply_doctor_tool_availability_overrides(
            [],
            [{"name": "honcho", "env_vars": [], "tools": ["query_user_context"]}],
        )

        assert available == ["honcho"]
        assert unavailable == []

    def test_leaves_honcho_unavailable_when_not_configured(self, monkeypatch):
        monkeypatch.setattr(doctor, "_honcho_is_configured_for_doctor", lambda: False)

        honcho_entry = {"name": "honcho", "env_vars": [], "tools": ["query_user_context"]}
        available, unavailable = doctor._apply_doctor_tool_availability_overrides(
            [],
            [honcho_entry],
        )

        assert available == []
        assert unavailable == [honcho_entry]


class TestHonchoDoctorConfigDetection:
    def test_reports_configured_when_enabled_with_api_key(self, monkeypatch):
        fake_config = SimpleNamespace(enabled=True, api_key="***")

        monkeypatch.setattr(
            "plugins.memory.honcho.client.HonchoClientConfig.from_global_config",
            lambda: fake_config,
        )

        assert doctor._honcho_is_configured_for_doctor()

    def test_reports_not_configured_without_api_key(self, monkeypatch):
        fake_config = SimpleNamespace(enabled=True, api_key="")

        monkeypatch.setattr(
            "plugins.memory.honcho.client.HonchoClientConfig.from_global_config",
            lambda: fake_config,
        )

        assert not doctor._honcho_is_configured_for_doctor()


def test_run_doctor_sets_interactive_env_for_tool_checks(monkeypatch, tmp_path):
    """Doctor should present CLI-gated tools as available in CLI context."""
    project_root = tmp_path / "project"
    elevate_home = tmp_path / ".elevate"
    project_root.mkdir()
    elevate_home.mkdir()

    monkeypatch.setattr(doctor_mod, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(doctor_mod, "ELEVATE_HOME", elevate_home)
    monkeypatch.delenv("ELEVATE_INTERACTIVE", raising=False)

    seen = {}

    def fake_check_tool_availability(*args, **kwargs):
        seen["interactive"] = os.getenv("ELEVATE_INTERACTIVE")
        raise SystemExit(0)

    fake_model_tools = types.SimpleNamespace(
        check_tool_availability=fake_check_tool_availability,
        TOOLSET_REQUIREMENTS={},
    )
    monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)

    with pytest.raises(SystemExit):
        doctor_mod.run_doctor(Namespace(fix=False))

    assert seen["interactive"] == "1"


def test_check_gateway_service_linger_warns_when_disabled(monkeypatch, tmp_path, capsys):
    unit_path = tmp_path / "elevate-gateway.service"
    unit_path.write_text("[Unit]\n")

    monkeypatch.setattr(gateway_cli, "is_linux", lambda: True)
    monkeypatch.setattr(gateway_cli, "get_systemd_unit_path", lambda: unit_path)
    monkeypatch.setattr(gateway_cli, "get_systemd_linger_status", lambda: (False, ""))

    issues = []
    doctor._check_gateway_service_linger(issues)

    out = capsys.readouterr().out
    assert "Gateway Service" in out
    assert "Systemd linger disabled" in out
    assert "loginctl enable-linger" in out
    assert issues == [
        "Enable linger for the gateway user service: sudo loginctl enable-linger $USER"
    ]


def test_check_gateway_service_linger_skips_when_service_not_installed(monkeypatch, tmp_path, capsys):
    unit_path = tmp_path / "missing.service"

    monkeypatch.setattr(gateway_cli, "is_linux", lambda: True)
    monkeypatch.setattr(gateway_cli, "get_systemd_unit_path", lambda: unit_path)

    issues = []
    doctor._check_gateway_service_linger(issues)

    out = capsys.readouterr().out
    assert out == ""
    assert issues == []


# ── Memory provider section (doctor should only check the *active* provider) ──


class TestDoctorMemoryProviderSection:
    """The ◆ Memory Provider section should respect memory.provider config."""

    def _make_elevate_home(self, tmp_path, provider=""):
        """Create a minimal ELEVATE_HOME with config.yaml."""
        home = tmp_path / ".elevate"
        home.mkdir(parents=True, exist_ok=True)
        import yaml
        config = {"memory": {"provider": provider}} if provider else {"memory": {}}
        (home / "config.yaml").write_text(yaml.dump(config))
        return home

    def _run_doctor_and_capture(self, monkeypatch, tmp_path, provider=""):
        """Run doctor and capture stdout."""
        home = self._make_elevate_home(tmp_path, provider)
        monkeypatch.setattr(doctor_mod, "ELEVATE_HOME", home)
        monkeypatch.setattr(doctor_mod, "PROJECT_ROOT", tmp_path / "project")
        monkeypatch.setattr(doctor_mod, "_DHH", str(home))
        (tmp_path / "project").mkdir(exist_ok=True)

        # Stub tool availability (returns empty) so doctor runs past it
        fake_model_tools = types.SimpleNamespace(
            check_tool_availability=lambda *a, **kw: ([], []),
            TOOLSET_REQUIREMENTS={},
        )
        monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)

        # Stub auth checks to avoid real API calls
        try:
            from elevate_cli import auth as _auth_mod
            monkeypatch.setattr(_auth_mod, "get_nous_auth_status", lambda: {})
            monkeypatch.setattr(_auth_mod, "get_codex_auth_status", lambda: {})
        except Exception:
            pass

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor_mod.run_doctor(Namespace(fix=False))
        return buf.getvalue()

    def test_no_provider_shows_builtin_ok(self, monkeypatch, tmp_path):
        out = self._run_doctor_and_capture(monkeypatch, tmp_path, provider="")
        assert "Memory Provider" in out
        assert "Built-in memory active" in out
        # Should NOT mention Honcho or Mem0 errors
        assert "Honcho API key" not in out
        assert "Mem0" not in out

    def test_honcho_provider_not_installed_shows_fail(self, monkeypatch, tmp_path):
        # Make honcho import fail
        monkeypatch.setitem(
            sys.modules, "plugins.memory.honcho.client", None
        )
        out = self._run_doctor_and_capture(monkeypatch, tmp_path, provider="honcho")
        assert "Memory Provider" in out
        # Should show failure since honcho is set but not importable
        assert "Built-in memory active" not in out

    def test_mem0_provider_not_installed_shows_fail(self, monkeypatch, tmp_path):
        # Make mem0 import fail
        monkeypatch.setitem(sys.modules, "plugins.memory.mem0", None)
        out = self._run_doctor_and_capture(monkeypatch, tmp_path, provider="mem0")
        assert "Memory Provider" in out
        assert "Built-in memory active" not in out


def test_run_doctor_termux_treats_docker_and_browser_warnings_as_expected(monkeypatch, tmp_path):
    helper = TestDoctorMemoryProviderSection()
    monkeypatch.setenv("TERMUX_VERSION", "0.118.3")
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")

    real_which = doctor_mod.shutil.which

    def fake_which(cmd):
        if cmd in {"docker", "node", "npm"}:
            return None
        return real_which(cmd)

    monkeypatch.setattr(doctor_mod.shutil, "which", fake_which)

    out = helper._run_doctor_and_capture(monkeypatch, tmp_path, provider="")

    assert "Docker backend is not available inside Termux" in out
    # Elevate is local-first now: doctor reports local browser mode and never
    # nags about the removed Browser Use cloud key.
    assert "Browser Use" not in out
    assert "BROWSER_USE_API_KEY" not in out
    assert "local mode" in out
    assert "Node.js not found (optional developer tooling in Termux)" in out
    assert "docker not found (optional)" not in out


def test_run_doctor_accepts_named_provider_from_providers_section(monkeypatch, tmp_path):
    home = tmp_path / ".elevate"
    home.mkdir(parents=True, exist_ok=True)

    import yaml

    (home / "config.yaml").write_text(
        yaml.dump(
            {
                "model": {
                    "provider": "volcengine-plan",
                    "default": "doubao-seed-2.0-code",
                },
                "providers": {
                    "volcengine-plan": {
                        "name": "volcengine-plan",
                        "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
                        "default_model": "doubao-seed-2.0-code",
                        "models": {"doubao-seed-2.0-code": {}},
                    }
                },
            }
        )
    )

    monkeypatch.setattr(doctor_mod, "ELEVATE_HOME", home)
    monkeypatch.setattr(doctor_mod, "PROJECT_ROOT", tmp_path / "project")
    monkeypatch.setattr(doctor_mod, "_DHH", str(home))
    (tmp_path / "project").mkdir(exist_ok=True)

    fake_model_tools = types.SimpleNamespace(
        check_tool_availability=lambda *a, **kw: ([], []),
        TOOLSET_REQUIREMENTS={},
    )
    monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)

    try:
        from elevate_cli import auth as _auth_mod
        monkeypatch.setattr(_auth_mod, "get_nous_auth_status", lambda: {})
        monkeypatch.setattr(_auth_mod, "get_codex_auth_status", lambda: {})
    except Exception:
        pass

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        doctor_mod.run_doctor(Namespace(fix=False))

    out = buf.getvalue()
    assert "model.provider 'volcengine-plan' is not a recognised provider" not in out


def test_run_doctor_termux_does_not_mark_browser_available_without_agent_browser(monkeypatch, tmp_path):
    home = tmp_path / ".elevate"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("memory: {}\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)

    monkeypatch.setenv("TERMUX_VERSION", "0.118.3")
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setattr(doctor_mod, "ELEVATE_HOME", home)
    monkeypatch.setattr(doctor_mod, "PROJECT_ROOT", project)
    monkeypatch.setattr(doctor_mod, "_DHH", str(home))
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda cmd: "/data/data/com.termux/files/usr/bin/node" if cmd in {"node", "npm"} else None)

    fake_model_tools = types.SimpleNamespace(
        check_tool_availability=lambda *a, **kw: (["terminal"], [{"name": "browser", "env_vars": [], "tools": ["browser_navigate"]}]),
        TOOLSET_REQUIREMENTS={
            "terminal": {"name": "terminal"},
            "browser": {"name": "browser"},
        },
    )
    monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)

    try:
        from elevate_cli import auth as _auth_mod
        monkeypatch.setattr(_auth_mod, "get_nous_auth_status", lambda: {})
        monkeypatch.setattr(_auth_mod, "get_codex_auth_status", lambda: {})
    except Exception:
        pass

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        doctor_mod.run_doctor(Namespace(fix=False))
    out = buf.getvalue()

    assert "✓ browser" not in out
    assert "browser" in out
    assert "system dependency not met" in out
    # Browser Use cloud removed — doctor is local-first and never references it.
    assert "Browser Use" not in out
    assert "BROWSER_USE_API_KEY" not in out


def test_run_doctor_kimi_cn_env_is_detected_and_probe_is_null_safe(monkeypatch, tmp_path):
    home = tmp_path / ".elevate"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("memory: {}\n", encoding="utf-8")
    (home / ".env").write_text("KIMI_CN_API_KEY=sk-test\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)

    monkeypatch.setattr(doctor_mod, "ELEVATE_HOME", home)
    monkeypatch.setattr(doctor_mod, "PROJECT_ROOT", project)
    monkeypatch.setattr(doctor_mod, "_DHH", str(home))
    monkeypatch.setenv("KIMI_CN_API_KEY", "sk-test")

    fake_model_tools = types.SimpleNamespace(
        check_tool_availability=lambda *a, **kw: ([], []),
        TOOLSET_REQUIREMENTS={},
    )
    monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)

    try:
        from elevate_cli import auth as _auth_mod
        monkeypatch.setattr(_auth_mod, "get_nous_auth_status", lambda: {})
        monkeypatch.setattr(_auth_mod, "get_codex_auth_status", lambda: {})
    except Exception:
        pass

    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append((url, headers, timeout))
        return types.SimpleNamespace(status_code=200)

    import httpx
    monkeypatch.setattr(httpx, "get", fake_get)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        doctor_mod.run_doctor(Namespace(fix=False))
    out = buf.getvalue()

    assert "API key or custom endpoint configured" in out
    assert "Kimi / Moonshot (China)" in out
    assert "str expected, not NoneType" not in out
    assert any(url == "https://api.moonshot.cn/v1/models" for url, _, _ in calls)


@pytest.mark.parametrize("base_url", [None, "https://opencode.ai/zen/go/v1"])
def test_run_doctor_opencode_go_skips_invalid_models_probe(monkeypatch, tmp_path, base_url):
    home = tmp_path / ".elevate"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("memory: {}\n", encoding="utf-8")
    (home / ".env").write_text("OPENCODE_GO_API_KEY=***\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)

    monkeypatch.setattr(doctor_mod, "ELEVATE_HOME", home)
    monkeypatch.setattr(doctor_mod, "PROJECT_ROOT", project)
    monkeypatch.setattr(doctor_mod, "_DHH", str(home))
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "sk-test")
    if base_url:
        monkeypatch.setenv("OPENCODE_GO_BASE_URL", base_url)
    else:
        monkeypatch.delenv("OPENCODE_GO_BASE_URL", raising=False)

    fake_model_tools = types.SimpleNamespace(
        check_tool_availability=lambda *a, **kw: ([], []),
        TOOLSET_REQUIREMENTS={},
    )
    monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)

    try:
        from elevate_cli import auth as _auth_mod
        monkeypatch.setattr(_auth_mod, "get_nous_auth_status", lambda: {})
        monkeypatch.setattr(_auth_mod, "get_codex_auth_status", lambda: {})
    except ImportError:
        pass

    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append((url, headers, timeout))
        return types.SimpleNamespace(status_code=200)

    import httpx
    monkeypatch.setattr(httpx, "get", fake_get)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        doctor_mod.run_doctor(Namespace(fix=False))
    out = buf.getvalue()

    assert any(
        "OpenCode Go" in line and "(key configured)" in line
        for line in out.splitlines()
    )
    assert not any(url == "https://opencode.ai/zen/go/v1/models" for url, _, _ in calls)
    assert not any("opencode" in url.lower() and "models" in url.lower() for url, _, _ in calls)


def _prepare_beta_doctor(monkeypatch, tmp_path, *, release_channel="beta"):
    home = tmp_path / ".elevate"
    home.mkdir(parents=True, exist_ok=True)
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)

    (home / "config.yaml").write_text(
        "provider: anthropic\n"
        "base_url: https://api.anthropic.com\n"
        "model:\n"
        "  provider: openrouter\n"
        "  default: anthropic/claude-sonnet-4\n"
        "memory: {}\n",
        encoding="utf-8",
    )
    (home / "auth.json").write_text(
        '{"providers":{"openai-codex":{"tokens":'
        '{"access_token":"local-token","refresh_token":"local-refresh"}}}}',
        encoding="utf-8",
    )

    provider_keys = (
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "GLM_API_KEY",
        "KIMI_API_KEY",
        "KIMI_CN_API_KEY",
        "STEPFUN_API_KEY",
        "ARCEEAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "HF_TOKEN",
        "NVIDIA_API_KEY",
        "DASHSCOPE_API_KEY",
        "MINIMAX_API_KEY",
        "MINIMAX_CN_API_KEY",
        "AI_GATEWAY_API_KEY",
        "KILOCODE_API_KEY",
        "OPENCODE_ZEN_API_KEY",
        "OPENCODE_GO_API_KEY",
    )
    (home / ".env").write_text(
        "".join(f"{key}=hostile-{key.lower()}\n" for key in provider_keys)
        + "FIRECRAWL_API_KEY=tool-firecrawl\n",
        encoding="utf-8",
    )
    for key in provider_keys:
        monkeypatch.setenv(key, f"hostile-{key.lower()}")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "hostile-aws-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "hostile-aws-secret")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "tool-firecrawl")
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", release_channel)
    monkeypatch.setenv("TERMINAL_ENV", "local")

    monkeypatch.setattr(doctor_mod, "ELEVATE_HOME", home)
    monkeypatch.setattr(doctor_mod, "PROJECT_ROOT", project)
    monkeypatch.setattr(doctor_mod, "_DHH", str(home))
    monkeypatch.setattr(doctor_mod, "_which", lambda _command: None)
    monkeypatch.setattr(doctor_mod, "_check_gateway_service_linger", lambda _issues: None)
    monkeypatch.setattr(doctor_mod, "_honcho_is_configured_for_doctor", lambda: False)

    fake_model_tools = types.SimpleNamespace(
        check_tool_availability=lambda *a, **kw: (["firecrawl"], []),
        TOOLSET_REQUIREMENTS={"firecrawl": {"name": "Firecrawl (tool credential)"}},
    )
    monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)

    from elevate_cli import debug_browser
    from elevate_cli import profiles

    monkeypatch.setattr(debug_browser, "is_supported", lambda: False)
    monkeypatch.setattr(profiles, "list_profiles", lambda: [])
    return home


def test_realtor_beta_doctor_never_reaches_alternate_provider_paths(
    monkeypatch,
    tmp_path,
):
    home = _prepare_beta_doctor(monkeypatch, tmp_path)

    def forbidden(name):
        def _forbidden(*_args, **_kwargs):
            raise AssertionError(f"unsupported provider path reached: {name}")

        return _forbidden

    from elevate_cli import auth as auth_mod
    from elevate_cli import config as config_mod
    from elevate_cli import providers as providers_mod
    from elevate_cli import xai_retirement
    from agent import bedrock_adapter
    import httpx

    unsupported_auth = (
        "get_nous_auth_status",
        "get_codex_auth_status",
        "get_gemini_oauth_auth_status",
        "get_minimax_oauth_auth_status",
        "get_xai_oauth_auth_status",
        "get_anthropic_key",
        "get_auth_status",
    )
    for name in unsupported_auth:
        monkeypatch.setattr(auth_mod, name, forbidden(name))
    monkeypatch.setattr(
        providers_mod,
        "resolve_provider_full",
        forbidden("resolve_provider_full"),
    )
    monkeypatch.setattr(config_mod, "check_config_version", lambda: (0, 999))
    monkeypatch.setattr(
        config_mod,
        "migrate_config",
        forbidden("generic config migration"),
    )
    monkeypatch.setattr(
        xai_retirement,
        "find_retired_xai_refs",
        forbidden("find_retired_xai_refs"),
    )
    monkeypatch.setattr(
        bedrock_adapter,
        "has_aws_credentials",
        forbidden("has_aws_credentials"),
    )
    monkeypatch.setattr(httpx, "get", forbidden("httpx.get"))
    monkeypatch.setattr(
        doctor_mod.subprocess,
        "run",
        forbidden("provider subprocess"),
    )
    monkeypatch.setitem(
        sys.modules,
        "model_tools",
        types.SimpleNamespace(
            check_tool_availability=forbidden("generic tool availability"),
            TOOLSET_REQUIREMENTS={},
        ),
    )

    actual_reader = doctor_mod.read_beta_codex_auth_status
    local_auth_reads = []

    def audited_local_reader(elevate_home):
        local_auth_reads.append(elevate_home)
        return actual_reader(elevate_home)

    monkeypatch.setattr(
        doctor_mod,
        "read_beta_codex_auth_status",
        audited_local_reader,
    )

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        doctor_mod.run_doctor(Namespace(fix=True))
    out = buf.getvalue()

    assert local_auth_reads == [home]
    assert "OpenAI Codex auth" in out
    assert "verified locally in this Beta profile" in out
    assert "Realtor Beta supports OpenAI Codex only" in out
    assert "inference-provider network probes disabled" in out
    assert "model.provider 'openrouter' is blocked by Realtor Beta policy" in out
    assert "model.default 'anthropic/claude-sonnet-4' is blocked" in out
    assert "Generic config auto-migration disabled in Realtor Beta" in out
    assert "Blocked root-level provider keys: provider, base_url" in out
    assert "Tool Availability" in out
    assert "Firecrawl tool credential" in out
    assert "configured; no network probe" in out
    assert "Submodules" not in out

    assert "Nous Portal auth" not in out
    assert "Google Gemini OAuth" not in out
    assert "MiniMax OAuth" not in out
    assert "xAI OAuth" not in out
    assert "xAI Model Retirement" not in out
    assert "OpenRouter API" not in out
    assert "Anthropic API" not in out
    assert "AWS Bedrock" not in out
    assert "Z.AI / GLM" not in out
    assert "Kimi / Moonshot" not in out

    config_after = (home / "config.yaml").read_text(encoding="utf-8")
    assert "provider: anthropic" in config_after
    assert "base_url: https://api.anthropic.com" in config_after


def test_realtor_beta_doctor_blocks_external_memory_without_loading_plugin(
    monkeypatch,
    tmp_path,
):
    home = _prepare_beta_doctor(monkeypatch, tmp_path)
    config_path = home / "config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "memory: {}",
            "memory:\n  provider: honcho",
        ),
        encoding="utf-8",
    )

    def forbidden(name):
        def _forbidden(*_args, **_kwargs):
            raise AssertionError(f"external memory path reached: {name}")

        return _forbidden

    from plugins import memory as memory_plugins
    from plugins.memory.honcho import client as honcho_client

    monkeypatch.setattr(
        honcho_client.HonchoClientConfig,
        "from_global_config",
        forbidden("HonchoClientConfig.from_global_config"),
    )
    monkeypatch.setattr(
        honcho_client,
        "get_honcho_client",
        forbidden("get_honcho_client"),
    )
    monkeypatch.setattr(
        memory_plugins,
        "load_memory_provider",
        forbidden("load_memory_provider"),
    )

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        doctor_mod.run_doctor(Namespace(fix=False))
    out = buf.getvalue()

    assert "Blocked stale memory provider 'honcho'" in out
    assert "Realtor Beta supports built-in or Holographic local memory only" in out
    assert "Honcho connected" not in out
    assert "Honcho API key" not in out


def test_nonexact_beta_doctor_preserves_generic_provider_diagnostics(
    monkeypatch,
    tmp_path,
):
    _prepare_beta_doctor(monkeypatch, tmp_path, release_channel="Beta")

    from elevate_cli import auth as auth_mod
    from agent import bedrock_adapter
    import httpx

    monkeypatch.setattr(auth_mod, "get_nous_auth_status", lambda: {})
    monkeypatch.setattr(auth_mod, "get_codex_auth_status", lambda: {})
    monkeypatch.setattr(auth_mod, "get_gemini_oauth_auth_status", lambda: {})
    monkeypatch.setattr(auth_mod, "get_minimax_oauth_auth_status", lambda: {})
    monkeypatch.setattr(auth_mod, "get_xai_oauth_auth_status", lambda: {})
    monkeypatch.setattr(auth_mod, "get_anthropic_key", lambda: None)
    monkeypatch.setattr(bedrock_adapter, "has_aws_credentials", lambda: False)

    http_calls = []

    def fake_get(url, headers=None, timeout=None):
        http_calls.append((url, headers, timeout))
        return types.SimpleNamespace(status_code=200)

    monkeypatch.setattr(httpx, "get", fake_get)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        doctor_mod.run_doctor(Namespace(fix=False))
    out = buf.getvalue()

    assert "Nous Portal auth" in out
    assert "Google Gemini OAuth" in out
    assert "MiniMax OAuth" in out
    assert "xAI OAuth" in out
    assert "OpenRouter API" in out
    assert any(url == doctor_mod.OPENROUTER_MODELS_URL for url, _, _ in http_calls)
