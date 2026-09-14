"""Config parsing helpers for Cortext agent-pack conversion."""

import json
import re
from pathlib import Path
from typing import Any


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return ""


_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def clean_cortext_time(raw: Any, fallback: Any) -> str:
    """Return a valid HH:MM time, falling back when the config value is bad."""
    value = str(raw or "").strip()
    if value and not value.startswith("{{") and _TIME_RE.match(value):
        return value
    fb = str(fallback or "").strip()
    return fb if _TIME_RE.match(fb) else ""


def strip_secrets(value: Any) -> Any:
    if isinstance(value, list):
        return [strip_secrets(item) for item in value]
    if not isinstance(value, dict):
        return value
    out: dict[str, Any] = {}
    for key, item in value.items():
        lower = str(key).lower().replace("-", "_")
        if (
            ("token" in lower and not lower.endswith("_env"))
            or "secret" in lower
            or "api_key" in lower
            or "apikey" in lower
            or "password" in lower
            or lower in {"pm2", "daemon", "ipc", "pty", "file_inbox", "fileinbox", "fast_checker"}
            or lower.startswith(("daemon_", "pm2_", "ipc_", "pty_"))
        ):
            continue
        out[key] = strip_secrets(item)
    return out


def load_json(path: Path) -> dict[str, Any]:
    raw = read_text(path)
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return strip_secrets(parsed) if isinstance(parsed, dict) else {}


def template_config_name(spec: dict[str, Any]) -> str:
    explicit = str(spec.get("template") or "").strip()
    if explicit:
        return explicit
    source = str(spec.get("source") or "").strip().strip("/")
    parts = source.split("/")
    if len(parts) >= 3 and parts[0] == "community" and parts[1] == "agents":
        return parts[2]
    return ""


def merge_cortext_config(template: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    merged = {**template, **config}
    for key in ("approval_rules", "ecosystem", "memory", "safety", "runtime", "lifecycle"):
        left = template.get(key)
        right = config.get(key)
        if isinstance(left, dict) and isinstance(right, dict):
            merged[key] = {**left, **right}
    return merged


def interval_to_schedule(value: str) -> str:
    clean = str(value or "").strip().lower()
    match = re.match(r"^(\d+)\s*h$", clean)
    if match:
        hours = max(1, int(match.group(1)))
        if hours == 24:
            return "0 8 * * *"
        return f"0 */{hours} * * *"
    return clean


def cortext_cron_schedule(cron: dict[str, Any]) -> str:
    raw_cron = str(cron.get("cron") or "").strip()
    if raw_cron:
        return raw_cron
    interval = str(cron.get("interval") or "").strip()
    if interval:
        return f"every {interval}"
    return ""


def config_enabled(value: Any, default: bool = False) -> bool:
    if isinstance(value, dict):
        if "enabled" in value:
            return bool(value.get("enabled"))
        return default
    if value is None:
        return default
    return bool(value)


def cortext_runtime_from_config(config: dict[str, Any]) -> dict[str, Any]:
    runtime: dict[str, Any] = {
        "runtime_type": str(config.get("runtime") or config.get("runtime_type") or "native").strip() or "native",
        "timezone": str(config.get("timezone") or "America/Vancouver").strip() or "America/Vancouver",
    }
    for source, target in (
        ("model", "model"),
        ("provider", "provider"),
        ("base_url", "base_url"),
        ("working_directory", "workdir"),
        ("workdir", "workdir"),
        ("ctx_warning_threshold", "context_warning_threshold"),
        ("context_warning_threshold", "context_warning_threshold"),
        ("ctx_handoff_threshold", "context_handoff_threshold"),
        ("context_handoff_threshold", "context_handoff_threshold"),
        ("codex_context_cap", "codex_context_cap"),
    ):
        value = config.get(source)
        if value not in (None, ""):
            runtime[target] = value
    if "context_warning_threshold" not in runtime:
        runtime["context_warning_threshold"] = 72
    if "context_handoff_threshold" not in runtime:
        runtime["context_handoff_threshold"] = 88
    return runtime


def cortext_lifecycle_from_config(config: dict[str, Any]) -> dict[str, Any]:
    lifecycle: dict[str, Any] = {
        "startup_delay": config.get("startup_delay", 0),
        "max_session_seconds": config.get("max_session_seconds", 7200),
        "max_crashes_per_day": config.get("max_crashes_per_day", 3),
        "crash_window_seconds": 86400,
        "crash_window_max": config.get("max_crashes_per_day", 3),
        "telegram_polling": config.get("telegram_polling", True),
    }
    crash_window = config.get("crash_window")
    if isinstance(crash_window, dict):
        seconds = crash_window.get("seconds") or crash_window.get("duration_seconds") or crash_window.get("window_seconds")
        max_crashes = crash_window.get("max_crashes") or crash_window.get("max") or crash_window.get("count")
        if seconds is not None:
            lifecycle["crash_window_seconds"] = seconds
        if max_crashes is not None:
            lifecycle["crash_window_max"] = max_crashes
    return lifecycle


def cortext_ecosystem_from_config(config: dict[str, Any], spec: dict[str, Any]) -> dict[str, bool]:
    ecosystem = config.get("ecosystem") if isinstance(config.get("ecosystem"), dict) else {}
    return {
        "local_version_control": config_enabled(ecosystem.get("local_version_control"), spec.get("id") in {"analyst"}),
        "upstream_sync": config_enabled(ecosystem.get("upstream_sync"), spec.get("id") == "analyst"),
        "catalog_browse": config_enabled(ecosystem.get("catalog_browse"), spec.get("id") == "analyst"),
        "community_publish": config_enabled(ecosystem.get("community_publish"), False),
    }


def automation_seeds_from_rules(
    rules: list[dict[str, Any]],
    *,
    agent_id: str,
    agent_name: str,
    runtime: dict[str, Any],
) -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    for rule in rules:
        name = str(rule.get("name") or "").strip()
        if not name or name.lower() == "heartbeat":
            continue
        schedule = str(rule.get("cron") or "").strip()
        if not schedule and rule.get("interval"):
            schedule = f"every {rule.get('interval')}"
        prompt = str(rule.get("prompt") or "").strip()
        if not schedule or not prompt:
            continue
        seeds.append(
            {
                "name": f"{agent_name} - {name}",
                "schedule": schedule,
                "prompt": prompt,
                "deliver": "local",
                "agent": agent_id,
                "workdir": runtime.get("workdir") or None,
                "model": runtime.get("model") or None,
                "provider": runtime.get("provider") or None,
                "base_url": runtime.get("base_url") or None,
                "enabled": False,
                "origin": {
                    "type": "cortext-cron",
                    "agent": agent_id,
                    "source": "cortext-preset",
                    "cortext_name": name,
                },
            }
        )
    return seeds
