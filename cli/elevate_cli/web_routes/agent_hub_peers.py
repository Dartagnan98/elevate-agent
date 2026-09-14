"""Peer-agent discovery helpers for Agent Hub routes."""

import json
import logging
import os
from pathlib import Path
from typing import Any


def build_agent_peers(log: logging.Logger) -> dict[str, Any]:
    """Return the list of Cortex OS-style peer agents on this Mac."""
    roots: list[Path] = []
    primary = os.environ.get("ELEVATE_PEERS_ROOT", "").strip()
    if primary:
        roots.append(Path(primary).expanduser())
    extra = os.environ.get("ELEVATE_PEERS_ROOTS", "").strip()
    if extra:
        for chunk in extra.split(":"):
            chunk = chunk.strip()
            if chunk:
                roots.append(Path(chunk).expanduser())
    if not roots:
        fallback = Path.home() / "claudeclaw" / "orgs"
        if fallback.exists():
            roots.append(fallback)

    peers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        try:
            for config_path in sorted(root.glob("*/agents/*/config.json")):
                try:
                    payload = json.loads(config_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                org = config_path.parents[2].name
                agent = str(payload.get("agent_name") or config_path.parent.name)
                key = f"{org}/{agent}"
                if key in seen:
                    continue
                seen.add(key)

                role_hint = ""
                for fname in ("AGENTS.md", "CLAUDE.md", "IDENTITY.md"):
                    agent_doc = config_path.parent / fname
                    if not agent_doc.exists():
                        continue
                    try:
                        for line in agent_doc.read_text(encoding="utf-8").splitlines():
                            stripped = line.strip()
                            if not stripped or stripped.startswith("#"):
                                continue
                            if stripped.startswith("@"):
                                continue
                            if len(stripped) > 140:
                                stripped = stripped[:137] + "\u2026"
                            role_hint = stripped
                            break
                        if role_hint:
                            break
                    except Exception:
                        continue

                telegram_chat_id = ""
                telegram_bot_handle = ""
                telegram_preview = ""
                telegram_source = ""

                def _capture_token(value: str, source: str) -> None:
                    nonlocal telegram_preview, telegram_source
                    value = (value or "").strip().strip("'\"")
                    if not value or telegram_preview:
                        return
                    telegram_preview = "\u2022\u2022\u2022" + value[-4:] if len(value) >= 4 else "\u2022\u2022\u2022"
                    telegram_source = source

                channels_blob = payload.get("channels")
                if isinstance(channels_blob, dict):
                    tg = channels_blob.get("telegram")
                    if isinstance(tg, dict):
                        chat = tg.get("chat_id") or tg.get("chatId")
                        if chat:
                            telegram_chat_id = str(chat)
                        handle = tg.get("bot_handle") or tg.get("botHandle") or tg.get("username")
                        if handle:
                            telegram_bot_handle = str(handle)
                        for k in ("bot_token", "botToken", "token"):
                            if tg.get(k):
                                _capture_token(str(tg[k]), f"{config_path.name}#channels.telegram.{k}")
                                break

                env_path = config_path.parent / ".env"
                if env_path.exists():
                    try:
                        for raw in env_path.read_text(encoding="utf-8").splitlines():
                            line = raw.strip()
                            if not line or line.startswith("#"):
                                continue
                            if "=" not in line:
                                continue
                            k, _, v = line.partition("=")
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k in ("TELEGRAM_BOT_TOKEN", "TG_BOT_TOKEN"):
                                _capture_token(v, ".env#" + k)
                            elif k in ("TELEGRAM_CHAT_ID", "TG_CHAT_ID") and not telegram_chat_id:
                                telegram_chat_id = v
                            elif k in ("TELEGRAM_BOT_USERNAME", "TG_BOT_USERNAME") and not telegram_bot_handle:
                                telegram_bot_handle = v
                    except Exception:
                        pass

                peers.append({
                    "org": org,
                    "name": agent,
                    "enabled": bool(payload.get("enabled", True)),
                    "workingDirectory": str(payload.get("working_directory") or ""),
                    "timezone": str(payload.get("timezone") or ""),
                    "communicationStyle": str(payload.get("communication_style") or ""),
                    "cronCount": len(payload.get("crons") or []),
                    "roleHint": role_hint,
                    "configPath": str(config_path),
                    "telegram": {
                        "configured": bool(telegram_preview or telegram_chat_id),
                        "botHandle": telegram_bot_handle,
                        "chatId": telegram_chat_id,
                        "tokenPreview": telegram_preview,
                        "source": telegram_source,
                    },
                })
        except Exception:
            log.exception("GET /api/agents/peers failed walking root=%s", root)
            continue
    return {"peers": peers, "rootsSearched": [str(r) for r in roots]}
