from types import SimpleNamespace

from elevate_cli.data.connection import _reset_schema_cache, connect
from elevate_cli.data.pg_server import pg_data_dir
from elevate_cli.local_databases import initialize_local_databases


def test_fresh_elevate_home_initializes_local_databases(monkeypatch):
    def fake_install_all(**_kwargs):
        job = SimpleNamespace(source_id="apple-messages")
        return [SimpleNamespace(ok=True, action="installed", job=job, message="fake")]

    from elevate_cli import sync_scheduler

    monkeypatch.setattr(sync_scheduler, "install_all", fake_install_all)
    _reset_schema_cache()
    try:
        results = initialize_local_databases()
        by_name = {result.name: result for result in results}

        assert all(result.ok for result in results), results
        assert {"operational", "sessions", "memory", "outreach", "sync-scheduler"} <= set(by_name)
        assert by_name["memory"].path == pg_data_dir()
        assert "embedded Postgres" in by_name["memory"].message

        with connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM _schema_migrations").fetchone()[0] > 0
            assert conn.execute("SELECT COUNT(*) FROM admin_action_registry").fetchone()[0] > 0
            assert conn.execute("SELECT COUNT(*) FROM pack_onboarding_items").fetchone()[0] > 0
            assert conn.execute("SELECT COUNT(*) FROM templates").fetchone()[0] > 0
            assert conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0] == 0
    finally:
        _reset_schema_cache()
