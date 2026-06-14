"""Caged Python SDK client."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional
from urllib.parse import quote

import httpx

from caged.errors import CagedAPIError, CagedTimeoutError
from caged.types import (
    APIKey,
    ExecResult,
    FileEntry,
    Port,
    Sandbox,
    SandboxCreateParams,
    Session,
    Snapshot,
    SnapshotCreateParams,
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
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=f"{self._base_url}/v1",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "caged-python/0.1.0",
            },
            timeout=timeout,
        )

        self.sandboxes = _SandboxesAPI(self)
        self.files = _FilesAPI(self)
        self.snapshots = _SnapshotsAPI(self)
        self.account = _AccountAPI(self)

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
        """Run a shell command in a sandbox and return its output and exit code.

        Supports pipes and redirects. A non-zero exit code does not raise;
        check ``result.ok`` or ``result.exit_code``.

        Usage::

            result = caged.sandboxes.exec(sandbox.id, 'claude -p "explain this repo"')
            print(result.output)
        """
        data = self._client._request(
            "POST", f"/sandboxes/{id}/exec", json={"command": command}, timeout=timeout
        )
        return ExecResult(
            output=data.get("output", ""),
            exit_code=data.get("exit_code", 0),
            error=data.get("error") or None,
        )

    def list(self) -> list[Sandbox]:
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

    def ports(self, id: str) -> list[Port]:
        """List open ports for a sandbox."""
        data = self._client._request("GET", f"/sandboxes/{id}/ports")
        return [Port(**p) for p in data]

    def trust_scores(self, sandbox_id: str) -> list[TrustScore]:
        """Get trust scores for a sandbox."""
        data = self._client._request("GET", f"/trust/sandboxes/{sandbox_id}")
        return [TrustScore(**s) for s in data]


class _FilesAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def list(self, sandbox_id: str, path: str = "/") -> list[FileEntry]:
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


class _SnapshotsAPI:
    def __init__(self, client: Caged) -> None:
        self._client = client

    def list(self, sandbox_id: str) -> list[Snapshot]:
        """List snapshots for a sandbox."""
        data = self._client._request("GET", f"/sandboxes/{sandbox_id}/snapshots")
        return [Snapshot(**{k: v for k, v in s.items() if k in Snapshot.__dataclass_fields__}) for s in data]

    def create(self, sandbox_id: str, name: Optional[str] = None, description: Optional[str] = None) -> Snapshot:
        """Create a snapshot of the sandbox workspace."""
        body: dict[str, Any] = {}
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
