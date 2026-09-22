"""Caged Python SDK client."""

from __future__ import annotations

import asyncio
import builtins
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from caged import _ws
from caged._version import __version__
from caged.errors import (
    CagedConnectionError,
    CagedError,
    CagedNotFoundError,
    CagedTimeoutError,
    error_for_status,
)
from caged.mcp import MCPClient
from caged.stream import ExecStream
from caged.terminal import TerminalSession
from caged.types import (
    MCPBinding,
    MCPBindResult,
    MCPCatalogueEntry,
    MCPGrantResult,
    MCPInputRequest,
    MCPOAuthAuthorization,
    MCPOAuthConsent,
    MCPOAuthState,
    MCPPolicyAdvice,
    MCPRefreshReport,
    MCPServer,
    MCPServerDetail,
    MCPServerTool,
    MCPToolDiff,
    MCPToolRevision,
    Account,
    AccountSession,
    AgentSession,
    AgentSessionPage,
    Alert,
    AlertPage,
    AlertRule,
    APIKey,
    CreatedAPIKey,
    EventPayload,
    ExecResult,
    FileEntry,
    GitDiff,
    IngestResponse,
    LogEntry,
    Notification,
    NotificationConfig,
    NotificationConfigUpdate,
    NotificationPage,
    Port,
    ReplayPage,
    ReplaySummary,
    RuleConfig,
    Sandbox,
    SandboxCreateParams,
    Snapshot,
    SnapshotDownload,
    SocketTicket,
    Subscription,
    TrustScoreSummary,
    Usage,
)

DEFAULT_BASE_URL = "https://api.caged.dev"
DEFAULT_TIMEOUT = 30.0

# Command execution can include long-running agent prompts.
DEFAULT_EXEC_TIMEOUT = 300.0

# Sandbox creation can include a repo clone and agent installs.
DEFAULT_CREATE_TIMEOUT = 360.0

_UNSET = object()


class Caged:
    """Caged SDK client.

    Usage::

        from caged import Caged

        with Caged(api_key=os.environ["CAGED_API_KEY"]) as caged:
            sandbox = caged.sandboxes.create(template="node-20")
            print(sandbox.id, sandbox.status)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise CagedError("api_key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=f"{self._base_url}/v1",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": f"caged-python/{__version__}",
            },
            # Every external call is bounded; per-call overrides are passed
            # explicitly by the methods that need a longer budget.
            timeout=timeout,
            transport=transport,
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
        self.mcp = _MCPAPI(self)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> Caged:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # --- transport ---

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = _UNSET,
        timeout: float | None = None,
    ) -> httpx.Response:
        effective_timeout = self._timeout if timeout is None else timeout
        kwargs: dict[str, Any] = {"timeout": effective_timeout}
        if params is not None:
            kwargs["params"] = {k: v for k, v in params.items() if v is not None}
        if json is not _UNSET:
            kwargs["json"] = json

        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise CagedTimeoutError(effective_timeout) from exc
        except httpx.HTTPError as exc:
            raise CagedConnectionError(
                f"{method} {path} failed before a response arrived: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise error_for_status(
                response.status_code, _try_json(response), response.text
            )
        return response

    def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        """Perform a request whose response body is JSON."""
        response = self._send(method, path, **kwargs)
        if not response.content:
            raise CagedError(
                f"{method} {path} returned {response.status_code} with an empty body "
                "where JSON was expected"
            )
        try:
            return response.json()
        except ValueError as exc:
            content_type = response.headers.get("content-type", "none")
            raise CagedError(
                f"{method} {path} returned {response.status_code} with a body that is "
                f"not JSON (content-type: {content_type})"
            ) from exc

    def _request_text(self, method: str, path: str, **kwargs: Any) -> str:
        """Perform a request whose response body is plain text."""
        return self._send(method, path, **kwargs).text

    def _request_none(self, method: str, path: str, **kwargs: Any) -> None:
        """Perform a request whose response body is discarded."""
        self._send(method, path, **kwargs)

    # --- websockets ---

    def socket_ticket(self) -> SocketTicket:
        """Mint a short-lived, single-use credential for one WebSocket.

        The browser API cannot set headers on a WebSocket handshake, so the
        credential has to ride in the URL — and a URL reaches every proxy
        that logs a request line. The API therefore issues tickets that
        expire in a minute and are refused anywhere but a handshake.
        """
        return SocketTicket.from_api(self._request_json("POST", "/auth/socket-ticket"))

    async def _socket_token(self) -> str:
        """Return the credential to put in a WebSocket handshake URL.

        Prefers a ticket. Falls back to the API key when the API does not
        serve the ticket endpoint — a deployment older than the endpoint
        would otherwise lose every socket — which is what this SDK always
        did, and what the server logs a warning about.
        """
        try:
            ticket = await asyncio.to_thread(self.socket_ticket)
        except CagedNotFoundError:
            return self._api_key
        return ticket.ticket or self._api_key

    async def _ws_connect(
        self, path: str, subprotocol: str, params: Mapping[str, Any] | None = None
    ) -> _ws.WebSocketLike:
        token = await self._socket_token()
        query = dict(params or {})
        query["token"] = token
        ws_base = self._base_url.replace("https://", "wss://").replace(
            "http://", "ws://"
        )
        url = f"{ws_base}/v1{path}?{urlencode(query)}"
        return await _ws.connect(url, subprotocol)


def _try_json(response: httpx.Response) -> Any:
    if not response.content:
        return None
    if "json" not in response.headers.get("content-type", ""):
        return None
    try:
        return response.json()
    except ValueError:
        return None


class _SandboxesAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def create(self, template: str = "minimal", **kwargs: Any) -> Sandbox:
        """Create a new sandbox.

        ``template`` is required by the API. Any other field of
        :class:`~caged.types.SandboxCreateParams` may be passed as a keyword;
        unset fields are omitted from the request body so the server's own
        defaults apply.
        """
        if not template:
            raise CagedError("template is required to create a sandbox")
        try:
            params = SandboxCreateParams(template=template, **kwargs)
        except TypeError as exc:
            raise CagedError(f"unknown sandbox create parameter: {exc}") from exc
        body = {
            k: v
            for k, v in asdict(params).items()
            if v is not None and v != [] and v != {}
        }
        data = self._client._request_json(
            "POST", "/sandboxes", json=body, timeout=DEFAULT_CREATE_TIMEOUT
        )
        return Sandbox.from_api(data)

    def exec(
        self, id: str, command: str, timeout: float = DEFAULT_EXEC_TIMEOUT
    ) -> ExecResult:
        """Run a shell command in a sandbox and return its output and exit code.

        Supports pipes and redirects. A non-zero exit code does not raise;
        check ``result.ok`` or ``result.exit_code``.

        Usage::

            result = caged.sandboxes.exec(sandbox.id, 'claude -p "explain this repo"')
            print(result.output)
        """
        data = self._client._request_json(
            "POST",
            f"/sandboxes/{_seg(id)}/exec",
            json={"command": command},
            timeout=timeout,
        )
        return ExecResult.from_api(data)

    async def exec_stream(self, id: str, command: str) -> ExecStream:
        """Run a command with real-time streaming output.

        Returns an async iterable that yields output chunks as they arrive
        and carries the command's exit code once it has finished.

        Usage::

            stream = await caged.sandboxes.exec_stream(sandbox.id, "npm test")
            async for chunk in stream:
                print(chunk, end="")
            print(f"Exit code: {stream.exit_code}")
        """
        ws = await self._client._ws_connect(
            f"/sandboxes/{_seg(id)}/terminal", "terminal"
        )
        stream = ExecStream(ws)
        await stream._start(command)
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
        ws = await self._client._ws_connect(
            f"/sandboxes/{_seg(id)}/terminal",
            "terminal",
            {"rows": rows, "cols": cols},
        )
        session = TerminalSession(ws)
        await session._start_listening()
        return session

    async def mcp(self, id: str) -> MCPClient:
        """Connect to the sandbox via MCP (Model Context Protocol).

        Provides tool calling for filesystem, terminal, git and network
        operations. The sandbox must be running.

        Usage::

            mcp = await caged.sandboxes.mcp(sandbox.id)
            tools = await mcp.list_tools()
            result = await mcp.call_tool("filesystem_read", {"path": "package.json"})
            await mcp.close()
        """
        ws = await self._client._ws_connect(f"/sandboxes/{_seg(id)}/mcp", "mcp")
        client = MCPClient(ws)
        await client._start_listening()
        await client.initialize()
        return client

    def list(self) -> builtins.list[Sandbox]:
        """List all sandboxes for the authenticated account."""
        return Sandbox.list_from_api(self._client._request_json("GET", "/sandboxes"))

    def get(self, id: str) -> Sandbox:
        """Get a sandbox by ID."""
        return Sandbox.from_api(
            self._client._request_json("GET", f"/sandboxes/{_seg(id)}")
        )

    def destroy(self, id: str) -> None:
        """Destroy (permanently delete) a sandbox."""
        self._client._request_none("DELETE", f"/sandboxes/{_seg(id)}")

    def pause(self, id: str) -> None:
        """Pause a running sandbox."""
        self._client._request_none("POST", f"/sandboxes/{_seg(id)}/pause")

    def resume(self, id: str) -> None:
        """Resume a paused sandbox."""
        self._client._request_none("POST", f"/sandboxes/{_seg(id)}/resume")

    def ports(self, id: str) -> builtins.list[Port]:
        """List open ports for a sandbox."""
        return Port.list_from_api(
            self._client._request_json("GET", f"/sandboxes/{_seg(id)}/ports")
        )

    def logs(self, id: str, tail: int | None = None) -> builtins.list[LogEntry]:
        """Fetch recent lifecycle log entries for a sandbox.

        ``tail`` is a line count; the API clamps it to its own ceiling.
        """
        return LogEntry.list_from_api(
            self._client._request_json(
                "GET", f"/sandboxes/{_seg(id)}/logs", params={"tail": tail}
            )
        )

    def trust_scores(self, sandbox_id: str) -> builtins.list[TrustScoreSummary]:
        """Trust scores for every agent session run in a sandbox.

        ``score`` is an integer out of 100.
        """
        return TrustScoreSummary.list_from_api(
            self._client._request_json("GET", f"/trust/sandboxes/{_seg(sandbox_id)}")
        )


class _FilesAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def list(
        self, sandbox_id: str, path: str = "/workspace"
    ) -> builtins.list[FileEntry]:
        """List files in a directory (default: ``/workspace``)."""
        return FileEntry.list_from_api(
            self._client._request_json(
                "GET", f"/sandboxes/{_seg(sandbox_id)}/files", params={"path": path}
            )
        )

    def read(self, sandbox_id: str, path: str) -> str:
        """Read file content.

        The endpoint answers ``text/plain``, so the file's bytes come back
        as a string rather than being parsed as JSON. Files over 1MB are
        rejected by the API.
        """
        return self._client._request_text(
            "GET",
            f"/sandboxes/{_seg(sandbox_id)}/files/content",
            params={"path": path},
        )

    def write(self, sandbox_id: str, path: str, content: str) -> None:
        """Write content to a file.

        The target path travels in the query string — that is where the API
        reads it from — and only the content is sent in the body.
        """
        self._client._request_none(
            "PUT",
            f"/sandboxes/{_seg(sandbox_id)}/files/content",
            params={"path": path},
            json={"content": content},
        )

    def git_diff(self, sandbox_id: str, path: str | None = None) -> GitDiff:
        """Git status and diff for a working tree (default: ``/workspace``)."""
        return GitDiff.from_api(
            self._client._request_json(
                "GET", f"/sandboxes/{_seg(sandbox_id)}/git/diff", params={"path": path}
            )
        )


class _SnapshotsAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def list(self, sandbox_id: str) -> builtins.list[Snapshot]:
        """List snapshots for a sandbox."""
        return Snapshot.list_from_api(
            self._client._request_json(
                "GET", f"/sandboxes/{_seg(sandbox_id)}/snapshots"
            )
        )

    def create(
        self,
        sandbox_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> Snapshot:
        """Create a snapshot of the sandbox workspace."""
        body: dict[str, Any] = {}
        if name:
            body["name"] = name
        if description:
            body["description"] = description
        return Snapshot.from_api(
            self._client._request_json(
                "POST", f"/sandboxes/{_seg(sandbox_id)}/snapshots", json=body
            )
        )

    def get(self, snapshot_id: str) -> Snapshot:
        """Get snapshot details."""
        return Snapshot.from_api(
            self._client._request_json("GET", f"/snapshots/{_seg(snapshot_id)}")
        )

    def delete(self, snapshot_id: str) -> None:
        """Delete a snapshot."""
        self._client._request_none("DELETE", f"/snapshots/{_seg(snapshot_id)}")

    def download(self, snapshot_id: str) -> SnapshotDownload:
        """Get a download URL for a snapshot, with its expiry."""
        return SnapshotDownload.from_api(
            self._client._request_json(
                "GET", f"/snapshots/{_seg(snapshot_id)}/download"
            )
        )

    def download_url(self, snapshot_id: str) -> str:
        """Get just the download URL for a snapshot.

        .. deprecated:: 0.3.0
           Use :meth:`download`, which also returns the expiry. This
           wrapper stays until at least 0.5.0.
        """
        _deprecated(
            "Caged.snapshots.download_url() is deprecated; use "
            "Caged.snapshots.download(), which also returns the expiry"
        )
        return self.download(snapshot_id).url

    def restore(self, snapshot_id: str, target_sandbox_id: str) -> None:
        """Restore a snapshot into a sandbox.

        ``target_sandbox_id`` is required: a snapshot is restored into a
        sandbox the caller names, not into the one it was taken from.
        """
        if not target_sandbox_id:
            raise CagedError("target_sandbox_id is required to restore a snapshot")
        self._client._request_none(
            "POST",
            f"/snapshots/{_seg(snapshot_id)}/restore",
            json={"target_sandbox_id": target_sandbox_id},
        )


class _AccountAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def get(self) -> Account:
        """Get the authenticated account."""
        return Account.from_api(self._client._request_json("GET", "/account"))

    def list_keys(self) -> builtins.list[APIKey]:
        """List API keys."""
        return APIKey.list_from_api(self._client._request_json("GET", "/account/keys"))

    def create_key(self, name: str, scope: str = "full") -> CreatedAPIKey:
        """Create a new API key.

        The secret is in ``result.key`` and is never returned again; the
        metadata is in ``result.info``. ``scope`` is "full" or "read_only".
        """
        return CreatedAPIKey.from_api(
            self._client._request_json(
                "POST", "/account/keys", json={"name": name, "scope": scope}
            )
        )

    def revoke_key(self, id: str) -> None:
        """Revoke an API key."""
        self._client._request_none("DELETE", f"/account/keys/{_seg(id)}")

    def list_sessions(self) -> builtins.list[AccountSession]:
        """List active dashboard sessions."""
        return AccountSession.list_from_api(
            self._client._request_json("GET", "/account/sessions")
        )

    def revoke_session(self, id: str) -> None:
        """Revoke a dashboard session."""
        self._client._request_none("DELETE", f"/account/sessions/{_seg(id)}")


class _SessionsAPI:
    """Agent session history and replay."""

    def __init__(self, client: Caged) -> None:
        self._client = client

    def list_by_sandbox(self, sandbox_id: str) -> builtins.list[AgentSession]:
        """List agent sessions for one sandbox."""
        return AgentSession.list_from_api(
            self._client._request_json("GET", f"/sandboxes/{_seg(sandbox_id)}/sessions")
        )

    def list(self, page: int = 1, per_page: int | None = None) -> AgentSessionPage:
        """List every agent session in the account, newest first.

        Paginated: the sessions are in ``result.data`` and the position in
        ``result.pagination``.
        """
        return AgentSessionPage.from_api(
            self._client._request_json(
                "GET", "/sessions", params={"page": page, "per_page": per_page}
            )
        )

    def get(self, session_id: str) -> AgentSession:
        """Get an agent session by ID."""
        return AgentSession.from_api(
            self._client._request_json("GET", f"/sessions/{_seg(session_id)}")
        )

    def replay(
        self,
        session_id: str,
        after_seq: int | None = None,
        limit: int | None = None,
        type: str | None = None,
    ) -> ReplayPage:
        """Fetch a page of a session's replay timeline.

        The endpoint answers an object, not a bare array: the events are in
        ``result.events``, and while ``result.has_more`` is true the next
        page starts at ``after_seq=result.next_seq``. ``limit`` is clamped
        to 1000 by the API.
        """
        return ReplayPage.from_api(
            self._client._request_json(
                "GET",
                f"/sessions/{_seg(session_id)}/replay",
                params={"after_seq": after_seq, "limit": limit, "type": type},
            )
        )

    def replay_summary(self, session_id: str) -> ReplaySummary:
        """Event counts and wall-clock duration for a session's replay.

        Tokens and cost are on :class:`~caged.types.AgentSession`, not here.
        """
        return ReplaySummary.from_api(
            self._client._request_json(
                "GET", f"/sessions/{_seg(session_id)}/replay/summary"
            )
        )


class _EventsAPI:
    """Observability event ingestion."""

    def __init__(self, client: Caged) -> None:
        self._client = client

    def ingest(self, events: builtins.list[EventPayload]) -> IngestResponse:
        """Ingest observability events. Max 1000 events per batch.

        The account is taken from the API key; an ``account_id`` on an event
        is ignored by the server.
        """
        if len(events) > 1000:
            raise CagedError(
                f"batch too large: {len(events)} events, the API accepts at most 1000"
            )
        body = {"events": [e.to_api() for e in events]}
        return IngestResponse.from_api(
            self._client._request_json("POST", "/events/ingest", json=body)
        )


class _AlertsAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def list(self, limit: int | None = None, offset: int | None = None) -> AlertPage:
        """List alerts for the account, newest first.

        The alerts are in ``result.alerts`` and the account's total in
        ``result.total``. ``limit`` must be 1-100; the API serves 50 for
        anything outside that.
        """
        return AlertPage.from_api(
            self._client._request_json(
                "GET", "/alerts", params={"limit": limit, "offset": offset}
            )
        )

    def get(self, id: str) -> Alert:
        """Get an alert by ID."""
        return Alert.from_api(self._client._request_json("GET", f"/alerts/{_seg(id)}"))

    def resolve(self, id: str) -> None:
        """Resolve an alert."""
        self._client._request_none("POST", f"/alerts/{_seg(id)}/resolve")

    def list_rules(self) -> builtins.list[AlertRule]:
        """List the account's alert rules."""
        return AlertRule.list_from_api(
            self._client._request_json("GET", "/alerts/rules")
        )

    def update_rule(
        self,
        id: str,
        enabled: bool | None = None,
        config: RuleConfig | None = None,
    ) -> AlertRule:
        """Enable, disable or retune an alert rule.

        Only what is passed is changed. The endpoint accepts exactly these
        two fields; a rule's type is fixed.
        """
        body: dict[str, Any] = {}
        if enabled is not None:
            body["enabled"] = enabled
        if config is not None:
            body["config"] = config.to_api()
        if not body:
            raise CagedError("update_rule needs enabled or config")
        return AlertRule.from_api(
            self._client._request_json("PUT", f"/alerts/rules/{_seg(id)}", json=body)
        )


class _NotificationsAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def list(
        self, unread_only: bool = False, limit: int | None = None
    ) -> NotificationPage:
        """List notifications.

        The notifications are in ``result.notifications`` and the unread
        badge count in ``result.unread_count``. ``limit`` must be 1-100.
        """
        params: dict[str, Any] = {"limit": limit}
        if unread_only:
            params["unread"] = "true"
        return NotificationPage.from_api(
            self._client._request_json("GET", "/notifications", params=params)
        )

    def list_unread(self, limit: int | None = None) -> builtins.list[Notification]:
        """The unread notifications only, as a plain list."""
        return self.list(unread_only=True, limit=limit).notifications

    def unread_count(self) -> int:
        """Count unread notifications.

        The endpoint answers ``{"unread_count": n}``; the key is not
        ``count``.
        """
        data = self._client._request_json("GET", "/notifications/unread-count")
        if not isinstance(data, Mapping) or "unread_count" not in data:
            raise CagedError(
                "GET /notifications/unread-count did not return an unread_count"
            )
        return int(data["unread_count"])

    def mark_read(self, id: str) -> None:
        """Mark one notification as read."""
        self._client._request_none("POST", f"/notifications/{_seg(id)}/read")

    def mark_all_read(self) -> None:
        """Mark every notification as read."""
        self._client._request_none("POST", "/notifications/read-all")

    def get_config(self) -> NotificationConfig:
        """Get the account's notification channel configuration.

        Credentials are never returned; each is reported as a
        ``*_configured`` boolean with a hint.
        """
        return NotificationConfig.from_api(
            self._client._request_json("GET", "/notifications/config")
        )

    def update_config(self, update: NotificationConfigUpdate) -> NotificationConfig:
        """Update the account's notification channel configuration.

        An omitted webhook URL is left as it is; pass
        :data:`~caged.types.CLEAR_CREDENTIAL` to remove one.
        """
        return NotificationConfig.from_api(
            self._client._request_json(
                "PUT", "/notifications/config", json=update.to_api()
            )
        )


class _BillingAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def get_subscription(self) -> Subscription:
        """Get the account's subscription. ``tier`` is the plan name."""
        return Subscription.from_api(
            self._client._request_json("GET", "/billing/subscription")
        )

    def get_usage(self) -> Usage:
        """Get metered compute time for the current billing period."""
        return Usage.from_api(self._client._request_json("GET", "/billing/usage"))

    def create_checkout(self, plan: str) -> str:
        """Create a Stripe Checkout session and return its URL.

        ``plan`` is "pro" or "team". It travels as ``plan_id``, which is the
        field the endpoint reads.
        """
        if not plan:
            raise CagedError("plan is required; it is 'pro' or 'team'")
        data = self._client._request_json(
            "POST", "/billing/checkout", json={"plan_id": plan}
        )
        return _url_from(data, "POST /billing/checkout")

    def create_portal(self) -> str:
        """Create a Stripe billing portal session and return its URL."""
        data = self._client._request_json("POST", "/billing/portal", json={})
        return _url_from(data, "POST /billing/portal")

    def cancel(self) -> None:
        """Cancel the subscription at the end of the current period."""
        self._client._request_none("POST", "/billing/cancel")


def _url_from(data: Any, what: str) -> str:
    if not isinstance(data, Mapping) or not isinstance(data.get("url"), str):
        raise CagedError(f"{what} did not return a url")
    return str(data["url"])


def _seg(value: str) -> str:
    """Quote a value for use as a single URL path segment."""
    return quote(str(value), safe="")


def _deprecated(message: str) -> None:
    warnings.warn(message, DeprecationWarning, stacklevel=3)


class _MCPAPI:
    """``client.mcp`` — third-party MCP servers an agent in a sandbox can use.

    Two facts about this surface are worth reading before the methods, because
    each is the difference between a working setup and a silent one, and neither
    is visible from a successful HTTP response:

    **Binding a server does not make its tools callable.** Caged's
    autonomy-tier table classifies its *own* tool names — ``filesystem_read``,
    ``terminal_exec``, ``git_push``. A brokered name like ``github__get_issue``
    matches none of them, so it is unclassified, and an unclassified tool is
    denied at **every** tier including ``autonomous``. That default is
    deliberate: Caged cannot know whether a stranger's tool reads an issue or
    wires money.

    :meth:`bind` returns the advice on its result, ``allow_tools=True`` writes
    the rule in the same request, :meth:`allow` writes it later, and
    :meth:`readiness` answers for every bound server at once.

    **A ``quarantined`` tool is a definition that CHANGED** since a human
    approved it. Caged hashes every tool definition at refresh and holds a
    changed one, so a server that is benign on Monday and poisoned on Tuesday
    becomes a review rather than a silent compromise. :meth:`tool_diff` shows
    the approved definition beside the current one; approving without reading it
    is the outcome the mechanism exists to prevent.

    Nothing here returns a credential or a token. The models have no field for
    one.
    """

    def __init__(self, client: Caged) -> None:
        self._client = client
        self.servers = _MCPServersAPI(client)
        self.bindings = _MCPBindingsAPI(client)
        self.oauth = _MCPOAuthAPI(client)
        self.inputs = _MCPInputsAPI(client)

    # --- shortcuts, because these are the three an operator reaches for ---

    def catalogue(self) -> builtins.list[MCPCatalogueEntry]:
        """List the servers Caged has reviewed.

        A server registered from this catalogue is ``verified`` and its tools
        arrive usable. One registered from an arbitrary URL is not, and its
        tools are held for review.
        """
        data = self._client._request_json("GET", "/mcp/catalogue")
        if isinstance(data, Mapping):
            data = data.get("servers")
        return MCPCatalogueEntry.list_from_api(data)

    def bind(
        self,
        server_id: str,
        persona_id: str | None = None,
        tools: Sequence[str] | None = None,
        deny: Sequence[str] | None = None,
        pinned: bool = False,
        argument_ceiling_bytes: int = 0,
        allow_tools: bool = False,
    ) -> MCPBindResult:
        """Make a server's tools visible to a subject.

        ``persona_id`` ``None`` binds at the account, which every persona sees.

        ``allow_tools`` also writes the policy rule that makes those tools
        callable. It defaults to ``False`` on purpose: binding a server and
        granting its tools are two decisions, and folding them together by
        default would make "I bound it to look at its catalogue" mean "I allowed
        it". What was wrong before was not that the grant was separate — it was
        that it was invisible, which is why the RESULT always carries
        :attr:`MCPBindResult.policy_advice`.
        """
        return self.bindings.create(
            server_id,
            persona_id=persona_id,
            tools=tools,
            deny=deny,
            pinned=pinned,
            argument_ceiling_bytes=argument_ceiling_bytes,
            allow_tools=allow_tools,
        )

    def unbind(self, binding_id: str) -> None:
        """Remove a binding. It takes effect on the agent's next ``tools/list``."""
        self.bindings.delete(binding_id)

    def tools(self, server_id: str) -> builtins.list[MCPServerTool]:
        """The pinned tool catalogue for one server, as an agent sees it."""
        return self.servers.get(server_id).tools

    def readiness(self, persona_id: str | None = None) -> builtins.list[MCPPolicyAdvice]:
        """Whether policy will allow each bound server's tools for a persona.

        This is the call to make when brokered calls are being refused and it is
        not obvious why. Every entry carries a ``status`` from a closed set, the
        deciding rule, and a ``remedy``.

        ``status`` is never reported as ``allowed`` when the answer could not be
        determined: an unresolvable policy is ``unknown``, because a readiness
        screen that renders a resolution failure as a green tick is worse than
        one that renders nothing.
        """
        params = {"persona_id": persona_id} if persona_id else None
        data = self._client._request_json("GET", "/mcp/readiness", params=params)
        if isinstance(data, Mapping):
            data = data.get("servers")
        return MCPPolicyAdvice.list_from_api(data)

    def advice(self, server_id: str, persona_id: str | None = None) -> MCPPolicyAdvice:
        """Whether policy will allow one server's tools for a persona."""
        params = {"persona_id": persona_id} if persona_id else None
        return MCPPolicyAdvice.from_api(
            self._client._request_json(
                "GET", f"/mcp/servers/{_seg(server_id)}/advice", params=params
            )
        )

    def allow(self, server_id: str, persona_id: str) -> MCPGrantResult:
        """Write the one policy rule that makes a server's tools callable.

        The rule is ``allow tool <alias>__*`` at glob priority: above the
        catch-all deny and **below** every always-on guardrail, so allowing an
        external server can never override the secret-path or private-network
        rules.

        ``persona_id`` is required, and not as an oversight. Caged's account
        policy layer is restriction-only — it decides only on an explicit deny or
        pause and otherwise allows by default — so an allow rule written there
        would be stored, displayed, and have no effect whatsoever.

        If the persona has no stored policy, Caged creates one as an exact copy
        of its tier template plus this rule, and says so in
        :attr:`MCPGrantResult.policy_created`. A policy containing only the allow
        rule would silently drop every guardrail the template carries, because a
        stored persona policy *replaces* the template rather than layering over
        it.

        Idempotent: a second call reports :attr:`MCPGrantResult.already_present`.
        """
        if not persona_id:
            raise CagedError(
                "persona_id is required: an allow rule for an external MCP server lives "
                "on a persona's policy, because Caged's account policy layer can only "
                "restrict and never grant"
            )
        return MCPGrantResult.from_api(
            self._client._request_json(
                "POST",
                f"/mcp/servers/{_seg(server_id)}/allow",
                json={"persona_id": persona_id},
            )
        )

    def disallow(self, server_id: str, persona_id: str) -> None:
        """Remove the rule Caged wrote.

        Only that rule. A rule you wrote yourself that happens to allow the same
        pattern is left alone — deleting somebody else's rule for looking like
        ours turns an undo into an outage.
        """
        if not persona_id:
            raise CagedError("persona_id is required")
        self._client._request_none(
            "DELETE",
            f"/mcp/servers/{_seg(server_id)}/allow",
            params={"persona_id": persona_id},
        )

    def tool_diff(self, server_id: str, tool: str) -> MCPToolDiff:
        """The definition a human approved, beside the one being advertised now.

        Read this before :meth:`approve_tool`. A review with one side is a
        consent dialog with the text removed, and it trains a reviewer to click
        approve.
        """
        return MCPToolDiff.from_api(
            self._client._request_json(
                "GET", f"/mcp/servers/{_seg(server_id)}/tools/{_seg(tool)}/diff"
            )
        )

    def tool_revisions(self, server_id: str, tool: str) -> builtins.list[MCPToolRevision]:
        """Every definition this server has advertised for this tool.

        Keyed by digest, so a server that reverts to a previously approved
        definition produces no second review, and a rejection survives a server
        re-advertising the same bytes on a loop.
        """
        data = self._client._request_json(
            "GET", f"/mcp/servers/{_seg(server_id)}/tools/{_seg(tool)}/revisions"
        )
        if isinstance(data, Mapping):
            data = data.get("revisions")
        return MCPToolRevision.list_from_api(data)

    def approve_tool(self, server_id: str, tool: str) -> None:
        """Release a pending or quarantined tool.

        Refused with a conflict if the definition carries an ``injection`` or
        ``shadowing`` flag: approving prompt-injected metadata is the exact
        outcome the mechanism exists to prevent, so it is not one click.
        """
        self._client._request_none(
            "POST", f"/mcp/servers/{_seg(server_id)}/tools/{_seg(tool)}/approve"
        )

    def reject_tool(self, server_id: str, tool: str, note: str = "") -> None:
        """Refuse a held definition, durably.

        The tool stays unavailable to every agent, and the refusal is recorded
        against this exact definition — so a server re-advertising the same bytes
        does not re-open the review.
        """
        self._client._request_none(
            "POST",
            f"/mcp/servers/{_seg(server_id)}/tools/{_seg(tool)}/reject",
            json={"note": note},
        )


class _MCPServersAPI:
    """``client.mcp.servers`` — registrations."""

    def __init__(self, client: Caged) -> None:
        self._client = client

    def add(
        self,
        alias: str | None = None,
        endpoint: str | None = None,
        catalogue_id: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
        auth_kind: str | None = None,
        credential: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> MCPServer:
        """Register a third-party MCP server.

        Registering makes a server **known**. It is visible to nothing until it
        is bound, and its tools are denied by policy until a rule allows them:
        the default visible set for an agent is empty, and that is the design
        rather than a safety net.

        ``credential`` is sealed by the API immediately and is never returned by
        any read. ``auth_kind="oauth"`` stores no credential at all — the token
        comes from a human completing the consent flow in
        :attr:`_MCPAPI.oauth`, and the result's
        :attr:`MCPServer.oauth_next_step` names it.
        """
        if not catalogue_id and not endpoint:
            raise CagedError(
                "one of catalogue_id or endpoint is required; "
                "client.mcp.catalogue() lists the reviewed servers"
            )
        body: dict[str, Any] = {}
        for key, value in (
            ("alias", alias),
            ("endpoint", endpoint),
            ("catalogue_id", catalogue_id),
            ("display_name", display_name),
            ("description", description),
            ("auth_kind", auth_kind),
            ("credential", credential),
        ):
            if value:
                body[key] = value
        if headers:
            body["headers"] = dict(headers)
            body.setdefault("auth_kind", "header")
        if credential and "auth_kind" not in body:
            body["auth_kind"] = "bearer"
        return MCPServer.from_api(
            self._client._request_json("POST", "/mcp/servers", json=body)
        )

    def list(self) -> builtins.list[MCPServer]:
        """List the account's registrations."""
        data = self._client._request_json("GET", "/mcp/servers")
        if isinstance(data, Mapping):
            data = data.get("servers")
        return MCPServer.list_from_api(data)

    def get(self, server_id: str) -> MCPServerDetail:
        """One registration and its pinned tool catalogue."""
        return MCPServerDetail.from_api(
            self._client._request_json("GET", f"/mcp/servers/{_seg(server_id)}")
        )

    def remove(self, server_id: str) -> None:
        """Deregister a server, its catalogue and every binding to it."""
        self._client._request_none("DELETE", f"/mcp/servers/{_seg(server_id)}")

    def refresh(self, server_id: str) -> MCPRefreshReport:
        """Re-fetch the server's tool catalogue and report what changed.

        A definition whose digest differs from the stored one is
        **quarantined**, not merged: it is advertised to no agent and fails the
        gate until a human decides. Read
        :attr:`MCPRefreshReport.quarantined` and then
        :meth:`_MCPAPI.tool_diff`.
        """
        return MCPRefreshReport.from_api(
            self._client._request_json("POST", f"/mcp/servers/{_seg(server_id)}/refresh")
        )


class _MCPBindingsAPI:
    """``client.mcp.bindings`` — who sees which server."""

    def __init__(self, client: Caged) -> None:
        self._client = client

    def create(
        self,
        server_id: str,
        persona_id: str | None = None,
        tools: Sequence[str] | None = None,
        deny: Sequence[str] | None = None,
        pinned: bool = False,
        argument_ceiling_bytes: int = 0,
        allow_tools: bool = False,
    ) -> MCPBindResult:
        """Bind a server to a persona, or to the account."""
        body: dict[str, Any] = {
            "server_id": server_id,
            "subject_kind": "persona" if persona_id else "account",
        }
        if persona_id:
            body["subject_id"] = persona_id
        if tools:
            body["tool_allowlist"] = list(tools)
        if deny:
            body["tool_denylist"] = list(deny)
        if pinned:
            body["pinned"] = True
        if argument_ceiling_bytes:
            body["argument_ceiling_bytes"] = argument_ceiling_bytes
        if allow_tools:
            # Omitted rather than sent as false, so a server that ever changes
            # its default is not overridden by a client that did not mean to.
            body["allow_tools"] = True
        return MCPBindResult.from_api(
            self._client._request_json("POST", "/mcp/bindings", json=body)
        )

    def list(self) -> builtins.list[MCPBinding]:
        """List the account's bindings."""
        data = self._client._request_json("GET", "/mcp/bindings")
        if isinstance(data, Mapping):
            data = data.get("bindings")
        return MCPBinding.list_from_api(data)

    def delete(self, binding_id: str) -> None:
        """Remove a binding."""
        self._client._request_none("DELETE", f"/mcp/bindings/{_seg(binding_id)}")


class _MCPOAuthAPI:
    """``client.mcp.oauth`` — authorizing a server, consent first.

    The order of these three calls **is** the security property, so they are
    three calls rather than one:

    1. :meth:`show` — read-only. Says which authorization server a browser would
       be sent to and which scopes are being asked for. Mints nothing.
    2. :meth:`consent` — records the human decision. Forwards nothing.
    3. :meth:`authorize` — requires a live consent, and only then mints a
       single-use state and returns the URL to open.

    One call that discovered, minted and redirected would be a side-effecting
    action reachable by anybody who could make an authenticated operator's
    browser visit it: a real authorization flow attributed to that operator,
    against a server they never chose, for scopes they never read. Caged is a
    proxy holding credentials for many upstreams on behalf of many subjects,
    which is the exact position that attack is described from.

    Caged holds the resulting token itself: sealed at rest, never written into a
    sandbox, never in an environment variable, and never returned by any read.
    """

    def __init__(self, client: Caged) -> None:
        self._client = client

    def show(self, server_id: str) -> MCPOAuthState:
        """What is authorized, and what authorizing would involve.

        Read-only. If discovery fails,
        :attr:`MCPOAuthState.discovery_error` is set and
        :attr:`MCPOAuthState.status` is still real: what is authorized remains
        true when a third party's metadata endpoint is down.
        """
        return MCPOAuthState.from_api(
            self._client._request_json("GET", f"/mcp/servers/{_seg(server_id)}/oauth")
        )

    def consent(
        self,
        server_id: str,
        issuer: str,
        scopes: Sequence[str],
        persona_id: str | None = None,
    ) -> MCPOAuthConsent:
        """Record the human decision. Nothing is forwarded to the third party.

        ``persona_id`` ``None`` records an ACCOUNT-wide consent, which is a real
        and different decision: making an operator record the same one per
        persona is how a consent record becomes a rubber stamp. A persona's own
        consent outranks the account-wide one.

        Show :attr:`MCPOAuthProspect.consent_statement` to the human first. A
        consent recorded from a discovered value nobody read is not a consent.
        """
        if not issuer:
            raise CagedError(
                "issuer is required: a consent names the authorization server it is for, "
                "and a server that later names a different one needs a new consent"
            )
        body: dict[str, Any] = {
            "approve": True,
            "issuer": issuer,
            "scopes": list(scopes),
        }
        if persona_id:
            # Omitted rather than sent empty: the API reads an empty string as a
            # malformed UUID, not as "account-wide".
            body["persona_id"] = persona_id
        data = self._client._request_json(
            "POST", f"/mcp/servers/{_seg(server_id)}/oauth/consent", json=body
        )
        if isinstance(data, Mapping) and "consent" in data:
            data = data["consent"]
        return MCPOAuthConsent.from_api(data or {})

    def authorize(self, server_id: str, persona_id: str | None = None) -> MCPOAuthAuthorization:
        """The URL to open. Requires a recorded consent.

        Raises a conflict when no live consent covers this subject — that
        refusal is the confused-deputy mitigation, not a missing feature — and
        when the recorded consent does not cover a scope the server now
        requires, naming the missing scope.
        """
        body: dict[str, Any] = {}
        if persona_id:
            body["persona_id"] = persona_id
        return MCPOAuthAuthorization.from_api(
            self._client._request_json(
                "POST", f"/mcp/servers/{_seg(server_id)}/oauth/authorize", json=body
            )
        )

    def forget(self, server_id: str) -> None:
        """Delete the stored token.

        The consent is kept: disconnecting and withdrawing permission are
        different decisions, and conflating them would make a reconnect silently
        permitted. Use :meth:`revoke_consent` for the other one.
        """
        self._client._request_none("DELETE", f"/mcp/servers/{_seg(server_id)}/oauth")

    def revoke_consent(self, server_id: str, consent_id: str) -> None:
        """Withdraw a recorded consent."""
        self._client._request_none(
            "DELETE",
            f"/mcp/servers/{_seg(server_id)}/oauth/consent",
            params={"consent_id": consent_id},
        )


class _MCPInputsAPI:
    """``client.mcp.inputs`` — questions servers asked, waiting on a person.

    Under the current MCP revision a server can ask the client a question
    mid-call. Caged routes it to a **human** rather than to the agent's model: in
    an unattended run the alternative is a model answering a stranger's question
    on somebody's behalf, which is what every other MCP client does.

    A *sampling* request — "run an inference on my prompt and hand back the
    completion" — never appears here. It is refused outright, because no approval
    makes spending the account's tokens on a third party's prompt safe.
    """

    def __init__(self, client: Caged) -> None:
        self._client = client

    def list(self) -> builtins.list[MCPInputRequest]:
        """The questions waiting on a person."""
        data = self._client._request_json("GET", "/mcp/inputs")
        if isinstance(data, Mapping):
            data = data.get("inputs")
        return MCPInputRequest.list_from_api(data)

    def get(self, input_id: str) -> MCPInputRequest:
        """One question set."""
        return MCPInputRequest.from_api(
            self._client._request_json("GET", f"/mcp/inputs/{_seg(input_id)}")
        )

    def respond(
        self,
        input_id: str,
        answers: Mapping[str, Any] | None = None,
        decline: bool = False,
        note: str = "",
    ) -> None:
        """Answer a server's question, or decline it.

        ``answers`` maps a question id to the JSON value that answers it.

        The agent's **next attempt at the same call** carries the answer to the
        server. Caged does not re-send the call itself: a tool call whose side
        effect may be half-done must not be repeated by infrastructure.

        A decline is a first-class answer, forwarded once as a real ``decline``,
        so a server that asked is told no rather than left waiting.
        """
        if not decline and not answers:
            raise CagedError("answers or decline=True is required")
        body: dict[str, Any] = {"note": note}
        if decline:
            body["decline"] = True
        else:
            body["answers"] = [
                {"id": question_id, "content": content}
                for question_id, content in (answers or {}).items()
            ]
        self._client._request_none(
            "POST", f"/mcp/inputs/{_seg(input_id)}/respond", json=body
        )
