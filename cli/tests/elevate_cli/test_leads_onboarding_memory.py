"""LEADS_ONBOARDING.md generation — the leads peer of ADMIN_ONBOARDING.md."""

from __future__ import annotations

from elevate_cli.data.leads_setup import leads_setup_memory_summary


class _FakeConn:
    def __init__(self, identity_row=None):
        self._row = identity_row

    def execute(self, *_a, **_k):
        class _Cur:
            def __init__(self, row):
                self._row = row

            def fetchone(self):
                return self._row

        return _Cur(self._row)


def _snapshot(**over):
    base = {
        "items": [
            {"key": "crm", "provider": "Lofty", "status": "connected"},
            {"key": "meta_lead_ads", "provider": "", "status": "missing"},
            {"key": "google_lead_forms", "provider": "", "status": "missing"},
            {"key": "website_form_webhook", "provider": "", "status": "missing"},
            {"key": "auto_reply_policy", "status": "ok",
             "value": {"enabled": False, "followUpCadenceDays": 2}},
        ],
        "leadSourcesReady": True,
        "outreachConnectors": [],
    }
    base.update(over)
    return base


def test_summary_includes_core_sections():
    md = leads_setup_memory_summary(_FakeConn(), _snapshot())
    assert "# Leads onboarding memory" in md
    assert "## CRM (system of record for leads)" in md
    assert "Lofty" in md
    assert "## Outreach channels" in md
    assert "## Auto-reply & cadence policy" in md
    assert "2 day(s)" in md
    # the guardrail that prevents the agent inventing ICP/voice/cadence
    assert "ASK, don't invent" in md


def test_summary_flags_drafts_only_when_no_channel():
    md = leads_setup_memory_summary(_FakeConn(), _snapshot())
    assert "drafts only" in md
    assert "Auto first-touch: off" in md


def test_summary_reports_connected_channels_and_auto_on():
    snap = _snapshot(
        outreachConnectors=[{"key": "imsg", "label": "Apple Messages", "connected": True}],
        items=[
            {"key": "crm", "provider": "Lofty", "status": "connected"},
            {"key": "auto_reply_policy", "status": "ok",
             "value": {"enabled": True, "followUpCadenceDays": 3}},
        ],
    )
    md = leads_setup_memory_summary(_FakeConn(), snap)
    assert "Apple Messages" in md
    assert "Auto first-touch: on" in md
    assert "3 day(s)" in md
