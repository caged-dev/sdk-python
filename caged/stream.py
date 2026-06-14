"""Streaming execution — real-time output from long-running commands.

Example::

    import asyncio
    from caged import Caged

    async def main():
        caged = Caged(api_key="caged_sk_...")
        stream = await caged.sandboxes.exec_stream("sandbox-id", "npm test")

        async for chunk in stream:
            print(chunk, end="")

        print(f"Exit code: {stream.exit_code}")

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Optional

import websockets
import websockets.client


class ExecStream:
    """Async iterable stream of command output over WebSocket."""

    def __init__(self, ws: websockets.client.ClientConnection) -> None:
        self._ws = ws
        self._queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        self._exit_code: Optional[int] = None
        self._error: Optional[Exception] = None
        self._done = False
        self._listen_task: Optional[asyncio.Task[None]] = None

    async def _start_listening(self) -> None:
        """Start the background listener."""
        self._listen_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        try:
            async for message in self._ws:
                try:
                    msg = json.loads(message)
                    if msg.get("type") == "output":
                        await self._queue.put(msg.get("data", ""))
                    elif msg.get("type") == "exit":
                        self._exit_code = msg.get("code", 0)
                        self._done = True
                        await self._queue.put(None)
                        return
                    elif msg.get("type") == "error":
                        self._error = RuntimeError(msg.get("message", "exec failed"))
                        self._done = True
                        await self._queue.put(None)
                        return
                except (json.JSONDecodeError, TypeError):
                    # Raw text fallback.
                    await self._queue.put(str(message))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._done = True
            await self._queue.put(None)

    @property
    def exit_code(self) -> Optional[int]:
        """The exit code (available after stream completes)."""
        return self._exit_code

    async def kill(self) -> None:
        """Close the stream and kill the process."""
        await self._ws.close()
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

    def __aiter__(self) -> AsyncIterator[str]:
        return self

    async def __anext__(self) -> str:
        if self._error:
            raise self._error
        chunk = await self._queue.get()
        if chunk is None:
            if self._error:
                raise self._error
            raise StopAsyncIteration
        return chunk

    async def text(self) -> str:
        """Collect all output as a single string."""
        parts: list[str] = []
        async for chunk in self:
            parts.append(chunk)
        return "".join(parts)
