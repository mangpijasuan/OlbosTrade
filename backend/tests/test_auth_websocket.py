"""
The app-level auth dependency has to work on WebSocket routes too.

This exists because of a real break found in review. `require_session` was
annotated `Request`; FastAPI supplies a `WebSocket` in a WebSocket scope, so
the dependency was uncallable on /api/ibkr/live and raised TypeError on every
connection attempt — regardless of whether auth was enabled. The frontend
streams live market data over that socket, so the default-off promise ("while
AUTH_ENABLED is false nothing changes") was false.

Nothing caught it: the route coverage test filtered on hasattr(r, "methods"),
which excludes WebSocket routes, and no test drove the socket through the app.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, WebSocket
from fastapi.testclient import TestClient

import app.core.database as db_mod
from app.api.auth_deps import require_session
from app.core.config import settings
from app.services.auth_service import SESSION_COOKIE_NAME

from test_auth_routes import _FakeSession, _Store  # in-memory database stand-in


@pytest.fixture
def ws_app(monkeypatch):
    store = _Store()
    monkeypatch.setattr(db_mod, "AsyncSessionLocal", lambda: _FakeSession(store))

    app = FastAPI(dependencies=[Depends(require_session)])

    @app.websocket("/api/ibkr/live")
    async def _live(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("live market data")

    return app


def test_websocket_works_while_auth_is_disabled(ws_app, monkeypatch):
    """
    The regression test proper. With AUTH_ENABLED false this must behave
    exactly as it did before auth existed.
    """
    monkeypatch.setattr(settings, "auth_enabled", False)
    with TestClient(ws_app).websocket_connect("/api/ibkr/live") as ws:
        assert ws.receive_text() == "live market data"


def test_websocket_without_a_session_is_refused_not_crashed_on(ws_app, monkeypatch):
    """
    With auth on the socket must be refused — and refused in the WebSocket
    protocol. An HTTPException raised during a handshake is not turned into a
    close frame by Starlette; it surfaces as a server error, which is the
    difference between "denied" and "broken".
    """
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setattr(settings, "auth_enabled", True)
    client = TestClient(ws_app)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/ibkr/live"):
            pass
    assert exc.value.code == 1008          # policy violation


def test_websocket_with_a_forged_cookie_is_refused(ws_app, monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setattr(settings, "auth_enabled", True)
    client = TestClient(ws_app)
    client.cookies.set(SESSION_COOKIE_NAME, "made-up-token")

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ibkr/live"):
            pass
