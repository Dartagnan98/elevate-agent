import asyncio
import logging
import os

from elevate_cli import cloud_skills
from elevate_cli import license as license_mod
from elevate_cli import web_cloud_skills


class _FakeApp:
    def __init__(self):
        self.handlers = []

    def on_event(self, name):
        def decorator(handler):
            self.handlers.append((name, handler))
            return handler

        return decorator


def test_install_cloud_skill_lifecycle_registers_handlers(monkeypatch):
    calls = []

    async def fake_kickoff(application, *, sync_once, heartbeat):
        calls.append(("startup", application, callable(sync_once), callable(heartbeat)))

    async def fake_stop(application):
        calls.append(("shutdown", application))

    monkeypatch.setattr(web_cloud_skills, "kickoff_cloud_skill_sync", fake_kickoff)
    monkeypatch.setattr(web_cloud_skills, "stop_cloud_skill_heartbeat", fake_stop)

    app = _FakeApp()
    web_cloud_skills.install_cloud_skill_lifecycle(app, log=logging.getLogger("test"))

    assert [name for name, _handler in app.handlers] == ["startup", "shutdown"]

    asyncio.run(app.handlers[0][1]())
    asyncio.run(app.handlers[1][1]())

    assert calls == [
        ("startup", app, True, True),
        ("shutdown", app),
    ]


def test_exact_beta_startup_cloud_sync_uses_signed_backend_resolver(monkeypatch):
    attacker_backend = "https://attacker.example.test"
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_BACKEND_URL", attacker_backend)
    monkeypatch.setattr(license_mod, "BACKEND_URL", attacker_backend)
    lic = license_mod.License(
        access_token="bearer-secret",
        refresh_token="refresh-secret",
        license_id="license-1",
        tier="pro",
        email="agent@example.test",
        expires_at=4_102_444_800,
        entitlements=[],
    )
    monkeypatch.setattr(license_mod, "load", lambda: lic)
    observed: list[str] = []

    def sync_all() -> dict:
        observed.append(license_mod.backend_url())
        return {"skill_count": 0, "removed": [], "errors": []}

    monkeypatch.setattr(cloud_skills, "sync_all", sync_all)

    web_cloud_skills._cloud_skill_sync_once("startup", log=logging.getLogger("test"))

    assert observed == [license_mod.DEFAULT_BACKEND]
    assert license_mod.BACKEND_URL == attacker_backend
    assert os.environ["ELEVATE_BACKEND_URL"] == attacker_backend
