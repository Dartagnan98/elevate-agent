"""Adversarial unit coverage for accepted-turn policy inheritance (A4).

The inheritance primitives in ``tools.approval`` are the only supported way
a child agent acquires an execution policy:

* ``derive_child_execution_policy`` — equal-or-narrower by construction;
  every widening attempt raises ``PolicyWideningError``.
* ``capture_inherited_execution_policy`` — dispatch-time snapshot of the
  parent's bound policy + durable revision; no bound policy captures as
  EXPLICIT no-policy; exact-Beta permits a DEFAULT policy only when the
  accepted turn explicitly selected bypass.
* ``inherited_execution_policy_scope`` — binds exactly the captured values
  around a child run and restores the worker thread's prior state on every
  exit path; ambient thread state can never leak in either direction.
"""

from __future__ import annotations

import threading

import pytest

from tools.approval import (
    Effect,
    EffectKind,
    ExecutionPolicy,
    ExecutionPolicyMode,
    InheritedPolicyBinding,
    PolicyWideningError,
    capture_inherited_execution_policy,
    derive_child_execution_policy,
    get_current_execution_policy,
    get_current_execution_policy_revision,
    inherited_execution_policy_scope,
    reset_current_execution_policy,
    set_current_execution_policy,
)


def _policy(mode: str = "draft_only", turn: str = "turn-inherit") -> ExecutionPolicy:
    return ExecutionPolicy.for_mode(turn, ExecutionPolicyMode.parse(mode))


@pytest.fixture(autouse=True)
def _no_ambient_policy():
    """Every test starts and must end with a clean policy context."""
    assert get_current_execution_policy() is None
    assert get_current_execution_policy_revision() is None
    yield
    assert get_current_execution_policy() is None
    assert get_current_execution_policy_revision() is None


@pytest.fixture
def bound_parent():
    """Bind a draft-only parent policy at revision 3 for the test body."""
    policy = _policy("draft_only")
    token = set_current_execution_policy(policy, policy_revision=3)
    try:
        yield policy
    finally:
        reset_current_execution_policy(token)


class TestDeriveChildExecutionPolicy:
    def test_default_derivation_is_equal_and_same_turn(self):
        parent = _policy("draft_only")
        child = derive_child_execution_policy(parent)
        assert child == parent
        assert child.accepted_turn_id == parent.accepted_turn_id

    def test_subset_narrowing_is_allowed(self):
        parent = _policy("draft_only")
        child = derive_child_execution_policy(
            parent,
            allowed_effects={Effect(EffectKind.READ)},
        )
        assert child.allowed_effects == frozenset({Effect(EffectKind.READ)})
        assert child.accepted_turn_id == parent.accepted_turn_id

    def test_mode_narrowing_is_allowed(self):
        parent = _policy("draft_only")
        child = derive_child_execution_policy(
            parent,
            allowed_effects={Effect(EffectKind.READ)},
            mode=ExecutionPolicyMode.READ_ONLY,
        )
        assert child.mode is ExecutionPolicyMode.READ_ONLY

    def test_effect_widening_raises(self):
        parent = ExecutionPolicy.for_mode(
            "turn-inherit", ExecutionPolicyMode.READ_ONLY
        )
        with pytest.raises(PolicyWideningError):
            derive_child_execution_policy(
                parent,
                allowed_effects={
                    Effect(EffectKind.READ),
                    Effect(EffectKind.WRITE_LOCAL, "draft"),
                },
            )

    @pytest.mark.parametrize(
        ("parent_mode", "wider_mode"),
        [
            ("read_only", "draft_only"),
            ("read_only", "default"),
            ("plan", "draft_only"),
            ("draft_only", "default"),
        ],
    )
    def test_mode_widening_raises(self, parent_mode, wider_mode):
        parent = _policy(parent_mode)
        with pytest.raises(PolicyWideningError):
            derive_child_execution_policy(parent, mode=wider_mode)

    def test_non_policy_parent_raises_typeerror(self):
        with pytest.raises(TypeError):
            derive_child_execution_policy({"mode": "default"})

    def test_turn_identity_cannot_be_replaced(self):
        parent = _policy("draft_only", turn="turn-a")
        child = derive_child_execution_policy(parent)
        grandchild = derive_child_execution_policy(child)
        assert grandchild.accepted_turn_id == "turn-a"

    def test_forged_narrow_override_cannot_escape_the_lattice(self):
        """P3 hardening (adversarial review): derivation re-verifies the
        result against the raw effect lattice from first principles, so a
        subclass overriding ``narrow`` to widen cannot hand a child more
        capability than the parent holds."""

        class _ForgedPolicy(ExecutionPolicy):
            __slots__ = ()

            def narrow(self, allowed_effects, *, mode=None):  # noqa: ARG002
                return ExecutionPolicy.for_mode(
                    self.accepted_turn_id, ExecutionPolicyMode.DEFAULT
                )

        forged = _ForgedPolicy(
            accepted_turn_id="turn-forged",
            mode=ExecutionPolicyMode.READ_ONLY,
            allowed_effects={Effect(EffectKind.READ)},
        )
        with pytest.raises(PolicyWideningError):
            derive_child_execution_policy(forged)

    def test_forged_non_exact_policy_result_is_rejected(self):
        """Even a forged narrow returning a widening SUBCLASS instance is
        refused before the lattice check via the exact-type gate."""

        class _ForgedResult(ExecutionPolicy):
            __slots__ = ()

        class _ForgedPolicy(ExecutionPolicy):
            __slots__ = ()

            def narrow(self, allowed_effects, *, mode=None):  # noqa: ARG002
                return _ForgedResult(
                    accepted_turn_id=self.accepted_turn_id,
                    mode=ExecutionPolicyMode.READ_ONLY,
                    allowed_effects={Effect(EffectKind.READ)},
                )

        forged = _ForgedPolicy(
            accepted_turn_id="turn-forged",
            mode=ExecutionPolicyMode.READ_ONLY,
            allowed_effects={Effect(EffectKind.READ)},
        )
        with pytest.raises(PolicyWideningError):
            derive_child_execution_policy(forged)

    def test_forged_policy_capture_fails_closed_to_no_policy(self):
        """The capture seam converts a derivation escape into an explicit
        no-policy binding — the child fails closed, never inherits wide."""

        class _ForgedPolicy(ExecutionPolicy):
            __slots__ = ()

            def narrow(self, allowed_effects, *, mode=None):  # noqa: ARG002
                return ExecutionPolicy.for_mode(
                    self.accepted_turn_id, ExecutionPolicyMode.DEFAULT
                )

        forged = _ForgedPolicy(
            accepted_turn_id="turn-forged",
            mode=ExecutionPolicyMode.READ_ONLY,
            allowed_effects={Effect(EffectKind.READ)},
        )
        from tools import approval as approval_module

        token = approval_module._current_execution_policy.set(forged)
        revision_token = (
            approval_module._current_execution_policy_revision.set(0)
        )
        try:
            binding = capture_inherited_execution_policy(
                parent_session_id="p-s"
            )
            assert binding.policy is None
            assert binding.policy_revision is None
        finally:
            approval_module._current_execution_policy_revision.reset(
                revision_token
            )
            approval_module._current_execution_policy.reset(token)


class TestCaptureInheritedExecutionPolicy:
    def test_no_bound_policy_captures_explicit_no_policy(self):
        binding = capture_inherited_execution_policy(parent_session_id="p-s")
        assert binding.policy is None
        assert binding.policy_revision is None
        assert binding.parent_session_id == "p-s"

    def test_bound_policy_and_revision_are_captured(self, bound_parent):
        binding = capture_inherited_execution_policy(parent_session_id="p-s")
        assert binding.policy == bound_parent
        assert binding.policy_revision == 3
        assert binding.parent_session_id == "p-s"

    def test_captured_policy_is_equal_or_narrower_by_construction(
        self, bound_parent
    ):
        binding = capture_inherited_execution_policy()
        # The derived policy must round-trip the narrowing lattice.
        assert (
            bound_parent.narrow(
                binding.policy.allowed_effects, mode=binding.policy.mode
            )
            == binding.policy
        )

    @pytest.mark.parametrize("bad_revision", [None, True, False, -1, "3", 2.0])
    def test_invalid_revision_captures_none_but_keeps_policy(self, bad_revision):
        policy = _policy("read_only")
        token = set_current_execution_policy(policy)
        # Bypass set_current_execution_policy's validation to simulate a
        # corrupted revision binding.
        from tools import approval as approval_module

        revision_token = approval_module._current_execution_policy_revision.set(
            bad_revision
        )
        try:
            binding = capture_inherited_execution_policy()
            assert binding.policy == policy
            assert binding.policy_revision is None
        finally:
            approval_module._current_execution_policy_revision.reset(
                revision_token
            )
            approval_module._current_execution_policy.reset(token.policy_token)

    def test_blank_parent_session_normalizes_to_none(self, bound_parent):
        assert (
            capture_inherited_execution_policy(
                parent_session_id="   "
            ).parent_session_id
            is None
        )
        assert (
            capture_inherited_execution_policy(
                parent_session_id=None
            ).parent_session_id
            is None
        )

    def test_beta_only_inherits_default_for_explicit_bypass(self, monkeypatch):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        wide = _policy("default")
        token = set_current_execution_policy(wide, policy_revision=1)
        try:
            binding = capture_inherited_execution_policy(parent_session_id="p")
            assert binding.policy is None
            assert binding.policy_revision is None
            monkeypatch.setattr(
                "tools.approval.get_permission_mode",
                lambda: "bypassPermissions",
            )
            binding = capture_inherited_execution_policy(parent_session_id="p")
            assert binding.policy == wide
            assert binding.policy_revision == 1
            assert binding.beta_bypass_permissions is True
        finally:
            reset_current_execution_policy(token)

    @pytest.mark.parametrize("mode", ["read_only", "plan", "draft_only"])
    def test_beta_keeps_policies_within_the_draft_only_ceiling(
        self, monkeypatch, mode
    ):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        policy = _policy(mode)
        token = set_current_execution_policy(policy, policy_revision=0)
        try:
            binding = capture_inherited_execution_policy()
            assert binding.policy == policy
            assert binding.policy_revision == 0
        finally:
            reset_current_execution_policy(token)

    def test_outside_beta_default_mode_policy_is_captured(self, monkeypatch):
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
        wide = _policy("default")
        token = set_current_execution_policy(wide, policy_revision=1)
        try:
            binding = capture_inherited_execution_policy()
            assert binding.policy == wide
            assert binding.policy_revision == 1
        finally:
            reset_current_execution_policy(token)


class TestInheritedExecutionPolicyScope:
    def test_scope_binds_exactly_the_captured_values(self):
        policy = _policy("read_only")
        binding = InheritedPolicyBinding(policy, 7, "p-s")
        with inherited_execution_policy_scope(binding):
            assert get_current_execution_policy() == policy
            assert get_current_execution_policy_revision() == 7

    def test_scope_shadows_a_wider_ambient_policy(self):
        """Ambient-widening injection: a pooled worker thread carrying a
        stale DEFAULT-mode binding from an unrelated turn must observe the
        child's inherited read-only policy, not its own."""
        ambient = _policy("default", turn="other-turn")
        token = set_current_execution_policy(ambient, policy_revision=9)
        try:
            child_policy = _policy("read_only")
            with inherited_execution_policy_scope(
                InheritedPolicyBinding(child_policy, 2, None)
            ):
                assert get_current_execution_policy() == child_policy
                assert get_current_execution_policy_revision() == 2
            assert get_current_execution_policy() == ambient
            assert get_current_execution_policy_revision() == 9
        finally:
            reset_current_execution_policy(token)

    @pytest.mark.parametrize(
        "garbage",
        [
            None,
            object(),
            {"policy": "default"},
            InheritedPolicyBinding(None, None, None),
            InheritedPolicyBinding("not-a-policy", 1, None),
        ],
    )
    def test_missing_or_invalid_binding_binds_explicit_no_policy(self, garbage):
        """No binding never means ambient: even with a live ambient policy on
        the thread, an absent/corrupt binding runs the child policyless."""
        ambient = _policy("default", turn="other-turn")
        token = set_current_execution_policy(ambient, policy_revision=4)
        try:
            with inherited_execution_policy_scope(garbage):
                assert get_current_execution_policy() is None
                assert get_current_execution_policy_revision() is None
            assert get_current_execution_policy() == ambient
        finally:
            reset_current_execution_policy(token)

    def test_invalid_revision_in_binding_binds_none_revision(self):
        policy = _policy("read_only")
        with inherited_execution_policy_scope(
            InheritedPolicyBinding(policy, -5, None)
        ):
            assert get_current_execution_policy() == policy
            assert get_current_execution_policy_revision() is None

    def test_scope_restores_on_exception(self):
        policy = _policy("read_only")
        with pytest.raises(RuntimeError):
            with inherited_execution_policy_scope(
                InheritedPolicyBinding(policy, 1, None)
            ):
                raise RuntimeError("child crashed")
        assert get_current_execution_policy() is None
        assert get_current_execution_policy_revision() is None

    def test_scope_restores_on_base_exception(self):
        policy = _policy("read_only")
        with pytest.raises(KeyboardInterrupt):
            with inherited_execution_policy_scope(
                InheritedPolicyBinding(policy, 1, None)
            ):
                raise KeyboardInterrupt()
        assert get_current_execution_policy() is None

    def test_nested_scopes_restore_lifo(self):
        """Child-of-child: the inner (grandchild) binding wins inside, the
        child binding is restored afterwards."""
        child_policy = _policy("draft_only")
        grandchild_policy = derive_child_execution_policy(
            child_policy,
            allowed_effects={Effect(EffectKind.READ)},
            mode=ExecutionPolicyMode.READ_ONLY,
        )
        with inherited_execution_policy_scope(
            InheritedPolicyBinding(child_policy, 1, None)
        ):
            with inherited_execution_policy_scope(
                InheritedPolicyBinding(grandchild_policy, 1, None)
            ):
                assert get_current_execution_policy() == grandchild_policy
            assert get_current_execution_policy() == child_policy

    def test_beta_bind_time_requires_explicit_bypass_stamp_for_default(
        self, monkeypatch
    ):
        """Cross-generation replay: a binding captured outside Beta must not
        widen a Beta process when replayed into it."""
        wide_binding = InheritedPolicyBinding(_policy("default"), 5, "p")
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        with inherited_execution_policy_scope(wide_binding):
            assert get_current_execution_policy() is None
            assert get_current_execution_policy_revision() is None
        explicit_binding = InheritedPolicyBinding(
            _policy("default"),
            5,
            "p",
            True,
        )
        with inherited_execution_policy_scope(explicit_binding):
            assert get_current_execution_policy() == explicit_binding.policy
            assert get_current_execution_policy_revision() == 5
            descendant = capture_inherited_execution_policy()
            assert descendant.policy == explicit_binding.policy
            assert descendant.beta_bypass_permissions is True

    def test_beta_bind_time_keeps_draft_only_binding(self, monkeypatch):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
        policy = _policy("draft_only")
        with inherited_execution_policy_scope(
            InheritedPolicyBinding(policy, 0, None)
        ):
            assert get_current_execution_policy() == policy
            assert get_current_execution_policy_revision() == 0

    def test_binding_does_not_leak_across_threads(self):
        """A scope entered on one thread is invisible on another (fresh
        contexts), and an unstamped thread observes no policy."""
        policy = _policy("draft_only")
        seen = {}
        entered = threading.Event()
        release = threading.Event()

        def _bound_worker():
            with inherited_execution_policy_scope(
                InheritedPolicyBinding(policy, 1, None)
            ):
                entered.set()
                release.wait(timeout=5)

        def _other_worker():
            entered.wait(timeout=5)
            seen["policy"] = get_current_execution_policy()
            release.set()

        t1 = threading.Thread(target=_bound_worker)
        t2 = threading.Thread(target=_other_worker)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        assert seen["policy"] is None

    def test_capture_then_scope_round_trip(self, bound_parent):
        """The full contract: capture on the dispatch thread, bind on a fresh
        worker thread, observe the derived policy there."""
        binding = capture_inherited_execution_policy(parent_session_id="p-s")
        observed = {}

        def _worker():
            with inherited_execution_policy_scope(binding):
                observed["policy"] = get_current_execution_policy()
                observed["revision"] = get_current_execution_policy_revision()

        thread = threading.Thread(target=_worker)
        thread.start()
        thread.join(timeout=5)
        assert observed["policy"] == bound_parent
        assert observed["revision"] == 3
