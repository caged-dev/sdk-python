"""WebSocket transport details shared by the terminal, stream and MCP clients.

Two things live here rather than in three places:

* :class:`WebSocketLike` — the small structural type this SDK actually uses.
  ``websockets`` renamed its client connection class between the versions
  this package supports (``WebSocketClientProtocol`` in 12/13,
  ``ClientConnection`` in 14+), so annotating against the concrete class made
  the type checker's answer depend on which version happened to be
  installed. The modules here only send text, close, and iterate messages.

* :func:`connect` — the handshake, including how the credential travels.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, cast

import websockets


class WebSocketLike(Protocol):
    """The part of a ``websockets`` connection this SDK uses."""

    async def send(self, message: str) -> None:  # pragma: no cover - protocol
        ...

    async def close(self) -> None:  # pragma: no cover - protocol
        ...

    def __aiter__(self) -> AsyncIterator[Any]:  # pragma: no cover - protocol
        ...


async def connect(url: str, subprotocol: str) -> WebSocketLike:
    """Open a WebSocket, negotiating the endpoint's own subprotocol.

    The subprotocol matters: the API's terminal endpoint offers "terminal"
    and its MCP endpoint offers "mcp". Asking for "mcp" on the terminal —
    which is what this SDK used to do for every socket — leaves the
    handshake with no agreed subprotocol, which the server tolerates today
    and is under no obligation to keep tolerating.
    """
    return cast(
        WebSocketLike,
        await websockets.connect(url, subprotocols=[subprotocol]),  # type: ignore[list-item]
    )
