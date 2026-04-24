"""
Shared platform registry for Elevate.

Single source of truth for platform metadata consumed by both
skills_config (label display) and tools_config (default toolset
resolution).  Import ``PLATFORMS`` from here instead of maintaining
duplicate dicts in each module.
"""

from collections import OrderedDict
from typing import NamedTuple


class PlatformInfo(NamedTuple):
    """Metadata for a single platform entry."""
    label: str
    default_toolset: str


# Ordered so that TUI menus are deterministic.
PLATFORMS: OrderedDict[str, PlatformInfo] = OrderedDict([
    ("cli",            PlatformInfo(label="🖥️  CLI",            default_toolset="elevate-cli")),
    ("telegram",       PlatformInfo(label="📱 Telegram",        default_toolset="elevate-telegram")),
    ("discord",        PlatformInfo(label="💬 Discord",         default_toolset="elevate-discord")),
    ("slack",          PlatformInfo(label="💼 Slack",           default_toolset="elevate-slack")),
    ("whatsapp",       PlatformInfo(label="📱 WhatsApp",        default_toolset="elevate-whatsapp")),
    ("signal",         PlatformInfo(label="📡 Signal",          default_toolset="elevate-signal")),
    ("bluebubbles",    PlatformInfo(label="💙 BlueBubbles",     default_toolset="elevate-bluebubbles")),
    ("email",          PlatformInfo(label="📧 Email",           default_toolset="elevate-email")),
    ("homeassistant",  PlatformInfo(label="🏠 Home Assistant",  default_toolset="elevate-homeassistant")),
    ("mattermost",     PlatformInfo(label="💬 Mattermost",      default_toolset="elevate-mattermost")),
    ("matrix",         PlatformInfo(label="💬 Matrix",          default_toolset="elevate-matrix")),
    ("dingtalk",       PlatformInfo(label="💬 DingTalk",        default_toolset="elevate-dingtalk")),
    ("feishu",         PlatformInfo(label="🪽 Feishu",          default_toolset="elevate-feishu")),
    ("wecom",          PlatformInfo(label="💬 WeCom",           default_toolset="elevate-wecom")),
    ("wecom_callback", PlatformInfo(label="💬 WeCom Callback",  default_toolset="elevate-wecom-callback")),
    ("weixin",         PlatformInfo(label="💬 Weixin",          default_toolset="elevate-weixin")),
    ("qqbot",          PlatformInfo(label="💬 QQBot",           default_toolset="elevate-qqbot")),
    ("webhook",        PlatformInfo(label="🔗 Webhook",         default_toolset="elevate-webhook")),
    ("api_server",     PlatformInfo(label="🌐 API Server",      default_toolset="elevate-api-server")),
    ("cron",           PlatformInfo(label="⏰ Cron",            default_toolset="elevate-cron")),
])


def platform_label(key: str, default: str = "") -> str:
    """Return the display label for a platform key, or *default*."""
    info = PLATFORMS.get(key)
    return info.label if info is not None else default
