"""Google Calendar -> Admin board event sync."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from elevate_cli import composio_client
from elevate_cli.config import load_config
from elevate_cli.data import connect
from elevate_cli.data.admin_calendar import (
    classify_calendar_kind,
    event_rows_from_payload,
    match_deal_by_address,
    prune_old_calendar_events,
    upsert_calendar_event,
)


_GOOGLE_CALENDAR_TOOLKITS = ("googlecalendar", "google-calendar", "gcal")
_EVENTS_LIST_TOOL = "GOOGLECALENDAR_EVENTS_LIST"


def _account_id(account: Mapping[str, Any]) -> str | None:
    raw = account.get("id") or account.get("connected_account_id") or account.get("connectedAccountId")
    return str(raw).strip() if raw else None


def _account_user_id(account: Mapping[str, Any]) -> str | None:
    raw = account.get("user_id") or account.get("userId")
    return str(raw).strip() if raw else None


def _event_id(event: Mapping[str, Any]) -> str | None:
    for key in ("id", "event_id", "eventId", "iCalUID", "ical_uid", "icalUid"):
        raw = event.get(key)
        if raw:
            return str(raw)
    return None


def _nested_datetime(event: Mapping[str, Any], key: str) -> Any:
    value = event.get(key)
    if isinstance(value, Mapping):
        return value.get("dateTime") or value.get("date_time") or value.get("date")
    return value


def _start_at(event: Mapping[str, Any]) -> Any:
    return (
        _nested_datetime(event, "start")
        or event.get("start_at")
        or event.get("startAt")
        or event.get("start_time")
        or event.get("startTime")
    )


def _end_at(event: Mapping[str, Any]) -> Any:
    return (
        _nested_datetime(event, "end")
        or event.get("end_at")
        or event.get("endAt")
        or event.get("end_time")
        or event.get("endTime")
    )


def _title(event: Mapping[str, Any]) -> str:
    raw = event.get("summary") or event.get("title") or event.get("name") or "Calendar event"
    return str(raw).strip() or "Calendar event"


def _location(event: Mapping[str, Any]) -> str | None:
    raw = event.get("location")
    if not raw:
        return None
    text = str(raw).strip()
    return text or None


def _calendar_args(days: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=max(1, min(int(days or 21), 90)))
    return {
        "calendar_id": "primary",
        "time_min": now.isoformat(),
        "time_max": horizon.isoformat(),
        "single_events": True,
        "order_by": "startTime",
        "max_results": 250,
    }


def _gws_calendar_rows(days: int) -> list[dict[str, Any]]:
    """Read the explicitly selected local Google Workspace connection.

    Fetch every page before writing local state. A failed or truncated read
    must not look like an empty calendar. Never run an interactive auth flow
    from this background job or include credential-bearing CLI output in errors.
    """
    search_path = os.pathsep.join(filter(None, (
        os.environ.get("PATH"), "/usr/local/bin", "/opt/homebrew/bin",
    )))
    binary = shutil.which("gws", path=search_path)
    if not binary:
        raise RuntimeError("Google Workspace CLI is not installed or not on PATH")
    args = _calendar_args(days)
    params = {
        "calendarId": args["calendar_id"],
        "timeMin": args["time_min"],
        "timeMax": args["time_max"],
        "singleEvents": args["single_events"],
        "orderBy": args["order_by"],
        "maxResults": args["max_results"],
    }
    rows: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    for _page in range(10):
        try:
            proc = subprocess.run(
                [binary, "calendar", "events", "list", "--params", json.dumps(params)],
                capture_output=True, text=True, timeout=20,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Google Workspace calendar read timed out") from None
        if proc.returncode != 0:
            raise RuntimeError(
                f"Google Workspace calendar read failed (exit {proc.returncode}); check its saved Google sign-in"
            )
        try:
            # gws may put a keyring status line before the JSON response.
            start = proc.stdout.index("{")
            payload, _end = json.JSONDecoder().raw_decode(proc.stdout[start:])
        except (ValueError, json.JSONDecodeError):
            raise RuntimeError("Google Workspace calendar returned invalid JSON") from None
        if not isinstance(payload, dict) or payload.get("error"):
            raise RuntimeError("Google Workspace calendar returned an API error")
        items = payload.get("items", [])
        if payload.get("kind") != "calendar#events" or not isinstance(items, list):
            raise RuntimeError("Google Workspace calendar returned an invalid event list")
        if any(not isinstance(item, dict) for item in items):
            raise RuntimeError("Google Workspace calendar returned an invalid event")
        rows.extend(items)
        token = payload.get("nextPageToken")
        if not token:
            return rows
        if not isinstance(token, str) or token in seen_tokens:
            raise RuntimeError("Google Workspace calendar pagination did not advance")
        seen_tokens.add(token)
        params["pageToken"] = token
    raise RuntimeError("Google Workspace calendar exceeded the 10-page read limit")


def _upsert_event_rows(conn: Any, rows: list[Mapping[str, Any]]) -> int:
    upserted = 0
    for row in rows:
        source_event_id = _event_id(row)
        start = _start_at(row)
        if not source_event_id or not start or row.get("status") == "cancelled":
            continue
        title = _title(row)
        location = _location(row)
        deal_id = match_deal_by_address(conn, title=title, location=location)
        upsert_calendar_event(
            conn,
            source="gcal",
            source_event_id=source_event_id,
            deal_id=deal_id,
            title=title,
            location=location,
            start_at=start,
            end_at=_end_at(row),
            kind=classify_calendar_kind(title),
            raw=dict(row),
        )
        upserted += 1
    return upserted


def _connected_accounts() -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    last_error: dict[str, Any] | None = None
    seen: set[str] = set()
    accounts: list[dict[str, Any]] = []
    for toolkit in _GOOGLE_CALENDAR_TOOLKITS:
        resp = composio_client.list_all_connected_accounts(toolkit=toolkit)
        if not resp.get("ok"):
            last_error = resp
            continue
        for account in (resp.get("data") or {}).get("items") or []:
            if not isinstance(account, dict):
                continue
            aid = _account_id(account)
            if not aid or aid in seen:
                continue
            seen.add(aid)
            accounts.append(account)
    return accounts, last_error


def sync_google_calendar_events(*, days: int = 21, provider: str = "composio") -> dict[str, Any]:
    if provider == "gws":
        try:
            rows = _gws_calendar_rows(days)
        except (OSError, RuntimeError) as exc:
            return {"ok": False, "reason": str(exc), "accounts": 0, "fetched": 0, "upserted": 0}
        with connect() as conn:
            upserted = _upsert_event_rows(conn, rows)
            pruned = prune_old_calendar_events(conn)
        return {
            "ok": True, "provider": "gws", "accounts": 1,
            "fetched": len(rows), "upserted": upserted, "pruned": pruned, "errors": [],
        }
    if provider != "composio":
        raise ValueError(f"Unknown calendar provider: {provider}")
    accounts, last_error = _connected_accounts()
    if not accounts:
        if last_error is not None:
            return {
                "ok": False,
                "skipped": True,
                "reason": "connected account lookup failed",
                "error": last_error.get("error"),
                "status": last_error.get("status"),
                "accounts": 0,
                "fetched": 0,
                "upserted": 0,
            }
        return {
            "ok": True,
            "skipped": True,
            "reason": "no connected google calendar accounts",
            "accounts": 0,
            "fetched": 0,
            "upserted": 0,
        }

    args = _calendar_args(days)
    fetched = 0
    upserted = 0
    errors: list[str] = []
    with connect() as conn:
        for account in accounts:
            aid = _account_id(account)
            if not aid:
                continue
            resp = composio_client.execute_tool(
                _EVENTS_LIST_TOOL,
                aid,
                args,
                user_id=_account_user_id(account),
            )
            if not resp.get("ok"):
                errors.append(str(resp.get("error") or "calendar tool failed"))
                continue
            payload = (resp.get("data") or {}).get("data") if isinstance(resp.get("data"), dict) else resp.get("data")
            if payload is None:
                payload = resp.get("data")
            rows = list(event_rows_from_payload(payload))
            fetched += len(rows)
            upserted += _upsert_event_rows(conn, rows)
        pruned = prune_old_calendar_events(conn)

    ok = not errors or upserted > 0
    return {
        "ok": ok,
        "skipped": False,
        "reason": None if ok else "; ".join(errors[:3]),
        "accounts": len(accounts),
        "fetched": fetched,
        "upserted": upserted,
        "pruned": pruned,
        "errors": errors[:10],
    }


def main(argv: list[str] | None = None) -> int:
    config = load_config() or {}
    calendar_config = config.get("admin_calendar") or {}
    provider = calendar_config.get("provider") or "composio"
    parser = argparse.ArgumentParser(description="Sync Google Calendar events into Admin board events.")
    parser.add_argument("--days", type=int, default=21)
    parser.add_argument("--provider", choices=("composio", "gws"), default=provider)
    args = parser.parse_args(argv)
    if args.provider not in {"composio", "gws"}:
        parser.error("admin_calendar.provider must be composio or gws")

    result = sync_google_calendar_events(days=args.days, provider=args.provider)
    if not result.get("ok"):
        status = result.get("status")
        reason = result.get("reason") or result.get("error") or "calendar sync failed"
        # Config/auth blockers should not make the recurring job noisy. The
        # connector setup screen is where the operator fixes the key/account.
        if status in {401, 403} or result.get("skipped"):
            print("wakeAgent: false")
            return 0
        print(f"Admin calendar sync failed: {reason}")
        return 1

    if result.get("upserted", 0) <= 0:
        print("wakeAgent: false")
        return 0

    print(
        "Admin calendar sync: "
        f"{result.get('upserted', 0)} events synced from "
        f"{result.get('accounts', 0)} account(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
