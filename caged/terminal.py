"""WebSocket-based terminal session for interactive PTY access to a sandbox.

Example::

    import asyncio
    from caged import Caged

    async def main():
        caged = Caged(api_key="caged_sk_...")
        terminal = await caged.sandboxes.terminal("sandbox-id")
        terminal.on_output(lambda data: print(data, end=""))
        await terminal.send("ls -la\n")
        await asyncio.sleep(2)
        await terminal.close()

    asyncio.run(main())

The wire protocol is ``api.terminalMessage``: ``{"type": "input" | "output" |
"resize" | "ping" | "pong", "data": str, "rows": int, "cols": int}``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from caged._ws import WebSocketLike
from caged.stream import _is_connection_closed


class TerminalSession:
    """Interactive terminal session over WebSocket."""

    def __init__(self, ws: WebSocketLike) -> None:
        self._ws = ws
        self._closed = False
        self._output_handlers: list[Callable[[str], Any]] = []
        self._close_handlers: list[Callable[[], Any]] = []
        self._error_handlers: list[Callable[[Exception], Any]] = []
        self._listen_task: asyncio.Task[None] | None = None

    async def _start_listening(self) -> None:
        """Start the background listener for WebSocket messages."""
        self._listen_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        try:
            async for message in self._ws:
                text = message
                if isinstance(text, bytes):
                    text = text.decode("utf-8", "replace")
                if not isinstance(text, str):
                    continue
                try:
                    msg = json.loads(text)
                except ValueError:
                    # Raw frame: still output.
                    self._emit(text)
                    continue
                if isinstance(msg, dict) and msg.get("type") == "output":
                    data = msg.get("data")
                    if isinstance(data, str) and data:
                        self._emit(data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - reported to the handlers
            if not _is_connection_closed(exc):
                for handler in self._error_handlers:
                    handler(exc)
        finally:
            self._closed = True
            for handler in self._close_handlers:
                handler()

    def _emit(self, data: str) -> None:
        for handler in self._output_handlers:
            handler(data)

    async def send(self, input: str) -> None:
        """Send input to the terminal (include ``\\n`` for Enter)."""
        if self._closed:
            raise RuntimeError("Terminal session is closed")
        await self._ws.send(json.dumps({"type": "input", "data": input}))

    async def resize(self, rows: int, cols: int) -> None:
        """Resize the terminal."""
        if self._closed:
            return
        await self._ws.send(json.dumps({"type": "resize", "rows": rows, "cols": cols}))

    def on_output(self, handler: Callable[[str], Any]) -> None:
        """Register a handler for terminal output."""
        self._output_handlers.append(handler)

    def on_close(self, handler: Callable[[], Any]) -> None:
        """Register a handler for close events."""
        self._close_handlers.append(handler)

    def on_error(self, handler: Callable[[Exception], Any]) -> None:
        """Register a handler for errors."""
        self._error_handlers.append(handler)

    @property
    def closed(self) -> bool:
        """Whether the session is closed."""
        return self._closed

    async def close(self) -> None:
        """Close the terminal session."""
        if not self._closed:
            self._closed = True
            await self._ws.close()
            if self._listen_task:
                self._listen_task.cancel()
                try:
                    await self._listen_task
                except asyncio.CancelledError:
                    pass
