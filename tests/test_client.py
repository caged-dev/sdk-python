"""Contract tests for the Caged Python SDK.

Every response body below is copied from the corresponding Go response
struct in ``internal/api``; every request assertion is what that handler
actually reads.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from caged import (
    Caged,
    CagedAPIError,
    CagedAuthError,
    CagedConnectionError,
    CagedError,
    CagedNotFoundError,
    CagedPlanLimitError,
    CagedRateLimitError,
    CagedServerError,
    CagedTimeoutError,
    CagedValidationError,
    EventPayload,
    NotificationConfigUpdate,
    RuleConfig,
    __version__,
)
from tests.conftest import Stub

SANDBOX: dict[str, Any] = {
    "id": "sbx_1",
    "status": "running",
    "template": "node-20",
    "cpus": 2,
    "memory_mb": 1024,
    "disk_gb": 5,
    "network_mode": "full",
    "created_at": "2026-09-20T00:00:00Z",
    "cost": 0.0,
    "llm_cost": 0.0,
    "total_cost": 0.0,
}
SNAPSHOT: dict[str, Any] = {
    "id": "snap_1",
    "sandbox_id": "sbx_1",
    "name": "cp1",
    "description": "",
    "status": "completed",
    "trigger": "manual",
    "size_bytes": 123,
    "created_at": "2026-09-20T00:00:00Z",
}
API_KEY: dict[str, Any] = {
    "id": "key_1",
    "name": "ci",
    "prefix": "caged_sk_ab",
    "scope": "full",
    "last_used": None,
    "expires_at": "2026-12-20T00:00:00Z",
    "created_at": "2026-09-20T00:00:00Z",
}
PORT: dict[str, Any] = {
    "port": 3000,
    "preview_url": "https://p.caged.dev/3000",
    "protocol": "http",
    "protected": False,
    "detected_at": "2026-09-20T00:00:00Z",
}
FILE_ENTRY: dict[str, Any] = {
    "name": "a.js",
    "path": "/workspace/a.js",
    "type": "file",
    "size": 10,
    "mod_time": "2026-09-20T00:00:00Z",
}
ACCOUNT_SESSION: dict[str, Any] = {
    "id": "s1",
    "user_agent": "ua",
    "ip": "1.2.3.4",
    "expires_at": "t",
    "created_at": "t",
}
AGENT_SESSION: dict[str, Any] = {
    "id": "ses_1",
    "sandbox_id": "sbx_1",
    "persona_id": None,
    "status": "completed",
    "agent_type": "claude-code",
    "model": "claude-sonnet-4",
    "tokens_in": 100,
    "tokens_out": 200,
    "cost_usd": 0.5,
    "llm_cost": 0.4,
    "compute_cost": 0.1,
    "total_cost": 0.5,
    "trust_score": 88,
    "event_count": 3,
    "duration_ms": 1000,
    "started_at": "2026-09-20T00:00:00Z",
    "ended_at": "2026-09-20T00:10:00Z",
}
REPLAY_PAGE: dict[str, Any] = {
    "events": [
        {
            "id": "ev_1",
            "session_id": "ses_1",
            "sequence": 1,
            "type": "llm_call",
            "timestamp": "2026-09-20T00:00:00Z",
            "duration_ms": 12.5,
            "data": {"model": "claude-sonnet-4"},
        }
    ],
    "has_more": True,
    "next_seq": 1,
    "total": 2,
}
REPLAY_SUMMARY: dict[str, Any] = {
    "session_id": "ses_1",
    "event_count": 42,
    "start_time": "2026-09-20T00:00:00Z",
    "end_time": "2026-09-20T00:10:00Z",
    "duration_ms": 600000.0,
    "types": {"llm_call": 40, "file_op": 2},
}
ALERT: dict[str, Any] = {
    "id": "alrt_1",
    "account_id": "acc_1",
    "rule_id": "rule_1",
    "rule_type": "budget_exceeded",
    "severity": "warning",
    "state": "open",
    "title": "Budget Threshold Exceeded",
    "message": "Session ses_1 has used 82% of $10.00 budget ($8.2000 spent)",
    "sandbox_id": "sbx_1",
    "session_id": "ses_1",
    "meta": {"percent": "82"},
    "created_at": "2026-09-20T00:00:00Z",
}
ALERT_PAGE: dict[str, Any] = {"alerts": [ALERT], "total": 1, "limit": 50, "offset": 0}
ALERT_RULE: dict[str, Any] = {
    "id": "rule_1",
    "account_id": "acc_1",
    "type": "budget_exceeded",
    "enabled": True,
    "config": {"threshold_percent": 80},
    "created_at": "2026-09-20T00:00:00Z",
}
NOTIFICATION: dict[str, Any] = {
    "id": "ntf_1",
    "account_id": "acc_1",
    "alert_id": "alrt_1",
    "channel": "in_app",
    "title": "Budget Threshold Exceeded",
    "message": "82% of budget spent",
    "read": False,
    "created_at": "2026-09-20T00:00:00Z",
}
NOTIFICATION_PAGE: dict[str, Any] = {
    "notifications": [NOTIFICATION],
    "unread_count": 1,
}
NOTIFICATION_CONFIG: dict[str, Any] = {
    "account_id": "acc_1",
    "enabled_channels": ["in_app", "slack"],
    "slack_channel_id": "C123",
    "slack_webhook_configured": True,
    "slack_webhook_hint": "...abcd",
    "slack_bot_token_configured": False,
    "discord_webhook_configured": False,
}
SUBSCRIPTION: dict[str, Any] = {
    "tier": "pro",
    "status": "active",
    "customer_id": "cus_1",
    "current_period_end": "2026-10-20T00:00:00Z",
    "cancel_at_period_end": False,
}
USAGE: dict[str, Any] = {
    "compute_minutes": 10,
    "reported_minutes": 8,
    "pending_seconds": 120,
}


def problem(status: int, title: str, detail: str) -> Stub:
    return Stub(
        status=status,
        json_body={
            "type": f"https://caged.dev/errors/{title}",
            "title": title,
            "status": status,
            "detail": detail,
        },
        content_type="application/problem+json",
    )


def query(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(urlparse(str(request.url)).query)


# --- construction ---------------------------------------------------------


def test_missing_api_key_raises_a_caged_error() -> None:
    with pytest.raises(CagedError):
        Caged(api_key="")


def test_base_url_trailing_slash_does_not_double_the_path(harness: Any) -> None:
    h = harness([Stub(json_body=[SANDBOX])], base_url="https://api.example.test/")
    h.caged.sandboxes.list()
    assert str(h.only().url) == "https://api.example.test/v1/sandboxes"


def test_first_request_carries_auth_and_user_agent(harness: Any) -> None:
    h = harness([Stub(json_body=[SANDBOX])])
    h.caged.sandboxes.list()
    req = h.only()
    assert req.headers["authorization"] == "Bearer caged_sk_test"
    assert req.headers["user-agent"] == f"caged-python/{__version__}"


# --- first call on a fresh client ----------------------------------------

FIRST_CALL_CASES: list[Any] = [
    ("sandboxes.create", [Stub(201, SANDBOX)], lambda c: c.sandboxes.create(template="node-20")),
    ("sandboxes.list", [Stub(json_body=[SANDBOX])], lambda c: c.sandboxes.list()),
    ("sandboxes.get", [Stub(json_body=SANDBOX)], lambda c: c.sandboxes.get("sbx_1")),
    ("sandboxes.exec", [Stub(json_body={"output": "hi", "exit_code": 0})], lambda c: c.sandboxes.exec("sbx_1", "echo hi")),
    ("sandboxes.pause", [Stub(204)], lambda c: c.sandboxes.pause("sbx_1")),
    ("sandboxes.resume", [Stub(204)], lambda c: c.sandboxes.resume("sbx_1")),
    ("sandboxes.destroy", [Stub(204)], lambda c: c.sandboxes.destroy("sbx_1")),
    ("sandboxes.ports", [Stub(json_body=[PORT])], lambda c: c.sandboxes.ports("sbx_1")),
    ("sandboxes.logs", [Stub(json_body=[{"timestamp": "t", "type": "lifecycle", "message": "m"}])], lambda c: c.sandboxes.logs("sbx_1")),
    ("sandboxes.trust_scores", [Stub(json_body=[{"session_id": "s1", "score": 90, "updated_at": "t"}])], lambda c: c.sandboxes.trust_scores("sbx_1")),
    ("files.list", [Stub(json_body=[FILE_ENTRY])], lambda c: c.files.list("sbx_1")),
    ("files.read", [Stub(text="console.log('hi')")], lambda c: c.files.read("sbx_1", "/workspace/a.js")),
    ("files.write", [Stub(json_body={"status": "ok", "path": "/workspace/a.js"})], lambda c: c.files.write("sbx_1", "/workspace/a.js", "x")),
    ("files.git_diff", [Stub(json_body={"files": [], "diff": "", "staged_diff": ""})], lambda c: c.files.git_diff("sbx_1")),
    ("snapshots.list", [Stub(json_body=[SNAPSHOT])], lambda c: c.snapshots.list("sbx_1")),
    ("snapshots.create", [Stub(201, SNAPSHOT)], lambda c: c.snapshots.create("sbx_1", name="cp1")),
    ("snapshots.get", [Stub(json_body=SNAPSHOT)], lambda c: c.snapshots.get("snap_1")),
    ("snapshots.delete", [Stub(204)], lambda c: c.snapshots.delete("snap_1")),
    ("snapshots.download", [Stub(json_body={"url": "https://s3/x", "expires_in_seconds": 3600})], lambda c: c.snapshots.download("snap_1")),
    ("snapshots.restore", [Stub(json_body={"status": "restored"})], lambda c: c.snapshots.restore("snap_1", "sbx_2")),
    ("account.get", [Stub(json_body={"id": "a", "email": "e", "name": "n", "tier": "free", "email_verified": True, "created_at": "t"})], lambda c: c.account.get()),
    ("account.list_keys", [Stub(json_body=[API_KEY])], lambda c: c.account.list_keys()),
    ("account.create_key", [Stub(201, {"key": "caged_sk_secret", "info": API_KEY})], lambda c: c.account.create_key("ci")),
    ("account.revoke_key", [Stub(204)], lambda c: c.account.revoke_key("key_1")),
    ("account.list_sessions", [Stub(json_body=[ACCOUNT_SESSION])], lambda c: c.account.list_sessions()),
    ("account.revoke_session", [Stub(204)], lambda c: c.account.revoke_session("s1")),
    ("sessions.list_by_sandbox", [Stub(json_body=[AGENT_SESSION])], lambda c: c.sessions.list_by_sandbox("sbx_1")),
    ("sessions.list", [Stub(json_body={"data": [AGENT_SESSION], "pagination": {"page": 1, "per_page": 20, "total": 1, "total_pages": 1}})], lambda c: c.sessions.list()),
    ("sessions.get", [Stub(json_body=AGENT_SESSION)], lambda c: c.sessions.get("ses_1")),
    ("sessions.replay", [Stub(json_body=REPLAY_PAGE)], lambda c: c.sessions.replay("ses_1")),
    ("sessions.replay_summary", [Stub(json_body=REPLAY_SUMMARY)], lambda c: c.sessions.replay_summary("ses_1")),
    ("events.ingest", [Stub(json_body={"accepted": 1, "errors": 0})], lambda c: c.events.ingest([EventPayload(type="llm_call", sandbox_id="sbx_1")])),
    ("alerts.list", [Stub(json_body=ALERT_PAGE)], lambda c: c.alerts.list()),
    ("alerts.get", [Stub(json_body=ALERT)], lambda c: c.alerts.get("alrt_1")),
    ("alerts.resolve", [Stub(204)], lambda c: c.alerts.resolve("alrt_1")),
    ("alerts.list_rules", [Stub(json_body=[ALERT_RULE])], lambda c: c.alerts.list_rules()),
    ("alerts.update_rule", [Stub(json_body=ALERT_RULE)], lambda c: c.alerts.update_rule("rule_1", enabled=False)),
    ("notifications.list", [Stub(json_body=NOTIFICATION_PAGE)], lambda c: c.notifications.list()),
    ("notifications.list_unread", [Stub(json_body=NOTIFICATION_PAGE)], lambda c: c.notifications.list_unread()),
    ("notifications.unread_count", [Stub(json_body={"unread_count": 3})], lambda c: c.notifications.unread_count()),
    ("notifications.mark_read", [Stub(204)], lambda c: c.notifications.mark_read("ntf_1")),
    ("notifications.mark_all_read", [Stub(204)], lambda c: c.notifications.mark_all_read()),
    ("notifications.get_config", [Stub(json_body=NOTIFICATION_CONFIG)], lambda c: c.notifications.get_config()),
    ("notifications.update_config", [Stub(json_body=NOTIFICATION_CONFIG)], lambda c: c.notifications.update_config(NotificationConfigUpdate(enabled_channels=["in_app"]))),
    ("billing.get_subscription", [Stub(json_body=SUBSCRIPTION)], lambda c: c.billing.get_subscription()),
    ("billing.get_usage", [Stub(json_body=USAGE)], lambda c: c.billing.get_usage()),
    ("billing.create_checkout", [Stub(json_body={"url": "https://checkout.stripe/x"})], lambda c: c.billing.create_checkout("pro")),
    ("billing.create_portal", [Stub(json_body={"url": "https://portal.stripe/x"})], lambda c: c.billing.create_portal()),
    ("billing.cancel", [Stub(204)], lambda c: c.billing.cancel()),
    ("socket_ticket", [Stub(json_body={"ticket": "caged_wst_x.y", "expires_in": 60, "expires_at": "t"})], lambda c: c.socket_ticket()),
]


@pytest.mark.parametrize(
    "name,stubs,call", FIRST_CALL_CASES, ids=[c[0] for c in FIRST_CALL_CASES]
)
def test_method_works_as_the_first_call(
    harness: Any, name: str, stubs: list[Stub], call: Callable[[Caged], Any]
) -> None:
    # Regression for the reported defect: each method must work when it is
    # the first thing a freshly constructed client does.
    h = harness(stubs)
    call(h.caged)
    assert len(h.requests) == 1


# --- request shapes the API actually requires -----------------------------


def test_files_write_sends_the_path_as_a_query_parameter(harness: Any) -> None:
    h = harness([Stub(json_body={"status": "ok", "path": "/workspace/a.js"})])
    h.caged.files.write("sbx_1", "/workspace/a.js", "hello")
    req = h.only()
    assert req.method == "PUT"
    assert urlparse(str(req.url)).path == "/v1/sandboxes/sbx_1/files/content"
    assert query(req)["path"] == ["/workspace/a.js"]
    assert json.loads(req.content) == {"content": "hello"}


def test_files_read_returns_raw_text(harness: Any) -> None:
    h = harness([Stub(text="console.log('hi')\n")])
    assert h.caged.files.read("sbx_1", "/a.js") == "console.log('hi')\n"
    assert query(h.only())["path"] == ["/a.js"]


def test_files_list_defaults_to_workspace(harness: Any) -> None:
    h = harness([Stub(json_body=[FILE_ENTRY])])
    h.caged.files.list("sbx_1")
    assert query(h.only())["path"] == ["/workspace"]


def test_snapshot_restore_sends_the_required_target(harness: Any) -> None:
    h = harness([Stub(json_body={"status": "restored"})])
    h.caged.snapshots.restore("snap_1", "sbx_2")
    assert json.loads(h.only().content) == {"target_sandbox_id": "sbx_2"}


def test_snapshot_restore_refuses_an_empty_target_before_the_network(harness: Any) -> None:
    h = harness([Stub(json_body={})])
    with pytest.raises(CagedError):
        h.caged.snapshots.restore("snap_1", "")
    assert h.requests == []


def test_create_refuses_an_empty_template_before_the_network(harness: Any) -> None:
    h = harness([Stub(json_body=SANDBOX)])
    with pytest.raises(CagedError):
        h.caged.sandboxes.create(template="")
    assert h.requests == []


def test_create_rejects_an_unknown_parameter_with_a_caged_error(harness: Any) -> None:
    h = harness([Stub(json_body=SANDBOX)])
    with pytest.raises(CagedError):
        h.caged.sandboxes.create(template="node-20", memory=1024)
    assert h.requests == []


def test_create_omits_unset_fields_so_server_defaults_apply(harness: Any) -> None:
    h = harness([Stub(201, SANDBOX)])
    h.caged.sandboxes.create(template="node-20")
    assert json.loads(h.only().content) == {"template": "node-20"}


def test_create_key_defaults_the_scope_the_api_validates(harness: Any) -> None:
    h = harness([Stub(201, {"key": "k", "info": API_KEY})])
    h.caged.account.create_key("ci")
    assert json.loads(h.only().content) == {"name": "ci", "scope": "full"}


def test_path_segments_are_quoted(harness: Any) -> None:
    h = harness([Stub(json_body=SANDBOX)])
    h.caged.sandboxes.get("a/../b")
    assert urlparse(str(h.only().url)).path == "/v1/sandboxes/a%2F..%2Fb"


def test_none_query_values_are_dropped(harness: Any) -> None:
    h = harness([Stub(json_body=[])])
    h.caged.sandboxes.logs("sbx_1")
    assert "tail" not in query(h.only())


# --- response shapes ------------------------------------------------------


def test_port_parses_preview_url(harness: Any) -> None:
    h = harness([Stub(json_body=[PORT])])
    ports = h.caged.sandboxes.ports("sbx_1")
    assert ports[0].preview_url == "https://p.caged.dev/3000"
    assert ports[0].protected is False


def test_file_entry_parses_mod_time_and_directory_type(harness: Any) -> None:
    h = harness([Stub(json_body=[{**FILE_ENTRY, "type": "directory"}])])
    entries = h.caged.files.list("sbx_1")
    assert entries[0].is_dir
    assert entries[0].mod_time == "2026-09-20T00:00:00Z"


def test_snapshot_parses_without_an_account_id(harness: Any) -> None:
    # The API does not return account_id on this payload.
    h = harness([Stub(json_body=SNAPSHOT)])
    snap = h.caged.snapshots.get("snap_1")
    assert snap.id == "snap_1"
    assert snap.completed_at is None


def test_git_diff_returns_a_structured_object(harness: Any) -> None:
    h = harness(
        [Stub(json_body={"files": [{"path": "a.js", "status": "modified"}], "diff": "d", "staged_diff": ""})]
    )
    diff = h.caged.files.git_diff("sbx_1")
    assert diff.files[0].status == "modified"
    assert diff.diff == "d"


def test_created_key_separates_the_secret_from_the_metadata(harness: Any) -> None:
    h = harness([Stub(201, {"key": "caged_sk_secret", "info": API_KEY})])
    created = h.caged.account.create_key("ci")
    assert created.key == "caged_sk_secret"
    assert created.info.scope == "full"


def test_trust_score_is_an_integer_out_of_100(harness: Any) -> None:
    h = harness([Stub(json_body=[{"session_id": "s1", "score": 90, "updated_at": "t"}])])
    assert h.caged.sandboxes.trust_scores("sbx_1")[0].score == 90


def test_unknown_response_fields_do_not_raise(harness: Any) -> None:
    # The SDK versions independently of the API: a field the server adds
    # tomorrow must not break a client shipped today.
    h = harness([Stub(json_body={**SANDBOX, "brand_new_field": 1})])
    assert h.caged.sandboxes.get("sbx_1").id == "sbx_1"


def test_missing_response_fields_fall_back_to_defaults(harness: Any) -> None:
    h = harness([Stub(json_body={"id": "sbx_1"})])
    sandbox = h.caged.sandboxes.get("sbx_1")
    assert sandbox.id == "sbx_1"
    assert sandbox.cost == 0.0
    assert sandbox.started_at is None


def test_a_sandbox_carries_both_halves_of_its_spend(harness: Any) -> None:
    """``cost`` is machine time alone; the budget is enforced against the sum.

    A client that showed ``cost`` against ``budget`` was showing a fraction
    of the figure the ceiling is compared to.
    """
    h = harness([Stub(json_body={**SANDBOX, "cost": 1.5, "llm_cost": 3.25, "total_cost": 4.75})])
    sandbox = h.caged.sandboxes.get("sbx_1")
    assert sandbox.cost == 1.5
    assert sandbox.llm_cost == 3.25
    assert sandbox.total_cost == 4.75


def test_non_json_body_on_a_json_endpoint_is_reported_clearly(harness: Any) -> None:
    h = harness([Stub(text="<html>502</html>", content_type="text/html")])
    with pytest.raises(CagedError, match="not JSON"):
        h.caged.sandboxes.list()


def test_empty_body_on_a_json_endpoint_is_reported_clearly(harness: Any) -> None:
    h = harness([Stub(204)])
    with pytest.raises(CagedError, match="empty body"):
        h.caged.sandboxes.list()


# --- errors ---------------------------------------------------------------


def test_problem_detail_is_surfaced_not_the_bare_status(harness: Any) -> None:
    h = harness([problem(400, "Bad Request", "missing path parameter")])
    with pytest.raises(CagedAPIError, match="missing path parameter"):
        h.caged.files.write("sbx_1", "/a", "x")


def test_problem_title_is_used_when_there_is_no_detail(harness: Any) -> None:
    h = harness(
        [Stub(400, {"title": "Bad Request", "status": 400}, content_type="application/problem+json")]
    )
    with pytest.raises(CagedAPIError, match=r"Bad Request \(HTTP 400\)"):
        h.caged.sandboxes.list()


def test_legacy_error_field_is_understood(harness: Any) -> None:
    h = harness([Stub(400, {"error": "target_sandbox_id required"})])
    with pytest.raises(CagedAPIError, match="target_sandbox_id required"):
        h.caged.snapshots.restore("snap_1", "sbx_2")


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, CagedValidationError),
        (401, CagedAuthError),
        (403, CagedAuthError),
        (404, CagedNotFoundError),
        (422, CagedValidationError),
        (429, CagedRateLimitError),
        (500, CagedServerError),
        (503, CagedServerError),
    ],
)
def test_status_maps_to_a_specific_error_class(
    harness: Any, status: int, expected: type
) -> None:
    h = harness([problem(status, "x", "y")])
    with pytest.raises(expected):
        h.caged.sandboxes.get("sbx_1")


def test_error_retains_status_detail_and_raw_body(harness: Any) -> None:
    h = harness([problem(404, "Not Found", "sandbox not found")])
    with pytest.raises(CagedNotFoundError) as excinfo:
        h.caged.sandboxes.get("sbx_1")
    err = excinfo.value
    assert err.status == 404
    assert err.detail == "sandbox not found"
    assert "sandbox not found" in err.text


def test_timeout_is_raised_as_a_caged_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    caged = Caged(
        api_key="caged_sk_test",
        base_url="https://api.example.test",
        timeout=0.5,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(CagedTimeoutError) as excinfo:
        caged.sandboxes.list()
    assert excinfo.value.timeout == 0.5
    caged.close()


def test_timeout_error_reports_the_per_call_budget_not_the_client_default() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    caged = Caged(
        api_key="caged_sk_test",
        base_url="https://api.example.test",
        timeout=30.0,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(CagedTimeoutError) as excinfo:
        caged.sandboxes.exec("sbx_1", "sleep 999", timeout=7.0)
    assert excinfo.value.timeout == 7.0
    caged.close()


def test_transport_failure_becomes_a_connection_error_naming_the_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    caged = Caged(
        api_key="caged_sk_test",
        base_url="https://api.example.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(CagedConnectionError, match="GET /sandboxes"):
        caged.sandboxes.list()
    caged.close()


# --- deprecations ---------------------------------------------------------


def test_download_url_still_works_but_warns(harness: Any) -> None:
    h = harness([Stub(json_body={"url": "https://s3/x", "expires_in_seconds": 3600})])
    with pytest.warns(DeprecationWarning):
        assert h.caged.snapshots.download_url("snap_1") == "https://s3/x"


def test_renamed_types_are_still_importable() -> None:
    from caged import AccountSession, Session, TrustScore, TrustScoreSummary

    assert TrustScore is TrustScoreSummary
    assert Session is AccountSession


# --- context manager ------------------------------------------------------


def test_client_closes_its_transport_on_exit(harness: Any) -> None:
    h = harness([Stub(json_body=[SANDBOX])])
    with h.caged as caged:
        caged.sandboxes.list()
    assert h.caged._client.is_closed


# --- classified refusals --------------------------------------------------

# Body observed from a real locally booted API server: internal/api's
# errRefused writes the RFC 7807 fields plus failure.Reason under "reason".
PLAN_LIMIT_BODY: dict[str, Any] = {
    "type": "https://caged.dev/errors/Forbidden",
    "title": "Forbidden",
    "status": 403,
    "detail": "plan limit reached: you already have 1 API keys, which is your plan's limit — upgrade for more",
    "reason": {
        "code": "plan_limit_reached",
        "message": "plan limit reached: you already have 1 API keys, which is your plan's limit — upgrade for more",
        "action": "upgrade_plan",
    },
}


def test_plan_limit_is_not_reported_as_an_auth_failure(harness: Any) -> None:
    # Both arrive as 403. Telling a caller their key is invalid when the key
    # is fine and the plan is the problem sends them to the wrong fix.
    h = harness([Stub(403, PLAN_LIMIT_BODY, content_type="application/problem+json")])
    with pytest.raises(CagedPlanLimitError) as excinfo:
        h.caged.account.create_key("second")
    err = excinfo.value
    assert err.reason is not None
    assert err.reason.code == "plan_limit_reached"
    assert err.reason.action == "upgrade_plan"
    assert "upgrade for more" in str(err)


def test_plan_limit_error_is_still_a_caged_api_error(harness: Any) -> None:
    h = harness([Stub(403, PLAN_LIMIT_BODY, content_type="application/problem+json")])
    with pytest.raises(CagedAPIError):
        h.caged.account.create_key("second")


def test_a_plain_auth_failure_stays_an_auth_error(harness: Any) -> None:
    h = harness([problem(403, "Forbidden", "this key is read-only")])
    with pytest.raises(CagedAuthError) as excinfo:
        h.caged.sandboxes.create(template="node-20")
    assert excinfo.value.reason is None


def test_a_chi_404_with_a_plain_text_body_is_reported_usefully(harness: Any) -> None:
    # A genuinely unregistered route answers chi's plain text, not JSON.
    h = harness([Stub(404, text="404 page not found")])
    with pytest.raises(CagedNotFoundError, match="404 page not found"):
        h.caged.sandboxes.get("sbx_1")


# --- shapes that only the shipping tree's methods touch -------------------
#
# The 0.2.0 client's 25 extra methods were never checked against the API.
# Every assertion below is a bug that shipped: an object read as an array, a
# key that does not exist, a request field the handler does not read.


def test_alerts_list_reads_the_object_the_endpoint_returns(harness: Any) -> None:
    # GET /v1/alerts answers {"alerts": [...], "total", "limit", "offset"}.
    # Iterating that as an array iterated the dict's KEYS.
    h = harness([Stub(json_body=ALERT_PAGE)])
    page = h.caged.alerts.list()
    assert page.total == 1
    assert page.alerts[0].rule_type == "budget_exceeded"
    assert page.alerts[0].severity == "warning"
    assert page.alerts[0].resolved is False


def test_alert_severities_are_the_ones_the_engine_emits(harness: Any) -> None:
    # Not "low"/"medium"/"high": alerts.Severity* is info/warning/critical.
    h = harness([Stub(json_body={**ALERT, "severity": "critical", "state": "resolved"})])
    alert = h.caged.alerts.get("alrt_1")
    assert alert.severity == "critical"
    assert alert.resolved is True


def test_alert_rule_tunables_are_nested_under_config(harness: Any) -> None:
    h = harness([Stub(json_body=[ALERT_RULE])])
    rules = h.caged.alerts.list_rules()
    assert rules[0].config.threshold_percent == 80
    assert rules[0].enabled is True


def test_update_rule_sends_only_what_changed(harness: Any) -> None:
    h = harness([Stub(json_body=ALERT_RULE)])
    h.caged.alerts.update_rule("rule_1", config=RuleConfig(threshold_percent=90))
    assert json.loads(h.only().content) == {"config": {"threshold_percent": 90}}


def test_update_rule_with_nothing_to_change_is_refused_locally(harness: Any) -> None:
    h = harness([Stub(json_body=ALERT_RULE)])
    with pytest.raises(CagedError):
        h.caged.alerts.update_rule("rule_1")
    assert h.requests == []


def test_notifications_list_reads_the_object_the_endpoint_returns(harness: Any) -> None:
    h = harness([Stub(json_body=NOTIFICATION_PAGE)])
    page = h.caged.notifications.list()
    assert page.unread_count == 1
    assert page.notifications[0].message == "82% of budget spent"
    assert page.notifications[0].channel == "in_app"


def test_unread_only_is_asked_for_the_way_the_handler_reads_it(harness: Any) -> None:
    h = harness([Stub(json_body=NOTIFICATION_PAGE)])
    h.caged.notifications.list(unread_only=True)
    assert query(h.only())["unread"] == ["true"]


def test_unread_count_reads_the_key_the_endpoint_sends(harness: Any) -> None:
    # The body is {"unread_count": n}; the old client read data["count"]
    # and raised KeyError on a successful response.
    h = harness([Stub(json_body={"unread_count": 3})])
    assert h.caged.notifications.unread_count() == 3


def test_unread_count_without_its_key_is_reported_clearly(harness: Any) -> None:
    h = harness([Stub(json_body={"count": 3})])
    with pytest.raises(CagedError, match="unread_count"):
        h.caged.notifications.unread_count()


def test_notification_config_never_carries_a_credential(harness: Any) -> None:
    # A read reports whether each channel is configured plus a hint; for a
    # webhook the URL is the credential, so it is not returned.
    h = harness([Stub(json_body=NOTIFICATION_CONFIG)])
    config = h.caged.notifications.get_config()
    assert config.slack_webhook_configured is True
    assert config.slack_webhook_hint == "...abcd"
    assert not hasattr(config, "slack_webhook_url")


def test_config_update_omits_what_was_not_set(harness: Any) -> None:
    # An omitted webhook means "leave it alone"; sending "" would erase the
    # account's stored one on every unrelated save.
    h = harness([Stub(json_body=NOTIFICATION_CONFIG)])
    h.caged.notifications.update_config(
        NotificationConfigUpdate(enabled_channels=["in_app"])
    )
    assert json.loads(h.only().content) == {"enabled_channels": ["in_app"]}


def test_a_webhook_can_be_cleared_explicitly(harness: Any) -> None:
    from caged import CLEAR_CREDENTIAL

    h = harness([Stub(json_body=NOTIFICATION_CONFIG)])
    h.caged.notifications.update_config(
        NotificationConfigUpdate(slack_webhook_url=CLEAR_CREDENTIAL)
    )
    assert json.loads(h.only().content) == {"slack_webhook_url": "__clear__"}


def test_checkout_sends_plan_id_not_plan(harness: Any) -> None:
    # The handler reads plan_id and 400s without it, so every call to the
    # old client's createCheckout failed.
    h = harness([Stub(json_body={"url": "https://checkout.stripe/x"})])
    assert h.caged.billing.create_checkout("pro") == "https://checkout.stripe/x"
    assert json.loads(h.only().content) == {"plan_id": "pro"}


def test_subscription_plan_name_is_tier(harness: Any) -> None:
    # SubscriptionStatus has no "plan" field, so the old dataclass could not
    # be built from a successful response at all.
    h = harness([Stub(json_body=SUBSCRIPTION)])
    sub = h.caged.billing.get_subscription()
    assert sub.tier == "pro"
    assert sub.status == "active"
    assert sub.trial_ends_at is None


def test_subscription_plan_alias_still_reads_but_warns(harness: Any) -> None:
    h = harness([Stub(json_body=SUBSCRIPTION)])
    sub = h.caged.billing.get_subscription()
    with pytest.warns(DeprecationWarning):
        assert sub.plan == "pro"


def test_usage_is_reported_in_minutes_and_banked_seconds(harness: Any) -> None:
    h = harness([Stub(json_body=USAGE)])
    usage = h.caged.billing.get_usage()
    assert usage.compute_minutes == 10
    assert usage.pending_seconds == 120
    assert usage.last_reported_at is None


def test_a_session_carries_both_halves_of_its_spend(harness: Any) -> None:
    h = harness([Stub(json_body=AGENT_SESSION)])
    session = h.caged.sessions.get("ses_1")
    assert session.cost_usd == 0.5
    assert session.llm_cost == 0.4
    assert session.compute_cost == 0.1
    assert session.total_cost == 0.5
    assert session.trust_score == 88


def test_a_session_without_a_persona_is_not_an_error(harness: Any) -> None:
    h = harness([Stub(json_body={**AGENT_SESSION, "persona_id": None})])
    assert h.caged.sessions.get("ses_1").persona_id is None


def test_account_session_listing_is_paginated(harness: Any) -> None:
    h = harness(
        [
            Stub(
                json_body={
                    "data": [AGENT_SESSION],
                    "pagination": {
                        "page": 2,
                        "per_page": 20,
                        "total": 21,
                        "total_pages": 2,
                    },
                }
            )
        ]
    )
    page = h.caged.sessions.list(page=2)
    assert page.pagination.total_pages == 2
    assert page.data[0].id == "ses_1"
    assert query(h.only())["page"] == ["2"]


def test_replay_is_an_object_with_pagination_not_an_array(harness: Any) -> None:
    h = harness([Stub(json_body=REPLAY_PAGE)])
    page = h.caged.sessions.replay("ses_1", after_seq=0, limit=50, type="llm_call")
    assert page.has_more is True
    assert page.next_seq == 1
    assert page.events[0].sequence == 1
    assert page.events[0].data == {"model": "claude-sonnet-4"}
    q = query(h.only())
    assert q["limit"] == ["50"] and q["type"] == ["llm_call"]


def test_replay_summary_counts_events_and_does_not_report_cost(harness: Any) -> None:
    h = harness([Stub(json_body=REPLAY_SUMMARY)])
    summary = h.caged.sessions.replay_summary("ses_1")
    assert summary.event_count == 42
    assert summary.types["llm_call"] == 40
    # The old model required total_events/tokens_in/cost_usd, none of which
    # this endpoint sends; per-session cost lives on AgentSession.
    assert not hasattr(summary, "cost_usd")


def test_event_ingest_sends_the_payload_key_and_a_timestamp(harness: Any) -> None:
    # events.Event has "payload"; anything sent as "data" was decoded into
    # nothing and silently dropped. A null timestamp was a 400.
    h = harness([Stub(json_body={"accepted": 1, "errors": 0})])
    result = h.caged.events.ingest(
        [
            EventPayload(
                type="llm_call",
                sandbox_id="sbx_1",
                session_id="ses_1",
                payload={"model": "claude", "tokens_in": 10},
                meta={"budget_usd": "10"},
            )
        ]
    )
    assert result.accepted == 1
    body = json.loads(h.only().content)
    event = body["events"][0]
    assert event["payload"] == {"model": "claude", "tokens_in": 10}
    assert event["meta"] == {"budget_usd": "10"}
    assert event["timestamp"].endswith("Z")
    assert "data" not in event
    assert "account_id" not in event


def test_event_data_alias_still_works_but_warns(harness: Any) -> None:
    h = harness([Stub(json_body={"accepted": 1, "errors": 0})])
    with pytest.warns(DeprecationWarning):
        h.caged.events.ingest(
            [EventPayload(type="tool_call", sandbox_id="sbx_1", data={"tool": "bash"})]
        )
    assert json.loads(h.only().content)["events"][0]["payload"] == {"tool": "bash"}


def test_an_oversized_batch_is_refused_before_the_network(harness: Any) -> None:
    h = harness([Stub(json_body={"accepted": 0, "errors": 0})])
    with pytest.raises(CagedError, match="1000"):
        h.caged.events.ingest(
            [EventPayload(type="command", sandbox_id="sbx_1")] * 1001
        )
    assert h.requests == []


def test_socket_ticket_is_minted_over_http_and_not_reused(harness: Any) -> None:
    h = harness([Stub(json_body={"ticket": "caged_wst_a.b", "expires_in": 60, "expires_at": "t"})])
    ticket = h.caged.socket_ticket()
    assert ticket.ticket == "caged_wst_a.b"
    assert ticket.expires_in == 60
    req = h.only()
    assert req.method == "POST"
    assert urlparse(str(req.url)).path == "/v1/auth/socket-ticket"
