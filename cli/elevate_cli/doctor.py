"""
Doctor command for elevate CLI.

Diagnoses issues with Elevate setup.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

from elevate_cli.config import get_project_root, get_elevate_home, get_env_path
from elevate_constants import display_elevate_home

PROJECT_ROOT = get_project_root()
ELEVATE_HOME = get_elevate_home()
_DHH = display_elevate_home()  # user-facing display path (e.g. ~/.elevate or ~/.elevate/profiles/coder)

# Load environment variables from ~/.elevate/.env so API key checks work
from dotenv import load_dotenv
_env_path = get_env_path()
if _env_path.exists():
    try:
        load_dotenv(_env_path, encoding="utf-8")
    except UnicodeDecodeError:
        load_dotenv(_env_path, encoding="latin-1")
# Also try project .env as dev fallback
load_dotenv(PROJECT_ROOT / ".env", override=False, encoding="utf-8")

from elevate_cli.colors import Colors, color
from elevate_cli.models import _ELEVATE_USER_AGENT
from elevate_constants import OPENROUTER_MODELS_URL
from utils import base_url_host_matches


_PROVIDER_ENV_HINTS = (
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_TOKEN",
    "OPENAI_BASE_URL",
    "NOUS_API_KEY",
    "GLM_API_KEY",
    "ZAI_API_KEY",
    "Z_AI_API_KEY",
    "KIMI_API_KEY",
    "KIMI_CN_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
    "KILOCODE_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "HF_TOKEN",
    "AI_GATEWAY_API_KEY",
    "OPENCODE_ZEN_API_KEY",
    "OPENCODE_GO_API_KEY",
    "XIAOMI_API_KEY",
)


from elevate_constants import is_termux as _is_termux


def _which(command: str) -> str | None:
    """Platform-safe wrapper around ``shutil.which``.

    Tests monkeypatch ``sys.platform`` to ``win32`` on non-Windows hosts to
    validate Windows-specific skips.  ``shutil.which`` follows ``sys.platform``
    and may call ``_winapi`` in that state, which is unavailable on macOS/Linux.
    Treat that synthetic case as "not found" instead of crashing doctor.
    """
    try:
        return shutil.which(command)
    except AttributeError:
        if sys.platform == "win32" and os.name != "nt":
            return None
        raise


def _python_install_cmd() -> str:
    return "python -m pip install" if _is_termux() else "uv pip install"


def _system_package_install_cmd(pkg: str) -> str:
    if _is_termux():
        return f"pkg install {pkg}"
    if sys.platform == "darwin":
        return f"brew install {pkg}"
    return f"sudo apt install {pkg}"


def _browser_use_setup_steps() -> list[str]:
    return [
        "1) Run elevate setup and choose Browser Use",
        "2) Set BROWSER_USE_API_KEY, or activate managed Browser Use",
    ]


def _has_provider_env_config(content: str) -> bool:
    """Return True when ~/.elevate/.env contains provider auth/base URL settings."""
    return any(key in content for key in _PROVIDER_ENV_HINTS)


def _honcho_is_configured_for_doctor() -> bool:
    """Return True when Honcho is configured, even if this process has no active session."""
    try:
        from plugins.memory.honcho.client import HonchoClientConfig

        cfg = HonchoClientConfig.from_global_config()
        return bool(cfg.enabled and (cfg.api_key or cfg.base_url))
    except Exception:
        return False


def _apply_doctor_tool_availability_overrides(available: list[str], unavailable: list[dict]) -> tuple[list[str], list[dict]]:
    """Adjust runtime-gated tool availability for doctor diagnostics."""
    if not _honcho_is_configured_for_doctor():
        return available, unavailable

    updated_available = list(available)
    updated_unavailable = []
    for item in unavailable:
        if item.get("name") == "honcho":
            if "honcho" not in updated_available:
                updated_available.append("honcho")
            continue
        updated_unavailable.append(item)
    return updated_available, updated_unavailable


def check_ok(text: str, detail: str = ""):
    print(f"  {color('✓', Colors.GREEN)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))

def check_warn(text: str, detail: str = ""):
    print(f"  {color('⚠', Colors.YELLOW)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))

def check_fail(text: str, detail: str = ""):
    print(f"  {color('✗', Colors.RED)} {text}" + (f" {color(detail, Colors.DIM)}" if detail else ""))

def check_info(text: str):
    print(f"    {color('→', Colors.CYAN)} {text}")


def _check_gateway_service_linger(issues: list[str]) -> None:
    """Warn when a systemd user gateway service will stop after logout."""
    try:
        from elevate_cli.gateway import (
            get_systemd_linger_status,
            get_systemd_unit_path,
            is_linux,
        )
    except Exception as e:
        check_warn("Gateway service linger", f"(could not import gateway helpers: {e})")
        return

    if not is_linux():
        return

    unit_path = get_systemd_unit_path()
    if not unit_path.exists():
        return

    print()
    print(color("◆ Gateway Service", Colors.CYAN, Colors.BOLD))

    linger_enabled, linger_detail = get_systemd_linger_status()
    if linger_enabled is True:
        check_ok("Systemd linger enabled", "(gateway service survives logout)")
    elif linger_enabled is False:
        check_warn("Systemd linger disabled", "(gateway may stop after logout)")
        check_info("Run: sudo loginctl enable-linger $USER")
        issues.append("Enable linger for the gateway user service: sudo loginctl enable-linger $USER")
    else:
        check_warn("Could not verify systemd linger", f"({linger_detail})")


def run_doctor(args):
    """Run diagnostic checks."""
    should_fix = getattr(args, 'fix', False)
    ack_target = getattr(args, 'ack', None)

    # Doctor runs from the interactive CLI, so CLI-gated tool availability
    # checks (like cronjob management) should see the same context as `elevate`.
    os.environ.setdefault("ELEVATE_INTERACTIVE", "1")

    # Handle `elevate doctor --ack <id>` as a fast path. Persist the ack and
    # return without running the rest of the diagnostics — the user has
    # already seen the advisory and just wants to silence it.
    if ack_target:
        try:
            from elevate_cli.security_advisories import (
                ADVISORIES,
                ack_advisory,
            )
        except Exception as e:
            print(color(f"Security advisory module unavailable: {e}", Colors.RED))
            sys.exit(1)
        valid_ids = {a.id for a in ADVISORIES}
        if ack_target not in valid_ids:
            print(color(
                f"Unknown advisory ID: {ack_target!r}. Known IDs: "
                f"{', '.join(sorted(valid_ids)) or '(none)'}",
                Colors.RED,
            ))
            sys.exit(2)
        if ack_advisory(ack_target):
            print(color(
                f"  ✓ Acknowledged advisory {ack_target}. "
                f"It will no longer trigger startup banners.",
                Colors.GREEN,
            ))
        else:
            print(color(
                f"  ✗ Failed to persist ack for {ack_target}. "
                f"Check ~/.elevate/config.yaml is writable.",
                Colors.RED,
            ))
            sys.exit(1)
        return

    issues = []
    manual_issues = []  # issues that can't be auto-fixed
    fixed_count = 0

    print()
    print(color("┌─────────────────────────────────────────────────────────┐", Colors.CYAN))
    print(color("│                 🩺 Elevate Doctor                        │", Colors.CYAN))
    print(color("└─────────────────────────────────────────────────────────┘", Colors.CYAN))

    # =========================================================================
    # Check: Security advisories (compromised packages on disk)
    # =========================================================================
    print()
    print(color("◆ Security Advisories", Colors.CYAN, Colors.BOLD))
    try:
        from elevate_cli.security_advisories import (
            detect_compromised,
            filter_unacked,
            full_remediation_text,
            get_acked_ids,
        )
        all_hits = detect_compromised()
        fresh_hits = filter_unacked(all_hits)
        if fresh_hits:
            for hit in fresh_hits:
                check_fail(
                    f"{hit.advisory.title}",
                    f"({hit.package}=={hit.installed_version})",
                )
                # Print the full remediation block, indented under the
                # check_fail header so it reads as a single section.
                for line in full_remediation_text(hit):
                    if line:
                        print(f"    {color(line, Colors.YELLOW)}")
                    else:
                        print()
                # Funnel into the action list so the summary block surfaces it
                # for users who scroll past the section.
                manual_issues.append(
                    f"Resolve security advisory {hit.advisory.id}: "
                    f"uninstall {hit.package}=={hit.installed_version} and "
                    f"rotate credentials, then run "
                    f"`elevate doctor --ack {hit.advisory.id}`."
                )
            # Acked-but-still-installed: show as informational so the user
            # knows the package is still on disk after the ack.
            acked_ids = get_acked_ids()
            for h in all_hits:
                if h.advisory.id in acked_ids:
                    check_warn(
                        f"{h.package}=={h.installed_version} still installed "
                        f"(advisory {h.advisory.id} acknowledged)",
                    )
        else:
            check_ok("No active security advisories")
    except Exception as e:
        # Never let a bug in the advisory check block the rest of doctor.
        check_warn(f"Security advisory check failed: {e}")

    # =========================================================================
    # Check: Python version
    # =========================================================================
    print()
    print(color("◆ Python Environment", Colors.CYAN, Colors.BOLD))
    
    py_version = sys.version_info
    if py_version >= (3, 11):
        check_ok(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}")
    elif py_version >= (3, 10):
        check_ok(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}")
        check_warn("Python 3.11+ recommended for RL Training tools (tinker requires >= 3.11)")
    elif py_version >= (3, 8):
        check_warn(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}", "(3.10+ recommended)")
    else:
        check_fail(f"Python {py_version.major}.{py_version.minor}.{py_version.micro}", "(3.10+ required)")
        issues.append("Upgrade Python to 3.10+")
    
    # Check if in virtual environment
    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        check_ok("Virtual environment active")
    else:
        check_warn("Not in virtual environment", "(recommended)")
    
    # =========================================================================
    # Check: Required packages
    # =========================================================================
    print()
    print(color("◆ Required Packages", Colors.CYAN, Colors.BOLD))
    
    required_packages = [
        ("openai", "OpenAI SDK"),
        ("rich", "Rich (terminal UI)"),
        ("dotenv", "python-dotenv"),
        ("yaml", "PyYAML"),
        ("httpx", "HTTPX"),
    ]
    
    optional_packages = [
        ("croniter", "Croniter (cron expressions)"),
        ("telegram", "python-telegram-bot"),
        ("discord", "discord.py"),
    ]
    
    for module, name in required_packages:
        try:
            __import__(module)
            check_ok(name)
        except ImportError:
            check_fail(name, "(missing)")
            issues.append(f"Install {name}: {_python_install_cmd()} {module}")
    
    for module, name in optional_packages:
        try:
            __import__(module)
            check_ok(name, "(optional)")
        except ImportError:
            check_warn(name, "(optional, not installed)")
    
    # =========================================================================
    # Check: Configuration files
    # =========================================================================
    print()
    print(color("◆ Configuration Files", Colors.CYAN, Colors.BOLD))
    
    # Check ~/.elevate/.env (primary location for user config)
    env_path = ELEVATE_HOME / '.env'
    if env_path.exists():
        check_ok(f"{_DHH}/.env file exists")
        
        # Check for common issues
        content = env_path.read_text()
        if _has_provider_env_config(content):
            check_ok("API key or custom endpoint configured")
        else:
            check_warn(f"No API key found in {_DHH}/.env")
            issues.append("Run 'elevate setup' to configure API keys")
    else:
        # Also check project root as fallback
        fallback_env = PROJECT_ROOT / '.env'
        if fallback_env.exists():
            check_ok(".env file exists (in project directory)")
        else:
            check_fail(f"{_DHH}/.env file missing")
            if should_fix:
                env_path.parent.mkdir(parents=True, exist_ok=True)
                env_path.touch()
                check_ok(f"Created empty {_DHH}/.env")
                check_info("Run 'elevate setup' to configure API keys")
                fixed_count += 1
            else:
                check_info("Run 'elevate setup' to create one")
                issues.append("Run 'elevate setup' to create .env")
    
    # Check ~/.elevate/config.yaml (primary) or project cli-config.yaml (fallback)
    config_path = ELEVATE_HOME / 'config.yaml'
    if config_path.exists():
        check_ok(f"{_DHH}/config.yaml exists")

        # Validate model.provider and model.default values
        try:
            import yaml as _yaml
            cfg = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            model_section = cfg.get("model") or {}
            provider_raw = (model_section.get("provider") or "").strip()
            provider = provider_raw.lower()
            default_model = (model_section.get("default") or model_section.get("model") or "").strip()

            known_providers: set = set()
            try:
                from elevate_cli.auth import PROVIDER_REGISTRY
                known_providers = set(PROVIDER_REGISTRY.keys()) | {"openrouter", "custom", "auto"}
            except Exception:
                pass
            try:
                from elevate_cli.config import get_compatible_custom_providers as _compatible_custom_providers
                from elevate_cli.providers import resolve_provider_full as _resolve_provider_full
            except Exception:
                _compatible_custom_providers = None
                _resolve_provider_full = None

            custom_providers = []
            if _compatible_custom_providers is not None:
                try:
                    custom_providers = _compatible_custom_providers(cfg)
                except Exception:
                    custom_providers = []

            user_providers = cfg.get("providers")
            if isinstance(user_providers, dict):
                known_providers.update(str(name).strip().lower() for name in user_providers if str(name).strip())
            for entry in custom_providers:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name") or "").strip()
                if name:
                    known_providers.add("custom:" + name.lower().replace(" ", "-"))

            canonical_provider = provider
            if provider and _resolve_provider_full is not None and provider != "auto":
                provider_def = _resolve_provider_full(provider, user_providers, custom_providers)
                canonical_provider = provider_def.id if provider_def is not None else None

            if provider and provider != "auto":
                if canonical_provider is None or (known_providers and canonical_provider not in known_providers):
                    known_list = ", ".join(sorted(known_providers)) if known_providers else "(unavailable)"
                    check_fail(
                        f"model.provider '{provider_raw}' is not a recognised provider",
                        f"(known: {known_list})",
                    )
                    issues.append(
                        f"model.provider '{provider_raw}' is unknown. "
                        f"Valid providers: {known_list}. "
                        f"Fix: run 'elevate config set model.provider <valid_provider>'"
                    )

            # Warn if model is set to a provider-prefixed name on a provider that doesn't use them
            if default_model and "/" in default_model and canonical_provider and canonical_provider not in ("openrouter", "custom", "auto", "ai-gateway", "kilocode", "opencode-zen", "huggingface", "nous"):
                check_warn(
                    f"model.default '{default_model}' uses a vendor/model slug but provider is '{provider_raw}'",
                    "(vendor-prefixed slugs belong to aggregators like openrouter)",
                )
                issues.append(
                    f"model.default '{default_model}' is vendor-prefixed but model.provider is '{provider_raw}'. "
                    "Either set model.provider to 'openrouter', or drop the vendor prefix."
                )

            # Check credentials for the configured provider.
            # Limit to API-key providers in PROVIDER_REGISTRY — other provider
            # types (OAuth, SDK, openrouter/anthropic/custom/auto) have their
            # own env-var checks elsewhere in doctor, and get_auth_status()
            # returns a bare {logged_in: False} for anything it doesn't
            # explicitly dispatch, which would produce false positives.
            if canonical_provider and canonical_provider not in ("auto", "custom", "openrouter"):
                try:
                    from elevate_cli.auth import PROVIDER_REGISTRY, get_auth_status
                    pconfig = PROVIDER_REGISTRY.get(canonical_provider)
                    if pconfig and getattr(pconfig, "auth_type", "") == "api_key":
                        status = get_auth_status(canonical_provider) or {}
                        configured = bool(status.get("configured") or status.get("logged_in") or status.get("api_key"))
                        if not configured:
                            check_fail(
                                f"model.provider '{canonical_provider}' is set but no API key is configured",
                                "(check ~/.elevate/.env or run 'elevate setup')",
                            )
                            issues.append(
                                f"No credentials found for provider '{canonical_provider}'. "
                                f"Run 'elevate setup' or set the provider's API key in {_DHH}/.env, "
                                f"or switch providers with 'elevate config set model.provider <name>'"
                            )
                except Exception:
                    pass

        except Exception as e:
            check_warn("Could not validate model/provider config", f"({e})")
    else:
        fallback_config = PROJECT_ROOT / 'cli-config.yaml'
        if fallback_config.exists():
            check_ok("cli-config.yaml exists (in project directory)")
        else:
            example_config = PROJECT_ROOT / 'cli-config.yaml.example'
            if should_fix and example_config.exists():
                config_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(example_config), str(config_path))
                check_ok(f"Created {_DHH}/config.yaml from cli-config.yaml.example")
                fixed_count += 1
            elif should_fix:
                check_warn("config.yaml not found and no example to copy from")
                manual_issues.append(f"Create {_DHH}/config.yaml manually")
            else:
                check_warn("config.yaml not found", "(using defaults)")

    # Check config version and stale keys
    config_path = ELEVATE_HOME / 'config.yaml'
    if config_path.exists():
        try:
            from elevate_cli.config import check_config_version, migrate_config
            current_ver, latest_ver = check_config_version()
            if current_ver < latest_ver:
                check_warn(
                    f"Config version outdated (v{current_ver} → v{latest_ver})",
                    "(new settings available)"
                )
                if should_fix:
                    try:
                        migrate_config(interactive=False, quiet=False)
                        check_ok("Config migrated to latest version")
                        fixed_count += 1
                    except Exception as mig_err:
                        check_warn(f"Auto-migration failed: {mig_err}")
                        issues.append("Run 'elevate setup' to migrate config")
                else:
                    issues.append("Run 'elevate doctor --fix' or 'elevate setup' to migrate config")
            else:
                check_ok(f"Config version up to date (v{current_ver})")
        except Exception:
            pass

        # Detect stale root-level model keys (known bug source — PR #4329)
        try:
            import yaml
            with open(config_path) as f:
                raw_config = yaml.safe_load(f) or {}
            stale_root_keys = [k for k in ("provider", "base_url") if k in raw_config and isinstance(raw_config[k], str)]
            if stale_root_keys:
                check_warn(
                    f"Stale root-level config keys: {', '.join(stale_root_keys)}",
                    "(should be under 'model:' section)"
                )
                if should_fix:
                    model_section = raw_config.setdefault("model", {})
                    for k in stale_root_keys:
                        if not model_section.get(k):
                            model_section[k] = raw_config.pop(k)
                        else:
                            raw_config.pop(k)
                    from utils import atomic_yaml_write
                    atomic_yaml_write(config_path, raw_config)
                    check_ok("Migrated stale root-level keys into model section")
                    fixed_count += 1
                else:
                    issues.append("Stale root-level provider/base_url in config.yaml — run 'elevate doctor --fix'")
        except Exception:
            pass

        # Detect stale platform_toolsets allowlists that predate a shipped
        # toolset (the bug that hid the browser toolset). When a platform has
        # an explicit allowlist, absorb any builtin toolset that is new since
        # it was written, then record the known set so future user-disables
        # still stick.
        try:
            import yaml
            from elevate_cli.tools_config import (
                CONFIGURABLE_TOOLSETS,
                _DEFAULT_OFF_TOOLSETS,
            )
            with open(config_path) as f:
                ts_config = yaml.safe_load(f) or {}
            builtin_keys = {k for k, _, _ in CONFIGURABLE_TOOLSETS}
            shipped = builtin_keys - set(_DEFAULT_OFF_TOOLSETS)
            platform_toolsets = ts_config.get("platform_toolsets") or {}
            known_map = ts_config.get("known_builtin_toolsets") or {}
            stale_platforms = []
            for platform, ts_list in platform_toolsets.items():
                if not isinstance(ts_list, list):
                    continue
                listed = {str(t) for t in ts_list}
                # Explicit allowlist = lists at least one configurable key.
                if not (listed & builtin_keys):
                    continue
                known = set(known_map.get(platform, []))
                missing = {
                    k for k in shipped
                    if k not in listed and k not in known
                }
                if missing:
                    stale_platforms.append((platform, missing))
            if stale_platforms:
                names = ", ".join(
                    f"{p} (+{', '.join(sorted(m))})" for p, m in stale_platforms
                )
                check_warn(
                    "platform_toolsets allowlist missing shipped toolsets",
                    f"({names})",
                )
                if should_fix:
                    for platform, missing in stale_platforms:
                        cur = [str(t) for t in platform_toolsets.get(platform, [])]
                        ts_config["platform_toolsets"][platform] = sorted(
                            set(cur) | missing
                        )
                    ts_config.setdefault("known_builtin_toolsets", {})
                    for platform in platform_toolsets:
                        ts_config["known_builtin_toolsets"][platform] = sorted(
                            builtin_keys
                        )
                    from utils import atomic_yaml_write
                    atomic_yaml_write(config_path, ts_config)
                    check_ok("Absorbed shipped toolsets into platform allowlists")
                    fixed_count += 1
                else:
                    issues.append(
                        "platform_toolsets allowlist is stale — run 'elevate doctor --fix'"
                    )
        except Exception:
            pass

        # Validate config structure (catches malformed custom_providers, etc.)
        try:
            from elevate_cli.config import validate_config_structure
            config_issues = validate_config_structure()
            if config_issues:
                print()
                print(color("◆ Config Structure", Colors.CYAN, Colors.BOLD))
                for ci in config_issues:
                    if ci.severity == "error":
                        check_fail(ci.message)
                    else:
                        check_warn(ci.message)
                    # Show the hint indented
                    for hint_line in ci.hint.splitlines():
                        check_info(hint_line)
                    issues.append(ci.message)
        except Exception:
            pass

    # =========================================================================
    # Check: xAI Model Retirement (May 15, 2026)
    # =========================================================================
    print()
    print(color("◆ xAI Model Retirement (May 15, 2026)", Colors.CYAN, Colors.BOLD))
    try:
        from elevate_cli.config import load_config
        from elevate_cli.xai_retirement import (
            MIGRATION_GUIDE_URL,
            find_retired_xai_refs,
            format_issue,
        )

        _xai_cfg = load_config()
        retired_refs = find_retired_xai_refs(_xai_cfg)
        if not retired_refs:
            check_ok("No retired xAI models in config")
        else:
            for ref in retired_refs:
                check_warn(format_issue(ref))
            check_info(f"Migration guide: {MIGRATION_GUIDE_URL}")
            manual_issues.append(
                f"Update {len(retired_refs)} retired xAI model reference(s) "
                f"in config.yaml — see {MIGRATION_GUIDE_URL}"
            )
    except Exception as _xai_check_err:
        check_warn("xAI retirement check skipped", f"({_xai_check_err})")

    # =========================================================================
    # Check: Auth providers
    # =========================================================================
    print()
    print(color("◆ Auth Providers", Colors.CYAN, Colors.BOLD))

    try:
        from elevate_cli.auth import (
            get_nous_auth_status,
            get_codex_auth_status,
            get_gemini_oauth_auth_status,
        )

        nous_status = get_nous_auth_status()
        if nous_status.get("logged_in"):
            check_ok("Nous Portal auth", "(logged in)")
        else:
            check_warn("Nous Portal auth", "(not logged in)")

        codex_status = get_codex_auth_status()
        if codex_status.get("logged_in"):
            check_ok("OpenAI Codex auth", "(logged in)")
        else:
            check_warn("OpenAI Codex auth", "(not logged in)")
            if codex_status.get("error"):
                check_info(codex_status["error"])

        gemini_status = get_gemini_oauth_auth_status()
        if gemini_status.get("logged_in"):
            email = gemini_status.get("email") or ""
            project = gemini_status.get("project_id") or ""
            pieces = []
            if email:
                pieces.append(email)
            if project:
                pieces.append(f"project={project}")
            suffix = f" ({', '.join(pieces)})" if pieces else ""
            check_ok("Google Gemini OAuth", f"(logged in{suffix})")
        else:
            check_warn("Google Gemini OAuth", "(not logged in)")
    except Exception as e:
        check_warn("Auth provider status", f"(could not check: {e})")

    # MiniMax OAuth — separate try/except so an import failure here cannot
    # disrupt the already-printed Nous/Codex/Gemini rows above.
    try:
        from elevate_cli.auth import get_minimax_oauth_auth_status
        minimax_status = get_minimax_oauth_auth_status() or {}
        if minimax_status.get("logged_in"):
            region = minimax_status.get("region", "global")
            check_ok("MiniMax OAuth", f"(logged in, region={region})")
        else:
            check_warn("MiniMax OAuth", "(not logged in)")
    except Exception:
        pass

    # xAI OAuth — separate try/except so an import failure here cannot
    # disrupt the already-printed rows above.
    try:
        from elevate_cli.auth import get_xai_oauth_auth_status
        xai_oauth_status = get_xai_oauth_auth_status() or {}
        if xai_oauth_status.get("logged_in"):
            check_ok("xAI OAuth", "(logged in)")
        else:
            check_warn("xAI OAuth", "(not logged in)")
            if xai_oauth_status.get("error"):
                check_info(xai_oauth_status["error"])
    except Exception:
        pass

    if _which("codex"):
        check_ok("codex CLI")
    else:
        check_warn("codex CLI not found", "(required for openai-codex login)")

    # =========================================================================
    # Check: Directory structure
    # =========================================================================
    print()
    print(color("◆ Directory Structure", Colors.CYAN, Colors.BOLD))
    
    elevate_home = ELEVATE_HOME
    if elevate_home.exists():
        check_ok(f"{_DHH} directory exists")
    else:
        if should_fix:
            elevate_home.mkdir(parents=True, exist_ok=True)
            check_ok(f"Created {_DHH} directory")
            fixed_count += 1
        else:
            check_warn(f"{_DHH} not found", "(will be created on first use)")
    
    # Check expected subdirectories
    expected_subdirs = ["cron", "sessions", "logs", "skills", "memories"]
    for subdir_name in expected_subdirs:
        subdir_path = elevate_home / subdir_name
        if subdir_path.exists():
            check_ok(f"{_DHH}/{subdir_name}/ exists")
        else:
            if should_fix:
                subdir_path.mkdir(parents=True, exist_ok=True)
                check_ok(f"Created {_DHH}/{subdir_name}/")
                fixed_count += 1
            else:
                check_warn(f"{_DHH}/{subdir_name}/ not found", "(will be created on first use)")
    
    # Check for SOUL.md persona file
    from elevate_cli.default_soul import DEFAULT_SOUL_MD, is_placeholder_soul

    soul_path = elevate_home / "SOUL.md"
    if soul_path.exists() and not is_placeholder_soul(
        soul_path.read_text(encoding="utf-8")
    ):
        check_ok(f"{_DHH}/SOUL.md exists (persona configured)")
    else:
        if soul_path.exists():
            check_warn(
                f"{_DHH}/SOUL.md is a blank placeholder",
                "(no persona — agent runs on the bare model default)",
            )
        else:
            check_warn(
                f"{_DHH}/SOUL.md not found",
                "(create it to give Elevate a custom personality)",
            )
        if should_fix:
            soul_path.parent.mkdir(parents=True, exist_ok=True)
            soul_path.write_text(DEFAULT_SOUL_MD, encoding="utf-8")
            check_ok(f"Seeded {_DHH}/SOUL.md with the default Elevate persona")
            fixed_count += 1
    
    # Check visible debug browser (macOS only)
    try:
        from elevate_cli import debug_browser as _db

        if _db.is_supported() and _db.chrome_binary() is not None:
            st = _db.status()
            if st["cdp_up"] and st["cdp_url_config"]:
                check_ok("Visible debug browser running (agent drives a window you can see)")
            elif st["debug_profile_exists"]:
                # Profile already cloned — a lightweight relaunch is safe.
                check_warn(
                    "Visible debug browser not running",
                    "(browser tool would fall back to hidden headless Chromium)",
                )
                if should_fix:
                    _db.install_launch_agent()
                    _db.set_cdp_config(True)
                    if _db.launch_chrome(wait=True):
                        check_ok("Relaunched the visible debug browser")
                        fixed_count += 1
                else:
                    issues.append(
                        "Visible debug browser is down — run 'elevate doctor --fix'"
                    )
            else:
                check_info(
                    "Visible debug browser not set up — run 'elevate browser setup' "
                    "so the agent drives a window you can watch, logged in as you"
                )
    except Exception:
        pass

    # Check memory directory
    memories_dir = elevate_home / "memories"
    if memories_dir.exists():
        check_ok(f"{_DHH}/memories/ directory exists")
        memory_file = memories_dir / "MEMORY.md"
        user_file = memories_dir / "USER.md"
        if memory_file.exists():
            size = len(memory_file.read_text(encoding="utf-8").strip())
            check_ok(f"MEMORY.md exists ({size} chars)")
        else:
            check_info("MEMORY.md not created yet (will be created when the agent first writes a memory)")
        if user_file.exists():
            size = len(user_file.read_text(encoding="utf-8").strip())
            check_ok(f"USER.md exists ({size} chars)")
        else:
            check_info("USER.md not created yet (will be created when the agent first writes a memory)")
    else:
        check_warn(f"{_DHH}/memories/ not found", "(will be created on first use)")
        if should_fix:
            memories_dir.mkdir(parents=True, exist_ok=True)
            check_ok(f"Created {_DHH}/memories/")
            fixed_count += 1
    
    # Check SQLite session store
    state_db_path = elevate_home / "state.db"
    if state_db_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(state_db_path))
            cursor = conn.execute("SELECT COUNT(*) FROM sessions")
            count = cursor.fetchone()[0]
            conn.close()
            check_ok(f"{_DHH}/state.db exists ({count} sessions)")
        except Exception as e:
            check_warn(f"{_DHH}/state.db exists but has issues: {e}")
    else:
        check_info(f"{_DHH}/state.db not created yet (will be created on first session)")

    # Check WAL file size (unbounded growth indicates missed checkpoints)
    wal_path = elevate_home / "state.db-wal"
    if wal_path.exists():
        try:
            wal_size = wal_path.stat().st_size
            if wal_size > 50 * 1024 * 1024:  # 50 MB
                check_warn(
                    f"WAL file is large ({wal_size // (1024*1024)} MB)",
                    "(may indicate missed checkpoints)"
                )
                if should_fix:
                    import sqlite3
                    conn = sqlite3.connect(str(state_db_path))
                    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    conn.close()
                    new_size = wal_path.stat().st_size if wal_path.exists() else 0
                    check_ok(f"WAL checkpoint performed ({wal_size // 1024}K → {new_size // 1024}K)")
                    fixed_count += 1
                else:
                    issues.append("Large WAL file — run 'elevate doctor --fix' to checkpoint")
            elif wal_size > 10 * 1024 * 1024:  # 10 MB
                check_info(f"WAL file is {wal_size // (1024*1024)} MB (normal for active sessions)")
        except Exception:
            pass

    _check_gateway_service_linger(issues)

    # =========================================================================
    # Check: Command installation (elevate bin symlink)
    # =========================================================================
    if sys.platform != "win32":
        print()
        print(color("◆ Command Installation", Colors.CYAN, Colors.BOLD))

        # Determine the venv entry point location
        _venv_bin = None
        for _venv_name in ("venv", ".venv"):
            _candidate = PROJECT_ROOT / _venv_name / "bin" / "elevate"
            if _candidate.exists():
                _venv_bin = _candidate
                break

        # Determine the expected command link directory (mirrors install.sh logic)
        _prefix = os.environ.get("PREFIX", "")
        _is_termux_env = bool(os.environ.get("TERMUX_VERSION")) or "com.termux/files/usr" in _prefix
        if _is_termux_env and _prefix:
            _cmd_link_dir = Path(_prefix) / "bin"
            _cmd_link_display = "$PREFIX/bin"
        else:
            _cmd_link_dir = Path.home() / ".local" / "bin"
            _cmd_link_display = "~/.local/bin"
        _cmd_link = _cmd_link_dir / "elevate"

        if _venv_bin is None:
            check_warn(
                "Venv entry point not found",
                "(elevate not in venv/bin/ or .venv/bin/ — reinstall with pip install -e '.[all]')"
            )
            manual_issues.append(
                f"Reinstall entry point: cd {PROJECT_ROOT} && source venv/bin/activate && pip install -e '.[all]'"
            )
        else:
            check_ok(f"Venv entry point exists ({_venv_bin.relative_to(PROJECT_ROOT)})")

            # Check the symlink at the command link location
            if _cmd_link.is_symlink():
                _target = _cmd_link.resolve()
                _expected = _venv_bin.resolve()
                if _target == _expected:
                    check_ok(f"{_cmd_link_display}/elevate → correct target")
                else:
                    check_warn(
                        f"{_cmd_link_display}/elevate points to wrong target",
                        f"(→ {_target}, expected → {_expected})"
                    )
                    if should_fix:
                        _cmd_link.unlink()
                        _cmd_link.symlink_to(_venv_bin)
                        check_ok(f"Fixed symlink: {_cmd_link_display}/elevate → {_venv_bin}")
                        fixed_count += 1
                    else:
                        issues.append(f"Broken symlink at {_cmd_link_display}/elevate — run 'elevate doctor --fix'")
            elif _cmd_link.exists():
                # It's a regular file, not a symlink — possibly a wrapper script
                check_ok(f"{_cmd_link_display}/elevate exists (non-symlink)")
            else:
                check_fail(
                    f"{_cmd_link_display}/elevate not found",
                    "(elevate command may not work outside the venv)"
                )
                if should_fix:
                    _cmd_link_dir.mkdir(parents=True, exist_ok=True)
                    _cmd_link.symlink_to(_venv_bin)
                    check_ok(f"Created symlink: {_cmd_link_display}/elevate → {_venv_bin}")
                    fixed_count += 1

                    # Check if the link dir is on PATH
                    _path_dirs = os.environ.get("PATH", "").split(os.pathsep)
                    if str(_cmd_link_dir) not in _path_dirs:
                        check_warn(
                            f"{_cmd_link_display} is not on your PATH",
                            "(add it to your shell config: export PATH=\"$HOME/.local/bin:$PATH\")"
                        )
                        manual_issues.append(f"Add {_cmd_link_display} to your PATH")
                else:
                    issues.append(f"Missing {_cmd_link_display}/elevate symlink — run 'elevate doctor --fix'")

    # =========================================================================
    # Check: External tools
    # =========================================================================
    print()
    print(color("◆ External Tools", Colors.CYAN, Colors.BOLD))
    
    # Git
    if _which("git"):
        check_ok("git")
    else:
        check_warn("git not found", "(optional)")
    
    # ripgrep (optional, for faster file search)
    if _which("rg"):
        check_ok("ripgrep (rg)", "(faster file search)")
    else:
        check_warn("ripgrep (rg) not found", "(file search uses grep fallback)")
        check_info(f"Install for faster search: {_system_package_install_cmd('ripgrep')}")
    
    # Docker (optional)
    terminal_env = os.getenv("TERMINAL_ENV", "local")
    if terminal_env == "docker":
        if _which("docker"):
            # Check if docker daemon is running
            try:
                result = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
            except subprocess.TimeoutExpired:
                result = None
            if result is not None and result.returncode == 0:
                check_ok("docker", "(daemon running)")
            else:
                check_fail("docker daemon not running")
                issues.append("Start Docker daemon")
        else:
            check_fail("docker not found", "(required for TERMINAL_ENV=docker)")
            issues.append("Install Docker or change TERMINAL_ENV")
    else:
        if _which("docker"):
            check_ok("docker", "(optional)")
        else:
            if _is_termux():
                check_info("Docker backend is not available inside Termux (expected on Android)")
            else:
                check_warn("docker not found", "(optional)")
    
    # SSH (if using ssh backend)
    if terminal_env == "ssh":
        ssh_host = os.getenv("TERMINAL_SSH_HOST")
        if ssh_host:
            # Try to connect
            try:
                result = subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", ssh_host, "echo ok"],
                    capture_output=True,
                    text=True,
                    timeout=15
                )
            except subprocess.TimeoutExpired:
                result = None
            if result is not None and result.returncode == 0:
                check_ok(f"SSH connection to {ssh_host}")
            else:
                check_fail(f"SSH connection to {ssh_host}")
                issues.append(f"Check SSH configuration for {ssh_host}")
        else:
            check_fail("TERMINAL_SSH_HOST not set", "(required for TERMINAL_ENV=ssh)")
            issues.append("Set TERMINAL_SSH_HOST in .env")
    
    # Daytona (if using daytona backend)
    if terminal_env == "daytona":
        daytona_key = os.getenv("DAYTONA_API_KEY")
        if daytona_key:
            check_ok("Daytona API key", "(configured)")
        else:
            check_fail("DAYTONA_API_KEY not set", "(required for TERMINAL_ENV=daytona)")
            issues.append("Set DAYTONA_API_KEY environment variable")
        try:
            from daytona import Daytona  # noqa: F401 — SDK presence check
            check_ok("daytona SDK", "(installed)")
        except ImportError:
            check_fail("daytona SDK not installed", "(pip install daytona)")
            issues.append("Install daytona SDK: pip install daytona")

    # Browser Use cloud is the supported base browser automation path. Node.js
    # remains optional developer tooling and should not be required by doctor.
    if os.getenv("BROWSER_USE_API_KEY"):
        check_ok("Browser Use", "(BROWSER_USE_API_KEY configured)")
    else:
        check_info("Browser Use not configured (set BROWSER_USE_API_KEY or activate managed tools)")
        for step in _browser_use_setup_steps():
            check_info(step)

    if _which("node"):
        check_ok("Node.js", "(optional developer tooling)")
    else:
        if _is_termux():
            check_info("Node.js not found (optional developer tooling in Termux)")
        else:
            check_info("Node.js not found (optional developer tooling)")
    
    # npm audit for all Node.js packages
    if _which("npm"):
        npm_dirs = [
            (PROJECT_ROOT / "scripts" / "whatsapp-bridge", "WhatsApp bridge"),
        ]
        for npm_dir, label in npm_dirs:
            if not (npm_dir / "node_modules").exists():
                continue
            try:
                audit_result = subprocess.run(
                    ["npm", "audit", "--json"],
                    cwd=str(npm_dir),
                    capture_output=True, text=True, timeout=30,
                )
                import json as _json
                audit_data = _json.loads(audit_result.stdout) if audit_result.stdout.strip() else {}
                vuln_count = audit_data.get("metadata", {}).get("vulnerabilities", {})
                critical = vuln_count.get("critical", 0)
                high = vuln_count.get("high", 0)
                moderate = vuln_count.get("moderate", 0)
                total = critical + high + moderate
                if total == 0:
                    check_ok(f"{label} deps", "(no known vulnerabilities)")
                elif critical > 0 or high > 0:
                    check_warn(
                        f"{label} deps",
                        f"({critical} critical, {high} high, {moderate} moderate — run: cd {npm_dir} && npm audit fix)"
                    )
                    issues.append(f"{label} has {total} npm vulnerability(ies)")
                else:
                    check_ok(f"{label} deps", f"({moderate} moderate vulnerability(ies))")
            except Exception:
                pass

    # =========================================================================
    # Check: API connectivity
    # =========================================================================
    print()
    print(color("◆ API Connectivity", Colors.CYAN, Colors.BOLD))
    
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        print("  Checking OpenRouter API...", end="", flush=True)
        try:
            import httpx
            response = httpx.get(
                OPENROUTER_MODELS_URL,
                headers={"Authorization": f"Bearer {openrouter_key}"},
                timeout=10
            )
            if response.status_code == 200:
                print(f"\r  {color('✓', Colors.GREEN)} OpenRouter API                          ")
            elif response.status_code == 401:
                print(f"\r  {color('✗', Colors.RED)} OpenRouter API {color('(invalid API key)', Colors.DIM)}                ")
                issues.append("Check OPENROUTER_API_KEY in .env")
            elif response.status_code == 402:
                print(f"\r  {color('✗', Colors.RED)} OpenRouter API {color('(out of credits — payment required)', Colors.DIM)}")
                issues.append(
                    "OpenRouter account has insufficient credits. "
                    "Fix: run 'elevate config set model.provider <provider>' to switch providers, "
                    "or fund your OpenRouter account at https://openrouter.ai/settings/credits"
                )
            elif response.status_code == 429:
                print(f"\r  {color('✗', Colors.RED)} OpenRouter API {color('(rate limited)', Colors.DIM)}                ")
                issues.append("OpenRouter rate limit hit — consider switching to a different provider or waiting")
            else:
                print(f"\r  {color('✗', Colors.RED)} OpenRouter API {color(f'(HTTP {response.status_code})', Colors.DIM)}                ")
        except Exception as e:
            print(f"\r  {color('✗', Colors.RED)} OpenRouter API {color(f'({e})', Colors.DIM)}                ")
            issues.append("Check network connectivity")
    else:
        check_warn("OpenRouter API", "(not configured)")
    
    from elevate_cli.auth import get_anthropic_key
    anthropic_key = get_anthropic_key()
    if anthropic_key:
        print("  Checking Anthropic API...", end="", flush=True)
        try:
            import httpx
            from agent.anthropic_adapter import _is_oauth_token, _COMMON_BETAS, _OAUTH_ONLY_BETAS

            headers = {"anthropic-version": "2023-06-01"}
            if _is_oauth_token(anthropic_key):
                headers["Authorization"] = f"Bearer {anthropic_key}"
                headers["anthropic-beta"] = ",".join(_COMMON_BETAS + _OAUTH_ONLY_BETAS)
            else:
                headers["x-api-key"] = anthropic_key
            response = httpx.get(
                "https://api.anthropic.com/v1/models",
                headers=headers,
                timeout=10
            )
            if response.status_code == 200:
                print(f"\r  {color('✓', Colors.GREEN)} Anthropic API                           ")
            elif response.status_code == 401:
                print(f"\r  {color('✗', Colors.RED)} Anthropic API {color('(invalid API key)', Colors.DIM)}                 ")
            else:
                msg = "(couldn't verify)"
                print(f"\r  {color('⚠', Colors.YELLOW)} Anthropic API {color(msg, Colors.DIM)}                 ")
        except Exception as e:
            print(f"\r  {color('⚠', Colors.YELLOW)} Anthropic API {color(f'({e})', Colors.DIM)}                 ")

    # -- API-key providers --
    # Tuple: (name, env_vars, default_url, base_env, supports_models_endpoint)
    # If supports_models_endpoint is False, we skip the health check and just show "configured"
    _apikey_providers = [
        ("Z.AI / GLM",      ("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"), "https://api.z.ai/api/paas/v4/models", "GLM_BASE_URL", True),
        ("Kimi / Moonshot",  ("KIMI_API_KEY",),                              "https://api.moonshot.ai/v1/models",   "KIMI_BASE_URL", True),
        ("StepFun Step Plan",   ("STEPFUN_API_KEY",),                           "https://api.stepfun.ai/step_plan/v1/models", "STEPFUN_BASE_URL", True),
        ("Kimi / Moonshot (China)", ("KIMI_CN_API_KEY",),                    "https://api.moonshot.cn/v1/models",   None, True),
        ("Arcee AI",         ("ARCEEAI_API_KEY",),                            "https://api.arcee.ai/api/v1/models",  "ARCEE_BASE_URL", True),
        ("DeepSeek",         ("DEEPSEEK_API_KEY",),                           "https://api.deepseek.com/v1/models",  "DEEPSEEK_BASE_URL", True),
        ("Hugging Face",     ("HF_TOKEN",),                                   "https://router.huggingface.co/v1/models", "HF_BASE_URL", True),
        ("NVIDIA NIM",       ("NVIDIA_API_KEY",),                             "https://integrate.api.nvidia.com/v1/models", "NVIDIA_BASE_URL", True),
        ("Alibaba/DashScope", ("DASHSCOPE_API_KEY",),                         "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models", "DASHSCOPE_BASE_URL", True),
        # MiniMax: the /anthropic endpoint doesn't support /models, but the /v1 endpoint does.
        ("MiniMax",          ("MINIMAX_API_KEY",),                            "https://api.minimax.io/v1/models",    "MINIMAX_BASE_URL", True),
        ("MiniMax (China)",  ("MINIMAX_CN_API_KEY",),                         "https://api.minimaxi.com/v1/models",  "MINIMAX_CN_BASE_URL", True),
        ("Vercel AI Gateway",       ("AI_GATEWAY_API_KEY",),                          "https://ai-gateway.vercel.sh/v1/models", "AI_GATEWAY_BASE_URL", True),
        ("Kilo Code",        ("KILOCODE_API_KEY",),                            "https://api.kilo.ai/api/gateway/models",  "KILOCODE_BASE_URL", True),
        ("OpenCode Zen",     ("OPENCODE_ZEN_API_KEY",),                        "https://opencode.ai/zen/v1/models",  "OPENCODE_ZEN_BASE_URL", True),
        # OpenCode Go has no shared /models endpoint; skip the health check.
        ("OpenCode Go",      ("OPENCODE_GO_API_KEY",),                         None,                                  "OPENCODE_GO_BASE_URL", False),
    ]
    for _pname, _env_vars, _default_url, _base_env, _supports_health_check in _apikey_providers:
        _key = ""
        for _ev in _env_vars:
            _key = os.getenv(_ev, "")
            if _key:
                break
        if _key:
            _label = _pname.ljust(20)
            # Some providers (like MiniMax) don't support /models endpoint
            if not _supports_health_check:
                print(f"  {color('✓', Colors.GREEN)} {_label} {color('(key configured)', Colors.DIM)}")
                continue
            print(f"  Checking {_pname} API...", end="", flush=True)
            try:
                import httpx
                _base = os.getenv(_base_env, "") if _base_env else ""
                # Auto-detect Kimi Code keys (sk-kimi-) → api.kimi.com/coding/v1
                # (OpenAI-compat surface, which exposes /models for health check).
                if not _base and _key.startswith("sk-kimi-"):
                    _base = "https://api.kimi.com/coding/v1"
                # Anthropic-compat endpoints (/anthropic, api.kimi.com/coding
                # with no /v1) don't support /models.  Rewrite to the OpenAI-compat
                # /v1 surface for health checks.
                if _base and _base.rstrip("/").endswith("/anthropic"):
                    from agent.auxiliary_client import _to_openai_base_url
                    _base = _to_openai_base_url(_base)
                if base_url_host_matches(_base, "api.kimi.com") and _base.rstrip("/").endswith("/coding"):
                    _base = _base.rstrip("/") + "/v1"
                _url = (_base.rstrip("/") + "/models") if _base else _default_url
                _headers = {
                    "Authorization": f"Bearer {_key}",
                    "User-Agent": _ELEVATE_USER_AGENT,
                }
                if base_url_host_matches(_base, "api.kimi.com"):
                    _headers["User-Agent"] = "claude-code/0.1.0"
                _resp = httpx.get(
                    _url,
                    headers=_headers,
                    timeout=10,
                )
                if _resp.status_code == 200:
                    print(f"\r  {color('✓', Colors.GREEN)} {_label}                          ")
                elif _resp.status_code == 401:
                    print(f"\r  {color('✗', Colors.RED)} {_label} {color('(invalid API key)', Colors.DIM)}           ")
                    issues.append(f"Check {_env_vars[0]} in .env")
                else:
                    print(f"\r  {color('⚠', Colors.YELLOW)} {_label} {color(f'(HTTP {_resp.status_code})', Colors.DIM)}           ")
            except Exception as _e:
                print(f"\r  {color('⚠', Colors.YELLOW)} {_label} {color(f'({_e})', Colors.DIM)}           ")

    # -- AWS Bedrock --
    # Bedrock uses the AWS SDK credential chain, not API keys.
    try:
        from agent.bedrock_adapter import has_aws_credentials, resolve_aws_auth_env_var, resolve_bedrock_region
        if has_aws_credentials():
            _auth_var = resolve_aws_auth_env_var()
            _region = resolve_bedrock_region()
            _label = "AWS Bedrock".ljust(20)
            print(f"  Checking AWS Bedrock...", end="", flush=True)
            try:
                import boto3
                _br_client = boto3.client("bedrock", region_name=_region)
                _br_resp = _br_client.list_foundation_models()
                _model_count = len(_br_resp.get("modelSummaries", []))
                print(f"\r  {color('✓', Colors.GREEN)} {_label} {color(f'({_auth_var}, {_region}, {_model_count} models)', Colors.DIM)}           ")
            except ImportError:
                print(f"\r  {color('⚠', Colors.YELLOW)} {_label} {color(f'(boto3 not installed — {sys.executable} -m pip install boto3)', Colors.DIM)}           ")
                issues.append(f"Install boto3 for Bedrock: {sys.executable} -m pip install boto3")
            except Exception as _e:
                _err_name = type(_e).__name__
                print(f"\r  {color('⚠', Colors.YELLOW)} {_label} {color(f'({_err_name}: {_e})', Colors.DIM)}           ")
                issues.append(f"AWS Bedrock: {_err_name} — check IAM permissions for bedrock:ListFoundationModels")
    except ImportError:
        pass  # bedrock_adapter not available — skip silently

    # =========================================================================
    # Check: Submodules
    # =========================================================================
    print()
    print(color("◆ Submodules", Colors.CYAN, Colors.BOLD))
    
    # tinker-atropos (RL training backend)
    tinker_dir = PROJECT_ROOT / "tinker-atropos"
    if tinker_dir.exists() and (tinker_dir / "pyproject.toml").exists():
        if py_version >= (3, 11):
            try:
                __import__("tinker_atropos")
                check_ok("tinker-atropos", "(RL training backend)")
            except ImportError:
                install_cmd = f"{_python_install_cmd()} -e ./tinker-atropos"
                check_warn("tinker-atropos found but not installed", f"(run: {install_cmd})")
                issues.append(f"Install tinker-atropos: {install_cmd}")
        else:
            check_warn("tinker-atropos requires Python 3.11+", f"(current: {py_version.major}.{py_version.minor})")
    else:
        check_warn("tinker-atropos not found", "(run: git submodule update --init --recursive)")
    
    # =========================================================================
    # Check: Tool Availability
    # =========================================================================
    print()
    print(color("◆ Tool Availability", Colors.CYAN, Colors.BOLD))
    
    try:
        # Add project root to path for imports
        sys.path.insert(0, str(PROJECT_ROOT))
        from model_tools import check_tool_availability, TOOLSET_REQUIREMENTS
        
        available, unavailable = check_tool_availability()
        available, unavailable = _apply_doctor_tool_availability_overrides(available, unavailable)
        
        for tid in available:
            info = TOOLSET_REQUIREMENTS.get(tid, {})
            check_ok(info.get("name", tid))
        
        for item in unavailable:
            env_vars = item.get("missing_vars") or item.get("env_vars") or []
            if env_vars:
                vars_str = ", ".join(env_vars)
                check_warn(item["name"], f"(missing {vars_str})")
            else:
                check_warn(item["name"], "(system dependency not met)")

        # Count disabled tools with API key requirements
        api_disabled = [u for u in unavailable if (u.get("missing_vars") or u.get("env_vars"))]
        if api_disabled:
            issues.append("Run 'elevate setup' to configure missing API keys for full tool access")
    except Exception as e:
        check_warn("Could not check tool availability", f"({e})")
    
    # =========================================================================
    # Check: Skills Hub
    # =========================================================================
    print()
    print(color("◆ Skills Hub", Colors.CYAN, Colors.BOLD))

    hub_dir = ELEVATE_HOME / "skills" / ".hub"
    if hub_dir.exists():
        check_ok("Skills Hub directory exists")
        lock_file = hub_dir / "lock.json"
        if lock_file.exists():
            try:
                import json
                lock_data = json.loads(lock_file.read_text())
                count = len(lock_data.get("installed", {}))
                check_ok(f"Lock file OK ({count} hub-installed skill(s))")
            except Exception:
                check_warn("Lock file", "(corrupted or unreadable)")
        quarantine = hub_dir / "quarantine"
        q_count = sum(1 for d in quarantine.iterdir() if d.is_dir()) if quarantine.exists() else 0
        if q_count > 0:
            check_warn(f"{q_count} skill(s) in quarantine", "(pending review)")
    else:
        check_warn("Skills Hub directory not initialized", "(run: elevate skills list)")

    from elevate_cli.config import get_env_value
    github_token = get_env_value("GITHUB_TOKEN") or get_env_value("GH_TOKEN")
    if github_token:
        check_ok("GitHub token configured (authenticated API access)")
    else:
        check_warn("No GITHUB_TOKEN", f"(60 req/hr rate limit — set in {_DHH}/.env for better rates)")

    # =========================================================================
    # Memory Provider (only check the active provider, if any)
    # =========================================================================
    print()
    print(color("◆ Memory Provider", Colors.CYAN, Colors.BOLD))

    _active_memory_provider = ""
    try:
        import yaml as _yaml
        _mem_cfg_path = ELEVATE_HOME / "config.yaml"
        if _mem_cfg_path.exists():
            with open(_mem_cfg_path) as _f:
                _raw_cfg = _yaml.safe_load(_f) or {}
            _active_memory_provider = (_raw_cfg.get("memory") or {}).get("provider", "")
    except Exception:
        pass

    if not _active_memory_provider:
        check_ok("Built-in memory active", "(no external provider configured — this is fine)")
    elif _active_memory_provider == "honcho":
        try:
            from plugins.memory.honcho.client import HonchoClientConfig, resolve_config_path
            hcfg = HonchoClientConfig.from_global_config()
            _honcho_cfg_path = resolve_config_path()

            if not _honcho_cfg_path.exists():
                check_warn("Honcho config not found", "run: elevate memory setup")
            elif not hcfg.enabled:
                check_info(f"Honcho disabled (set enabled: true in {_honcho_cfg_path} to activate)")
            elif not (hcfg.api_key or hcfg.base_url):
                check_fail("Honcho API key or base URL not set", "run: elevate memory setup")
                issues.append("No Honcho API key — run 'elevate memory setup'")
            else:
                from plugins.memory.honcho.client import get_honcho_client, reset_honcho_client
                reset_honcho_client()
                try:
                    get_honcho_client(hcfg)
                    check_ok(
                        "Honcho connected",
                        f"workspace={hcfg.workspace_id} mode={hcfg.recall_mode} freq={hcfg.write_frequency}",
                    )
                except Exception as _e:
                    check_fail("Honcho connection failed", str(_e))
                    issues.append(f"Honcho unreachable: {_e}")
        except ImportError:
            check_fail("honcho-ai not installed", "pip install honcho-ai")
            issues.append("Honcho is set as memory provider but honcho-ai is not installed")
        except Exception as _e:
            check_warn("Honcho check failed", str(_e))
    elif _active_memory_provider == "mem0":
        try:
            from plugins.memory.mem0 import _load_config as _load_mem0_config
            mem0_cfg = _load_mem0_config()
            mem0_key = mem0_cfg.get("api_key", "")
            if mem0_key:
                check_ok("Mem0 API key configured")
                check_info(f"user_id={mem0_cfg.get('user_id', '?')}  agent_id={mem0_cfg.get('agent_id', '?')}")
            else:
                check_fail("Mem0 API key not set", "(set MEM0_API_KEY in .env or run elevate memory setup)")
                issues.append("Mem0 is set as memory provider but API key is missing")
        except ImportError:
            check_fail("Mem0 plugin not loadable", "pip install mem0ai")
            issues.append("Mem0 is set as memory provider but mem0ai is not installed")
        except Exception as _e:
            check_warn("Mem0 check failed", str(_e))
    else:
        # Generic check for other memory providers (openviking, hindsight, etc.)
        try:
            from plugins.memory import load_memory_provider
            _provider = load_memory_provider(_active_memory_provider)
            if _provider and _provider.is_available():
                check_ok(f"{_active_memory_provider} provider active")
            elif _provider:
                check_warn(f"{_active_memory_provider} configured but not available", "run: elevate memory status")
            else:
                check_warn(f"{_active_memory_provider} plugin not found", "run: elevate memory setup")
        except Exception as _e:
            check_warn(f"{_active_memory_provider} check failed", str(_e))

    # =========================================================================
    # Profiles
    # =========================================================================
    try:
        from elevate_cli.profiles import list_profiles, _get_wrapper_dir, profile_exists
        import re as _re

        named_profiles = [p for p in list_profiles() if not p.is_default]
        if named_profiles:
            print()
            print(color("◆ Profiles", Colors.CYAN, Colors.BOLD))
            check_ok(f"{len(named_profiles)} profile(s) found")
            wrapper_dir = _get_wrapper_dir()
            for p in named_profiles:
                parts = []
                if p.gateway_running:
                    parts.append("gateway running")
                if p.model:
                    parts.append(p.model[:30])
                if not (p.path / "config.yaml").exists():
                    parts.append("⚠ missing config")
                if not (p.path / ".env").exists():
                    parts.append("no .env")
                wrapper = wrapper_dir / p.name
                if not wrapper.exists():
                    parts.append("no alias")
                status = ", ".join(parts) if parts else "configured"
                check_ok(f"  {p.name}: {status}")

            # Check for orphan wrappers
            if wrapper_dir.is_dir():
                for wrapper in wrapper_dir.iterdir():
                    if not wrapper.is_file():
                        continue
                    try:
                        content = wrapper.read_text()
                        if "elevate -p" in content:
                            _m = _re.search(r"elevate -p (\S+)", content)
                            if _m and not profile_exists(_m.group(1)):
                                check_warn(f"Orphan alias: {wrapper.name} → profile '{_m.group(1)}' no longer exists")
                    except Exception:
                        pass
    except ImportError:
        pass
    except Exception:
        pass

    # =========================================================================
    # Summary
    # =========================================================================
    print()
    remaining_issues = issues + manual_issues
    if should_fix and fixed_count > 0:
        print(color("─" * 60, Colors.GREEN))
        print(color(f"  Fixed {fixed_count} issue(s).", Colors.GREEN, Colors.BOLD), end="")
        if remaining_issues:
            print(color(f" {len(remaining_issues)} issue(s) require manual intervention.", Colors.YELLOW, Colors.BOLD))
        else:
            print()
        print()
        if remaining_issues:
            for i, issue in enumerate(remaining_issues, 1):
                print(f"  {i}. {issue}")
            print()
    elif remaining_issues:
        print(color("─" * 60, Colors.YELLOW))
        print(color(f"  Found {len(remaining_issues)} issue(s) to address:", Colors.YELLOW, Colors.BOLD))
        print()
        for i, issue in enumerate(remaining_issues, 1):
            print(f"  {i}. {issue}")
        print()
        if not should_fix:
            print(color("  Tip: run 'elevate doctor --fix' to auto-fix what's possible.", Colors.DIM))
    else:
        print(color("─" * 60, Colors.GREEN))
        print(color("  All checks passed! 🎉", Colors.GREEN, Colors.BOLD))
    
    print()
