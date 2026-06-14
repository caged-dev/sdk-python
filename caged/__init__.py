"""Caged SDK — Official Python client for the Caged AI Agent Sandbox Platform."""

from caged.client import Caged
from caged.errors import CagedError, CagedAPIError, CagedTimeoutError
from caged.types import (
    ExecResult,
    Sandbox,
    SandboxCreateParams,
    FileEntry,
    Snapshot,
    SnapshotCreateParams,
    APIKey,
    Session,
    TrustScore,
    Port,
)

__version__ = "0.2.0"
__all__ = [
    "Caged",
    "CagedError",
    "CagedAPIError",
    "CagedTimeoutError",
    "ExecResult",
    "Sandbox",
    "SandboxCreateParams",
    "FileEntry",
    "Snapshot",
    "SnapshotCreateParams",
    "APIKey",
    "Session",
    "TrustScore",
    "Port",
]
