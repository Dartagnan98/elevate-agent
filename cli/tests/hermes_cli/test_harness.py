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
                {"run_id": "r1", "status": "running", "route_label": "Agent Routing (Outreach)"}
            ],
        },
        include_profiles=False,
    )

    assert snapshot["server"]["pattern"] == "single-local-gateway"
    assert snapshot["orchestration"]["coordinator"] == "executive-assistant"
    assert snapshot["orchestration"]["route_labeled_runs"] == 1
    assert snapshot["skills"]["mode"] == "manifest-visible-detail-lazy"
    assert snapshot["memory"]["embeddings_enabled"] is True
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
