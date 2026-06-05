"""CDP-backed writer for Xposure PCS listing engagement snapshots.

This module is intentionally small and standalone because the visible
dashboard run needs the browser to stay observable while avoiding a giant
JSON payload flowing back through the agent conversation. The agent logs
into Xposure in a normal browser session, then this writer attaches to that
same Chrome DevTools target, scrapes the DataTables model + Client View HTML,
and appends compact JSONL locally.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

import websockets

from elevate_cli.xposure_board import board_config, portal_host


def _contacts_url() -> str:
    return board_config()["contacts_url"]


class CdpError(RuntimeError):
    """Raised when the Chrome DevTools Protocol call fails."""


class CdpClient:
    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self._next_id = 0
        self._ws: Any = None

    async def __aenter__(self) -> "CdpClient":
        self._ws = await websockets.connect(self.ws_url, max_size=None)
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if self._ws is not None:
            await self._ws.close()

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        if self._ws is None:
            raise CdpError("CDP websocket is not connected")
        self._next_id += 1
        msg_id = self._next_id
        await self._ws.send(json.dumps({
            "id": msg_id,
            "method": method,
            "params": params or {},
        }))
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
            payload = json.loads(raw)
            if payload.get("id") != msg_id:
                continue
            if payload.get("error"):
                raise CdpError(f"{method} failed: {payload['error']}")
            return payload.get("result") or {}


def _read_cdp_json(cdp_url: str, path: str) -> Any:
    url = cdp_url.rstrip("/") + path
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _pick_page_target(cdp_url: str) -> dict[str, Any]:
    targets = _read_cdp_json(cdp_url, "/json")
    pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if not pages:
        raise CdpError("no debuggable browser page found on CDP endpoint")
    for needle in (portal_host(), "xposureapp.com"):
        for page in pages:
            if needle in str(page.get("url") or ""):
                return page
    return pages[0]


def _runtime_value(result: dict[str, Any]) -> Any:
    if result.get("exceptionDetails"):
        details = result["exceptionDetails"]
        text = details.get("text") or details.get("exception", {}).get("description")
        raise CdpError(f"runtime exception: {text}")
    obj = result.get("result") or {}
    if "value" in obj:
        return obj["value"]
    if "description" in obj:
        return obj["description"]
    return None


async def _evaluate(
    cdp: CdpClient,
    expression: str,
    *,
    timeout_seconds: float,
) -> Any:
    result = await cdp.call(
        "Runtime.evaluate",
        {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
            "timeout": int(timeout_seconds * 1000),
        },
        timeout=timeout_seconds + 30,
    )
    return _runtime_value(result)


async def _wait_for_contacts(cdp: CdpClient, *, timeout_seconds: int = 90) -> dict[str, Any]:
    await cdp.call("Page.enable")
    await cdp.call("Runtime.enable")
    await cdp.call("Page.navigate", {"url": _contacts_url()})
    expression = f"""
new Promise((resolve) => {{
  const started = Date.now();
  const timeoutMs = {timeout_seconds * 1000};
  const tick = () => {{
    const ok = !!(window.jQuery && jQuery.fn && jQuery.fn.DataTable &&
      document.querySelector('#pcs-contacts-table'));
    if (ok) {{
      resolve({{ok: true, url: location.href, title: document.title}});
      return;
    }}
    if (Date.now() - started > timeoutMs) {{
      resolve({{
        ok: false,
        url: location.href,
        title: document.title,
        body: (document.body && document.body.innerText || '').slice(0, 800)
      }});
      return;
    }}
    setTimeout(tick, 1000);
  }};
  tick();
}})
"""
    value = await _evaluate(cdp, expression, timeout_seconds=timeout_seconds + 10)
    if not isinstance(value, dict) or not value.get("ok"):
        raise CdpError(f"contacts table not ready: {value}")
    return value


def _scrape_expression(emails: list[str]) -> str:
    wanted_json = json.dumps(sorted({email.strip().lower() for email in emails if email.strip()}))
    dologin_url = board_config()["dologin_url"]
    return f"""
(async () => {{
  const wanted = new Set({wanted_json});
  const DOLOGIN_URL = {json.dumps(dologin_url)};
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const norm = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const intFromText = (value) => {{
    const m = norm(value).replace(/,/g, '').match(/-?\\d+/);
    return m ? Number(m[0]) : null;
  }};
  const priceCents = (value) => {{
    const m = norm(value).replace(/,/g, '').match(/\\$?\\s*(\\d+(?:\\.\\d{{1,2}})?)/);
    return m ? Math.round(Number(m[1]) * 100) : null;
  }};
  const dedupeRepeated = (value) => {{
    let text = norm(value);
    if (!text) return null;
    const parts = text.split(' ');
    if (parts.length > 1 && parts.length % 2 === 0) {{
      const half = parts.length / 2;
      if (parts.slice(0, half).join(' ') === parts.slice(half).join(' ')) {{
        text = parts.slice(0, half).join(' ');
      }}
    }}
    return text || null;
  }};
  const text = (root, selector) => {{
    const el = root.querySelector(selector);
    return el ? dedupeRepeated(el.textContent) : null;
  }};
  const field = (card, names) => {{
    const wantedNames = names.map((name) => name.toLowerCase());
    for (const label of Array.from(card.querySelectorAll('td.listing-label'))) {{
      const key = norm(label.textContent).replace(/[®:]/g, '').toLowerCase();
      if (!wantedNames.includes(key)) continue;
      return dedupeRepeated(label.nextElementSibling ? label.nextElementSibling.textContent : '');
    }}
    return null;
  }};
  const parseClientDate = (value) => {{
    const clean = norm(value).replace(/^Viewed\\s+/i, '').replace(/Pacific time/i, '').trim();
    if (!clean) return null;
    const months = {{jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,sept:9,oct:10,nov:11,dec:12}};
    const m = clean.match(/^([A-Za-z]{{3,9}})\\s+(\\d{{1,2}})\\/(\\d{{2,4}})(?:\\s+(\\d{{1,2}}):(\\d{{2}})\\s*(AM|PM))?/i);
    if (!m) return null;
    const month = months[m[1].slice(0, 3).toLowerCase()];
    if (!month) return null;
    const day = Number(m[2]);
    let year = Number(m[3]);
    if (year < 100) year += 2000;
    let hour = Number(m[4] || 0);
    const minute = Number(m[5] || 0);
    const ampm = (m[6] || '').toUpperCase();
    if (ampm === 'PM' && hour < 12) hour += 12;
    if (ampm === 'AM' && hour === 12) hour = 0;
    const pad = (n) => String(n).padStart(2, '0');
    const offset = month >= 4 && month <= 10 ? '-07:00' : '-08:00';
    return `${{year}}-${{pad(month)}}-${{pad(day)}}T${{pad(hour)}}:${{pad(minute)}}:00${{offset}}`;
  }};
  const tabCount = (doc, label) => {{
    const lower = label.toLowerCase();
    for (const el of Array.from(doc.querySelectorAll('.nav-link,.listings-tab,a,button'))) {{
      const t = norm(el.textContent);
      if (t.toLowerCase().startsWith(lower)) return intFromText(t);
    }}
    return null;
  }};
  const parseListing = (card) => {{
    const viewedTexts = Array.from(card.querySelectorAll('.viewed-info'))
      .map((el) => norm(el.textContent)).filter(Boolean);
    let viewCount = 0;
    let lastViewedAt = null;
    for (const item of viewedTexts) {{
      const views = item.match(/(\\d+)\\s+views?/i);
      if (views) viewCount = Math.max(viewCount, Number(views[1]));
      if (/^Viewed\\b/i.test(item)) lastViewedAt = parseClientDate(item);
    }}
    const mls = field(card, ['MLS']) || field(card, ['MLS#']);
    const state = viewCount > 0 || lastViewedAt
      ? 'viewed'
      : (String(card.className || '').includes('has-changes') ? 'pc' : 'older');
    return {{
      mls_id: mls ? String(mls).replace(/\\D/g, '') || String(mls) : null,
      address: text(card, '.listing-address'),
      major_area: text(card, '.listing-area'),
      minor_area: text(card, '.listing-subarea'),
      list_price_cents: priceCents(text(card, '.listing-price')),
      status: field(card, ['Status']),
      beds: intFromText(field(card, ['Bed', 'Beds'])),
      baths: intFromText(field(card, ['Bath', 'Baths'])),
      year_built: intFromText(field(card, ['Year Built'])),
      style: field(card, ['Style']),
      property_type: field(card, ['Type', 'Property Type']),
      dom_days: intFromText(field(card, ['DOM'])),
      view_count: viewCount,
      last_viewed_at: lastViewedAt,
      view_state: state,
    }};
  }};
  const parseSearch = async (contact, search) => {{
    const params = new URLSearchParams([
      ['currentContactID', String(contact.contactId)],
      ['currentSearchID', String(search.searchId)],
      ['autoAgtLogin', 'true'],
      ['pcsResultVisibility', '1'],
      ['returnAction', 'contacts'],
    ]);
    const resp = await fetch(DOLOGIN_URL, {{
      method: 'POST',
      body: params,
      credentials: 'include',
    }});
    const html = await resp.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const bodyText = norm(doc.body ? doc.body.textContent : '');
    const resultText = text(doc, '#search-results-tab') || text(doc, '.results-info-text') || bodyText;
    const access = bodyText.match(/Last Client Access:\\s*([A-Za-z]{{3,9}}\\s+\\d{{1,2}}\\/\\d{{2,4}}(?:\\s+\\d{{1,2}}:\\d{{2}}\\s*(?:AM|PM))?)/i);
    const cards = Array.from(doc.querySelectorAll('.listing-container'));
    return {{
      scraped_at: new Date().toISOString(),
      buyer_email: String(contact.email || '').toLowerCase(),
      xposure_contact_id: String(contact.contactId),
      search_id: String(search.searchId),
      summary: {{
        results: intFromText(resultText),
        favorites: tabCount(doc, 'Favorites') ?? Number(search.favorites || 0),
        removed: tabCount(doc, 'Removed'),
        queue: tabCount(doc, 'Queue') ?? Number(search.queue || 0),
        total_found: intFromText(resultText),
        last_access: access ? parseClientDate(access[1]) : null,
      }},
      listings: cards.map(parseListing).filter((listing) => listing.mls_id),
    }};
  }};

  const dt = $('#pcs-contacts-table').DataTable();
  dt.page.len(-1).draw(false);
  await sleep(5000);
  const contacts = dt.rows().data().toArray()
    .filter((c) => wanted.has(String(c.email || '').toLowerCase()))
    .map((c) => ({{
      contactId: String(c.contactId || ''),
      email: String(c.email || '').toLowerCase(),
      searches: Array.isArray(c.searches) ? c.searches.map((s) => ({{
        searchId: String(s.searchId || ''),
        title: s.title || '',
        active: !!s.isActive,
        favorites: Number(s.favorites_count || 0),
        queue: Number(s.queuedListingsCount || 0),
        enableBinocularView: s.enableBinocularView !== false,
      }})) : [],
    }}));
  const records = [];
  const errors = [];
  let searchCount = 0;
  let skippedDisabled = 0;
  for (const contact of contacts) {{
    for (const search of contact.searches) {{
      if (!search.searchId) continue;
      if (search.enableBinocularView === false) {{
        skippedDisabled += 1;
        continue;
      }}
      searchCount += 1;
      try {{
        records.push(await parseSearch(contact, search));
      }} catch (err) {{
        errors.push({{
          contactId: contact.contactId,
          searchId: search.searchId,
          message: String(err && err.message || err),
        }});
      }}
    }}
  }}
  const matchedEmails = new Set(contacts.map((c) => c.email));
  return {{
    records,
    contactsMatched: contacts.length,
    searchCount,
    skippedDisabled,
    missingCount: Array.from(wanted).filter((email) => !matchedEmails.has(email)).length,
    errors,
  }};
}})()
"""


async def run_writer(args: argparse.Namespace) -> dict[str, Any]:
    emails = [
        line.strip().lower()
        for line in Path(args.emails_file).read_text().splitlines()
        if line.strip() and "@" in line
    ]
    if not emails:
        raise CdpError("email target file is empty")

    target = _pick_page_target(args.cdp)
    snapshot = Path(args.snapshot).expanduser()
    async with CdpClient(target["webSocketDebuggerUrl"]) as cdp:
        ready = await _wait_for_contacts(cdp, timeout_seconds=args.ready_timeout)
        scraped = await _evaluate(
            cdp,
            _scrape_expression(emails),
            timeout_seconds=args.scrape_timeout,
        )

    if not isinstance(scraped, dict):
        raise CdpError(f"unexpected scrape result: {type(scraped).__name__}")

    records = scraped.get("records") or []
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    with snapshot.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n")

    listing_count = sum(len(rec.get("listings") or []) for rec in records if isinstance(rec, dict))
    errors = scraped.get("errors") or []
    return {
        "ok": True,
        "url": ready.get("url"),
        "targets": len(emails),
        "contacts_matched": scraped.get("contactsMatched", 0),
        "searches_seen": scraped.get("searchCount", 0),
        "skipped_disabled": scraped.get("skippedDisabled", 0),
        "missing_count": scraped.get("missingCount", 0),
        "records_appended": len(records),
        "listings_seen": listing_count,
        "errors": len(errors),
        "snapshot": str(snapshot),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emails-file", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--ready-timeout", type=int, default=90)
    parser.add_argument("--scrape-timeout", type=int, default=360)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    try:
        result = asyncio.run(run_writer(args))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
