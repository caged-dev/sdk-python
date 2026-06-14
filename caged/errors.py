"""Error types for the Caged SDK."""

from __future__ import annotations

from typing import Any, Optional


class CagedError(Exception):
    """Base error for all Caged SDK errors."""

    pass


class CagedAPIError(CagedError):
    """Raised when the API returns a non-2xx response."""

    def __init__(self, status: int, body: Optional[Any] = None) -> None:
        self.status = status
        self.body = body
        message = "Unknown API error"
        if isinstance(body, dict) and "error" in body:
            message = body["error"]
        else:
            message = f"API error: {status}"
        super().__init__(message)


class CagedTimeoutError(CagedError):
    """Raised when a request exceeds the configured timeout."""

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        super().__init__(f"Request timed out after {timeout}s")
