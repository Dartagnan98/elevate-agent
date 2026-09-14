"""Admin onboarding chat and browser-use routes."""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from elevate_cli.config import load_config


class _OnboardingChatMessage(BaseModel):
    role: str
    content: str


class _OnboardingChatBody(BaseModel):
    messages: List[_OnboardingChatMessage] = []


class _OnboardingBrowserUseBody(BaseModel):
    portalKey: str  # mls | compliance | showing
    taskHint: Optional[str] = None


_ONBOARDING_CHAT_SYSTEM = (
    "You are Elevate's onboarding coach for a Canadian real estate agent. "
    "Tone: direct operator, no fluff, no 'do you have', no 'would you like to'. "
    "Get-it-done energy. Treat the snapshot below as ground truth — the wizard "
    "is done, the agent is up to date. "
    "RULES: "
    "(1) Always lead with current state: name the province and what's already "
    "connected (with provider names). Don't ask questions about anything the "
    "snapshot shows as connected/configured. "
    "IMPORTANT: 'Still missing' has two sub-buckets — items that the user "
    "set up but Elevate hasn't yet captured a runtime verification ping for "
    "(status=connected/configured AND key in missingRequiredKeys, listed under "
    "'Pending verification'), and items the user hasn't picked a provider for "
    "(status=missing, listed under 'Not picked yet'). NEVER tell the user a "
    "Pending-verification item is 'missing' or that they need to reconnect "
    "it — say 'health-check pending, will clear on next sync' instead. Only "
    "items in 'Not picked yet' need user action. "
    "(2) After the state line, name the next concrete 'Not picked yet' gap "
    "and tell the user how to close it — not 'do you have a calendar', but "
    "'Next: Calendar — click Connect on the Calendar card in the connectors "
    "panel'. If everything is either connected or pending verification, say "
    "so; do not invent action items. "
    "(3) Never say you're 'making' or 'creating' something that already exists. "
    "(4) Never offer to import 'any spreadsheets of contacts, deals, listings, "
    "or past clients' unless the user brings them up first. The CRM already "
    "covers that surface area. "
    "(5) Keep replies to 1-3 short sentences. No bullet lists, no markdown, no "
    "'great question' / 'happy to help'. "
    "(6) OAuth connectors (Google Drive, Gmail, Calendar): say 'click Connect "
    "on the X card'. Portal logins (MLS, compliance, showing): say 'enter URL "
    "+ email + password on the X card, then hit Connect & analyze'. When the "
    "snapshot lists a saved portal login URL or provider home page for the "
    "missing item, paste that URL verbatim in the reply so the user can click "
    "through directly. Plain https URLs render as clickable links in the chat "
    "bubble — do not wrap them in markdown. "
    "(7) If the user asks 'where are we at' or similar status questions, "
    "restate: province, completion %, connected items with providers, missing "
    "items with the next action to close the first one. "
    "(8) If everything required is in, say so in one sentence and ask if "
    "anything else needs tightening up. Do not invent tasks."
)


_PROVIDER_HOMEPAGE = {
    "google calendar": "https://calendar.google.com",
    "google drive": "https://drive.google.com",
    "gmail": "https://mail.google.com",
    "outlook": "https://outlook.live.com",
    "microsoft 365": "https://outlook.office.com",
    "lofty": "https://app.lofty.com",
    "follow up boss": "https://app.followupboss.com",
    "kvcore": "https://www.kvcore.com",
    "boldtrail": "https://www.boldtrail.com",
    "matrix": "https://matrix.realtor.ca",
    "paragon": "https://paragonconnect.com",
    "stellar mls": "https://www.stellarmls.com",
    "broker bay": "https://brokerbay.com",
    "showingtime": "https://www.showingtime.com",
    "showami": "https://www.showami.com",
    "webforms": "https://wf.crea.ca",
    "transactiondesk": "https://www.transactiondesk.com",
    "dotloop": "https://www.dotloop.com",
    "skyslope": "https://www.skyslope.com",
    "docusign": "https://www.docusign.com",
    "authentisign": "https://www.authentisign.com",
}


def _provider_home_url(provider: str) -> str:
    if not provider:
        return ""
    return _PROVIDER_HOMEPAGE.get(provider.strip().lower(), "")


def _onboarding_chat_context(setup: Dict[str, Any]) -> str:
    """Compact snapshot context appended to the system prompt."""
    profile = setup.get("profile") or {}
    items = setup.get("items") or []
    missing = setup.get("missingRequiredKeys") or []
    by_key = {it["key"]: it for it in items if isinstance(it, dict) and it.get("key")}
    lines = [
        "--- CURRENT SETUP SNAPSHOT ---",
        f"Realtor: {profile.get('realtorLegalName') or '(unset)'} @ {profile.get('brokerageName') or '(unset)'}",
        f"Province: {profile.get('province') or '(unset)'} · Market: {profile.get('market') or '(unset)'}",
        f"Completion: {setup.get('completionPct') or 0}% ({setup.get('completedRequiredCount') or 0}/{setup.get('requiredCount') or 0})",
    ]
    if missing:
        pending_verify: List[str] = []
        not_picked: List[str] = []
        for k in missing:
            it = by_key.get(k) or {}
            label = it.get("label") or k
            status = (it.get("status") or "").strip()
            if status in ("connected", "configured"):
                pending_verify.append(label)
            else:
                not_picked.append(label)
        if pending_verify:
            lines.append(f"Pending verification (provider set, health-check not yet captured): {', '.join(pending_verify)}")
        if not_picked:
            lines.append(f"Not picked yet (user action required): {', '.join(not_picked)}")
        if not pending_verify and not not_picked:
            lines.append("All required items present.")
    else:
        lines.append("All required items present.")
    for key in ("drive", "crm", "mls", "compliance", "showing"):
        item = by_key.get(key)
        if item:
            provider = item.get("provider") or "(none)"
            lines.append(f"{key}: {provider} [{item.get('status') or 'missing'}]")

    browser_item = by_key.get("browser_workflows") or {}
    browser_value = browser_item.get("value") if isinstance(browser_item.get("value"), dict) else {}
    playbooks = browser_value.get("playbooks") if isinstance(browser_value.get("playbooks"), dict) else {}
    portal_urls: List[str] = []
    for portal_key, label in (("mls", "MLS"), ("compliance", "Compliance"), ("showing", "Showing")):
        pb = playbooks.get(portal_key) if isinstance(playbooks.get(portal_key), dict) else {}
        url = (pb.get("loginUrl") or "").strip()
        if url:
            portal_urls.append(f"{label} login URL: {url}")
    if portal_urls:
        lines.append("--- SAVED PORTAL LOGINS ---")
        lines.extend(portal_urls)

    home_lines: List[str] = []
    for key in ("calendar", "email", "drive", "crm", "mls", "compliance", "showing"):
        item = by_key.get(key) or {}
        if item.get("status") in ("connected", "configured"):
            continue
        provider = (item.get("provider") or "").strip()
        home = _provider_home_url(provider)
        if home:
            home_lines.append(f"{key} ({provider}): {home}")
    if home_lines:
        lines.append("--- PROVIDER HOMEPAGES FOR PENDING ITEMS ---")
        lines.extend(home_lines)

    return "\n".join(lines)


_CONNECTOR_NEXT_ACTION = {
    "calendar": "click Connect on the Calendar card.",
    "email": "click Connect on the Email card.",
    "drive": "click Connect on the Drive card.",
    "crm": "click Connect on the CRM card or paste your spreadsheet path.",
    "mls": "enter URL + email + password on the MLS card, then hit Connect & analyze.",
    "compliance_platform": "enter URL + email + password on the Compliance card, then hit Connect & analyze.",
    "showing_platform": "enter URL + email + password on the Showing card, then hit Connect & analyze.",
    "photo_processing": "pick a provider on the Photo processing card.",
    "fintrac_workflow": "pick a FINTRAC workflow on the card.",
    "forms_provider": "pick your forms provider on the card.",
    "signing_provider": "pick your signing provider on the card.",
    "approval_channel": "pick your approval channel (Telegram / email).",
}


def _onboarding_fallback_reply(messages: List[Dict[str, str]], setup: Dict[str, Any]) -> str:
    """Deterministic guidance when no LLM is configured.

    Mirrors the system prompt: state-first, direct next-action ask.
    """
    profile = setup.get("profile") or {}
    items = setup.get("items") or []
    by_key: Dict[str, Dict[str, Any]] = {it["key"]: it for it in items if isinstance(it, dict) and it.get("key")}
    missing = list(setup.get("missingRequiredKeys") or [])
    province = (profile.get("province") or "").strip().upper()
    pct = setup.get("completionPct") or 0
    last = (messages[-1].get("content") if messages else "") or ""
    last_lower = last.lower()

    browser_item = by_key.get("browser_workflows") or {}
    browser_value = browser_item.get("value") if isinstance(browser_item.get("value"), dict) else {}
    playbooks = browser_value.get("playbooks") if isinstance(browser_value.get("playbooks"), dict) else {}

    def _portal_url(portal_key: str) -> str:
        pb = playbooks.get(portal_key) if isinstance(playbooks.get(portal_key), dict) else {}
        return (pb.get("loginUrl") or "").strip()

    def _next_action_with_url(missing_key: str) -> str:
        base = _CONNECTOR_NEXT_ACTION.get(missing_key, "")
        if missing_key == "mls":
            url = _portal_url("mls")
            if url:
                return f"{base} ({url})"
        if missing_key == "compliance_platform":
            url = _portal_url("compliance")
            if url:
                return f"{base} ({url})"
        if missing_key == "showing_platform":
            url = _portal_url("showing")
            if url:
                return f"{base} ({url})"
        item = by_key.get(missing_key) or {}
        provider = (item.get("provider") or "").strip()
        home = _provider_home_url(provider)
        if home and base:
            return f"{base} Sign-in: {home}"
        return base

    connected_bits: List[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("status") not in ("connected", "configured"):
            continue
        label = (it.get("label") or it.get("key") or "").strip()
        provider = (it.get("provider") or "").strip()
        if not label:
            continue
        connected_bits.append(f"{label} ({provider})" if provider else label)

    pending_verify_labels: List[str] = []
    not_picked_labels: List[str] = []
    not_picked_keys: List[str] = []
    for k in missing:
        it = by_key.get(k) or {}
        label = it.get("label") or k
        status = (it.get("status") or "").strip()
        if status in ("connected", "configured"):
            pending_verify_labels.append(label)
        else:
            not_picked_labels.append(label)
            not_picked_keys.append(k)

    next_action = _next_action_with_url(not_picked_keys[0]) if not_picked_keys else None

    status_re_ask = any(
        token in last_lower
        for token in ("where are we", "status", "where we at", "what's left", "where do we", "what do we need")
    )

    if status_re_ask or not messages:
        head = f"{province + ', ' if province else ''}{pct}% wired up."
        connected_line = f" Connected: {', '.join(connected_bits)}." if connected_bits else ""
        pending_line = (
            f" Health-check pending (will clear on next sync): {', '.join(pending_verify_labels)}."
            if pending_verify_labels else ""
        )
        if not_picked_labels:
            tail = (
                f" Not picked yet: {', '.join(not_picked_labels)}. Next: {not_picked_labels[0]} — {next_action}"
                if next_action else f" Not picked yet: {', '.join(not_picked_labels)}."
            )
        elif pending_verify_labels:
            tail = " No user action needed — pending items will clear automatically."
        else:
            tail = " Everything required is in. Anything else to tighten?"
        return head + connected_line + pending_line + tail

    if "spreadsheet" in last_lower or "sheet" in last_lower:
        crm = (profile.get("crmProvider") or "").strip()
        if crm:
            return f"{crm} is already wired in as your CRM — leads, contacts, deals all flow through it. Drop a sheet only if there's data not in {crm} yet."
        return "Paste the Google Sheet URL into your drive folder; the next sync will pick it up."

    if not_picked_labels and next_action:
        return f"{not_picked_labels[0]} is the next gap — {next_action}"
    if not_picked_labels:
        return f"Still need to pick: {', '.join(not_picked_labels)}. Knock them out in the connectors panel."
    if pending_verify_labels:
        return (
            f"Pending health-check on {', '.join(pending_verify_labels)} — these are wired up, "
            f"verification ping just hasn't landed. Will clear on next sync."
        )
    return "Everything required is in. Anything else to tighten before we go live?"


def create_admin_onboarding_router(
    *,
    log: logging.Logger | None = None,
) -> APIRouter:
    router = APIRouter()
    _log = log or logging.getLogger(__name__)

    @router.post("/api/admin/onboarding/chat")
    def post_admin_onboarding_chat(body: _OnboardingChatBody):
        """LLM-backed onboarding coach. Falls back to deterministic guidance when no auxiliary client is configured."""
        try:
            from elevate_cli.data import connect, get_admin_setup
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Onboarding chat unavailable: {exc}")

        try:
            with connect() as conn:
                setup = get_admin_setup(conn)
        except Exception as exc:
            _log.exception("onboarding chat: failed to read admin_setup snapshot")
            setup = {}

        messages = [m.dict() for m in body.messages if m.content.strip()]
        context = _onboarding_chat_context(setup)
        system_prompt = _ONBOARDING_CHAT_SYSTEM + "\n\n" + context

        try:
            from agent.auxiliary_client import get_text_auxiliary_client

            client, model = get_text_auxiliary_client("onboarding_chat")
        except Exception as exc:
            _log.info("onboarding chat: auxiliary client unavailable (%s) — falling back", exc)
            return {"ok": True, "reply": _onboarding_fallback_reply(messages, setup), "model": None}

        if client is None or not model:
            return {"ok": True, "reply": _onboarding_fallback_reply(messages, setup), "model": None}

        payload_messages = [{"role": "system", "content": system_prompt}, *messages]
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=payload_messages,
                temperature=0.4,
                max_tokens=400,
                timeout=20,
            )
            text = (resp.choices[0].message.content or "").strip()
        except Exception as exc:
            _log.info("onboarding chat: LLM call failed (%s) — falling back", exc)
            return {"ok": True, "reply": _onboarding_fallback_reply(messages, setup), "model": model, "warning": str(exc)}

        if not text:
            text = _onboarding_fallback_reply(messages, setup)
        return {"ok": True, "reply": text, "model": model}


    def _browser_use_api_key() -> Optional[str]:
        """Pull a direct browser-use API key from env or YAML config."""
        for env_key in ("BROWSER_USE_API_KEY", "BROWSERUSE_API_KEY"):
            value = os.environ.get(env_key)
            if value:
                return value.strip()
        try:
            cfg = load_config() or {}
        except Exception:
            return None
        browser_cfg = (cfg.get("browser") or {}) if isinstance(cfg, dict) else {}
        candidate = browser_cfg.get("api_key") if isinstance(browser_cfg, dict) else None
        return str(candidate).strip() if candidate else None


    @router.post("/api/admin/onboarding/browser-use/launch")
    def post_admin_onboarding_browser_use_launch(body: _OnboardingBrowserUseBody):
        """Fire a browser-use cloud task against a portal saved in admin_setup."""
        portal_key = (body.portalKey or "").strip().lower()
        if portal_key not in {"mls", "compliance", "showing"}:
            raise HTTPException(status_code=400, detail="portalKey must be one of mls | compliance | showing")

        try:
            from elevate_cli.data import connect, get_admin_setup

            with connect() as conn:
                setup = get_admin_setup(conn)
        except Exception as exc:
            _log.exception("browser-use launch: snapshot read failed")
            raise HTTPException(status_code=500, detail=f"Read setup failed: {exc}")

        items = setup.get("items") or []
        browser_item = next(
            (it for it in items if isinstance(it, dict) and it.get("key") == "browser_workflows"),
            None,
        )
        playbooks = (((browser_item or {}).get("value") or {}).get("playbooks") or {}) if browser_item else {}
        playbook = playbooks.get(portal_key) or {}
        login_url = (playbook.get("loginUrl") or "").strip()
        credential_ref = (playbook.get("credentialRef") or "").strip()
        provider = (playbook.get("provider") or "").strip()
        notes = (playbook.get("notes") or "").strip()
        if not login_url:
            return {"ok": False, "error": f"No login URL saved for {portal_key} portal yet. Add it in the connectors card first."}

        api_key = _browser_use_api_key()
        if not api_key:
            return {
                "ok": False,
                "error": "BROWSER_USE_API_KEY not configured. Add it under Tools → Browser Use.",
                "portal": {"loginUrl": login_url, "provider": provider, "credentialRef": credential_ref},
            }

        province = (setup.get("profile") or {}).get("province") or ""
        task = body.taskHint or (
            f"Sign in to {provider or portal_key} at {login_url} using credentials referenced "
            f"by '{credential_ref or '(unspecified — ask the agent)'}'. "
            f"This is a {province or 'Canadian'} real-estate agent's {portal_key} portal. "
            "Once logged in, scan the dashboard and summarize: current active listings, pending "
            "transactions, any compliance alerts, and the structure of the main navigation. "
            "Report back as plain text — do not modify any data."
        )
        if notes:
            task += f"\n\nAgent notes about this portal:\n{notes}"

        request_body = json.dumps({"task": task, "save_browser_data": True}).encode("utf-8")
        request = urllib.request.Request(
            "https://api.browser-use.com/api/v1/run-task",
            data=request_body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                data = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            try:
                err_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            _log.warning("browser-use launch: HTTP %s — %s", exc.code, err_body[:400])
            return {"ok": False, "error": f"browser-use returned {exc.code}: {err_body[:200] or exc.reason}"}
        except Exception as exc:
            _log.exception("browser-use launch: request failed")
            return {"ok": False, "error": f"browser-use call failed: {exc}"}

        task_id = data.get("id") or data.get("task_id") or data.get("uuid")
        return {
            "ok": True,
            "taskId": task_id,
            "runUrl": data.get("live_url") or (f"https://cloud.browser-use.com/tasks/{task_id}" if task_id else None),
            "raw": data,
        }



    return router
