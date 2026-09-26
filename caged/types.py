"""Type definitions for the Caged SDK.

Every dataclass below mirrors a Go response struct in the API's
``internal/api`` (or the domain package that handler marshals directly).
Field names are the JSON keys, not snake-cased approximations of them.

All fields carry a default and every response model is built through
:meth:`_Model.from_api`, which ignores keys it does not know and leaves
absent ones at their default. That is deliberate: this SDK versions
independently of the API, so a field the server adds must never raise in a
client, and a field the server omits must surface as ``None`` rather than a
``TypeError`` from three frames down. Before 0.3.0 these were plain
dataclasses with required positional fields and nine of them could not be
built from a real response at all.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Literal, TypeVar

SandboxStatus = Literal["pending", "running", "paused", "stopped", "error", "destroyed"]
SnapshotStatus = Literal["pending", "completed", "failed"]
FileType = Literal["file", "directory"]
AlertSeverity = Literal["info", "warning", "critical"]
AlertState = Literal["open", "resolved", "muted"]
SessionStatus = Literal["active", "completed", "failed"]

T = TypeVar("T", bound="_Model")


class _Model:
    """Mixin giving every response model a tolerant constructor."""

    @classmethod
    def from_api(cls: type[T], data: Mapping[str, Any]) -> T:
        """Build the model from a decoded JSON object.

        Unknown keys are dropped; missing keys keep their default.
        """
        if not isinstance(data, Mapping):
            raise TypeError(
                f"{cls.__name__}.from_api expected a JSON object, "
                f"got {type(data).__name__}"
            )
        known = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def list_from_api(cls: type[T], data: Any) -> list[T]:
        """Build a list of models from a decoded JSON array.

        ``None`` becomes an empty list: a few endpoints still answer ``null``
        for an empty collection, and a client that has to tell those apart
        from "no data" has been handed the server's bug.
        """
        if data is None:
            return []
        if not isinstance(data, list):
            raise TypeError(
                f"{cls.__name__}.list_from_api expected a JSON array, "
                f"got {type(data).__name__}"
            )
        return [cls.from_api(item) for item in data]


@dataclass
class SandboxConfigSummary(_Model):
    """Summary of the ``.caged.yaml`` config detected for a sandbox."""

    source: str = ""
    raw: str | None = None


@dataclass
class Sandbox(_Model):
    """Mirrors ``api.SandboxResponse``."""

    id: str = ""
    status: SandboxStatus = "pending"
    template: str = ""
    ip: str | None = None
    cpus: int = 0
    memory_mb: int = 0
    disk_gb: int = 0
    network_mode: str = ""
    repo_url: str | None = None
    budget: float | None = None
    init_script: str | None = None
    timeout: int | None = None
    config: dict[str, Any] | None = None
    created_at: str = ""
    #: RFC 3339; ``None`` until the sandbox has started.
    started_at: str | None = None
    #: RFC 3339; ``None`` while the sandbox is still running.
    stopped_at: str | None = None
    #: Dollars of accrued COMPUTE -- machine time -- spent so far. Always
    #: present, including zero. This is half the money: model spend is
    #: metered per session and reported as :attr:`llm_cost`. Showing
    #: ``cost`` against ``budget`` shows a fraction of the figure the
    #: ceiling is compared to.
    cost: float = 0.0
    #: Dollars this sandbox's sessions have spent on model tokens.
    llm_cost: float = 0.0
    #: ``cost + llm_cost``: the figure the budget is enforced against. Show
    #: THIS one next to ``budget``.
    total_cost: float = 0.0


@dataclass
class ExecResult(_Model):
    """Mirrors ``api.ExecResponse``.

    A non-zero ``exit_code`` means the command ran and failed; ``error`` is
    only set when the command could not be run at all.
    """

    output: str = ""
    exit_code: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.error


@dataclass
class SandboxCreateParams:
    """Parameters for creating a sandbox. Mirrors ``api.CreateSandboxRequest``.

    ``template`` is required by the API; the rest are optional and are
    omitted from the request body when left unset, so the server's own
    defaults apply rather than defaults guessed here.

    The templates this API serves are "minimal", "node-22", "node-20",
    "python-312", "python-311" and "desktop" (see
    ``rootfs.AvailableTemplates``); the aliases "node", "python", "gui" and
    "computer" also resolve. ``agents`` accepts "claude-code", "aider",
    "codex", "grok", "cline", "continue", "goose", plus custom MCP agents.
    """

    template: str = "minimal"
    cpus: int | None = None
    memory_mb: int | None = None
    disk_gb: int | None = None
    network_mode: str | None = None
    allowlist: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    repo: str | None = None
    repo_token: str | None = None
    repo_branch: str | None = None
    repo_commit: str | None = None
    repo_subdir: str | None = None
    budget: float | None = None
    init_script: str | None = None
    secrets: list[str] = field(default_factory=list)
    timeout: int | None = None
    packages: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    persona_id: str | None = None
    harness_id: str | None = None


@dataclass
class FileEntry(_Model):
    """Mirrors ``api.FileEntry``.

    ``type`` is ``"directory"``, not ``"dir"``, and the timestamp key is
    ``mod_time``.
    """

    name: str = ""
    path: str = ""
    type: FileType = "file"
    size: int = 0
    mod_time: str = ""

    @property
    def is_dir(self) -> bool:
        return self.type == "directory"


@dataclass
class GitFileStatus(_Model):
    """Mirrors ``api.GitFileStatus``."""

    path: str = ""
    #: "modified", "added", "deleted" or "untracked".
    status: str = ""


@dataclass
class GitDiff(_Model):
    """Mirrors the response of ``GET /v1/sandboxes/{id}/git/diff``.

    The endpoint returns an object, not a diff string.
    """

    files: list[GitFileStatus] = field(default_factory=list)
    diff: str = ""
    staged_diff: str = ""

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> GitDiff:
        built = super().from_api(data)
        built.files = GitFileStatus.list_from_api(data.get("files") or [])
        return built


@dataclass
class Snapshot(_Model):
    """Mirrors ``api.snapshotResponse``.

    The API does not return ``account_id`` on this payload — a snapshot is
    only ever served to the account that owns it.
    """

    id: str = ""
    sandbox_id: str = ""
    name: str = ""
    description: str = ""
    status: SnapshotStatus = "pending"
    trigger: str = ""
    size_bytes: int = 0
    created_at: str = ""
    completed_at: str | None = None


@dataclass
class SnapshotCreateParams:
    """Parameters for creating a snapshot."""

    name: str | None = None
    description: str | None = None


@dataclass
class SnapshotDownload(_Model):
    """Mirrors ``api.downloadResponse``.

    With a filesystem-backed store ``url`` is the API-relative streaming
    path ``/v1/snapshots/{id}/download/content``, which needs the API key.
    """

    url: str = ""
    expires_in_seconds: int = 0


@dataclass
class APIKey(_Model):
    """Mirrors ``api.apiKeyResponse``."""

    id: str = ""
    name: str = ""
    prefix: str = ""
    #: "full" or "read_only".
    scope: str = ""
    #: RFC 3339, or ``None`` when the key has never been used.
    last_used: str | None = None
    #: RFC 3339, or ``None`` when the key does not expire.
    expires_at: str | None = None
    created_at: str = ""


@dataclass
class CreatedAPIKey(_Model):
    """Mirrors ``api.createAPIKeyResponse``. The secret is returned once."""

    key: str = ""
    info: APIKey = field(default_factory=APIKey)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> CreatedAPIKey:
        built = super().from_api(data)
        built.info = APIKey.from_api(data.get("info") or {})
        return built


@dataclass
class AccountSession(_Model):
    """Mirrors ``api.accountSessionResponse`` (a dashboard login session).

    The API emits ``ip``, not ``ip_address``, and reports ``expires_at``
    rather than a last-active timestamp.
    """

    id: str = ""
    user_agent: str = ""
    ip: str = ""
    expires_at: str = ""
    created_at: str = ""


@dataclass
class Account(_Model):
    """Mirrors ``api.accountResponse``."""

    id: str = ""
    email: str = ""
    name: str = ""
    tier: str = ""
    email_verified: bool = False
    created_at: str = ""


@dataclass
class TrustScoreSummary(_Model):
    """Mirrors ``api.TrustScoreSummary``.

    ``score`` is an integer out of 100, not a 0-1 fraction, and the
    per-rule breakdown is not part of this listing.
    """

    session_id: str = ""
    score: int = 0
    updated_at: str = ""


@dataclass
class LogEntry(_Model):
    """Mirrors ``api.LogEntryResponse``."""

    timestamp: str = ""
    type: str = ""
    message: str = ""


@dataclass
class Refusal(_Model):
    """Mirrors ``failure.Reason`` — the machine-readable half of a refusal.

    Present on refusals the API classified (``api.RefusalProblem``). Branch
    on ``code``, not on the message: the message is prose for a human and
    may be reworded, ``code`` is stable.
    """

    #: Stable cause, e.g. "plan_limit_reached", "policy_denied".
    code: str = ""
    #: One sentence, safe to show a user.
    message: str = ""
    #: Next step the caller can take, e.g. "upgrade_plan". Empty if none.
    action: str = ""
    #: What ``subject_id`` identifies.
    subject_type: str = ""
    #: Public ID of the thing to act on.
    subject_id: str = ""


@dataclass
class Port(_Model):
    """Mirrors ``api.portResponse``.

    There is no ``state`` field and the URL key is ``preview_url``.
    """

    port: int = 0
    preview_url: str = ""
    protocol: str = ""
    protected: bool = False
    #: RFC 3339; ``None`` when the host did not report a detection time.
    detected_at: str | None = None


@dataclass
class SocketTicket(_Model):
    """Mirrors ``api.socketTicketResponse``.

    A short-lived, single-use credential for a WebSocket upgrade, minted by
    ``POST /v1/auth/socket-ticket``. The SDK mints one per socket rather
    than putting the account's API key in a URL, because a handshake URL
    reaches every proxy that logs a request line.
    """

    ticket: str = ""
    expires_in: int = 0
    expires_at: str = ""


# --- Pagination ---


@dataclass
class Pagination(_Model):
    """Mirrors ``api.Pagination``."""

    page: int = 1
    per_page: int = 0
    total: int = 0
    total_pages: int = 0


# --- Agent sessions ---


@dataclass
class AgentSession(_Model):
    """Mirrors ``api.sessionResponse`` — one agent run inside a sandbox.

    ``cost_usd`` is the blended total: model spend plus this session's share
    of its sandbox's machine time (ADR-036). :attr:`llm_cost` and
    :attr:`compute_cost` are its two halves and :attr:`total_cost` repeats
    the blended figure under the name the rest of the API uses. All four are
    always present, including zero.

    ``trust_score`` is an integer out of 100, or ``None`` when the session
    has not been scored.
    """

    id: str = ""
    sandbox_id: str = ""
    #: The Persona that worked this session as a Shift, or ``None`` for
    #: direct sandbox usage.
    persona_id: str | None = None
    status: SessionStatus = "active"
    agent_type: str | None = None
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    llm_cost: float = 0.0
    compute_cost: float = 0.0
    total_cost: float = 0.0
    trust_score: int | None = None
    event_count: int = 0
    duration_ms: int | None = None
    started_at: str = ""
    ended_at: str | None = None


@dataclass
class AgentSessionPage(_Model):
    """Mirrors ``api.sessionListResponse`` — one page of account sessions."""

    data: list[AgentSession] = field(default_factory=list)
    pagination: Pagination = field(default_factory=Pagination)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> AgentSessionPage:
        built = super().from_api(data)
        built.data = AgentSession.list_from_api(data.get("data") or [])
        built.pagination = Pagination.from_api(data.get("pagination") or {})
        return built


# --- Replay ---


@dataclass
class ReplayEvent(_Model):
    """Mirrors ``replay.ReplayEvent``.

    ``data`` is the event's own payload and its shape depends on ``type``;
    it is handed over decoded but untyped.
    """

    id: str = ""
    session_id: str = ""
    sequence: int = 0
    type: str = ""
    timestamp: str = ""
    duration_ms: float = 0.0
    data: Any = None


@dataclass
class ReplayPage(_Model):
    """Mirrors ``replay.QueryResult`` — one page of a session's timeline.

    ``GET /v1/sessions/{id}/replay`` answers an object with the events
    inside it, not a bare array, and it is paginated: pass
    :attr:`next_seq` back as ``after_seq`` while :attr:`has_more`.
    """

    events: list[ReplayEvent] = field(default_factory=list)
    has_more: bool = False
    next_seq: int = 0
    total: int = 0

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> ReplayPage:
        built = super().from_api(data)
        built.events = ReplayEvent.list_from_api(data.get("events") or [])
        return built


@dataclass
class ReplaySummary(_Model):
    """Mirrors ``replay.SessionSummary``.

    This endpoint counts events and measures wall time; it does not report
    tokens, cost, tools used or files modified. Token and cost totals for a
    session are on :class:`AgentSession`.
    """

    session_id: str = ""
    event_count: int = 0
    start_time: str = ""
    end_time: str = ""
    duration_ms: float = 0.0
    #: Event count per event type.
    types: dict[str, int] = field(default_factory=dict)


# --- Event ingestion ---

#: Event types the pipeline knows (``events.KnownTypes``). Anything else is
#: recorded as "other".
EVENT_TYPES = (
    "llm_call",
    "tool_call",
    "file_op",
    "command",
    "network",
    "error",
    "lifecycle",
    "desktop",
)


@dataclass
class EventPayload:
    """One event submitted to ``POST /v1/events/ingest``.

    Mirrors ``events.Event``. The event body goes in :attr:`payload` — the
    key the server reads — and free-form string tags go in :attr:`meta`.
    ``account_id`` is not accepted: the server stamps it from the API key.

    ``timestamp`` must be an RFC 3339 string; left unset, :meth:`to_api`
    stamps "now" in UTC. It used to be omitted, which the server rejected
    with a 400 because it decodes into a non-nullable ``time.Time``.
    """

    type: str
    sandbox_id: str = ""
    session_id: str = ""
    id: str = ""
    process_id: str = ""
    timestamp: str | None = None
    duration_ns: int | None = None
    meta: dict[str, str] = field(default_factory=dict)
    payload: dict[str, Any] | None = None
    #: Deprecated alias for :attr:`payload`.
    #:
    #: .. deprecated:: 0.3.0
    #:    The server reads ``payload``; anything sent as ``data`` was
    #:    silently discarded. Removed no earlier than 0.5.0.
    data: dict[str, Any] | None = None

    def to_api(self) -> dict[str, Any]:
        """Render the event as the JSON object the API accepts."""
        payload = self.payload
        if self.data is not None:
            warnings.warn(
                "EventPayload.data is deprecated and was never read by the "
                "API; use EventPayload.payload",
                DeprecationWarning,
                stacklevel=2,
            )
            if payload is None:
                payload = self.data
        body: dict[str, Any] = {
            "type": self.type,
            "timestamp": self.timestamp or _now_rfc3339(),
        }
        if self.id:
            body["id"] = self.id
        if self.sandbox_id:
            body["sandbox_id"] = self.sandbox_id
        if self.session_id:
            body["session_id"] = self.session_id
        if self.process_id:
            body["process_id"] = self.process_id
        if self.duration_ns is not None:
            body["duration_ns"] = self.duration_ns
        if self.meta:
            body["meta"] = self.meta
        if payload is not None:
            body["payload"] = payload
        return body


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class IngestResponse(_Model):
    """Mirrors ``events.IngestResponse``."""

    accepted: int = 0
    errors: int = 0


# --- Alerts ---


@dataclass
class Alert(_Model):
    """Mirrors ``alerts.Alert``.

    The severities are "info", "warning" and "critical"; the state is
    "open", "resolved" or "muted". The rule that fired is ``rule_type``,
    and the human-readable pair is ``title`` plus ``message``.
    """

    id: str = ""
    account_id: str = ""
    rule_id: str = ""
    rule_type: str = ""
    severity: AlertSeverity = "info"
    state: AlertState = "open"
    title: str = ""
    message: str = ""
    sandbox_id: str = ""
    session_id: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    created_at: str = ""
    resolved_at: str | None = None

    @property
    def resolved(self) -> bool:
        return self.state == "resolved"


@dataclass
class AlertPage(_Model):
    """Mirrors the ``GET /v1/alerts`` body.

    The endpoint answers an object with the alerts inside it, plus the
    total and the window that was served.
    """

    alerts: list[Alert] = field(default_factory=list)
    total: int = 0
    limit: int = 0
    offset: int = 0

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> AlertPage:
        built = super().from_api(data)
        built.alerts = Alert.list_from_api(data.get("alerts") or [])
        return built


@dataclass
class RuleConfig(_Model):
    """Mirrors ``alerts.RuleConfig``.

    Which fields matter depends on the rule type: ``threshold_percent`` for
    "budget_exceeded", ``multiplier_threshold`` for "cost_anomaly",
    ``idle_minutes`` for "agent_stuck", ``error_count_threshold`` with
    ``window_minutes`` for "error_spike", ``score_threshold`` for
    "trust_score_low". Zero means "use the server's default".
    """

    threshold_percent: float = 0.0
    multiplier_threshold: float = 0.0
    idle_minutes: int = 0
    error_count_threshold: int = 0
    window_minutes: int = 0
    score_threshold: int = 0

    def to_api(self) -> dict[str, Any]:
        """Render the config, omitting the fields left at zero."""
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if getattr(self, f.name)
        }


@dataclass
class AlertRule(_Model):
    """Mirrors ``alerts.Rule``.

    The tunables live in :attr:`config`; there is no top-level ``threshold``
    or ``cooldown_minutes``, and channels are configured per account through
    the notification config rather than per rule.
    """

    id: str = ""
    account_id: str = ""
    type: str = ""
    enabled: bool = False
    config: RuleConfig = field(default_factory=RuleConfig)
    created_at: str = ""

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> AlertRule:
        built = super().from_api(data)
        built.config = RuleConfig.from_api(data.get("config") or {})
        return built


# --- Notifications ---


@dataclass
class Notification(_Model):
    """Mirrors ``notifications.Notification``.

    The body key is ``message``, not ``body``, and the channel it was
    delivered on is ``channel``.
    """

    id: str = ""
    account_id: str = ""
    alert_id: str = ""
    #: "slack", "discord", "email" or "in_app".
    channel: str = ""
    title: str = ""
    message: str = ""
    read: bool = False
    created_at: str = ""


@dataclass
class NotificationPage(_Model):
    """Mirrors the ``GET /v1/notifications`` body."""

    notifications: list[Notification] = field(default_factory=list)
    unread_count: int = 0

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> NotificationPage:
        built = super().from_api(data)
        built.notifications = Notification.list_from_api(
            data.get("notifications") or []
        )
        return built


@dataclass
class NotificationConfig(_Model):
    """Mirrors ``api.notificationConfigResponse``.

    A read never returns a credential — for a webhook the URL *is* the
    credential — so each one is reported as a boolean plus a hint. Write
    them with :class:`NotificationConfigUpdate`.
    """

    account_id: str = ""
    enabled_channels: list[str] = field(default_factory=list)
    slack_channel_id: str = ""
    email_address: str = ""
    slack_webhook_configured: bool = False
    slack_webhook_hint: str = ""
    slack_bot_token_configured: bool = False
    slack_bot_token_hint: str = ""
    discord_webhook_configured: bool = False
    discord_webhook_hint: str = ""


#: Sent in place of a webhook URL to remove the stored one. An omitted
#: credential means "leave it alone" — see ``api.ClearCredentialSentinel``.
CLEAR_CREDENTIAL = "__clear__"


@dataclass
class NotificationConfigUpdate:
    """Body for ``PUT /v1/notifications/config``.

    Only the fields set here are sent. An omitted webhook URL leaves the
    stored one untouched; pass :data:`CLEAR_CREDENTIAL` to remove it. The
    Slack bot token cannot be set through this endpoint.
    """

    #: Any of "slack", "discord", "email", "in_app".
    enabled_channels: list[str] | None = None
    slack_channel_id: str | None = None
    email_address: str | None = None
    slack_webhook_url: str | None = None
    discord_webhook_url: str | None = None

    def to_api(self) -> dict[str, Any]:
        """Render the update, omitting fields left unset."""
        body: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value is not None:
                body[f.name] = value
        return body


# --- Billing ---


@dataclass
class Subscription(_Model):
    """Mirrors ``subscription.SubscriptionStatus``.

    The plan name is ``tier`` ("free", "pro", "team") and the trial key is
    ``trial_ends_at``.
    """

    tier: str = ""
    status: str = ""
    customer_id: str = ""
    current_period_end: str | None = None
    cancel_at_period_end: bool = False
    trial_ends_at: str | None = None

    @property
    def plan(self) -> str:
        """Deprecated alias for :attr:`tier`.

        .. deprecated:: 0.3.0
           The API has always called this ``tier``; ``plan`` could never be
           populated from a response. Removed no earlier than 0.5.0.
        """
        warnings.warn(
            "Subscription.plan is deprecated; use Subscription.tier",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.tier


@dataclass
class Usage(_Model):
    """Mirrors ``subscription.AccountUsage`` — metered compute this period."""

    #: Reported minutes plus the banked sub-minute remainder.
    compute_minutes: int = 0
    reported_minutes: int = 0
    pending_seconds: int = 0
    last_reported_at: str | None = None


# --- third-party MCP servers -------------------------------------------------
#
# The models below mirror ``internal/api``'s MCP surface. Two of them carry the
# facts that make the difference between a working setup and a silent one, so
# they are worth reading before the rest:
#
# * :class:`MCPPolicyAdvice` — whether policy will actually allow a bound
#   server's tools. A brokered tool name matches nothing in Caged's
#   autonomy-tier table, so a bound external tool is denied at every tier until
#   a rule allows it. Binding alone is not enough, and this model is how the
#   SDK says so.
# * :class:`MCPToolDiff` — the definition a human approved beside the one the
#   server is advertising now. Approving a change without reading it is the
#   outcome digest pinning exists to prevent.
#
# None of these has a field for a credential or a token, and none ever will:
# Caged does not return one, and a model with a field for it would surface one
# the day the server started sending it.

MCPServerStatus = Literal["pending", "active", "quarantined", "disabled"]
MCPToolState = Literal["pending", "active", "quarantined", "withdrawn"]
MCPAuthKind = Literal["none", "bearer", "header", "oauth"]
MCPPolicyStatus = Literal[
    "allowed",
    "partial",
    "needs_approval",
    "unclassified",
    "denied",
    "no_tools",
    "unknown",
]


@dataclass
class MCPServer(_Model):
    """Mirrors ``api.MCPServerResponse`` — one registered third-party server."""

    id: str = ""
    alias: str = ""
    display_name: str = ""
    description: str = ""
    transport: str = ""
    endpoint: str = ""
    catalogue_id: str = ""
    #: ``False`` for a server registered from an arbitrary URL rather than from
    #: Caged's reviewed catalogue. The word also reaches the agent's model in
    #: the tool framing, so it is not cosmetic.
    verified: bool = False
    #: WHICH kind of credential is stored, never the value.
    auth_kind: MCPAuthKind | str = "none"
    protocol_era: str = ""
    protocol_version: str = ""
    status: MCPServerStatus | str = "pending"
    quarantine_reason: str = ""
    #: Set on an ``oauth`` registration that is not authorized yet. It names
    #: the flow, so a registered-but-silent server is not a mystery.
    oauth_next_step: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class MCPServerTool(_Model):
    """Mirrors ``api.MCPToolResponse`` — one pinned catalogue entry.

    Named ``MCPServerTool`` rather than ``MCPTool`` because
    :class:`caged.mcp.MCPTool` already means "a tool on the agent's own MCP
    connection". These are different things and a shared name would make the
    wrong one importable.
    """

    name: str = ""
    #: What an agent calls and what a policy rule matches: ``alias__tool``.
    namespaced_name: str = ""
    description: str = ""
    state: MCPToolState | str = "pending"
    flags: list[str] = field(default_factory=list)
    #: Named an estimate because it is one: a measured character heuristic,
    #: not a BPE count.
    definition_tokens_estimate: int = 0
    first_seen_at: str = ""
    last_seen_at: str = ""
    approved_at: str | None = None


@dataclass
class MCPServerDetail(MCPServer):
    """A registration plus its pinned tool catalogue."""

    tools: list[MCPServerTool] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> MCPServerDetail:
        built = super().from_api(data)
        built.tools = MCPServerTool.list_from_api(data.get("tools") or [])
        return built


@dataclass
class MCPBinding(_Model):
    """Mirrors ``api.MCPBindingResponse`` — what a subject may SEE.

    A binding is not authorization. It decides what is advertised; whether a
    call is permitted is a policy decision on the namespaced name, per call.
    See :class:`MCPPolicyAdvice`.
    """

    id: str = ""
    server_id: str = ""
    subject_kind: str = ""
    subject_id: str = ""
    tool_allowlist: list[str] = field(default_factory=list)
    tool_denylist: list[str] = field(default_factory=list)
    pinned: bool = False
    enabled: bool = True
    argument_ceiling_bytes: int = 0
    created_at: str = ""


@dataclass
class MCPPolicyDecider(_Model):
    """Which policy and rule decided, and whether anybody can edit it."""

    layer: str = ""
    policy_id: str = ""
    policy_name: str = ""
    rule_id: str = ""
    by_default: bool = False
    #: ``False`` for an autonomy-tier template, which is code rather than data.
    #: A client must not send a reader to a policy editor that cannot reach it.
    editable: bool = False


@dataclass
class MCPPolicyAdvice(_Model):
    """Whether policy will actually allow a bound server's tools.

    This is the model to read when brokered calls are being refused. Caged's
    autonomy-tier table classifies its OWN tool names, so a third-party name
    like ``github__get_issue`` is unclassified — and an unclassified tool is
    denied at **every** tier, including ``autonomous``.

    That default is deliberate: Caged cannot know whether a stranger's tool
    reads an issue or wires money. :meth:`caged.client._MCPAPI.allow` writes
    the one rule that clears it.
    """

    server_id: str = ""
    alias: str = ""
    persona_id: str = ""
    status: MCPPolicyStatus | str = "unknown"
    tools_evaluated: int = 0
    tools_allowed: int = 0
    tools_paused: int = 0
    tools_denied: int = 0
    #: An action token — ``allow_mcp_server``, ``edit_policy``,
    #: ``change_autonomy_tier``, ``contact_support`` — or empty when nothing
    #: needs doing.
    remedy: str = ""
    rule_id: str = ""
    tool_pattern: str = ""
    granted_rule_exists: bool = False
    explanation: str = ""
    allow_endpoint: str = ""
    decided_by: MCPPolicyDecider = field(default_factory=lambda: MCPPolicyDecider())

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> MCPPolicyAdvice:
        built = super().from_api(data)
        built.decided_by = MCPPolicyDecider.from_api(data.get("decided_by") or {})
        return built

    @property
    def needs_allow_rule(self) -> bool:
        """``True`` when one ``allow`` call would make these tools callable."""
        return self.remedy == "allow_mcp_server" and not self.granted_rule_exists


@dataclass
class MCPGrantResult(_Model):
    """What writing the policy allow rule did."""

    policy_id: str = ""
    rule_id: str = ""
    #: ``True`` when the persona had no stored policy and Caged created one as
    #: an exact copy of its tier template plus this rule. Surfaced because
    #: "Caged created a policy for this persona" is a fact to learn now rather
    #: than later.
    policy_created: bool = False
    tier_template_id: str = ""
    tool_pattern: str = ""
    #: ``True`` when the rule was already there and nothing changed.
    already_present: bool = False


@dataclass
class MCPBindResult(MCPBinding):
    """A created binding plus what still has to happen.

    ``policy_advice`` is why this type exists rather than returning a bare
    :class:`MCPBinding`: an operator who binds a server and is not told that
    its tools are still denied discovers it one refused call at a time.
    """

    policy_advice: MCPPolicyAdvice | None = None
    policy_rule_written: MCPGrantResult | None = None
    policy_rule_error: str = ""

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> MCPBindResult:
        built = super().from_api(data)
        advice = data.get("policy_advice")
        built.policy_advice = MCPPolicyAdvice.from_api(advice) if advice else None
        written = data.get("policy_rule_written")
        built.policy_rule_written = MCPGrantResult.from_api(written) if written else None
        return built


@dataclass
class MCPRefreshReport(_Model):
    """What one catalogue refresh did.

    ``quarantined`` is the one to act on: a definition whose digest differs
    from the stored one is held, not merged, and its tool is advertised to no
    agent until a human decides.
    """

    server_id: str = ""
    alias: str = ""
    protocol_era: str = ""
    protocol_version: str = ""
    added: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    withdrawn: list[str] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)


@dataclass
class MCPCatalogueEntry(_Model):
    """One server Caged has reviewed. Registering from here is VERIFIED."""

    id: str = ""
    display_name: str = ""
    description: str = ""
    endpoint: str = ""
    transport: str = ""
    auth_kind: str = ""
    default_alias: str = ""


@dataclass
class MCPToolRevision(_Model):
    """One definition a server has advertised, and the decision about it."""

    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    decision: Literal["pending", "approved", "rejected"] | str = "pending"
    note: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    definition_tokens_estimate: int = 0


@dataclass
class MCPToolDiff(_Model):
    """What changed between the approved definition and the current one.

    ``approved`` is ``None`` when nothing has ever been approved: a first
    sighting has nothing to compare against, and ``explanation`` says so rather
    than reading as "nothing changed".

    ``added_properties`` is the one to read first. A new parameter on an
    existing tool is how a tool acquires a field an agent can be talked into
    filling with a secret.
    """

    alias: str = ""
    tool_name: str = ""
    namespaced_name: str = ""
    state: str = ""
    approved: MCPToolRevision | None = None
    current: MCPToolRevision | None = None
    changed: list[str] = field(default_factory=list)
    added_properties: list[str] = field(default_factory=list)
    removed_properties: list[str] = field(default_factory=list)
    approved_digest: str = ""
    current_digest: str = ""
    explanation: str = ""
    approve_endpoint: str = ""
    reject_endpoint: str = ""

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> MCPToolDiff:
        built = super().from_api(data)
        approved = data.get("approved")
        built.approved = MCPToolRevision.from_api(approved) if approved else None
        current = data.get("current")
        built.current = MCPToolRevision.from_api(current) if current else None
        return built


@dataclass
class MCPOAuthStatus(_Model):
    """What is currently authorized. There is no field for a token.

    Caged holds the token itself: sealed at rest, never written into a sandbox,
    never in an environment variable, and never returned by any API read. A
    model with a field for one would surface it the day that changed.
    """

    server_id: str = ""
    authorized: bool = False
    issuer: str = ""
    scopes: list[str] = field(default_factory=list)
    expires_at: str = ""
    has_refresh_token: bool = False
    obtained_at: str = ""
    #: Reported rather than hidden: an operator whose calls started failing
    #: needs to see this.
    expired: bool = False


@dataclass
class MCPOAuthConsent(_Model):
    """One recorded human decision.

    ``persona_id`` empty is an ACCOUNT-wide consent, which is a real and
    different decision from a per-persona one. A persona's own consent outranks
    the account-wide one.
    """

    id: str = ""
    account_id: str = ""
    persona_id: str = ""
    server_id: str = ""
    issuer: str = ""
    scopes: list[str] = field(default_factory=list)
    granted_by: str = ""
    granted_at: str = ""
    revoked_at: str | None = None

    @property
    def live(self) -> bool:
        """``True`` while the consent still stands."""
        return self.revoked_at is None


@dataclass
class MCPOAuthProspect(_Model):
    """What authorizing would involve — the consent screen's contents.

    Nothing is minted or stored to produce this. It is the READ that comes
    before the decision, which is the order the confused-deputy mitigation
    depends on.
    """

    server_id: str = ""
    alias: str = ""
    issuer: str = ""
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    resource_name: str = ""
    resource: str = ""
    scopes: list[str] = field(default_factory=list)
    client_id_metadata_document_supported: bool = False
    #: Caged's own sentence for the screen: what is about to happen, in the
    #: order it happens. Show it to the human. Recording a consent from a
    #: discovered value nobody read is not a consent.
    consent_statement: str = ""


@dataclass
class MCPOAuthState(_Model):
    """The OAuth surface for one server: status, consents, and the prospect."""

    status: MCPOAuthStatus = field(default_factory=lambda: MCPOAuthStatus())
    consents: list[MCPOAuthConsent] = field(default_factory=list)
    prospect: MCPOAuthProspect | None = None
    #: Set when discovery failed. It is reported alongside a real ``status``
    #: rather than replacing it: what is authorized is still true when a third
    #: party's metadata endpoint is down.
    discovery_error: str = ""

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> MCPOAuthState:
        built = super().from_api(data)
        built.status = MCPOAuthStatus.from_api(data.get("status") or {})
        built.consents = MCPOAuthConsent.list_from_api(data.get("consents") or [])
        prospect = data.get("prospect")
        built.prospect = MCPOAuthProspect.from_api(prospect) if prospect else None
        return built


@dataclass
class MCPOAuthAuthorization(_Model):
    """The URL to open, and how long it is live for."""

    authorization_url: str = ""
    expires_in_seconds: int = 0
    note: str = ""


@dataclass
class MCPInputQuestion(_Model):
    """One question a third-party server asked, sanitised by the API."""

    id: str = ""
    #: From a closed set: ``elicitation``, ``roots``, ``url``, ``unknown``. An
    #: unrecognised upstream kind arrives as ``unknown`` rather than being
    #: defaulted to ``elicitation``.
    kind: str = ""
    message: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> MCPInputQuestion:
        built = super().from_api(data)
        # The API calls this ``schema``; the model does not, because
        # ``schema`` shadows a builtin-adjacent name on a dataclass and reads
        # badly next to ``input_schema`` everywhere else in this module.
        built.input_schema = data.get("schema") or {}
        return built


@dataclass
class MCPInputRequest(_Model):
    """A question set waiting on a person.

    The call it belongs to has already returned to the agent with "a human has
    been asked, retry later". Answering this makes the agent's next attempt at
    the same call complete; Caged does not re-send the call itself, because a
    tool call whose side effect may be half-done must not be repeated by
    infrastructure.
    """

    id: str = ""
    sandbox_id: str = ""
    server_id: str = ""
    alias: str = ""
    #: The namespaced name the agent used.
    tool: str = ""
    round: int = 0
    round_limit: int = 0
    state: str = ""
    questions: list[MCPInputQuestion] = field(default_factory=list)
    approval_id: str = ""
    created_at: str = ""
    expires_at: str = ""

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> MCPInputRequest:
        built = super().from_api(data)
        built.questions = MCPInputQuestion.list_from_api(data.get("questions") or [])
        return built
