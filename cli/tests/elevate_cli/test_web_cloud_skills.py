import asyncio
import logging

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
