"""CRM write actions for source connectors."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from elevate_cli.source_connector_modules.integration_settings import _as_dict


JsonRecord = dict[str, Any]


def _source_connectors():
    from elevate_cli import source_connectors

    return source_connectors


# ── CRM write layer (create, note, stage update) ──────────────────────────────


def _sierra_headers(api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Sierra-ApiKey": api_key,
        "Sierra-OriginatingSystemName": "elevate",
    }


def _sierra_write(path: str, api_key: str, body: JsonRecord, method: str = "POST") -> Any:
    base = "https://api.sierrainteractivedev.com"
    url = f"{base}/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=_sierra_headers(api_key), method=method)
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _sierra_get(path: str, api_key: str, params: dict[str, Any] | None = None) -> Any:
    base = "https://api.sierrainteractivedev.com"
    url = f"{base}/{path.lstrip('/')}"
    if params:
        url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"
    request = urllib.request.Request(url, headers=_sierra_headers(api_key), method="GET")
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _brivity_headers(api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Token token={api_key}",
    }


def _brivity_write(path: str, api_key: str, body: JsonRecord, method: str = "POST") -> Any:
    base = "https://www.brivity.com"
    url = f"{base}/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=_brivity_headers(api_key), method=method)
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(1024 * 1024 * 4)
    return json.loads(raw.decode("utf-8") or "{}")


def _resolve_crm_context(
    config: dict[str, Any],
) -> tuple[str, str, JsonRecord, dict[str, str]]:
    """Return (provider, api_key, crm_config, env_values)."""
    env_values = _source_connectors()._combined_env(config)
    integrations = _as_dict(config.get("integrations"))
    crm = _source_connectors()._merge_crm(integrations.get("crm"))
    # Honor whatever CRM was picked at onboarding/config — never assume Lofty.
    provider = _source_connectors()._canonical_crm_provider(crm.get("provider"))
    env_key = str(crm.get("api_key_env") or "CRM_API_KEY")
    api_key = str(env_values.get(env_key) or "").strip()
    if not api_key and provider == "lofty":
        api_key = str(env_values.get("LOFTY_API_KEY") or env_values.get("LOFTY_ACCESS_TOKEN") or "").strip()
    return provider, api_key, crm, env_values


def crm_find_lead(
    email: str = "",
    config: dict[str, Any] | None = None,
    *,
    phone: str = "",
) -> JsonRecord | None:
    """Find a CRM lead by email (or phone fallback). Returns normalized {id, stage, tags} or None."""
    config = config or _source_connectors().load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)

    def _normalize_lofty(lead: JsonRecord) -> JsonRecord:
        return {
            "id": str(lead.get("leadId") or ""),
            "stage": str(lead.get("stage") or ""),
            "tags": [t.get("tagName") for t in (lead.get("tags") or []) if t.get("tagName")],
            "raw": lead,
        }

    if provider == "lofty":
        if email:
            payload = _source_connectors()._lofty_get(f"v1.0/leads?email={urllib.parse.quote(email)}&limit=1", env_values)
            lead = ((payload.get("leads") or []) + [None])[0]
            if lead:
                return _normalize_lofty(lead)
        if phone:
            payload = _source_connectors()._lofty_get(f"v1.0/leads?phone={urllib.parse.quote(phone)}&limit=1", env_values)
            lead = ((payload.get("leads") or []) + [None])[0]
            if lead:
                return _normalize_lofty(lead)
        return None

    if provider == "followupboss":
        if email:
            payload = _source_connectors()._generic_crm_get(crm, api_key, "v1/people", {"email": email, "limit": 1})
            people = payload.get("people") or []
            if people:
                p = people[0]
                return {"id": str(p.get("id") or ""), "stage": str(p.get("stage") or ""), "tags": list(p.get("tags") or []), "raw": p}
        if phone:
            payload = _source_connectors()._generic_crm_get(crm, api_key, "v1/people", {"phone": phone, "limit": 1})
            people = payload.get("people") or []
            if people:
                p = people[0]
                return {"id": str(p.get("id") or ""), "stage": str(p.get("stage") or ""), "tags": list(p.get("tags") or []), "raw": p}
        return None

    if provider == "sierra":
        if email:
            payload = _sierra_get("leads", api_key, {"email": email, "limit": 1})
            leads = (payload.get("data") or {}).get("leads") or []
            if leads:
                lead = leads[0]
                return {"id": str(lead.get("id") or lead.get("leadId") or ""), "stage": str(lead.get("status") or ""), "tags": list(lead.get("tags") or []), "raw": lead}
        if phone:
            payload = _sierra_get("leads", api_key, {"phone": phone, "limit": 1})
            leads = (payload.get("data") or {}).get("leads") or []
            if leads:
                lead = leads[0]
                return {"id": str(lead.get("id") or lead.get("leadId") or ""), "stage": str(lead.get("status") or ""), "tags": list(lead.get("tags") or []), "raw": lead}
        return None

    if provider == "brivity":
        # Brivity has no public search endpoint -- caller must track ids externally
        return None

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_find_lead not yet implemented for provider: {provider}")


def crm_create_lead(
    contact: JsonRecord,
    config: dict[str, Any] | None = None,
) -> str:
    """Create a lead in the CRM. contact = {firstName, lastName, email, phone, source, stage, tags}.
    Returns the new lead's CRM id."""
    config = config or _source_connectors().load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)
    first = str(contact.get("firstName") or "")
    last = str(contact.get("lastName") or "")
    email = str(contact.get("email") or "")
    phone = str(contact.get("phone") or "")
    source = str(contact.get("source") or "elevate")
    stage = str(contact.get("stage") or "New Leads")
    tags = list(contact.get("tags") or [])

    if provider == "lofty":
        body: JsonRecord = {"firstName": first, "lastName": last, "source": source, "stage": stage, "tags": tags}
        if email:
            body["emails"] = [email]
        if phone:
            body["phones"] = [phone]
        result = _source_connectors()._lofty_write("v1.0/leads", env_values, body, method="POST")
        return str(result.get("leadId") or result.get("id") or "")

    if provider == "followupboss":
        body = {"firstName": first, "lastName": last, "source": source}
        if email:
            body["emails"] = [{"value": email, "type": "work"}]
        if phone:
            body["phones"] = [{"value": phone, "type": "mobile"}]
        result = _source_connectors()._generic_crm_write(crm, api_key, "v1/people", body, method="POST")
        lead_id = str(result.get("id") or result.get("person", {}).get("id") or "")
        if lead_id and stage and stage != "New Leads":
            _source_connectors()._generic_crm_write(crm, api_key, f"v1/people/{lead_id}", {"stage": stage}, method="PUT")
        return lead_id

    if provider == "sierra":
        body = {"firstName": first, "lastName": last, "source": source}
        if email:
            body["email"] = email
        if phone:
            body["phone"] = phone
        if tags:
            body["tags"] = tags
        if stage:
            body["leadType"] = stage  # Sierra uses leadType on create, status on update
        note_text = str(contact.get("note") or "")
        if note_text:
            body["note"] = note_text
        result = _sierra_write("leads", api_key, body, method="POST")
        return str((result.get("data") or {}).get("id") or "")

    if provider == "brivity":
        # Brivity uses snake_case and encodes notes in description
        body = {"source": source}
        if first:
            body["first_name"] = first
        if last:
            body["last_name"] = last
        if email:
            body["email"] = email
        if phone:
            body["phone"] = phone
        if stage:
            # Brivity status enum: new, unqualified, watch, nurture, hot, archived
            body["status"] = stage.lower()
        note_text = str(contact.get("note") or "")
        if note_text:
            body["description"] = note_text
        result = _brivity_write("api/v2/leads", api_key, body, method="POST")
        return str((result.get("lead") or result).get("id") or "")

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_create_lead not yet implemented for provider: {provider}")


def crm_add_note(
    lead_id: str,
    note: str,
    config: dict[str, Any] | None = None,
) -> bool:
    """Add a note to an existing CRM lead. Returns True on success."""
    config = config or _source_connectors().load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)

    if provider == "lofty":
        try:
            _source_connectors()._lofty_write(f"v1.0/leads/{lead_id}/notes", env_values, {"content": note}, method="POST")
            return True
        except Exception:
            return False

    if provider == "followupboss":
        try:
            _source_connectors()._generic_crm_write(crm, api_key, "v1/notes", {"personId": int(lead_id), "body": note}, method="POST")
            return True
        except Exception:
            return False

    if provider == "sierra":
        try:
            _sierra_write(f"leads/{lead_id}/note", api_key, {"message": note}, method="POST")
            return True
        except Exception:
            return False

    if provider == "brivity":
        # Brivity has no notes endpoint -- notes must go into description at create time
        return False

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_add_note not yet implemented for provider: {provider}")


def sync_pending_notes_to_lofty(
    config: dict[str, Any] | None = None,
    *,
    limit: int = 25,
    max_attempts: int = 5,
) -> JsonRecord:
    """Push every ``notes`` row with ``crm_sync_state='pending'`` to
    Lofty. Returns a summary ``{pushed, skipped, failed, errors[]}``.

    Skip rules (counted in ``skipped``, not retried):
      * non-Lofty CRM provider — caller picked the wrong source.
      * Contact has no ``lofty_id`` identity — we have nowhere to POST.

    Failure rules:
      * 4xx → ``mark_lofty_failed(permanent=True)`` — payload bad, retry
        won't fix it. Operator can re-trigger by editing the body.
      * 5xx / timeout / unknown → ``mark_lofty_failed(permanent=False)`` —
        attempt counter bumps; row stays ``pending`` until ``max_attempts``.

    Content prefix: ``[AI/{author_name}] {body}`` — so the operator can
    skim Lofty's note feed and know what wrote each line.
    """
    config = config or _source_connectors().load_config()
    provider, _api_key, _crm, env_values = _resolve_crm_context(config)

    summary: JsonRecord = {
        "provider": provider,
        "pushed": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    if provider != "lofty":
        # Future: dispatch to followupboss / sierra / etc. For now only
        # Lofty is wired — others fall through silently to keep the cron
        # safe to run regardless of which CRM the operator connected.
        return summary

    headers, _auth_type = _source_connectors()._lofty_headers(env_values)
    if not headers.get("Authorization"):
        summary["errors"].append("LOFTY_API_KEY / LOFTY_ACCESS_TOKEN not set")
        return summary

    from elevate_cli.data import (
        connect as _db_connect,
        list_pending_lofty_notes,
        mark_lofty_synced,
        mark_lofty_failed,
    )

    with _db_connect() as conn:
        pending = list_pending_lofty_notes(conn, limit=limit, max_attempts=max_attempts)
        for note in pending:
            note_id = note["id"]
            contact_id = note["contactId"]
            # Resolve the contact's Lofty lead id via the identities table.
            lofty_row = conn.execute(
                "SELECT value FROM identities "
                "WHERE contact_id=? AND kind='lofty_id' LIMIT 1",
                (contact_id,),
            ).fetchone()
            if lofty_row is None or not lofty_row["value"]:
                # No Lofty linkage — permanently fail. If a Lofty identity
                # gets added later, the operator can re-trigger by editing
                # the note body (which moves it back to pending).
                mark_lofty_failed(
                    conn,
                    note_id=note_id,
                    error="contact has no lofty_id identity",
                    permanent=True,
                )
                summary["skipped"] += 1
                continue
            lead_id = str(lofty_row["value"])
            content = f"[AI/{note['authorName']}] {note['body']}"

            try:
                resp = _source_connectors()._lofty_write(
                    f"v1.0/leads/{lead_id}/notes",
                    env_values,
                    {"content": content},
                    method="POST",
                )
            except urllib.error.HTTPError as exc:
                if 400 <= exc.code < 500:
                    mark_lofty_failed(
                        conn,
                        note_id=note_id,
                        error=f"HTTP {exc.code}: {exc.reason}",
                        permanent=True,
                    )
                    summary["failed"] += 1
                else:
                    mark_lofty_failed(
                        conn,
                        note_id=note_id,
                        error=f"HTTP {exc.code}: {exc.reason}",
                        permanent=False,
                    )
                    summary["errors"].append(f"{note_id}: HTTP {exc.code}")
                continue
            except Exception as exc:
                mark_lofty_failed(
                    conn,
                    note_id=note_id,
                    error=str(exc)[:500],
                    permanent=False,
                )
                summary["errors"].append(f"{note_id}: {exc}")
                continue

            lofty_note_id = None
            if isinstance(resp, dict):
                # Lofty returns either {"noteId": …} or wraps the row under
                # "data". Probe both shapes.
                raw = resp.get("noteId") or resp.get("id")
                if raw is None and isinstance(resp.get("data"), dict):
                    raw = resp["data"].get("noteId") or resp["data"].get("id")
                if raw is not None:
                    lofty_note_id = str(raw)

            if lofty_note_id:
                mark_lofty_synced(conn, note_id=note_id, lofty_note_id=lofty_note_id)
                summary["pushed"] += 1
            else:
                # POST succeeded (no exception) but we couldn't parse the
                # id. Mark synced with a placeholder so we don't double-post,
                # but flag in errors so the operator can investigate.
                mark_lofty_synced(conn, note_id=note_id, lofty_note_id=f"unknown:{note_id}")
                summary["pushed"] += 1
                summary["errors"].append(
                    f"{note_id}: posted but noteId missing from response"
                )

    return summary


def crm_update_stage(
    lead_id: str,
    stage: str,
    tags: list[str] | None = None,
    config: dict[str, Any] | None = None,
) -> bool:
    """Update a CRM lead's stage and optionally merge tags. Returns True on success."""
    config = config or _source_connectors().load_config()
    provider, api_key, crm, env_values = _resolve_crm_context(config)

    if provider == "lofty":
        body: JsonRecord = {"stage": stage}
        if tags is not None:
            body["tags"] = tags
        try:
            _source_connectors()._lofty_write(f"v1.0/leads/{lead_id}", env_values, body, method="PUT")
            return True
        except Exception:
            return False

    if provider == "followupboss":
        body = {"stage": stage}
        try:
            _source_connectors()._generic_crm_write(crm, api_key, f"v1/people/{lead_id}", body, method="PUT")
            return True
        except Exception:
            return False

    if provider == "sierra":
        # Sierra status enum: New, Qualify, Active, Prime, Pending, Closed, Archived, Junk, DoNotContact, Watch, Blocked
        body = {"status": stage}
        if tags is not None:
            body["tags"] = tags
        try:
            _sierra_write(f"leads/{lead_id}", api_key, body, method="PUT")
            return True
        except Exception:
            return False

    if provider == "brivity":
        # Brivity has no status-update endpoint -- re-POST with status to upsert by email
        # Caller should use crm_create_lead with status set instead
        return False

    if provider == "boldtrail":
        raise NotImplementedError(
            "BoldTrail write API requires partner access. "
            "Request the Public V2 reference at support@insiderealestate.com."
        )

    raise NotImplementedError(f"crm_update_stage not yet implemented for provider: {provider}")
