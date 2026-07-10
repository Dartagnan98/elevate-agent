from elevate_cli.operational_freshness import _sync_labels


def test_operational_freshness_uses_beta_profile_service_labels(monkeypatch):
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")

    labels = _sync_labels()

    assert labels == [
        "ai.elevate.gateway-beta",
        "ai.elevate.sync-apple-messages-beta",
        "ai.elevate.sync-crm-beta",
        "ai.elevate.sync-social-beta",
    ]
    assert "ai.elevate.gateway" not in labels
