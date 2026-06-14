"""Type definitions for the Caged SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


SandboxStatus = Literal["pending", "running", "paused", "stopped", "error", "destroyed"]
SnapshotStatus = Literal["pending", "completed", "failed"]


@dataclass
class Sandbox:
    id: str
    status: SandboxStatus
    template: str
    cpus: int
    memory_mb: int
    disk_gb: int
    network_mode: str
    created_at: str
    ip: Optional[str] = None
    repo_url: Optional[str] = None
    budget: Optional[float] = None
    init_script: Optional[str] = None
    timeout: Optional[int] = None


@dataclass
class ExecResult:
    """Result of executing a command in a sandbox.

    A non-zero ``exit_code`` means the command ran and failed; ``error`` is
    only set for infrastructure failures (sandbox unreachable, etc.).
    """

    output: str
    exit_code: int
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.error


@dataclass
class SandboxCreateParams:
    """Parameters for creating a sandbox."""

    template: str = "minimal"
    cpus: int = 2
    memory_mb: int = 512
    disk_gb: int = 5
    network_mode: str = "full"
    allowlist: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    repo: Optional[str] = None
    repo_branch: Optional[str] = None
    repo_commit: Optional[str] = None
    repo_subdir: Optional[str] = None
    repo_token: Optional[str] = None
    init_script: Optional[str] = None
    secrets: List[str] = field(default_factory=list)
    budget: Optional[float] = None
    timeout: Optional[int] = None
    packages: List[str] = field(default_factory=list)
    agents: List[str] = field(default_factory=list)


@dataclass
class FileEntry:
    name: str
    path: str
    type: Literal["file", "dir"]
    size: Optional[int] = None
    modified: Optional[str] = None


@dataclass
class Snapshot:
    id: str
    sandbox_id: str
    account_id: str
    name: str
    trigger: str
    status: SnapshotStatus
    created_at: str
    description: Optional[str] = None
    size_bytes: Optional[int] = None
    completed_at: Optional[str] = None


@dataclass
class SnapshotCreateParams:
    """Parameters for creating a snapshot."""

    name: Optional[str] = None
    description: Optional[str] = None


@dataclass
class APIKey:
    id: str
    name: str
    prefix: str
    created_at: str
    last_used_at: Optional[str] = None


@dataclass
class Session:
    id: str
    user_agent: str
    ip_address: str
    created_at: str
    last_active_at: str


@dataclass
class TrustScore:
    session_id: str
    sandbox_id: str
    score: float
    factors: Dict[str, float] = field(default_factory=dict)
    updated_at: str = ""


@dataclass
class Port:
    port: int
    protocol: str
    state: str
    url: Optional[str] = None


# --- Logs ---


@dataclass
class LogEntry:
    timestamp: str
    type: str
    message: str


# --- Agent Sessions ---


@dataclass
class AgentSession:
    id: str
    sandbox_id: str
    status: Literal["active", "completed", "failed"]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    event_count: int
    started_at: str
    agent_type: Optional[str] = None
    model: Optional[str] = None
    trust_score: Optional[float] = None
    duration_ms: Optional[int] = None
    ended_at: Optional[str] = None


# --- Replay ---


@dataclass
class ReplayEvent:
    id: str
    session_id: str
    type: str
    timestamp: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplaySummary:
    session_id: str
    total_events: int
    duration_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    tools_used: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    trust_score: Optional[float] = None


# --- Events ---


@dataclass
class EventPayload:
    type: str
    sandbox_id: str
    data: Dict[str, Any] = field(default_factory=dict)
    id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: Optional[str] = None


@dataclass
class IngestResponse:
    accepted: int
    errors: int


# --- Alerts ---


@dataclass
class Alert:
    id: str
    type: str
    severity: Literal["low", "medium", "high", "critical"]
    message: str
    resolved: bool
    created_at: str
    sandbox_id: Optional[str] = None
    resolved_at: Optional[str] = None


@dataclass
class AlertRule:
    id: str
    type: str
    enabled: bool
    channels: List[str] = field(default_factory=list)
    threshold: Optional[float] = None
    cooldown_minutes: Optional[int] = None


# --- Notifications ---


@dataclass
class Notification:
    id: str
    type: str
    title: str
    body: str
    read: bool
    created_at: str
    alert_id: Optional[str] = None


@dataclass
class NotificationConfig:
    email_enabled: bool = True
    slack_enabled: bool = False
    slack_webhook_url: Optional[str] = None
    discord_enabled: bool = False
    discord_webhook_url: Optional[str] = None
    channels: Dict[str, bool] = field(default_factory=dict)


# --- Billing ---


@dataclass
class Subscription:
    plan: str
    status: Literal["active", "trialing", "canceled", "past_due", "none"]
    current_period_end: Optional[str] = None
    cancel_at_period_end: Optional[bool] = None
    trial_end: Optional[str] = None


@dataclass
class APIKey:
    id: str
    name: str
    prefix: str
    created_at: str
    last_used_at: Optional[str] = None


@dataclass
class Session:
    id: str
    user_agent: str
    ip_address: str
    created_at: str
    last_active_at: str


@dataclass
class TrustScore:
    session_id: str
    sandbox_id: str
    score: float
    factors: dict[str, float]
    updated_at: str


@dataclass
class Port:
    port: int
    protocol: str
    state: str
    url: Optional[str] = None
