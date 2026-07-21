"""The three severances that make a truthful local-only declaration possible.

A board tool is only allowed to declare ``write_local:<scope>`` if the outward
branches hanging off it are genuinely unreachable under that ceiling. Four
such branches exist in the shipped code:

1. ``elevate_cli.data.deals._dispatch_safely`` — a deal stage move can reach
   ``dispatch.evaluate(create_cron_jobs=True)``, which calls
   ``cron.jobs.create_job`` with a Telegram delivery lane. Severed on
   ``spawn``.
2. ``tools.lead_status_crm.push_lead_status_to_crm`` — a status change can be
   mirrored into Lofty / Follow Up Boss / Sierra, whose own automations can
   then reach the realtor's clients. Severed on ``write_external:crm``.
3. ``elevate_cli.kanban_db._cleanup_workspace`` — completing a card rmtree's
   a scratch directory and shells out to ``tmux``. Severed on
   ``destructive``.
4. ``elevate_cli.kanban_db.dispatch_once`` — a created card is an ENQUEUE, and
   this tick is what turns an enqueued card into a detached ``elevate chat``
   subprocess.

(1)-(3) are cut on a CAPABILITY, not on a release channel or a config flag, so
they keep holding if Beta's kill-switches are ever removed. For (1) that
required more than an in-turn check: cutting only the immediate call would be a
DEFERRAL, since the queued ``admin_action_runs`` row survives and a later drain
runs with no policy bound. So the restriction is stamped ON THE ROW at insert
and re-checked at ``dispatch_action_run_to_cron``, and only an explicit human
approval clears it.

(4) is deliberately a release-policy check instead — it sits in the unattended
dispatcher loop, which by construction has no accepted-turn policy to consult,
so it uses the same ``scheduled_execution_disabled_reason()`` gate every other
unattended entrypoint uses.

Every capability test below asserts the same two-sided property: severed under
the workspace ceiling, UNCHANGED with no policy bound (the CLI / dashboard /
background path) and under Stable's DEFAULT ceiling.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.approval import (
    ExecutionPolicy,
    ExecutionPolicyMode,
    get_current_execution_policy,
    reset_current_execution_policy,
    set_current_execution_policy,
)


@pytest.fixture(autouse=True)
def _no_ambient_policy():
    assert get_current_execution_policy() is None
    yield
    assert get_current_execution_policy() is None


@pytest.fixture
def board_policy():
    """Bind the exact-Beta cohort ceiling for the test body."""
    token = set_current_execution_policy(
        ExecutionPolicy.for_mode("turn-board", ExecutionPolicyMode.WORKSPACE),
        policy_revision=1,
    )
    try:
        yield
    finally:
        reset_current_execution_policy(token)


@pytest.fixture
def stable_policy():
    """Bind Stable's DEFAULT ceiling for the test body."""
    token = set_current_execution_policy(
        ExecutionPolicy.for_mode("turn-stable", ExecutionPolicyMode.DEFAULT),
        policy_revision=1,
    )
    try:
        yield
    finally:
        reset_current_execution_policy(token)


# ---------------------------------------------------------------------------
# 1. Cron / Telegram severance on a deal stage move
# ---------------------------------------------------------------------------


@pytest.fixture
def recorded_evaluate(monkeypatch):
    """Record every ``dispatch.evaluate`` call ``_dispatch_safely`` makes."""
    from elevate_cli.data import dispatch as dispatch_module

    calls: list[dict] = []

    def _evaluate(conn, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(dispatch_module, "evaluate", _evaluate)
    return calls


def _dispatch(triggers=(("stage_entry", {"to_stage": 2}),)):
    from elevate_cli.data.deals import _dispatch_safely

    _dispatch_safely(
        None,
        deal_id="deal-1",
        deal_event_id="event-1",
        actor="skill:admin_deal",
        triggers=triggers,
    )


def test_board_ceiling_severs_the_cron_handoff(recorded_evaluate, board_policy):
    """A card move must not be able to spawn work that messages a human."""
    _dispatch()
    assert recorded_evaluate
    for call in recorded_evaluate:
        assert call["create_cron_jobs"] is False


def test_the_queued_run_row_still_gets_written(recorded_evaluate, board_policy):
    """Severing the handoff must not sever the local record of it.

    ``evaluate`` is still called for every trigger — matching rules persist
    their queued ``admin_action_runs`` rows, which is a local write to the
    same operational store the board write already covers.
    """
    _dispatch(
        triggers=(("stage_exit", {"from_stage": 1}), ("stage_entry", {"to_stage": 2}))
    )
    assert [call["trigger"] for call in recorded_evaluate] == [
        "stage_exit",
        "stage_entry",
    ]


def test_no_bound_policy_leaves_the_cron_handoff_untouched(recorded_evaluate):
    """Stable byte-identical: the CLI/dashboard path is not a policy context."""
    _dispatch()
    assert recorded_evaluate
    for call in recorded_evaluate:
        assert call["create_cron_jobs"] is True


def test_default_ceiling_leaves_the_cron_handoff_untouched(
    recorded_evaluate, stable_policy
):
    _dispatch()
    assert recorded_evaluate
    for call in recorded_evaluate:
        assert call["create_cron_jobs"] is True


@pytest.mark.parametrize(
    "mode", [ExecutionPolicyMode.READ_ONLY, ExecutionPolicyMode.PLAN,
             ExecutionPolicyMode.DRAFT_ONLY]
)
def test_every_narrower_ceiling_also_severs_the_cron_handoff(
    recorded_evaluate, mode
):
    token = set_current_execution_policy(
        ExecutionPolicy.for_mode("turn-narrow", mode), policy_revision=1
    )
    try:
        _dispatch()
    finally:
        reset_current_execution_policy(token)
    assert recorded_evaluate
    for call in recorded_evaluate:
        assert call["create_cron_jobs"] is False


def test_the_severance_is_not_a_release_channel_check(
    recorded_evaluate, board_policy, monkeypatch
):
    """Beta's cron kill-switch is a setting; this is a capability boundary.

    Force the channel to Stable while the board ceiling is bound: the handoff
    must still be severed, because the cut is made on the policy.
    """
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")
    _dispatch()
    assert recorded_evaluate
    for call in recorded_evaluate:
        assert call["create_cron_jobs"] is False


# ---------------------------------------------------------------------------
# 1b. The severance is DURABLE, not a deferral
#
# Cutting only the in-turn call would leave the queued ``admin_action_runs``
# row behind, and any later drain running outside a policy context would hand
# it to cron exactly as before — reaching a human asynchronously from a write
# the agent made. So the restriction travels on the ROW.
# ---------------------------------------------------------------------------


def test_mark_spawn_withheld_preserves_the_original_payload():
    from elevate_cli.data import dispatch as d

    payload = d._mark_spawn_withheld({"trigger": "stage_entry"})
    assert d._spawn_is_withheld(payload) is True
    assert payload["trigger"] == "stage_entry"


def _insert_run_capture(monkeypatch):
    """Drive the real ``_insert_run`` and capture what it wrote.

    This exercises the STAMPING ITSELF, not the helper it calls. Without it,
    both stamping lines could be deleted from ``_insert_run`` and every other
    test in this file would still pass — the load-bearing half of the
    severance would be unpinned.
    """
    from elevate_cli.data import dispatch as d

    written: dict = {}
    wakes: list[str] = []

    class _Cursor:
        def __init__(self, row=None):
            self._row = row

        def fetchone(self):
            return self._row

    class _Conn:
        def execute(self, sql, params=()):
            if sql.strip().startswith("INSERT INTO admin_action_runs"):
                written["payload_json"] = params[5]
                written["status"] = params[4]
                return _Cursor()
            return _Cursor(None)

    monkeypatch.setattr(
        d, "_select_action_run_with_registry", lambda conn, rid: {"id": rid}
    )
    monkeypatch.setattr(d, "_row_to_run", lambda row: dict(row))
    monkeypatch.setattr(
        d,
        "_request_agent_worker_wake",
        lambda *, reason, actor: wakes.append(reason),
    )

    d._insert_run(
        _Conn(),
        registry_id="reg-1",
        deal_id="deal-1",
        deal_event_id=None,
        payload={"trigger": "stage_entry"},
    )
    return written, wakes


def test_insert_run_stamps_the_row_under_the_board_ceiling(
    board_policy, monkeypatch
):
    from elevate_cli.data import dispatch as d

    written, wakes = _insert_run_capture(monkeypatch)

    assert d._spawn_is_withheld(d._decode_json(written["payload_json"])) is True
    # Waking the drain for a row the drain must park is noise.
    assert wakes == []


def test_insert_run_leaves_the_legacy_path_unstamped(monkeypatch):
    """Stable byte-identical: no policy bound means no stamp and a normal wake."""
    from elevate_cli.data import dispatch as d

    written, wakes = _insert_run_capture(monkeypatch)

    assert d._spawn_is_withheld(d._decode_json(written["payload_json"])) is False
    assert d._decode_json(written["payload_json"]) == {"trigger": "stage_entry"}
    assert len(wakes) == 1


def test_insert_run_leaves_the_default_ceiling_unstamped(stable_policy, monkeypatch):
    from elevate_cli.data import dispatch as d

    written, wakes = _insert_run_capture(monkeypatch)

    assert d._spawn_is_withheld(d._decode_json(written["payload_json"])) is False
    assert len(wakes) == 1


def test_the_spawn_withheld_prompt_cannot_be_mistaken_for_an_info_card():
    """Consent-scope guard.

    ``deals._is_missing_info_prompt`` treats any prompt carrying
    ``requiredFields`` as an "Info needed" card and deduplicates other runs
    behind it. If the spawn-withheld prompt looked like one, approving
    "Start this in the background?" would ALSO release a deferred skill the
    realtor was never shown — a consent smear on the one card whose entire
    job is scoping consent.
    """
    import inspect

    from elevate_cli.data import dispatch as d
    from elevate_cli.data.deals import _is_missing_info_prompt

    source = inspect.getsource(d.dispatch_action_run_to_cron)
    start = source.index("spawn_withheld")
    prompt_block = source[max(0, start - 400):start + 200]
    assert "requiredFields" not in prompt_block

    assert (
        _is_missing_info_prompt(
            {
                "title": "Start this in the background?",
                "message": d._SPAWN_WITHHELD_MESSAGE,
                "kind": "spawn_withheld",
            }
        )
        is False
    )


def test_spawn_permission_probe_tracks_the_bound_policy(board_policy):
    from elevate_cli.data import dispatch as d

    assert d._spawn_permitted_for_current_turn() is False


def test_spawn_permission_probe_permits_the_legacy_path():
    from elevate_cli.data import dispatch as d

    assert d._spawn_permitted_for_current_turn() is True


def test_a_stamped_row_is_never_handed_to_cron_even_with_no_policy_bound(
    monkeypatch,
):
    """The attack this closes: sever in-turn, then drain later unpoliced.

    ``drain_queued_action_runs`` and the gateway agent worker run with NO
    accepted-turn policy, where the capability probe permits by design. If the
    refusal lived only in the probe, the queued row would dispatch there.
    """
    from elevate_cli.data import dispatch as d

    class _Row(dict):
        def keys(self):  # sqlite3.Row-compatible enough for the code path
            return super().keys()

    row = _Row(
        {
            "id": "run-1",
            "deal_id": "deal-1",
            "status": "queued",
            "payload_json": d._encode_json(
                d._mark_spawn_withheld({"trigger": "stage_entry"})
            ),
        }
    )
    updates: list[tuple] = []

    class _Conn:
        def execute(self, sql, params=()):
            updates.append((sql, params))

            class _C:
                def fetchone(_self):
                    return None

            return _C()

    monkeypatch.setattr(d, "_run_lookup", lambda conn, rid: row)
    monkeypatch.setattr(
        d,
        "_select_action_run_with_registry",
        lambda conn, rid: row,
    )
    monkeypatch.setattr(d, "_row_to_run", lambda r: dict(r))

    def _must_not_run(*_a, **_k):
        raise AssertionError("a withheld run was handed to cron")

    monkeypatch.setattr(d, "_spawn_cron_job", _must_not_run)
    monkeypatch.setattr(d, "_new_callback_token", _must_not_run)

    assert get_current_execution_policy() is None  # the drain's context
    d.dispatch_action_run_to_cron(_Conn(), "run-1", actor="agent-worker")

    assert updates, "the withheld run was not parked"
    sql, params = updates[0]
    assert "status='waiting_human'" in sql
    # The realtor is told what happened in words they can act on, not a code.
    assert "background" in d._SPAWN_WITHHELD_MESSAGE
    assert "your go-ahead" in d._SPAWN_WITHHELD_MESSAGE
    assert "spawn_withheld" in params[0]


def test_a_human_approval_releases_the_stamp():
    """The realtor asking for it IS the consent the severance held out for."""
    from elevate_cli.data import dispatch as d

    payload = d._mark_spawn_withheld({"trigger": "stage_entry"})
    released = dict(payload)
    released.pop(d._SPAWN_WITHHELD_KEY, None)
    assert d._spawn_is_withheld(released) is False


def test_the_stamp_survives_the_other_payload_rewriters():
    """Laundering check: nothing that rewrites payload_json may drop the stamp.

    ``park_run_for_live_forms_provider`` and the admin-setup block path both
    read-modify-write the payload. If either replaced it wholesale, a stamped
    run would come back out unstamped and become dispatchable.
    """
    import inspect

    from elevate_cli.data import dispatch as d

    for func in (
        d.park_run_for_live_forms_provider,
        d.dispatch_action_run_to_cron,
    ):
        source = inspect.getsource(func)
        # Both must build on the decoded existing payload, never a fresh dict.
        assert '_decode_json(row["payload_json"])' in source, func.__name__
        assert "payload_json=?" not in source.split("_decode_json", 1)[0], func.__name__

    payload = d._mark_spawn_withheld({"trigger": "stage_entry"})
    # Simulate the read-modify-write both functions perform.
    rewritten = dict(payload)
    rewritten["requiresLiveFormsProvider"] = True
    rewritten["dispatchBlocked"] = {"message": "setup"}
    assert d._spawn_is_withheld(rewritten) is True


def test_the_severance_is_checked_before_any_other_dispatch_branch():
    """Ordering matters: the refusal must precede the forms/setup branches."""
    import inspect

    from elevate_cli.data import dispatch as d

    source = inspect.getsource(d.dispatch_action_run_to_cron)
    assert source.index("_spawn_is_withheld") < source.index(
        "_admin_setup_dispatch_block_reason"
    )
    assert source.index("_spawn_is_withheld") < source.index(
        "live_forms_provider_block_reason_for_run"
    )
    assert source.index("_spawn_is_withheld") < source.index("_new_callback_token")


def test_an_unstamped_row_is_untouched_by_the_new_branch():
    from elevate_cli.data import dispatch as d

    assert d._spawn_is_withheld({"trigger": "stage_entry"}) is False
    assert d._spawn_is_withheld(None) is False
    assert d._spawn_is_withheld("not-a-dict") is False


# ---------------------------------------------------------------------------
# 1c. Kanban's enqueue -> spawn relationship
# ---------------------------------------------------------------------------


def test_kanban_dispatch_tick_refuses_to_spawn_under_beta(monkeypatch):
    """``kanban_create`` is an enqueue; this loop is what turns it into a
    detached ``elevate chat`` subprocess."""
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    from elevate_cli import kanban_db

    def _must_not_run(*_a, **_k):
        raise AssertionError("the kanban dispatcher spawned a worker under Beta")

    result = kanban_db.dispatch_once(None, spawn_fn=_must_not_run)

    assert result.spawned == []
    assert result.promoted == 0


def test_kanban_dispatch_tick_is_unchanged_off_beta(monkeypatch):
    """Stable byte-identical: the refusal is release-policy scoped."""
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "stable")
    from elevate_cli import kanban_db

    reached: list[str] = []

    def _fake_waitpid(*_a, **_k):
        reached.append("tick-body")
        raise ChildProcessError

    monkeypatch.setattr(kanban_db.os, "waitpid", _fake_waitpid)
    with pytest.raises(Exception):
        # Reaches the real tick body (and then fails on the None connection),
        # which is the point: it was not short-circuited.
        kanban_db.dispatch_once(None, spawn_fn=lambda *a, **k: None)
    assert reached == ["tick-body"]


# ---------------------------------------------------------------------------
# 2. CRM mirror severance on a lead status change
# ---------------------------------------------------------------------------


@pytest.fixture
def crm_mirror_on(monkeypatch):
    """Turn the operator's CRM mirror ON and trip-wire every outward call."""
    from tools import lead_status_crm

    monkeypatch.setattr(lead_status_crm, "_load_config_safely", lambda: {
        "crm": {"push_status": True},
    })
    monkeypatch.setattr(lead_status_crm, "_onboarding_crm", lambda conn: {})

    def _must_not_run(*_a, **_k):
        raise AssertionError("an outward CRM call was made")

    import elevate_cli.source_connectors as source_connectors

    for name in ("crm_find_lead", "crm_update_stage", "crm_add_note"):
        monkeypatch.setattr(source_connectors, name, _must_not_run, raising=False)
    return monkeypatch


CONTACT = {
    "id": "c-1",
    "displayName": "Test Lead",
    "primaryEmail": "lead@example.com",
    "primaryPhone": "+15550001111",
}


def test_board_ceiling_withholds_the_crm_mirror(crm_mirror_on, board_policy):
    from tools.lead_status_crm import push_lead_status_to_crm

    result = push_lead_status_to_crm(None, CONTACT, "follow_up")

    assert result == {"pushed": False, "reason": "not_authorized"}


def test_the_mirror_is_withheld_before_the_lead_is_even_looked_up(
    crm_mirror_on, board_policy
):
    """The severance sits above ``crm_find_lead``.

    That matters: looking the lead up is itself an authenticated request to
    the realtor's CRM carrying their contact's email and phone. The refusal
    must happen before anything leaves the machine, which the trip-wired
    connectors in ``crm_mirror_on`` assert by raising if called.
    """
    from tools.lead_status_crm import push_lead_status_to_crm

    assert push_lead_status_to_crm(None, CONTACT, "dead")["reason"] == "not_authorized"


def test_a_disabled_mirror_still_reports_disabled_not_unauthorized(board_policy):
    """Ordering check: the opt-in gate stays first, so the common case reads
    the same as it always has."""
    from tools.lead_status_crm import push_lead_status_to_crm

    result = push_lead_status_to_crm(None, CONTACT, "follow_up")
    assert result["pushed"] is False
    assert result["reason"] in {"disabled", "error"}


def test_the_local_label_write_is_not_blocked_by_the_withheld_mirror(
    crm_mirror_on, board_policy
):
    """Severing the mirror must not sever the board write it hangs off."""
    from tools.lead_status_tool import _maybe_push_crm

    # ``_maybe_push_crm`` is the seam the handler calls AFTER the local write
    # has already been committed; it must return cleanly, never raise.
    assert _maybe_push_crm(None, CONTACT, "follow_up")["reason"] == "not_authorized"


def test_no_bound_policy_leaves_the_mirror_reachable(monkeypatch):
    """Stable byte-identical: with no policy bound the push proceeds to the
    connector layer exactly as before (and fails there, in the test, for want
    of a configured CRM)."""
    from tools import lead_status_crm

    monkeypatch.setattr(lead_status_crm, "_load_config_safely", lambda: {
        "crm": {"push_status": True},
    })
    monkeypatch.setattr(lead_status_crm, "_onboarding_crm", lambda conn: {})

    seen: list[str] = []

    def _find(email, config, phone=None):
        seen.append(email)
        return None

    import elevate_cli.source_connectors as source_connectors

    monkeypatch.setattr(source_connectors, "crm_find_lead", _find, raising=False)

    result = lead_status_crm.push_lead_status_to_crm(None, CONTACT, "follow_up")

    assert seen == ["lead@example.com"]
    assert result["reason"] == "lead_not_in_crm"


def test_the_declaration_and_the_dispatch_read_the_same_switch(monkeypatch):
    """One expression decides both, so they cannot drift.

    ``crm_status_push_enabled`` is what the effect resolver consults and what
    ``push_lead_status_to_crm`` evaluates. Flip the underlying config and both
    sides move together.
    """
    from tools import lead_status_crm

    monkeypatch.setattr(lead_status_crm, "_onboarding_crm", lambda conn: {})

    monkeypatch.setattr(lead_status_crm, "_load_config_safely", lambda: {})
    assert lead_status_crm.crm_status_push_enabled(None) is False

    monkeypatch.setattr(
        lead_status_crm, "_load_config_safely", lambda: {"crm": {"push_status": True}}
    )
    assert lead_status_crm.crm_status_push_enabled(None) is True


def test_the_onboarding_profile_still_wins_over_config(monkeypatch):
    from tools import lead_status_crm

    monkeypatch.setattr(
        lead_status_crm, "_load_config_safely", lambda: {"crm": {"push_status": True}}
    )
    monkeypatch.setattr(
        lead_status_crm, "_onboarding_crm", lambda conn: {"push": "off", "map": {}}
    )
    assert lead_status_crm.crm_status_push_enabled(None) is False


# ---------------------------------------------------------------------------
# 3. Destructive severance on completing a kanban card
# ---------------------------------------------------------------------------


class _WorkspaceRowConn:
    """Minimal conn returning one scratch-workspace task row."""

    def __init__(self, path: Path):
        self._row = {"workspace_kind": "scratch", "workspace_path": str(path)}

    def execute(self, _sql, _params=()):
        row = self._row

        class _Cursor:
            def fetchone(self_inner):
                return row

        return _Cursor()


@pytest.fixture
def scratch_dir(tmp_path, monkeypatch):
    from elevate_cli import kanban_db

    monkeypatch.setattr(kanban_db, "_cleanup_worker_tmux", lambda conn, tid: None)
    workspace = tmp_path / "scratch-task"
    workspace.mkdir()
    (workspace / "worker-output.txt").write_text("evidence", encoding="utf-8")
    return workspace


def test_board_ceiling_keeps_the_scratch_workspace(scratch_dir, board_policy):
    """Closing a card is a board write; deleting a directory tree is not."""
    from elevate_cli.kanban_db import _cleanup_workspace

    _cleanup_workspace(_WorkspaceRowConn(scratch_dir), "task-1")

    assert scratch_dir.exists()
    assert (scratch_dir / "worker-output.txt").read_text(encoding="utf-8") == "evidence"


def test_no_bound_policy_still_cleans_the_scratch_workspace(scratch_dir):
    """Stable byte-identical: the dispatcher's own cleanup is unchanged."""
    from elevate_cli.kanban_db import _cleanup_workspace

    _cleanup_workspace(_WorkspaceRowConn(scratch_dir), "task-1")

    assert not scratch_dir.exists()


def test_default_ceiling_still_cleans_the_scratch_workspace(
    scratch_dir, stable_policy
):
    from elevate_cli.kanban_db import _cleanup_workspace

    _cleanup_workspace(_WorkspaceRowConn(scratch_dir), "task-1")

    assert not scratch_dir.exists()
