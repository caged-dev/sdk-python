"""Test harness: a recording httpx transport, so no test touches the network."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from caged import Caged


@dataclass
class Stub:
    """One canned response."""

    status: int = 200
    json_body: Any = None
    text: str | None = None
    content_type: str | None = None

    def to_response(self) -> httpx.Response:
        if self.status == 204:
            return httpx.Response(204)
        if self.text is not None:
            return httpx.Response(
                self.status,
                text=self.text,
                headers={"content-type": self.content_type or "text/plain; charset=utf-8"},
            )
        return httpx.Response(
            self.status,
            content=json.dumps(self.json_body).encode(),
            headers={"content-type": self.content_type or "application/json"},
        )


@dataclass
class Harness:
    caged: Caged
    requests: list[httpx.Request] = field(default_factory=list)

    def only(self) -> httpx.Request:
        assert len(self.requests) == 1, f"expected 1 request, got {len(self.requests)}"
        return self.requests[0]

    def body(self) -> dict[str, Any]:
        raw = self.only().content
        return json.loads(raw) if raw else {}


@pytest.fixture
def harness() -> Callable[..., Harness]:
    """Builds a client whose transport is a recording stub.

    ``stubs`` is consumed in order; the last entry repeats, so a single stub
    answers every call.
    """

    def build(stubs: list[Stub], **kwargs: Any) -> Harness:
        recorded: list[httpx.Request] = []
        state = {"i": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            stub = stubs[min(state["i"], len(stubs) - 1)]
            state["i"] += 1
            return stub.to_response()

        client = Caged(
            api_key="caged_sk_test",
            base_url=kwargs.pop("base_url", "https://api.example.test"),
            transport=httpx.MockTransport(handler),
            **kwargs,
        )
        return Harness(caged=client, requests=recorded)

    return build
