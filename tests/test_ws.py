"""Tests for the three WebSocket clients, against a fake socket.

No test here opens a connection: :class:`FakeWS` implements the same small
surface (``send``, ``close``, async iteration) that ``caged._ws.WebSocketLike``
declares, which is the whole reason that protocol exists.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from caged import ExecStream, MCPClient, MCPError, TerminalSession
from caged.stream import _MarkerFilter

_EOF = object()


class FakeWS:
    """A WebSocket whose frames the test pushes in."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False
        self._queue: asyncio.Queue[Any] = asyncio.Queue()

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True
        self._queue.put_nowait(_EOF)

    def __aiter__(self) -> Any:
        return self._frames()

    async def _frames(self) -> Any:
        while True:
            frame = await self._queue.get()
            if frame is _EOF:
                return
            yield frame

    def push(self, obj: Any) -> None:
        self._queue.put_nowait(obj if isinstance(obj, str) else json.dumps(obj))

    def output(self, data: str) -> None:
        self.push({"type": "output", "data": data})

    def eof(self) -> None:
        self._queue.put_nowait(_EOF)


def sent_bodies(ws: FakeWS) -> list[str]:
    return [json.loads(m)["data"] for m in ws.sent]


# --- the marker protocol --------------------------------------------------


def test_marker_filter_drops_the_banner_and_the_shell_echo() -> None:
    f = _MarkerFilter(begin="BEGIN", end="EXIT")
    out, done = f.feed("Welcome to Ubuntu\nstty -echo; printf BEGIN\n")
    assert out == ""
    assert done is False


def test_marker_filter_emits_output_and_reads_the_exit_code() -> None:
    f = _MarkerFilter(begin="BEGIN", end="EXIT")
    f.feed("banner\nBEGIN\n")
    out, done = f.feed("hello world\nEXIT7\n")
    assert out == "hello world\n"
    assert done is True
    assert f.exit_code == 7


def test_marker_filter_survives_a_marker_split_across_frames() -> None:
    # The reason output is held back rather than emitted straight through: a
    # PTY read boundary can land in the middle of a marker.
    f = _MarkerFilter(begin="BEGIN", end="EXIT")
    f.feed("noise BEG")
    out, done = f.feed("IN\nreal output\n")
    assert done is False
    f.feed("more\nEX")
    out2, done2 = f.feed("IT0\n")
    assert done2 is True
    assert f.exit_code == 0
    assert (out + out2).endswith("more\n")
    assert "real output\n" in out + out2


def test_marker_filter_waits_for_the_exit_digits() -> None:
    f = _MarkerFilter(begin="BEGIN", end="EXIT")
    f.feed("BEGIN\n")
    out, done = f.feed("done\nEXIT")
    assert done is False
    assert f.exit_code is None
    _, done = f.feed("13\n")
    assert done is True
    assert f.exit_code == 13


def test_marker_filter_holds_back_only_a_bounded_tail() -> None:
    f = _MarkerFilter(begin="B", end="E")
    f.feed("B\n")
    out, _ = f.feed("x" * 500)
    assert len(out) > 400


# --- ExecStream -----------------------------------------------------------


async def test_exec_stream_yields_output_and_reports_the_exit_code() -> None:
    ws = FakeWS()
    stream = ExecStream(ws)
    await stream._start("npm test")

    lines = sent_bodies(ws)
    assert len(lines) == 3
    assert lines[1] == "npm test\n"
    begin = stream._filter._begin
    end = stream._filter._end

    ws.output("Ubuntu 24.04 LTS\n")
    ws.output(f"{begin}\n")
    ws.output("2 passing\n")
    ws.output(f"{end}1\n")

    chunks = [chunk async for chunk in stream]
    assert "".join(chunks) == "2 passing\n"
    assert stream.exit_code == 1
    assert ws.closed is True


async def test_exec_stream_leaves_the_exit_code_unknown_if_the_socket_drops() -> None:
    # A dropped connection is not a successful command. Defaulting to 0 here
    # would report a pass for a run nobody saw finish.
    ws = FakeWS()
    stream = ExecStream(ws)
    await stream._start("sleep 100")
    ws.output(f"{stream._filter._begin}\npartial")
    ws.eof()

    assert await stream.text() == "partial"
    assert stream.exit_code is None


async def test_exec_stream_passes_a_multi_line_command_through_untouched() -> None:
    ws = FakeWS()
    stream = ExecStream(ws)
    command = "for f in *.py; do\n  echo $f\ndone"
    await stream._start(command)
    assert sent_bodies(ws)[1] == command + "\n"
    await stream.kill()


async def test_exec_stream_asks_the_shell_to_report_and_exit() -> None:
    ws = FakeWS()
    stream = ExecStream(ws)
    await stream._start("true")
    last = sent_bodies(ws)[2]
    assert "__caged_rc=$?" in last
    assert "exit $__caged_rc" in last
    await stream.kill()


# --- TerminalSession ------------------------------------------------------


async def test_terminal_delivers_output_to_handlers() -> None:
    ws = FakeWS()
    session = TerminalSession(ws)
    await session._start_listening()
    seen: list[str] = []
    session.on_output(seen.append)
    ws.output("$ ")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert seen == ["$ "]
    await session.close()


async def test_terminal_send_and_resize_speak_the_wire_protocol() -> None:
    ws = FakeWS()
    session = TerminalSession(ws)
    await session._start_listening()
    await session.send("ls\n")
    await session.resize(40, 120)
    assert json.loads(ws.sent[0]) == {"type": "input", "data": "ls\n"}
    assert json.loads(ws.sent[1]) == {"type": "resize", "rows": 40, "cols": 120}
    await session.close()


async def test_terminal_refuses_to_send_after_close() -> None:
    ws = FakeWS()
    session = TerminalSession(ws)
    await session._start_listening()
    await session.close()
    with pytest.raises(RuntimeError):
        await session.send("ls\n")


async def test_terminal_close_handlers_run_when_the_peer_hangs_up() -> None:
    ws = FakeWS()
    session = TerminalSession(ws)
    await session._start_listening()
    closed: list[bool] = []
    session.on_close(lambda: closed.append(True))
    ws.eof()
    for _ in range(4):
        await asyncio.sleep(0)
    assert closed == [True]
    assert session.closed is True


# --- MCPClient ------------------------------------------------------------


async def test_mcp_initialize_announces_the_package_version() -> None:
    from caged import __version__

    ws = FakeWS()
    client = MCPClient(ws)
    await client._start_listening()
    task = asyncio.create_task(client.initialize())
    await asyncio.sleep(0)
    request = json.loads(ws.sent[0])
    assert request["method"] == "initialize"
    assert request["params"]["clientInfo"] == {
        "name": "caged-python",
        "version": __version__,
    }
    ws.push({"jsonrpc": "2.0", "id": request["id"], "result": {"protocolVersion": "x"}})
    assert await task == {"protocolVersion": "x"}
    await client.close()


async def test_mcp_list_tools_tolerates_a_field_it_does_not_know() -> None:
    ws = FakeWS()
    client = MCPClient(ws)
    await client._start_listening()
    task = asyncio.create_task(client.list_tools())
    await asyncio.sleep(0)
    request_id = json.loads(ws.sent[0])["id"]
    ws.push(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "terminal_exec",
                        "description": "run a command",
                        "inputSchema": {"type": "object"},
                        "annotations": {"readOnlyHint": False},
                    }
                ]
            },
        }
    )
    tools = await task
    assert tools[0].name == "terminal_exec"
    assert tools[0].inputSchema == {"type": "object"}
    await client.close()


async def test_mcp_error_response_becomes_an_mcp_error() -> None:
    ws = FakeWS()
    client = MCPClient(ws)
    await client._start_listening()
    task = asyncio.create_task(client.call_tool("nope"))
    await asyncio.sleep(0)
    request_id = json.loads(ws.sent[0])["id"]
    ws.push(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "unknown tool: nope"},
        }
    )
    with pytest.raises(MCPError, match="unknown tool: nope") as excinfo:
        await task
    assert excinfo.value.code == -32601
    await client.close()


async def test_mcp_pending_requests_fail_when_the_socket_closes() -> None:
    ws = FakeWS()
    client = MCPClient(ws)
    await client._start_listening()
    task = asyncio.create_task(client.ping())
    await asyncio.sleep(0)
    ws.eof()
    with pytest.raises(MCPError, match="closed"):
        await task


async def test_mcp_notifications_reach_their_handler() -> None:
    ws = FakeWS()
    client = MCPClient(ws)
    await client._start_listening()
    seen: list[tuple[str, Any]] = []
    client.on_notification(lambda method, params: seen.append((method, params)))
    ws.push({"jsonrpc": "2.0", "method": "notifications/progress", "params": {"n": 1}})
    for _ in range(3):
        await asyncio.sleep(0)
    assert seen == [("notifications/progress", {"n": 1})]
    await client.close()
