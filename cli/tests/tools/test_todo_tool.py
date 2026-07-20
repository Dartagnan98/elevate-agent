"""Tests for the todo tool module."""

import json

from tools.todo_tool import TodoStore, parse_todo_injection, todo_tool


class TestWriteAndRead:
    def test_write_replaces_list(self):
        store = TodoStore()
        items = [
            {"id": "1", "content": "First task", "status": "pending"},
            {"id": "2", "content": "Second task", "status": "in_progress"},
        ]
        result = store.write(items)
        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[1]["status"] == "in_progress"

    def test_read_returns_copy(self):
        store = TodoStore()
        store.write([{"id": "1", "content": "Task", "status": "pending"}])
        items = store.read()
        items[0]["content"] = "MUTATED"
        assert store.read()[0]["content"] == "Task"

    def test_write_deduplicates_duplicate_ids(self):
        store = TodoStore()
        result = store.write([
            {"id": "1", "content": "First version", "status": "pending"},
            {"id": "2", "content": "Other task", "status": "pending"},
            {"id": "1", "content": "Latest version", "status": "in_progress"},
        ])
        assert result == [
            {"id": "2", "content": "Other task", "status": "pending"},
            {"id": "1", "content": "Latest version", "status": "in_progress"},
        ]


class TestHasItems:
    def test_empty_store(self):
        store = TodoStore()
        assert store.has_items() is False

    def test_non_empty_store(self):
        store = TodoStore()
        store.write([{"id": "1", "content": "x", "status": "pending"}])
        assert store.has_items() is True


class TestFormatForInjection:
    def test_empty_returns_none(self):
        store = TodoStore()
        assert store.format_for_injection() is None

    def test_non_empty_has_markers(self):
        store = TodoStore()
        store.write([
            {"id": "1", "content": "Do thing", "status": "completed"},
            {"id": "2", "content": "Next", "status": "pending"},
            {"id": "3", "content": "Working", "status": "in_progress"},
        ])
        text = store.format_for_injection()
        # Completed items are filtered out of injection
        assert "[x]" not in text
        assert "Do thing" not in text
        # Active items are included
        assert "[ ]" in text
        assert "[>]" in text
        assert "Next" in text
        assert "Working" in text
        assert "context compression" in text.lower()


class TestParseTodoInjection:
    def test_parses_active_snapshot(self):
        store = TodoStore()
        store.write([
            {"id": "1", "content": "Done already", "status": "completed"},
            {"id": "2", "content": "Next", "status": "pending"},
            {"id": "3", "content": "Working", "status": "in_progress"},
        ])

        assert parse_todo_injection(store.format_for_injection()) == [
            {"id": "2", "content": "Next", "status": "pending"},
            {"id": "3", "content": "Working", "status": "in_progress"},
        ]

    def test_ignores_unrelated_text(self):
        assert parse_todo_injection("nothing to see") == []


class TestMergeMode:
    def test_update_existing_by_id(self):
        store = TodoStore()
        store.write([
            {"id": "1", "content": "Original", "status": "pending"},
        ])
        store.write(
            [{"id": "1", "status": "completed"}],
            merge=True,
        )
        items = store.read()
        assert len(items) == 1
        assert items[0]["status"] == "completed"
        assert items[0]["content"] == "Original"

    def test_merge_appends_new(self):
        store = TodoStore()
        store.write([{"id": "1", "content": "First", "status": "pending"}])
        store.write(
            [{"id": "2", "content": "Second", "status": "pending"}],
            merge=True,
        )
        items = store.read()
        assert len(items) == 2


class TestTodoToolFunction:
    def test_read_mode(self):
        store = TodoStore()
        store.write([{"id": "1", "content": "Task", "status": "pending"}])
        result = json.loads(todo_tool(store=store))
        assert result["summary"]["total"] == 1
        assert result["summary"]["pending"] == 1

    def test_write_mode(self):
        store = TodoStore()
        result = json.loads(todo_tool(
            todos=[{"id": "1", "content": "New", "status": "in_progress"}],
            store=store,
        ))
        assert result["summary"]["in_progress"] == 1

    def test_no_store_returns_error(self):
        result = json.loads(todo_tool())
        assert "error" in result


class TestTodoEffectClassification:
    """The todo tool's effects are argument-resolved against the per-session
    in-memory plan store: reads are ``read:session_plan``, writes are the
    ``write_local:session_plan`` capability the PLAN / DRAFT_ONLY policy
    ceilings sanction."""

    def _policy(self, mode):
        from tools.approval import ExecutionPolicy

        return ExecutionPolicy.for_mode("turn-todo", mode)

    def test_todo_is_declared_via_resolver_only(self):
        import tools.todo_tool as todo_module
        from tools.registry import registry

        entry = registry.get_entry("todo")
        assert entry is not None
        assert entry.effects is None
        assert entry.effect_resolver is todo_module._todo_effect_resolver
        assert registry.get_effect_metadata("todo") == {
            "declared": True,
            "effects": frozenset(),
            "has_resolver": True,
        }

    def test_todo_read_resolves_to_session_plan_read(self):
        from tools.approval import (
            Effect,
            ExecutionPolicyMode,
            authorize_effects,
        )
        from tools.registry import registry

        expected = frozenset({Effect.parse("read:session_plan")})
        for args in ({}, {"merge": True}, {"todos": None}):
            resolved = registry.resolve_effects("todo", args)
            assert resolved == expected

        decision = authorize_effects(
            self._policy(ExecutionPolicyMode.READ_ONLY),
            registry.resolve_effects("todo", {}),
        )
        assert decision.allowed is True
        assert decision.denied_effects == frozenset()

    def test_todo_write_resolves_to_session_plan_write(self):
        from tools.approval import Effect
        from tools.registry import registry

        expected = frozenset({Effect.parse("write_local:session_plan")})
        write_args = (
            {"todos": [{"id": "1", "content": "x", "status": "pending"}]},
            {"todos": []},  # empty list still REPLACES the plan — a write
            {"todos": [], "merge": True},
        )
        for args in write_args:
            assert registry.resolve_effects("todo", args) == expected

    def test_todo_write_denied_read_only_allowed_plan_and_draft(self):
        from tools.approval import (
            Effect,
            ExecutionPolicyMode,
            authorize_effects,
        )
        from tools.registry import registry

        resolved = registry.resolve_effects(
            "todo", {"todos": [{"id": "1", "content": "x", "status": "pending"}]}
        )

        denied = authorize_effects(
            self._policy(ExecutionPolicyMode.READ_ONLY), resolved
        )
        assert denied.allowed is False
        assert denied.denied_effects == frozenset(
            {Effect.parse("write_local:session_plan")}
        )

        for mode in (
            ExecutionPolicyMode.PLAN,
            ExecutionPolicyMode.DRAFT_ONLY,
            ExecutionPolicyMode.DEFAULT,
        ):
            decision = authorize_effects(self._policy(mode), resolved)
            assert decision.allowed is True, mode
            assert decision.denied_effects == frozenset()

    def test_todo_resolver_branch_matches_handler_write_condition(self):
        """The resolver must classify a call as a write exactly when the
        handler would mutate the store."""
        from tools.approval import Effect
        from tools.registry import registry

        read_effect = frozenset({Effect.parse("read:session_plan")})
        write_effect = frozenset({Effect.parse("write_local:session_plan")})

        # Read branch: handler leaves the store untouched.
        store = TodoStore()
        seeded = [{"id": "1", "content": "keep", "status": "pending"}]
        store.write(seeded)
        args = {"merge": False}
        assert registry.resolve_effects("todo", args) == read_effect
        before = store.read()
        json.loads(todo_tool(todos=args.get("todos"), store=store))
        assert store.read() == before

        # Write branch: same handler condition (todos is not None) mutates.
        args = {"todos": []}
        assert registry.resolve_effects("todo", args) == write_effect
        json.loads(todo_tool(todos=args.get("todos"), store=store))
        assert store.read() == []

    def test_todo_read_never_touches_filesystem(self, tmp_path, monkeypatch):
        """Adversarial: a declared-read todo call must not create files or
        spawn anything, even with a populated store."""
        import subprocess

        def unexpected_effect(*_args, **_kwargs):
            raise AssertionError("todo read attempted a non-read effect")

        monkeypatch.setattr(subprocess, "Popen", unexpected_effect)
        monkeypatch.chdir(tmp_path)

        store = TodoStore()
        store.write(
            [
                {"id": "1", "content": "First", "status": "in_progress"},
                {"id": "2", "content": "Second", "status": "pending"},
            ]
        )
        before = sorted(str(p) for p in tmp_path.rglob("*"))
        result = json.loads(todo_tool(store=store))

        assert result["summary"]["total"] == 2
        assert sorted(str(p) for p in tmp_path.rglob("*")) == before
