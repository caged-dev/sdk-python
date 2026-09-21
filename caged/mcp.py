"""MCP (Model Context Protocol) client for interacting with sandbox tools.

Example::

    import asyncio
    from caged import Caged

    async def main():
        caged = Caged(api_key="caged_sk_...")
        mcp = await caged.sandboxes.mcp("sandbox-id")

        tools = await mcp.list_tools()
        result = await mcp.call_tool("terminal_exec", {"command": "npm test"})
        print(result["content"][0]["text"])

        await mcp.close()

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields
from typing import Any, TypeVar

from caged._version import __version__
from caged._ws import WebSocketLike
from caged.stream import _is_connection_closed

M = TypeVar("M", bound="_MCPModel")


class MCPError(Exception):
    """Error returned by the MCP server."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"MCP error {code}: {message}")


class _MCPModel:
    """Tolerant constructor, for the same reason the HTTP models have one.

    An MCP server is free to add fields to a tool, resource or prompt
    definition. Splatting the object into a dataclass made that addition a
    ``TypeError`` in the client.
    """

    @classmethod
    def from_api(cls: type[M], data: Mapping[str, Any]) -> M:
        if not isinstance(data, Mapping):
            raise TypeError(
                f"{cls.__name__}.from_api expected a JSON object, "
                f"got {type(data).__name__}"
            )
        known = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def list_from_api(cls: type[M], data: Any) -> list[M]:
        if not isinstance(data, list):
            return []
        return [cls.from_api(item) for item in data if isinstance(item, Mapping)]


@dataclass
class MCPTool(_MCPModel):
    """An MCP tool definition."""

    name: str = ""
    description: str = ""
    inputSchema: dict[str, Any] = field(default_factory=dict)  # noqa: N815 - wire name


@dataclass
class MCPResource(_MCPModel):
    """An MCP resource definition."""

    uri: str = ""
    name: str = ""
    description: str = ""
    mimeType: str | None = None  # noqa: N815 - wire name


@dataclass
class MCPPrompt(_MCPModel):
    """An MCP prompt definition."""

    name: str = ""
    description: str = ""
    arguments: list[dict[str, Any]] = field(default_factory=list)


class MCPClient:
    """MCP client for calling sandbox tools via WebSocket (JSON-RPC 2.0)."""

    def __init__(self, ws: WebSocketLike) -> None:
        self._ws = ws
        self._closed = False
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._notification_handlers: list[Callable[[str, Any], Any]] = []
        self._close_handlers: list[Callable[[], Any]] = []
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
                    continue
                if not isinstance(msg, dict):
                    continue
                self._dispatch(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - delivered to waiters below
            if not _is_connection_closed(exc):
                self._fail_pending(exc)
        finally:
            self._closed = True
            self._fail_pending(MCPError(-1, "MCP connection closed"))
            for handler in self._close_handlers:
                handler()

    def _dispatch(self, msg: dict[str, Any]) -> None:
        msg_id = msg.get("id")
        if isinstance(msg_id, int):
            future = self._pending.pop(msg_id, None)
            if future is None or future.done():
                return
            error = msg.get("error")
            if isinstance(error, Mapping):
                code = error.get("code")
                message = error.get("message")
                future.set_exception(
                    MCPError(
                        code if isinstance(code, int) else -1,
                        message if isinstance(message, str) else "unknown MCP error",
                    )
                )
            else:
                future.set_result(msg.get("result"))
            return
        method = msg.get("method")
        if isinstance(method, str):
            for handler in self._notification_handlers:
                handler(method, msg.get("params"))

    def _fail_pending(self, exc: Exception) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()

    async def _request(self, method: str, params: Any = None) -> Any:
        """Send a JSON-RPC request and wait for the response."""
        if self._closed:
            raise MCPError(-1, "MCP connection closed")

        self._request_id += 1
        req_id = self._request_id
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future

        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params

        await self._ws.send(json.dumps(payload))
        return await future

    async def initialize(self) -> dict[str, Any]:
        """Initialize the MCP session. Called automatically on connect."""
        result = await self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                # Read from the package version rather than written out
                # again: a hardcoded version here is how the published
                # 0.2.0 came to announce itself as 0.1.0.
                "clientInfo": {"name": "caged-python", "version": __version__},
            },
        )
        return result if isinstance(result, dict) else {}

    async def list_tools(self) -> list[MCPTool]:
        """List available tools in the sandbox."""
        result = await self._request("tools/list", {})
        return MCPTool.list_from_api(_field(result, "tools"))

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Call a tool by name with arguments."""
        result = await self._request(
            "tools/call", {"name": name, "arguments": arguments or {}}
        )
        return result if isinstance(result, dict) else {}

    async def list_resources(self) -> list[MCPResource]:
        """List available resources."""
        result = await self._request("resources/list", {})
        return MCPResource.list_from_api(_field(result, "resources"))

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a resource by URI."""
        result = await self._request("resources/read", {"uri": uri})
        return result if isinstance(result, dict) else {}

    async def list_prompts(self) -> list[MCPPrompt]:
        """List available prompts."""
        result = await self._request("prompts/list", {})
        return MCPPrompt.list_from_api(_field(result, "prompts"))

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Get a prompt with arguments."""
        result = await self._request(
            "prompts/get", {"name": name, "arguments": arguments or {}}
        )
        return result if isinstance(result, dict) else {}

    async def ping(self) -> None:
        """Ping the server."""
        await self._request("ping", {})

    def on_notification(self, handler: Callable[[str, Any], Any]) -> None:
        """Listen for server notifications."""
        self._notification_handlers.append(handler)

    def on_close(self, handler: Callable[[], Any]) -> None:
        """Register a close handler."""
        self._close_handlers.append(handler)

    @property
    def closed(self) -> bool:
        """Whether the connection is closed."""
        return self._closed

    async def close(self) -> None:
        """Close the MCP connection."""
        if not self._closed:
            self._closed = True
            await self._ws.close()
            if self._listen_task:
                self._listen_task.cancel()
                try:
                    await self._listen_task
                except asyncio.CancelledError:
                    pass


def _field(result: Any, key: str) -> Any:
    return result.get(key) if isinstance(result, Mapping) else None
