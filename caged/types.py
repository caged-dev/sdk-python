"""Type definitions for the Caged SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


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
    allowlist: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    repo: Optional[str] = None
    repo_branch: Optional[str] = None
    repo_commit: Optional[str] = None
    repo_subdir: Optional[str] = None
    repo_token: Optional[str] = None
    init_script: Optional[str] = None
    secrets: list[str] = field(default_factory=list)
    budget: Optional[float] = None  # Budget cap in USD
    timeout: Optional[int] = None  # Idle timeout in seconds
    packages: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)  # e.g. ["claude", "aider"]


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
    factors: dict[str, float]
    updated_at: str


@dataclass
class Port:
    port: int
    protocol: str
    state: str
    url: Optional[str] = None
