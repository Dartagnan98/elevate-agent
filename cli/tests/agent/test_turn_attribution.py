"""Resolution logic for turn attribution (pure, no DB writes).

We monkeypatch the roster fetchers so the test is hermetic — it exercises the
explicit-id, fuzzy-match, mutation-skip, and sticky-boost paths without a live
database.
"""

from __future__ import annotations

import agent.turn_attribution as ta


_DEALS = [
    {"id": "deal-maple", "address": "412 Maple Ridge Rd", "title": "412 Maple Ridge"},
    {"id": "deal-lewis", "address": "88 Lewis Creek Lane", "title": "Lewis Creek"},
    {"id": "deal-generic", "address": "", "title": "CMA"},
]
_CONTACTS = [
    {"id": "c-shawn", "displayName": "Shawn Calhoon", "primaryEmail": "shawn@example.com"},
    {"id": "c-rod", "displayName": "Rod Berkey", "primaryEmail": "rodberkey@hotmail.ca"},
    {"id": "c-steph", "displayName": "Stephanie Power", "primaryEmail": "steph@example.com"},
]


class _FakeConn:
    pass


def _patch_roster(monkeypatch):
    monkeypatch.setattr(ta, "list_deals", lambda conn, **k: list(_DEALS), raising=False)
    monkeypatch.setattr(ta, "find_contacts", lambda conn, **k: list(_CONTACTS), raising=False)
    # The names are imported inside resolve_attributions via
    # `from elevate_cli.data import ...`, so patch there too.
    import elevate_cli.data as d
    monkeypatch.setattr(d, "list_deals", lambda conn, **k: list(_DEALS))
    monkeypatch.setattr(d, "find_contacts", lambda conn, **k: list(_CONTACTS))


def _asst(content, tool_calls=None):
    m = {"role": "assistant", "content": content}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return m


def _tc(name, args):
    import json
    return {"id": "x", "function": {"name": name, "arguments": json.dumps(args)}}


def test_explicit_deal_id_readonly_is_attributed(monkeypatch):
    _patch_roster(monkeypatch)
    msgs = [
        {"role": "user", "content": "what's the status"},
        _asst("here it is", [_tc("admin_deal", {"action": "show", "deal_id": "deal-maple"})]),
    ]
    out = ta.resolve_attributions(_FakeConn(), msgs)
    ids = {(a.entity_kind, a.entity_id) for a in out}
    assert ("deal", "deal-maple") in ids


def test_explicit_deal_mutation_is_skipped(monkeypatch):
    _patch_roster(monkeypatch)
    msgs = [
        {"role": "user", "content": "advance it"},
        _asst("done", [_tc("admin_deal", {"action": "set_fields", "deal_id": "deal-maple",
                                            "fields": {"listPrice": 500000}})]),
    ]
    out = ta.resolve_attributions(_FakeConn(), msgs)
    # It logged itself via the formal tool — no activity marker.
    assert all(a.entity_id != "deal-maple" for a in out)


def test_fuzzy_address_match(monkeypatch):
    _patch_roster(monkeypatch)
    msgs = [
        {"role": "user", "content": "draft the counter for 412 Maple Ridge Rd"},
        _asst("Drafted a counter-offer for 412 Maple Ridge Rd.",
              [_tc("draft_message", {"to": "buyer"})]),
    ]
    out = ta.resolve_attributions(_FakeConn(), msgs)
    deal = next((a for a in out if a.entity_id == "deal-maple"), None)
    assert deal is not None and deal.confidence >= ta.AUTO_LOG_THRESHOLD


def test_no_false_positive_on_generic_title(monkeypatch):
    _patch_roster(monkeypatch)
    msgs = [
        {"role": "user", "content": "run a CMA"},
        _asst("Working on the CMA now.", [_tc("terminal", {"command": "ls"})]),
    ]
    out = ta.resolve_attributions(_FakeConn(), msgs)
    # "CMA" is too generic / short — must NOT attribute deal-generic.
    assert all(a.entity_id != "deal-generic" for a in out)


def test_email_match(monkeypatch):
    _patch_roster(monkeypatch)
    msgs = [
        {"role": "user", "content": "follow up"},
        _asst("Emailing rodberkey@hotmail.ca now.", [_tc("draft_message", {})]),
    ]
    out = ta.resolve_attributions(_FakeConn(), msgs)
    assert any(a.entity_id == "c-rod" for a in out)


def test_single_token_needs_sticky(monkeypatch):
    _patch_roster(monkeypatch)
    msgs = [
        {"role": "user", "content": "draft something for Stephanie"},
        _asst("Drafting a note for Stephanie.", [_tc("draft_message", {})]),
    ]
    # Without sticky: single first-name token scores 0.4 < 0.7 → not logged.
    out = ta.resolve_attributions(_FakeConn(), msgs)
    assert all(a.entity_id != "c-steph" for a in out)
    # With sticky (we worked Stephanie earlier this session): boosted over bar.
    out2 = ta.resolve_attributions(_FakeConn(), msgs, sticky_ids={"c-steph"})
    assert any(a.entity_id == "c-steph" for a in out2)


def test_full_name_match(monkeypatch):
    _patch_roster(monkeypatch)
    msgs = [
        {"role": "user", "content": "prep for the meeting"},
        _asst("Reviewed Shawn Calhoon's file and drafted a reply.", [_tc("read_file", {})]),
    ]
    out = ta.resolve_attributions(_FakeConn(), msgs)
    assert any(a.entity_id == "c-shawn" for a in out)
