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

# How this works, and why it is not just "send the command"

There is no streaming exec endpoint. The only streaming surface is the
terminal WebSocket, which attaches a login shell to a PTY and speaks
``{"type": "input" | "output" | "resize"}`` — and nothing else. It never
sends an ``exit`` message and has no notion of a command's exit code.

So this used to send the command into the shell and then wait for a message
type the server does not emit: ``exit_code`` stayed ``None`` forever and the
iterator only ended when the sandbox's idle timeout closed the socket. The
output also included the login banner, the shell's own echo of the command,
and the prompt.

Instead the command is bracketed by two markers carrying a per-call nonce.
Everything before the first is dropped (banner, echo), the exit code is read
from the second, and the shell is asked to exit, which closes the stream
deterministically rather than at a timeout.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import uuid
from collections.abc import AsyncIterator

from caged._ws import WebSocketLike


class ExecStream:
    """Async iterable stream of one command's output over a terminal socket."""

    def __init__(self, ws: WebSocketLike) -> None:
        self._ws = ws
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._error: Exception | None = None
        self._done = False
        self._listen_task: asyncio.Task[None] | None = None
        nonce = uuid.uuid4().hex[:16]
        self._filter = _MarkerFilter(
            begin=f"__CAGED_BEGIN_{nonce}__", end=f"__CAGED_EXIT_{nonce}__"
        )

    async def _start(self, command: str) -> None:
        """Start listening, then drive the command through the shell."""
        self._listen_task = asyncio.create_task(self._listen())
        for line in self._filter.shell_lines(command):
            await self._ws.send(json.dumps({"type": "input", "data": line}))

    async def _listen(self) -> None:
        try:
            async for message in self._ws:
                text = _message_text(message)
                if text is None:
                    continue
                out, finished = self._filter.feed(text)
                if out:
                    await self._queue.put(out)
                if finished:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - reported to the consumer
            if not _is_connection_closed(exc):
                self._error = exc
        finally:
            self._done = True
            tail = self._filter.flush()
            if tail:
                await self._queue.put(tail)
            await self._queue.put(None)
            # The shell has exited, or the socket has gone; either way the
            # connection is finished with. Closing here rather than leaving
            # it to the caller keeps a completed stream from holding a
            # socket open for the rest of the process's life.
            with contextlib.suppress(Exception):
                await self._ws.close()

    @property
    def exit_code(self) -> int | None:
        """The command's exit code, once the stream has completed.

        ``None`` while it is still running, and also if the connection
        dropped before the command finished — in which case the exit status
        is genuinely unknown rather than zero.
        """
        return self._filter.exit_code

    async def kill(self) -> None:
        """Close the stream, abandoning the command."""
        await self._ws.close()
        if self._listen_task:
            self._listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task

    def __aiter__(self) -> AsyncIterator[str]:
        return self

    async def __anext__(self) -> str:
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


def _message_text(message: object) -> str | None:
    """Pull the output text out of one terminal protocol message."""
    if isinstance(message, bytes):
        message = message.decode("utf-8", "replace")
    if not isinstance(message, str):
        return None
    try:
        parsed = json.loads(message)
    except ValueError:
        # Not JSON: the endpoint speaks JSON, but a raw frame is still
        # output rather than something to discard.
        return message
    if isinstance(parsed, dict) and parsed.get("type") == "output":
        data = parsed.get("data")
        return data if isinstance(data, str) else None
    return None


def _is_connection_closed(exc: Exception) -> bool:
    """Whether an exception is just the peer hanging up.

    Matched by name rather than by class so this does not have to import a
    different exception path for each supported ``websockets`` version.
    """
    return type(exc).__name__.startswith("ConnectionClosed")


class _MarkerFilter:
    """Extracts one command's output and exit code from a shell PTY stream.

    Separated from the socket so it can be tested directly, including the
    case that makes naive versions of this wrong: a marker split across two
    WebSocket messages.
    """

    def __init__(self, begin: str, end: str) -> None:
        self._begin = begin
        self._end = end
        self._buf = ""
        self._started = False
        self._finished = False
        self._exit_code: int | None = None
        # Hold back enough characters that a marker straddling two messages
        # is still found, plus room for the exit digits and the newline.
        self._keep = max(len(begin), len(end) + 12)

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    def shell_lines(self, command: str) -> list[str]:
        """The lines to type into the shell to run ``command``.

        Three separate lines, not one: the command is passed through
        untouched, so a multi-line command (a heredoc, a ``for`` loop) still
        works. ``$?`` then reports the last command's status, which is what
        a shell means by the status of what it just ran.
        """
        return [
            # Suppress the shell's echo of the lines below, then mark the
            # start of real output. `stty` is absent in some minimal images;
            # a failure there costs an echoed command line, not the command.
            f"stty -echo 2>/dev/null; printf '%s\\n' '{self._begin}'\n",
            command if command.endswith("\n") else command + "\n",
            f"__caged_rc=$?; printf '%s%d\\n' '{self._end}' \"$__caged_rc\"; "
            f"exit $__caged_rc\n",
        ]

    def feed(self, chunk: str) -> tuple[str, bool]:
        """Consume one chunk of PTY output.

        Returns the text to hand the caller and whether the command has
        finished.
        """
        if self._finished:
            return "", True
        self._buf += chunk

        if not self._started:
            index = self._buf.find(self._begin)
            if index < 0:
                # Keep only enough to catch a marker split across messages.
                if len(self._buf) > self._keep:
                    self._buf = self._buf[-self._keep :]
                return "", False
            self._buf = self._buf[index + len(self._begin) :].lstrip("\r\n")
            self._started = True

        index = self._buf.find(self._end)
        if index < 0:
            if len(self._buf) <= self._keep:
                return "", False
            out = self._buf[: -self._keep]
            self._buf = self._buf[-self._keep :]
            return out, False

        out = self._buf[:index]
        tail = self._buf[index + len(self._end) :]
        match = re.match(r"\s*(\d+)", tail)
        if match is None:
            # The marker has arrived but its digits have not. Emit what came
            # before it and wait; the buffer keeps the marker so the next
            # chunk completes it.
            self._buf = self._buf[index:]
            return out, False
        self._exit_code = int(match.group(1))
        self._finished = True
        self._buf = ""
        return out, True

    def flush(self) -> str:
        """Whatever is still held back when the stream ends unfinished.

        Output is deliberately held back so a marker straddling two frames is
        still recognised, which means that at the moment a socket drops the
        last few hundred characters the user did see are still in this
        buffer. Dropping them lost the tail of every interrupted command --
        and for a command whose entire output was shorter than the held-back
        window, it lost all of it.

        A trailing fragment that could be the beginning of the end marker is
        not emitted: it is protocol, not output.
        """
        if self._finished or not self._started:
            self._buf = ""
            return ""
        out = self._buf
        self._buf = ""
        for cut in range(len(self._end) - 1, 0, -1):
            if out.endswith(self._end[:cut]):
                return out[:-cut]
        return out
