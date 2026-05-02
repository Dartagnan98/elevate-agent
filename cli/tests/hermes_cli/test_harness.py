from elevate_cli.harness import build_harness_snapshot, format_harness_snapshot


def test_harness_snapshot_without_profiles_is_stable(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))

    snapshot = build_harness_snapshot(
        config={
            "approvals": {"mode": "manual"},
            "safety": {"external_actions": "review"},
        },
        sessions={"active": 0},
        memory={
            "provider": "builtin",
            "journal": {"pending": 2, "processed": 3, "session_segment_count": 1},
            "embedding": {"enabled": True, "provider": "openai", "model": "text-embedding-3-small"},
            "graph": {"nodes": [{"id": "n1"}], "edges": []},
        },
        skills={"enabled": 4, "total": 5},
        toolsets={"enabled": ["memory", "messaging"]},
        orchestration={
            "agents": [
                {"agent_id": "executive-assistant", "tier": "primary", "status": "ready"},
                {"agent_id": "outreach", "tier": "specialist", "status": "running"},
            ],
            "runs": [
                {"run_id": "r1", "status": "running", "route_label": "Agent Routing (Outreach)"},
                {"run_id": "r2", "status": "queued"},
                {"run_id": "r3", "status": "queued", "metadata": {"blocked_by": ["r1"]}},
            ],
            "plan_graph": {
                "ready_run_ids": ["r2"],
                "blocked_run_ids": ["r3"],
                "active_run_ids": ["r1"],
                "completed_run_ids": [],
                "cycle_run_ids": [],
                "unresolved_dependency_ids": [],
                "next_ready_run_ids": ["r2"],
            },
        },
        include_profiles=False,
    )

    assert snapshot["server"]["pattern"] == "single-local-gateway"
    assert snapshot["orchestration"]["coordinator"] == "executive-assistant"
    assert snapshot["orchestration"]["route_labeled_runs"] == 1
    assert snapshot["orchestration"]["plan_graph"]["ready_runs"] == 1
    assert snapshot["orchestration"]["plan_graph"]["blocked_runs"] == 1
    assert snapshot["skills"]["mode"] == "manifest-visible-detail-lazy"
    assert snapshot["memory"]["embeddings_enabled"] is True
    assert snapshot["memory"]["pipeline"]["state"] == "backlog"
    assert snapshot["memory"]["pipeline"]["search"] == "done"
    assert snapshot["safety"]["human_communication_requires_review"] is True
    assert snapshot["performance"]["available"] is False


def test_format_harness_snapshot_contains_key_sections(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    snapshot = build_harness_snapshot(config={}, include_profiles=False)

    output = format_harness_snapshot(snapshot)

    assert "Elevate Harness" in output
    assert "Gateway:" in output
    assert "Orchestration:" in output
    assert "Memory:" in output
    assert "Safety:" in output


def test_harness_prefers_live_memory_activity(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))

    snapshot = build_harness_snapshot(
        config={},
        sessions={},
        memory={
            "provider": "holographic",
            "facts": 4,
            "indexed_facts": 3,
            "journal": {"pending": 1, "failed": 0},
            "embedding": {"enabled": True},
            "activity": {
                "state": "searching",
                "updated_at": "2026-05-01T00:00:00Z",
                "pipeline": {
                    "derived_from_journal": False,
                    "search": "running",
                    "verify": "pending",
                    "inject": "pending",
                    "maintain": "pending",
                    "active": True,
                    "last_step": "search",
                },
                "recent_events": [{"kind": "memory.prefetch", "message": "started"}],
            },
            "graph": {"nodes": [], "edges": []},
        },
        skills={},
        toolsets={},
        orchestration={},
        include_profiles=False,
    )

    pipeline = snapshot["memory"]["pipeline"]
    assert pipeline["derived_from_journal"] is False
    assert pipeline["state"] == "searching"
    assert pipeline["search"] == "running"
    assert pipeline["recent_events"][0]["kind"] == "memory.prefetch"
