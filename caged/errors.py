"""Error types for the Caged SDK."""

from __future__ import annotations

from typing import Any, Optional

from caged.types import Refusal


class CagedError(Exception):
    """Base error for all Caged SDK errors."""


class CagedAPIError(CagedError):
    """Raised when the API returns a non-2xx response.

    The API answers errors with RFC 7807 problem details
    (``{"type", "title", "status", "detail"}``), which is where the
    human-readable sentence lives. A handful of older handlers answer
    ``{"error": "..."}`` instead, and the replay routes answer plain text.
    All three are understood here, so the caller always gets the server's own
    sentence rather than a bare status code.
    """

    def __init__(
        self,
        status: int,
        body: Optional[Any] = None,
        text: str = "",
    ) -> None:
        self.status = status
        #: Parsed body, when the response was JSON.
        self.body = body
        #: Raw response text, always retained.
        self.text = text
        self.detail = _detail(body)
        #: Machine-readable refusal reason, when the API classified this
        #: failure. Branch on ``reason.code``, never on the message text.
        self.reason: Optional[Refusal] = _reason(body)
        super().__init__(_message(status, body, text))


class CagedAuthError(CagedAPIError):
    """401/403 — the API key is missing, invalid, or lacks the scope.

    A read-only key refused on a write lands here, with the server's own
    sentence naming the scope.
    """


class CagedNotFoundError(CagedAPIError):
    """404 — the sandbox, snapshot, key, session or alert does not exist."""


class CagedValidationError(CagedAPIError):
    """400/422 — the request was rejected by validation."""


class CagedRateLimitError(CagedAPIError):
    """429 — the account's rate limit or tier limit was hit."""


class CagedPlanLimitError(CagedAPIError):
    """The account's plan does not allow the request.

    The API answers this with 403 and ``reason.code == "plan_limit_reached"``.
    Without this class it would arrive as a :class:`CagedAuthError`, which
    reads as "your key is wrong" when the key is fine and the plan is the
    problem. ``reason.action`` is ``"upgrade_plan"``.
    """


class CagedServerError(CagedAPIError):
    """5xx — the API, or a service behind it, failed."""


class CagedTimeoutError(CagedError):
    """Raised when a request exceeds the timeout in force for that call."""

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        super().__init__(f"Request timed out after {timeout}s")


class CagedConnectionError(CagedError):
    """Raised when the transport failed before a response arrived."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


def _reason(body: Any) -> Optional[Refusal]:
    if not isinstance(body, dict):
        return None
    raw = body.get("reason")
    if not isinstance(raw, dict) or not raw.get("code"):
        return None
    return Refusal.from_api(raw)


def _detail(body: Any) -> Optional[str]:
    if not isinstance(body, dict):
        return None
    for key in ("detail", "error"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _message(status: int, body: Any, text: str) -> str:
    detail = _detail(body)
    if detail:
        return detail
    if isinstance(body, dict):
        title = body.get("title")
        if isinstance(title, str) and title:
            return f"{title} (HTTP {status})"
    trimmed = (text or "").strip()
    if trimmed and len(trimmed) <= 200:
        return f"HTTP {status}: {trimmed}"
    return f"HTTP {status}"


_BY_STATUS: dict[int, type[CagedAPIError]] = {
    400: CagedValidationError,
    401: CagedAuthError,
    403: CagedAuthError,
    404: CagedNotFoundError,
    422: CagedValidationError,
    429: CagedRateLimitError,
}


def error_for_status(status: int, body: Any, text: str) -> CagedAPIError:
    """Return the most specific error class for a failed response."""
    # Checked before the status map: a plan limit and a bad key are both
    # 403, and telling a caller their key is invalid when it is not sends
    # them to the wrong fix.
    reason = _reason(body)
    if reason is not None and reason.code == "plan_limit_reached":
        return CagedPlanLimitError(status, body, text)
    cls: type[CagedAPIError] | None = _BY_STATUS.get(status)
    if cls is None:
        cls = CagedServerError if status >= 500 else CagedAPIError
    return cls(status, body, text)
