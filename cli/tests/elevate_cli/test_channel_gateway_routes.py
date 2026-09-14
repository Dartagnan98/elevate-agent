from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from elevate_cli.web_routes.channel_gateway import register_gateway_routes


class Proc:
    pid = 1234


class Log:
    def exception(self, *_args, **_kwargs):
        pass


def make_client(spawn):
    app = FastAPI()
    router = APIRouter()
    register_gateway_routes(router, log=Log(), spawn_elevate_action=spawn)
    app.include_router(router)
    return TestClient(app)


def test_gateway_restart_route_spawns_restart_action():
    calls = []

    def spawn(args, name):
        calls.append((args, name))
        return Proc()

    resp = make_client(spawn).post("/api/gateway/restart")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "pid": 1234, "name": "gateway-restart"}
    assert calls == [(["gateway", "restart"], "gateway-restart")]


def test_gateway_start_route_spawns_replace_runner():
    calls = []

    def spawn(args, name):
        calls.append((args, name))
        return Proc()

    resp = make_client(spawn).post("/api/gateway/start")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "pid": 1234, "name": "gateway-start"}
    assert calls == [(["gateway", "run", "--replace"], "gateway-start")]
