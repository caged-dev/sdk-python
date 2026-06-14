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
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import websockets
import websockets.client


class MCPError(Exception):
    """Error returned by the MCP server."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"MCP error {code}: {message}")


@dataclass
class MCPTool:
    """An MCP tool definition."""
    name: str
    description: str = ""
    inputSchema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPResource:
    """An MCP resource definition."""
    uri: str
    name: str
    description: str = ""
    mimeType: Optional[str] = None


@dataclass
class MCPPrompt:
    """An MCP prompt definition."""
    name: str
    description: str = ""
    arguments: List[Dict[str, Any]] = field(default_factory=list)


class MCPClient:
    """MCP client for calling sandbox tools via WebSocket (JSON-RPC 2.0)."""

    def __init__(self, ws: websockets.client.ClientConnection) -> None:
        self._ws = ws
        self._closed = False
        self._request_id = 0
        self._pending: Dict[int, asyncio.Future[Any]] = {}
        self._notification_handlers: List[Callable[[str, Any], Any]] = []
        self._close_handlers: List[Callable[[], Any]] = []
        self._listen_task: Optional[asyncio.Task[None]] = None

    async def _start_listening(self) -> None:
        """Start the background listener for WebSocket messages."""
        self._listen_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        try:
            async for message in self._ws:
                try:
                    msg = json.loads(message)
                    if "id" in msg and msg["id"] is not None:
                        future = self._pending.pop(msg["id"], None)
                        if future and not future.done():
                            if "error" in msg:
                                err = msg["error"]
                                future.set_exception(
                                    MCPError(err.get("code", -1), err.get("message", "Unknown"))
                                )
                            else:
                                future.set_result(msg.get("result"))
                    elif "method" in msg and "id" not in msg:
                        # Server notification.
                        for handler in self._notification_handlers:
                            handler(msg["method"], msg.get("params"))
                except (json.JSONDecodeError, TypeError):
                    pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._closed = True
            # Reject all pending requests.
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("MCP connection closed"))
            self._pending.clear()
            for handler in self._close_handlers:
                handler()

    async def _request(self, method: str, params: Any = None) -> Any:
        """Send a JSON-RPC request and wait for the response."""
        if self._closed:
            raise RuntimeError("MCP connection closed")

        self._request_id += 1
        req_id = self._request_id
        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[req_id] = future

        payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params

        await self._ws.send(json.dumps(payload))
        return await future

    async def initialize(self) -> Dict[str, Any]:
        """Initialize the MCP session. Called automatically on connect."""
        return await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "caged-python", "version": "0.2.0"},
        })

    async def list_tools(self) -> List[MCPTool]:
        """List available tools in the sandbox."""
        result = await self._request("tools/list", {})
        return [MCPTool(**t) for t in result.get("tools", [])]

    async def call_tool(
        self, name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Call a tool by name with arguments."""
        return await self._request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })

    async def list_resources(self) -> List[MCPResource]:
        """List available resources."""
        result = await self._request("resources/list", {})
        return [MCPResource(**r) for r in result.get("resources", [])]

    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read a resource by URI."""
        return await self._request("resources/read", {"uri": uri})

    async def list_prompts(self) -> List[MCPPrompt]:
        """List available prompts."""
        result = await self._request("prompts/list", {})
        return [MCPPrompt(**p) for p in result.get("prompts", [])]

    async def get_prompt(
        self, name: str, arguments: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Get a prompt with arguments."""
        return await self._request("prompts/get", {
            "name": name,
            "arguments": arguments or {},
        })

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
