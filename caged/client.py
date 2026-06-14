"""Caged Python SDK client."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
import websockets
import websockets.client

from caged.errors import CagedAPIError, CagedTimeoutError
from caged.mcp import MCPClient
from caged.stream import ExecStream
from caged.terminal import TerminalSession
from caged.types import (
    AgentSession,
    Alert,
    AlertRule,
    APIKey,
    EventPayload,
    ExecResult,
    FileEntry,
    IngestResponse,
    LogEntry,
    Notification,
    NotificationConfig,
    Port,
    ReplayEvent,
    ReplaySummary,
    Sandbox,
    SandboxCreateParams,
    Session,
    Snapshot,
    SnapshotCreateParams,
    Subscription,
    TrustScore,
)

DEFAULT_BASE_URL = "https://api.caged.dev"
DEFAULT_TIMEOUT = 30.0

# Command execution can include long-running agent prompts.
DEFAULT_EXEC_TIMEOUT = 300.0

# Sandbox creation can include a repo clone and agent installs.
DEFAULT_CREATE_TIMEOUT = 360.0


class Caged:
    """
    Caged SDK client.

    Usage::

        from caged import Caged

        caged = Caged(api_key="caged_sk_...")
        sandbox = caged.sandboxes.create(template="node-20")
        print(sandbox.id, sandbox.status)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=f"{self._base_url}/v1",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "caged-python/0.2.0",
            },
            timeout=timeout,
        )

        self.sandboxes = _SandboxesAPI(self)
        self.files = _FilesAPI(self)
        self.snapshots = _SnapshotsAPI(self)
        self.account = _AccountAPI(self)
        self.sessions = _SessionsAPI(self)
        self.events = _EventsAPI(self)
        self.alerts = _AlertsAPI(self)
        self.notifications = _NotificationsAPI(self)
        self.billing = _BillingAPI(self)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "Caged":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise CagedTimeoutError(self._client.timeout.read or DEFAULT_TIMEOUT) from exc

        if response.status_code >= 400:
            body = response.json() if response.content else None
            raise CagedAPIError(response.status_code, body)

        if response.status_code == 204:
            return None
        return response.json()

    def _ws_url(self, path: str) -> str:
        """Build a WebSocket URL with auth token."""
        ws_base = self._base_url.replace("http://", "ws://").replace("https://", "wss://")
        url = f"{ws_base}/v1{path}"
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}token={self._api_key}"


# --- Sandboxes ---


class _SandboxesAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def create(
        self,
        template: str = "minimal",
        cpus: int = 2,
        memory_mb: int = 512,
        **kwargs: Any,
    ) -> Sandbox:
        """Create a new sandbox."""
        params = SandboxCreateParams(template=template, cpus=cpus, memory_mb=memory_mb, **kwargs)
        body = {k: v for k, v in asdict(params).items() if v is not None and v != [] and v != {}}
        data = self._client._request("POST", "/sandboxes", json=body, timeout=DEFAULT_CREATE_TIMEOUT)
        return Sandbox(**{k: v for k, v in data.items() if k in Sandbox.__dataclass_fields__})

    def exec(self, id: str, command: str, timeout: float = DEFAULT_EXEC_TIMEOUT) -> ExecResult:
        """Run a shell command in a sandbox and return its output and exit code."""
        data = self._client._request(
            "POST", f"/sandboxes/{id}/exec", json={"command": command}, timeout=timeout
        )
        return ExecResult(
            output=data.get("output", ""),
            exit_code=data.get("exit_code", 0),
            error=data.get("error") or None,
        )

    async def exec_stream(self, id: str, command: str) -> ExecStream:
        """Run a command with real-time streaming output.

        Returns an async iterable that yields output chunks as they arrive.

        Usage::

            stream = await caged.sandboxes.exec_stream(sandbox.id, "npm test")
            async for chunk in stream:
                print(chunk, end="")
            print(f"Exit code: {stream.exit_code}")
        """
        url = self._client._ws_url(f"/sandboxes/{id}/terminal")
        ws = await websockets.connect(url, subprotocols=["mcp"])
        # Send command once connected.
        await ws.send(json.dumps({"type": "input", "data": command + "\n"}))
        stream = ExecStream(ws)
        await stream._start_listening()
        return stream

    async def terminal(
        self, id: str, rows: int = 24, cols: int = 80
    ) -> TerminalSession:
        """Connect an interactive terminal session to the sandbox.

        Usage::

            terminal = await caged.sandboxes.terminal(sandbox.id)
            terminal.on_output(lambda data: print(data, end=""))
            await terminal.send("ls -la\\n")
            await terminal.close()
        """
        url = self._client._ws_url(f"/sandboxes/{id}/terminal?rows={rows}&cols={cols}")
        ws = await websockets.connect(url, subprotocols=["mcp"])
        session = TerminalSession(ws)
        await session._start_listening()
        return session

    async def mcp(self, id: str) -> MCPClient:
        """Connect to the sandbox via MCP (Model Context Protocol).

        Provides tool calling for filesystem, terminal, git, and network operations.

        Usage::

            mcp = await caged.sandboxes.mcp(sandbox.id)
            tools = await mcp.list_tools()
            result = await mcp.call_tool("filesystem_read", {"path": "package.json"})
            await mcp.close()
        """
        url = self._client._ws_url(f"/sandboxes/{id}/mcp")
        ws = await websockets.connect(url, subprotocols=["mcp"])
        client = MCPClient(ws)
        await client._start_listening()
        await client.initialize()
        return client

    def list(self) -> List[Sandbox]:
        """List all sandboxes for the authenticated account."""
        data = self._client._request("GET", "/sandboxes")
        return [Sandbox(**{k: v for k, v in s.items() if k in Sandbox.__dataclass_fields__}) for s in data]

    def get(self, id: str) -> Sandbox:
        """Get a sandbox by ID."""
        data = self._client._request("GET", f"/sandboxes/{id}")
        return Sandbox(**{k: v for k, v in data.items() if k in Sandbox.__dataclass_fields__})

    def destroy(self, id: str) -> None:
        """Destroy a sandbox."""
        self._client._request("DELETE", f"/sandboxes/{id}")

    def pause(self, id: str) -> None:
        """Pause a running sandbox."""
        self._client._request("POST", f"/sandboxes/{id}/pause")

    def resume(self, id: str) -> None:
        """Resume a paused sandbox."""
        self._client._request("POST", f"/sandboxes/{id}/resume")

    def logs(self, id: str, tail: Optional[int] = None) -> List[LogEntry]:
        """Get sandbox logs (stdout/stderr)."""
        query = f"?tail={tail}" if tail else ""
        data = self._client._request("GET", f"/sandboxes/{id}/logs{query}")
        return [LogEntry(**entry) for entry in data]

    def ports(self, id: str) -> List[Port]:
        """List open ports for a sandbox."""
        data = self._client._request("GET", f"/sandboxes/{id}/ports")
        return [Port(**p) for p in data]

    def trust_scores(self, sandbox_id: str) -> List[TrustScore]:
        """Get trust scores for a sandbox."""
        data = self._client._request("GET", f"/trust/sandboxes/{sandbox_id}")
        return [TrustScore(**s) for s in data]


# --- Files ---


class _FilesAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def list(self, sandbox_id: str, path: str = "/") -> List[FileEntry]:
        """List files in a directory."""
        data = self._client._request("GET", f"/sandboxes/{sandbox_id}/files", params={"path": path})
        return [FileEntry(**f) for f in data]

    def read(self, sandbox_id: str, path: str) -> str:
        """Read file content."""
        return self._client._request("GET", f"/sandboxes/{sandbox_id}/files/content", params={"path": path})

    def write(self, sandbox_id: str, path: str, content: str) -> None:
        """Write content to a file."""
        self._client._request("PUT", f"/sandboxes/{sandbox_id}/files/content", json={"path": path, "content": content})

    def git_diff(self, sandbox_id: str) -> str:
        """Get git diff for the sandbox workspace."""
        return self._client._request("GET", f"/sandboxes/{sandbox_id}/git/diff")


# --- Snapshots ---


class _SnapshotsAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def list(self, sandbox_id: str) -> List[Snapshot]:
        """List snapshots for a sandbox."""
        data = self._client._request("GET", f"/sandboxes/{sandbox_id}/snapshots")
        return [Snapshot(**{k: v for k, v in s.items() if k in Snapshot.__dataclass_fields__}) for s in data]

    def create(self, sandbox_id: str, name: Optional[str] = None, description: Optional[str] = None) -> Snapshot:
        """Create a snapshot of the sandbox workspace."""
        body: Dict[str, Any] = {}
        if name:
            body["name"] = name
        if description:
            body["description"] = description
        data = self._client._request("POST", f"/sandboxes/{sandbox_id}/snapshots", json=body)
        return Snapshot(**{k: v for k, v in data.items() if k in Snapshot.__dataclass_fields__})

    def get(self, snapshot_id: str) -> Snapshot:
        """Get snapshot details."""
        data = self._client._request("GET", f"/snapshots/{snapshot_id}")
        return Snapshot(**{k: v for k, v in data.items() if k in Snapshot.__dataclass_fields__})

    def delete(self, snapshot_id: str) -> None:
        """Delete a snapshot."""
        self._client._request("DELETE", f"/snapshots/{snapshot_id}")

    def download_url(self, snapshot_id: str) -> str:
        """Get a presigned download URL for a snapshot."""
        data = self._client._request("GET", f"/snapshots/{snapshot_id}/download")
        return data["url"]

    def restore(self, snapshot_id: str) -> None:
        """Restore a snapshot into its sandbox."""
        self._client._request("POST", f"/snapshots/{snapshot_id}/restore")


# --- Account ---


class _AccountAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def list_keys(self) -> List[APIKey]:
        """List API keys."""
        data = self._client._request("GET", "/account/keys")
        return [APIKey(**k) for k in data]

    def create_key(self, name: str) -> Dict[str, Any]:
        """Create a new API key. Returns key data including the secret."""
        return self._client._request("POST", "/account/keys", json={"name": name})

    def revoke_key(self, id: str) -> None:
        """Revoke an API key."""
        self._client._request("DELETE", f"/account/keys/{id}")

    def list_sessions(self) -> List[Session]:
        """List active sessions."""
        data = self._client._request("GET", "/account/sessions")
        return [Session(**s) for s in data]

    def revoke_session(self, id: str) -> None:
        """Revoke a session."""
        self._client._request("DELETE", f"/account/sessions/{id}")


# --- Sessions (Agent session history & replay) ---


class _SessionsAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def list_by_sandbox(self, sandbox_id: str) -> List[AgentSession]:
        """List agent sessions for a sandbox."""
        data = self._client._request("GET", f"/sandboxes/{sandbox_id}/sessions")
        return [AgentSession(**{k: v for k, v in s.items() if k in AgentSession.__dataclass_fields__}) for s in data]

    def get(self, session_id: str) -> AgentSession:
        """Get an agent session by ID."""
        data = self._client._request("GET", f"/sessions/{session_id}")
        return AgentSession(**{k: v for k, v in data.items() if k in AgentSession.__dataclass_fields__})

    def replay(self, session_id: str) -> List[ReplayEvent]:
        """Get full replay timeline for a session."""
        data = self._client._request("GET", f"/sessions/{session_id}/replay")
        return [ReplayEvent(**{k: v for k, v in e.items() if k in ReplayEvent.__dataclass_fields__}) for e in data]

    def replay_summary(self, session_id: str) -> ReplaySummary:
        """Get a summary of a session replay (cost, tokens, duration)."""
        data = self._client._request("GET", f"/sessions/{session_id}/replay/summary")
        return ReplaySummary(**{k: v for k, v in data.items() if k in ReplaySummary.__dataclass_fields__})


# --- Events (Observability ingestion) ---


class _EventsAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def ingest(self, events: List[EventPayload]) -> IngestResponse:
        """Ingest observability events. Max 1000 events per batch."""
        body = {"events": [asdict(e) for e in events]}
        data = self._client._request("POST", "/events/ingest", json=body)
        return IngestResponse(**data)


# --- Alerts ---


class _AlertsAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def list(self) -> List[Alert]:
        """List all alerts for the account."""
        data = self._client._request("GET", "/alerts")
        return [Alert(**{k: v for k, v in a.items() if k in Alert.__dataclass_fields__}) for a in data]

    def get(self, id: str) -> Alert:
        """Get an alert by ID."""
        data = self._client._request("GET", f"/alerts/{id}")
        return Alert(**{k: v for k, v in data.items() if k in Alert.__dataclass_fields__})

    def resolve(self, id: str) -> None:
        """Resolve an alert."""
        self._client._request("POST", f"/alerts/{id}/resolve")

    def list_rules(self) -> List[AlertRule]:
        """List alert rules."""
        data = self._client._request("GET", "/alerts/rules")
        return [AlertRule(**{k: v for k, v in r.items() if k in AlertRule.__dataclass_fields__}) for r in data]

    def update_rule(self, id: str, **kwargs: Any) -> AlertRule:
        """Update an alert rule."""
        data = self._client._request("PUT", f"/alerts/rules/{id}", json=kwargs)
        return AlertRule(**{k: v for k, v in data.items() if k in AlertRule.__dataclass_fields__})


# --- Notifications ---


class _NotificationsAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def list(self) -> List[Notification]:
        """List notifications."""
        data = self._client._request("GET", "/notifications")
        return [Notification(**{k: v for k, v in n.items() if k in Notification.__dataclass_fields__}) for n in data]

    def unread_count(self) -> int:
        """Get unread notification count."""
        data = self._client._request("GET", "/notifications/unread-count")
        return data["count"]

    def mark_read(self, id: str) -> None:
        """Mark a notification as read."""
        self._client._request("POST", f"/notifications/{id}/read")

    def mark_all_read(self) -> None:
        """Mark all notifications as read."""
        self._client._request("POST", "/notifications/read-all")

    def get_config(self) -> NotificationConfig:
        """Get notification configuration."""
        data = self._client._request("GET", "/notifications/config")
        return NotificationConfig(**{k: v for k, v in data.items() if k in NotificationConfig.__dataclass_fields__})

    def update_config(self, **kwargs: Any) -> NotificationConfig:
        """Update notification configuration."""
        data = self._client._request("PUT", "/notifications/config", json=kwargs)
        return NotificationConfig(**{k: v for k, v in data.items() if k in NotificationConfig.__dataclass_fields__})


# --- Billing ---


class _BillingAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def get_subscription(self) -> Subscription:
        """Get current subscription details."""
        data = self._client._request("GET", "/billing/subscription")
        return Subscription(**{k: v for k, v in data.items() if k in Subscription.__dataclass_fields__})

    def create_checkout(self, plan: str) -> str:
        """Create a Stripe checkout session. Returns checkout URL."""
        data = self._client._request("POST", "/billing/checkout", json={"plan": plan})
        return data["url"]

    def create_portal(self) -> str:
        """Create a Stripe billing portal session. Returns portal URL."""
        data = self._client._request("POST", "/billing/portal")
        return data["url"]

    def cancel(self) -> None:
        """Cancel the current subscription."""
        self._client._request("POST", "/billing/cancel")

    def restore(self, snapshot_id: str) -> None:
        """Restore a snapshot into its sandbox."""
        self._client._request("POST", f"/snapshots/{snapshot_id}/restore")


class _AccountAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def list_keys(self) -> list[APIKey]:
        """List API keys."""
        data = self._client._request("GET", "/account/keys")
        return [APIKey(**k) for k in data]

    def create_key(self, name: str) -> dict[str, Any]:
        """Create a new API key. Returns the key (only shown once)."""
        return self._client._request("POST", "/account/keys", json={"name": name})

    def revoke_key(self, id: str) -> None:
        """Revoke an API key."""
        self._client._request("DELETE", f"/account/keys/{id}")

    def list_sessions(self) -> list[Session]:
        """List active sessions."""
        data = self._client._request("GET", "/account/sessions")
        return [Session(**s) for s in data]

    def revoke_session(self, id: str) -> None:
        """Revoke a session."""
        self._client._request("DELETE", f"/account/sessions/{id}")
