"""How the credential reaches a WebSocket handshake.

A handshake cannot carry an Authorization header, so the credential rides in
the URL — where it reaches every intermediary that logs a request line. The
API mints single-use tickets for exactly this, and warns when it sees a
long-lived credential in a handshake instead. This SDK used to send the raw
API key on every socket.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from caged import Caged
from caged import _ws as ws_module

TICKET = {"ticket": "caged_wst_abc.def", "expires_in": 60, "expires_at": "t"}


class RecordingConnect:
    def __init__(self) -> None:
        self.url = ""
        self.subprotocol = ""

    async def __call__(self, url: str, subprotocol: str) -> Any:
        self.url = url
        self.subprotocol = subprotocol
        return object()


@pytest.fixture
def connects(monkeypatch: pytest.MonkeyPatch) -> RecordingConnect:
    recorder = RecordingConnect()
    monkeypatch.setattr(ws_module, "connect", recorder)
    return recorder


def client(handler: Any, **kwargs: Any) -> Caged:
    return Caged(
        api_key="caged_sk_test",
        base_url=kwargs.pop("base_url", "https://api.example.test"),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def ticket_handler(request: httpx.Request) -> httpx.Response:
    assert urlparse(str(request.url)).path == "/v1/auth/socket-ticket"
    return httpx.Response(200, json=TICKET)


async def test_a_socket_carries_a_ticket_not_the_api_key(connects: Any) -> None:
    caged = client(ticket_handler)
    await caged.sandboxes.terminal("sbx_1", rows=40, cols=120)
    query = parse_qs(urlparse(connects.url).query)
    assert query["token"] == ["caged_wst_abc.def"]
    assert "caged_sk_test" not in connects.url
    assert query["rows"] == ["40"] and query["cols"] == ["120"]
    caged.close()


async def test_https_becomes_wss(connects: Any) -> None:
    caged = client(ticket_handler)
    await caged.sandboxes.mcp("sbx_1")
    assert connects.url.startswith("wss://api.example.test/v1/sandboxes/sbx_1/mcp?")
    caged.close()


async def test_http_becomes_ws_for_local_development(connects: Any) -> None:
    caged = client(ticket_handler, base_url="http://localhost:8080")
    await caged.sandboxes.mcp("sbx_1")
    assert connects.url.startswith("ws://localhost:8080/v1/sandboxes/sbx_1/mcp?")
    caged.close()


async def test_each_endpoint_asks_for_its_own_subprotocol(connects: Any) -> None:
    caged = client(ticket_handler)
    await caged.sandboxes.terminal("sbx_1")
    assert connects.subprotocol == "terminal"
    await caged.sandboxes.mcp("sbx_1")
    assert connects.subprotocol == "mcp"
    caged.close()


async def test_an_api_without_the_ticket_endpoint_still_gets_a_socket(
    connects: Any,
) -> None:
    # Falls back to the key rather than losing every socket against an API
    # deployed before POST /v1/auth/socket-ticket existed.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="404 page not found")

    caged = client(handler)
    await caged.sandboxes.terminal("sbx_1")
    query = parse_qs(urlparse(connects.url).query)
    assert query["token"] == ["caged_sk_test"]
    caged.close()


async def test_a_real_refusal_from_the_ticket_endpoint_is_not_swallowed(
    connects: Any,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"title": "Unauthorized", "status": 401, "detail": "invalid API key"},
            headers={"content-type": "application/problem+json"},
        )

    caged = client(handler)
    with pytest.raises(Exception, match="invalid API key"):
        await caged.sandboxes.terminal("sbx_1")
    caged.close()
