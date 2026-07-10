"""C6 — dashboard WS auth reads the token from the subprotocol (kept out of the
URL, so it never lands in proxy/tunnel logs) with a query fallback for older
clients. One of these tokens grants a PTY shell, so URL exposure matters.
"""
from elevate_cli.web_routes.chat_websockets import _WS_AUTH_PROTO, _ws_auth_token


class _FakeWS:
    def __init__(self, subprotocols=None, query_token=""):
        self.scope = {"subprotocols": list(subprotocols or [])}
        self.query_params = {"token": query_token}


def test_prefers_token_from_subprotocol():
    ws = _FakeWS(subprotocols=[_WS_AUTH_PROTO, "SECRET123"], query_token="")
    assert _ws_auth_token(ws) == "SECRET123"


def test_falls_back_to_query_when_no_subprotocol():
    ws = _FakeWS(subprotocols=[], query_token="QTOKEN")
    assert _ws_auth_token(ws) == "QTOKEN"


def test_marker_without_token_falls_back():
    ws = _FakeWS(subprotocols=[_WS_AUTH_PROTO], query_token="QTOKEN")
    assert _ws_auth_token(ws) == "QTOKEN"


def test_empty_when_nothing_provided():
    ws = _FakeWS(subprotocols=[], query_token="")
    assert _ws_auth_token(ws) == ""
