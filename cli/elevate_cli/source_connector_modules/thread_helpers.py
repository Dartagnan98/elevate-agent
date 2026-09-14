"""Thread row helpers for source inbox records."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from elevate_cli.source_connector_modules.record_snapshots import _list_record_snapshot
from elevate_cli.source_connector_modules.source_io import _parse_record_dt, _record_timestamp, _safe_int, _tag_text


JsonRecord = dict[str, Any]


def _thread_key(record: JsonRecord) -> str:
    for key in ("conversation_id", "source_record_id", "contact_id", "handle", "chat_identifier"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return "unknown-thread"


def _record_person_name(record: JsonRecord) -> str:
    for key in ("display_name", "name", "full_name", "contact_name", "handle", "chat_identifier", "conversation_id"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return "Client conversation"


def _channel_label(source_id: str, source: JsonRecord, record: JsonRecord) -> str:
    service = str(record.get("service") or "").strip()
    if service:
        return service
    raw_channel = str(record.get("channel") or "").strip()
    if raw_channel == "apple-messages":
        return "Messages"
    if raw_channel.lower().replace("-", " ") == "lofty crm":
        return "Lofty CRM"
    if raw_channel:
        return raw_channel.replace("-", " ").title()
    return str(source.get("label") or source_id).strip() or source_id


def _latest_text(record: JsonRecord) -> str:
    for key in ("last_text", "text", "summary", "title"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return "No preview text yet."


_AUTOMATED_LOCALPARTS = {
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply", "do_not_reply",
    "mailer-daemon", "mailerdaemon", "postmaster", "bounce", "bounces", "notification",
    "notifications", "alerts", "alert", "info", "infoalerts", "newsletter", "news",
    "marketing", "promotions", "promo", "promos", "deals", "offers", "updates",
    "update", "system", "auto", "automated", "noreplies", "support", "help",
    "hello", "team", "service", "services", "billing", "receipts", "orders", "order",
    "shipping", "ship", "tracking", "account", "accounts", "security", "feedback",
    "reply", "replies", "customersupport", "customer-support", "customerservice",
    "customer-service", "care", "reminders", "reminder", "verify", "verification",
    "confirm", "confirmation", "receipt", "invoice", "invoices", "members",
    "membership", "subscriptions", "subscribe", "unsubscribe", "list", "lists",
    "broadcast", "campaign", "campaigns", "digest", "weekly", "daily", "drop",
    "drops",
}

_AUTOMATED_DOMAIN_HINTS = (
    "accounts.google.com", "google.com", "googlemail.com", "mail-noreply",
    "scotiabank.com", "scotiabank.ca", "rbc.com", "td.com", "amazon.com",
    "amazonses.com", "shopify.com", "mailchimp.com", "sendgrid.net", "klaviyomail.com",
    "klaviyo.com", "mailerlite.com", "constantcontact.com", "hubspot.com",
    "intercom-mail.com", "linkedin.com", "facebookmail.com", "instagram-mail.com",
    "twittermail.com", "stripe.com", "squareup.com", "uber.com", "doordash.com",
    "shipstation.com", "ups.com", "fedex.com", "usps.com", "canadapost.ca",
    "ticketmaster.com", "eventbrite.com", "zoom.us", "calendly.com", "github.com",
    "githubmail.com", "atlassian.net", "notion.so", "figma.com", "slack.com",
    "spotify.com", "netflix.com", "apple.com", "appleid.apple.com", "youtube.com",
    "discord.com", "patreon.com", "medium.com", "substack.com", "wix.com",
    "squarespace.com", "wordpress.com", "godaddy.com", "namecheap.com",
)


def _extract_email(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", str(text))
    return match.group(0).lower() if match else ""


def _is_automated_email(email: str) -> bool:
    """Heuristic: is this sender a noreply / newsletter / transactional source?"""
    if not email or "@" not in email:
        return False
    local, _, domain = email.partition("@")
    local = local.lower().strip()
    domain = domain.lower().strip()
    if not local or not domain:
        return False
    # Strong patterns in the localpart
    if "noreply" in local or "no-reply" in local or "donotreply" in local or "do-not-reply" in local:
        return True
    if local in _AUTOMATED_LOCALPARTS:
        return True
    # Common bulk-mail subdomain hints
    for hint in _AUTOMATED_DOMAIN_HINTS:
        if domain == hint or domain.endswith("." + hint):
            return True
    if domain.startswith(("mail.", "email.", "newsletter.", "news.", "alerts.", "notify.", "notifications.", "updates.", "promo.", "send.", "sender.", "delivery.")):
        return True
    # Domain ends with -mail.com / -email.com / -mailer.* (transactional ESP patterns)
    if re.search(r"-(mail|email|mailer|notify|sender)\.[a-z]{2,}$", domain):
        return True
    return False


def _is_automated_sender_record(record: JsonRecord) -> bool:
    """Inspect a normalized message/contact record and decide if the sender is automated."""
    candidates: list[str] = []
    for key in ("from", "sender", "display_name", "personName", "handle", "email"):
        val = record.get(key)
        if isinstance(val, dict):
            for sub in ("email", "address", "value", "id"):
                if val.get(sub):
                    candidates.append(str(val[sub]))
        elif isinstance(val, (list, tuple)):
            for item in val:
                if isinstance(item, str):
                    candidates.append(item)
        elif val:
            candidates.append(str(val))
    for raw in candidates:
        email = _extract_email(raw)
        if email and _is_automated_email(email):
            return True
    return False


def _heat_score_for_record(record: JsonRecord) -> tuple[int, str]:
    if _is_automated_sender_record(record):
        return 0, "normal"
    explicit = record.get("heat_score") or record.get("lead_score") or record.get("score")
    score = _safe_int(explicit, 35 if explicit is None else 0)
    haystack = " ".join(
        _tag_text(record.get(key))
        for key in ("ai_stage", "stage", "status", "priority", "tags", "source", "summary", "title")
    )
    if any(word in haystack for word in ("high_priority", "hot", "urgent", "overdue", "new lead", "needs follow")):
        score += 34
    if any(word in haystack for word in ("warm", "active", "prospecting", "ai_prospecting", "buyer", "seller")):
        score += 18
    if record.get("direction") == "inbound":
        score += 16
    score += min(_safe_int(record.get("inbound_count")), 18)

    latest = _parse_record_dt(_record_timestamp(record))
    if latest:
        age = datetime.now(timezone.utc) - latest
        if age <= timedelta(hours=24):
            score += 16
        elif age <= timedelta(days=7):
            score += 8

    score = max(0, min(score, 100))
    if score >= 76:
        label = "hot"
    elif score >= 54:
        label = "warm"
    elif score >= 35:
        label = "watch"
    else:
        label = "normal"
    return score, label


def _thread_from_record(source: JsonRecord, record: JsonRecord, status: str | None = None) -> JsonRecord:
    source_id = str(source.get("id") or record.get("source_id") or "").strip()
    thread_id = _thread_key(record)
    heat_score, heat_label = _heat_score_for_record(record)
    return {
        "id": f"{source_id}:{thread_id}",
        "sourceId": source_id,
        "sourceLabel": str(source.get("label") or source_id),
        "sourceState": source.get("state"),
        "threadId": thread_id,
        "conversationId": record.get("conversation_id") or record.get("source_record_id"),
        "contactId": record.get("contact_id"),
        "personName": _record_person_name(record),
        "channel": _channel_label(source_id, source, record),
        "latestText": _latest_text(record),
        "latestAt": _record_timestamp(record),
        "direction": str(record.get("direction") or "").strip() or None,
        "messageCount": _safe_int(record.get("total_messages") or record.get("message_count"), 1),
        "inboundCount": _safe_int(record.get("inbound_count")),
        "outboundCount": _safe_int(record.get("outbound_count")),
        "heatScore": heat_score,
        "heatLabel": heat_label,
        "status": status or "open",
        "record": _list_record_snapshot(record),
    }
