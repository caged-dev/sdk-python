"""Caged SDK — Official Python client for the Caged AI Agent Sandbox Platform."""

from caged.client import Caged
from caged.errors import CagedError, CagedAPIError, CagedTimeoutError
from caged.mcp import MCPClient, MCPError, MCPTool, MCPResource, MCPPrompt
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

__version__ = "0.2.0"
__all__ = [
    "Caged",
    "CagedError",
    "CagedAPIError",
    "CagedTimeoutError",
    # WebSocket
    "TerminalSession",
    "MCPClient",
    "MCPError",
    "MCPTool",
    "MCPResource",
    "MCPPrompt",
    "ExecStream",
    # Types
    "AgentSession",
    "Alert",
    "AlertRule",
    "APIKey",
    "EventPayload",
    "ExecResult",
    "FileEntry",
    "IngestResponse",
    "LogEntry",
    "Notification",
    "NotificationConfig",
    "Port",
    "ReplayEvent",
    "ReplaySummary",
    "Sandbox",
    "SandboxCreateParams",
    "Session",
    "Snapshot",
    "SnapshotCreateParams",
    "Subscription",
    "TrustScore",
]
