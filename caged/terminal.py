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
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, List, Optional

import websockets
import websockets.client


class TerminalSession:
    """Interactive terminal session over WebSocket."""

    def __init__(self, ws: websockets.client.ClientConnection) -> None:
        self._ws = ws
        self._closed = False
        self._output_handlers: List[Callable[[str], Any]] = []
        self._close_handlers: List[Callable[[], Any]] = []
        self._error_handlers: List[Callable[[Exception], Any]] = []
        self._listen_task: Optional[asyncio.Task[None]] = None

    async def _start_listening(self) -> None:
        """Start the background listener for WebSocket messages."""
        self._listen_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        try:
            async for message in self._ws:
                try:
                    msg = json.loads(message)
                    if msg.get("type") == "output" and msg.get("data"):
                        for handler in self._output_handlers:
                            handler(msg["data"])
                except (json.JSONDecodeError, TypeError):
                    # Raw text fallback.
                    for handler in self._output_handlers:
                        handler(str(message))
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as exc:
            for handler in self._error_handlers:
                handler(exc)
        finally:
            self._closed = True
            for handler in self._close_handlers:
                handler()

    async def send(self, input: str) -> None:
        """Send input to the terminal (include \\n for Enter)."""
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
