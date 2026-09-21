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
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from collections.abc import Mapping
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
