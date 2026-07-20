"""Package A5 — outbound send-queue lane fail-closed under exact Realtor Beta.

The durable sender (``elevate_cli/sender.py``) is a direct external-effect
lane — Composio provider sends, native Apple Messages, agent dispatchers —
that never passes through the accepted-turn registry/effect-broker
boundary.  Every production caller (gateway cron ticker, app approve-tick,
source-sender web route, inbox retry route, approve-thread) converges on
the module's two chokepoints, ``tick`` and ``dispatch_one``.  Under exact
Beta both refuse with a typed payload BEFORE any queue-state write,
stale-send recovery, row claim, or dispatcher invocation; rows stay
durably queued.  Stable behavior is byte-identical, and the exact-lowercase
channel contract holds (``BeTa`` is not Beta).
"""

from __future__ import annotations


from elevate_cli import sender


def _forbid(monkeypatch, obj, names):
    for name in names:
        monkeypatch.setattr(
            obj,
            name,
            lambda *a, _n=name, **k: (_ for _ in ()).throw(
                AssertionError(f"{_n} must not run under exact Beta")
            ),
        )


def _queued_row(**overrides):
    row = {
        "id": "q-beta-1",
        "channel": "email",
        "attempts": 0,
        "status": "queued",
        "payload": {"slug": "GMAIL_SEND_EMAIL", "args": {}},
        "providerMessageId": None,
        "taskId": "task-1",
    }
    row.update(overrides)
    return row


class TestExactBetaSenderRefusal:
    def test_tick_refuses_before_any_queue_mutation(self, monkeypatch):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        _forbid(
            monkeypatch,
            sender.outreach_db,
            ("recover_stale_sends", "claim_due_sends", "mark_sent",
             "mark_failed", "mark_retrying"),
        )

        counts = sender.tick(batch=20)

        assert counts["claimed"] == 0
        assert counts["sent"] == 0
        assert counts["retrying"] == 0
        assert counts["failed"] == 0
        assert counts["recovered_sent"] == 0
        assert counts["recovered_failed"] == 0
        assert sender.BETA_OUTBOUND_SEND_DISABLED_CODE in counts["policy_blocked"]

    def test_dispatch_one_refuses_before_dispatcher_and_marks(self, monkeypatch):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        _forbid(
            monkeypatch,
            sender.outreach_db,
            ("mark_sent", "mark_failed", "mark_retrying"),
        )
        _forbid(monkeypatch, sender, ("get_dispatcher",))

        result = sender.dispatch_one(_queued_row())

        assert result["status"] == "policy_blocked"
        assert result["error_code"] == sender.BETA_OUTBOUND_SEND_DISABLED_CODE
        assert sender.BETA_OUTBOUND_SEND_DISABLED_CODE in result["lastError"]
        assert result["id"] == "q-beta-1"
        assert result["providerMessageId"] is None

    def test_dispatch_one_refuses_even_the_crash_recovery_short_circuit(
        self, monkeypatch
    ):
        """A row carrying prior provider evidence (crash between provider
        success and ``mark_sent``) is ALSO left untouched: the refusal
        precedes every queue-state write, so exact Beta performs zero
        mutations of any kind."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        _forbid(monkeypatch, sender.outreach_db, ("mark_sent",))

        result = sender.dispatch_one(
            _queued_row(status="sending", providerMessageId="pm-123")
        )

        assert result["status"] == "policy_blocked"
        assert result["error_code"] == sender.BETA_OUTBOUND_SEND_DISABLED_CODE

    def test_sandbox_flag_cannot_reopen_the_lane_under_exact_beta(
        self, monkeypatch
    ):
        """The outreach sandbox stub still exercises the queue in Stable
        dry-runs, but under exact Beta even the stub is refused: the policy
        gate precedes dispatcher selection entirely."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        monkeypatch.setenv("ELEVATE_OUTREACH_SANDBOX", "1")
        _forbid(
            monkeypatch,
            sender.outreach_db,
            ("mark_sent", "mark_failed", "mark_retrying"),
        )

        result = sender.dispatch_one(_queued_row())

        assert result["status"] == "policy_blocked"

    def test_typed_reason_helper_matches_channel_contract(self, monkeypatch):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        reason = sender.outbound_send_disabled_reason()
        assert reason is not None
        assert sender.BETA_OUTBOUND_SEND_DISABLED_CODE in reason

        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
        assert sender.outbound_send_disabled_reason() is None


class TestStableByteParity:
    def test_stable_tick_still_recovers_claims_and_dispatches(self, monkeypatch):
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
        recovered = []
        claimed = []
        monkeypatch.setattr(
            sender.outreach_db,
            "recover_stale_sends",
            lambda: recovered.append(1) or {"sent": 0, "failed": 0},
        )
        monkeypatch.setattr(
            sender.outreach_db,
            "claim_due_sends",
            lambda limit, skip_channels=None: claimed.append(limit) or [],
        )

        counts = sender.tick(batch=7)

        assert recovered == [1]
        assert claimed == [7]
        assert counts["claimed"] == 0
        assert "policy_blocked" not in counts

    def test_stable_sandbox_dispatch_still_marks_sent(self, monkeypatch):
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
        monkeypatch.setenv("ELEVATE_OUTREACH_SANDBOX", "1")
        marked = []
        monkeypatch.setattr(
            sender.outreach_db,
            "mark_sent",
            lambda queue_id, pmid: marked.append((queue_id, pmid))
            or {"status": "sent", "id": queue_id, "providerMessageId": pmid},
        )

        result = sender.dispatch_one(_queued_row())

        assert result["status"] == "sent"
        assert len(marked) == 1
        assert marked[0][0] == "q-beta-1"
        assert marked[0][1].startswith("stub-email-")

    def test_noncanonical_channel_keeps_stable_sender_behavior(self, monkeypatch):
        """Exact-lowercase contract: ``BeTa`` must NOT inherit Beta clamps."""
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "BeTa")
        assert sender.outbound_send_disabled_reason() is None
        monkeypatch.setenv("ELEVATE_OUTREACH_SANDBOX", "1")
        marked = []
        monkeypatch.setattr(
            sender.outreach_db,
            "mark_sent",
            lambda queue_id, pmid: marked.append(queue_id)
            or {"status": "sent", "id": queue_id, "providerMessageId": pmid},
        )
        result = sender.dispatch_one(_queued_row(id="q-nc-1"))
        assert result["status"] == "sent"
        assert marked == ["q-nc-1"]
