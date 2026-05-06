from __future__ import annotations

import copy
import re
from typing import Any

BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-]+")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
COOKIE_RE = re.compile(r"(?i)(cookie|set-cookie)\s*[:=]\s*[^\n\r]+")
PASSWORD_RE = re.compile(r"(?i)(password\s*[=:]\s*)[^\n\r&]+")

SENSITIVE_KEY_PARTS = {
    "cookie",
    "authorization",
    "access_token",
    "refresh_token",
    "id_token",
    "idtoken",
    "accesstoken",
    "refreshtoken",
    "okta-token-storage",
    "localstorage",
    "sessionstorage",
    "password",
    "passwd",
    "secret",
    "token",
}


def redact_sensitive_text(text: str) -> str:
    text = BEARER_RE.sub("Bearer [REDACTED_BEARER_TOKEN]", text)
    text = JWT_RE.sub("[REDACTED_JWT]", text)
    text = COOKIE_RE.sub(lambda m: f"{m.group(1)}: [REDACTED_COOKIE]", text)
    text = PASSWORD_RE.sub(lambda m: f"{m.group(1)}[REDACTED_PASSWORD]", text)
    return text


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "").replace("_", "")
    raw_lowered = key.lower()
    return any(part in lowered or part in raw_lowered for part in SENSITIVE_KEY_PARTS)


def sanitize_browser_snapshot(value: Any) -> Any:
    """Remove credential-bearing fields from browser/page snapshots.

    This is intentionally conservative. Browser storage/cookies/tokens are never
    needed for source ingestion and should not enter logs, RAG, or rules packs.
    """
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, list):
        return [sanitize_browser_snapshot(v) for v in value]
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            if key in {"localStorage", "sessionStorage"}:
                continue
            if key == "fields" and isinstance(child, list):
                cleaned[key] = [
                    {**f, "value": "[REDACTED_PASSWORD_FIELD]"}
                    if isinstance(f, dict) and str(f.get("type", "")).lower() == "password"
                    else sanitize_browser_snapshot(f)
                    for f in child
                ]
                continue
            if isinstance(child, dict) and str(child.get("type", "")).lower() == "password":
                redacted = copy.deepcopy(child)
                redacted["value"] = "[REDACTED_PASSWORD_FIELD]"
                cleaned[key] = redacted
                continue
            if _is_sensitive_key(key):
                cleaned[key] = "[REDACTED]"
                continue
            cleaned[key] = sanitize_browser_snapshot(child)
        return cleaned
    return value
