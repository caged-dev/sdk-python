# caged-sdk

Official Python SDK for the [Caged](https://caged.dev) AI Agent Sandbox
Platform. A thin, typed wrapper over the Caged REST API — no client-side
business logic, no hidden state, one HTTP call per method.

[![PyPI](https://img.shields.io/pypi/v/caged-sdk)](https://pypi.org/project/caged-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/caged-sdk)](https://pypi.org/project/caged-sdk/)

Python 3.10+. Two dependencies: `httpx` and `websockets`.

## Installation

```bash
pip install caged-sdk
```

The distribution is **`caged-sdk`**; the import name is `caged`. PyPI's
`caged` is an unrelated project, which is why installing the wrong one looks
fine until the first call.

> **0.3.0 repairs calls that failed for every user of 0.1.0 and 0.2.0.**
> `files.write`, `files.read`, `snapshots.restore` and nine response models
> could not succeed against the live API. See [CHANGELOG.md](CHANGELOG.md).

## Quick Start

```python
import os
from caged import Caged

with Caged(api_key=os.environ["CAGED_API_KEY"]) as caged:
    # Create a sandbox. `template` is required.
    sandbox = caged.sandboxes.create(template="python-312", memory_mb=1024)
    print(f"Sandbox {sandbox.id} is {sandbox.status}")

    # Run a command. A non-zero exit code is a result, not an exception.
    result = caged.sandboxes.exec(sandbox.id, "python --version")
    print(result.output, result.exit_code, result.ok)

    # Write and read files
    caged.files.write(sandbox.id, "/workspace/hello.py", "print('hi')")
    content = caged.files.read(sandbox.id, "/workspace/hello.py")

    # Snapshot, then restore it into a fresh sandbox
    snapshot = caged.snapshots.create(sandbox.id, name="checkpoint-1")
    replica = caged.sandboxes.create(template="python-312")
    caged.snapshots.restore(snapshot.id, replica.id)

    caged.sandboxes.destroy(replica.id)
    caged.sandboxes.destroy(sandbox.id)
```

## Configuration

```python
caged = Caged(
    api_key="caged_sk_...",             # Required
    base_url="https://api.caged.dev",   # Optional (default)
    timeout=30.0,                       # Optional: seconds
)
```

Every request is bounded by a timeout. `sandboxes.create` and
`sandboxes.exec` use longer defaults (360s and 300s) because a create can
clone a repo and install agents, and an exec can be a long-running agent
prompt. `exec` takes a per-call `timeout`.

Use the client as a context manager, or call `close()`, so the underlying
connection pool is released.

## Templates

`minimal`, `node-22`, `node-20`, `python-312`, `python-311`, `desktop`. The
aliases `node`, `python`, `gui` and `computer` also resolve. An unknown
template is a 400 that names the valid set.

## Field naming

Response models carry the API's own JSON keys — `memory_mb`, `exit_code`,
`preview_url`, `mod_time` — rather than renamed equivalents. Models ignore
response fields they do not know and default the ones a response omits, so a
newer server cannot break an older client.

## Streaming Exec

```python
import asyncio
from caged import Caged

async def main() -> None:
    with Caged(api_key="caged_sk_...") as caged:
        sandbox = caged.sandboxes.create(template="node-20")

        stream = await caged.sandboxes.exec_stream(sandbox.id, "npm test")
        async for chunk in stream:
            print(chunk, end="")

        # None if the connection dropped before the command finished: the
        # status is then unknown, not zero.
        print(f"\nExit code: {stream.exit_code}")

asyncio.run(main())
```

There is no streaming exec endpoint. This drives the terminal WebSocket and
brackets the command with markers carrying a per-call nonce, so the login
banner, the shell's echo and the prompt are stripped and the exit code is
read back from the shell.

## Interactive Terminal (WebSocket)

```python
import asyncio
from caged import Caged

async def main() -> None:
    with Caged(api_key="caged_sk_...") as caged:
        sandbox = caged.sandboxes.create(template="node-20")

        terminal = await caged.sandboxes.terminal(sandbox.id, rows=40, cols=120)
        terminal.on_output(lambda data: print(data, end=""))
        await terminal.send("ls -la\n")
        await asyncio.sleep(2)
        await terminal.resize(50, 160)
        await terminal.close()

asyncio.run(main())
```

A WebSocket handshake cannot carry an `Authorization` header, so the
credential rides in the URL — where every proxy that logs a request line
sees it. The SDK therefore mints a single-use ticket
(`POST /v1/auth/socket-ticket`, exposed as `caged.socket_ticket()`) for each
socket and sends that instead of your API key, falling back to the key only
against an API too old to serve tickets.

## MCP (Model Context Protocol)

```python
import asyncio
from caged import Caged

async def main() -> None:
    with Caged(api_key="caged_sk_...") as caged:
        sandbox = caged.sandboxes.create(template="node-20")

        mcp = await caged.sandboxes.mcp(sandbox.id)  # initialises the session

        for tool in await mcp.list_tools():
            print(f"  {tool.name}: {tool.description}")

        result = await mcp.call_tool("terminal_exec", {"command": "npm test"})
        print(result["content"][0]["text"])

        await mcp.close()

asyncio.run(main())
```

`MCPClient` also has `list_resources()`, `read_resource(uri)`,
`list_prompts()`, `get_prompt(name, arguments)`, `ping()`,
`on_notification(handler)` and `on_close(handler)`. A JSON-RPC error
surfaces as `MCPError` carrying the server's `code` and `message`.

## Session Replay

```python
caged = Caged(api_key="caged_sk_...")

# Every session in the account, newest first (paginated)
page = caged.sessions.list(page=1)
for s in page.data:
    print(f"{s.id}: {s.agent_type} — LLM ${s.llm_cost:.4f} "
          f"+ compute ${s.compute_cost:.4f} = ${s.total_cost:.4f}")
print(f"page {page.pagination.page} of {page.pagination.total_pages}")

# Or just one sandbox's sessions
sessions = caged.sessions.list_by_sandbox("sandbox-id")

# Replay timeline. The endpoint answers an object, not a bare array.
replay = caged.sessions.replay(sessions[0].id, limit=500)
for event in replay.events:
    print(f"[{event.timestamp}] #{event.sequence} {event.type}: {event.data}")
while replay.has_more:
    replay = caged.sessions.replay(sessions[0].id, after_seq=replay.next_seq)

summary = caged.sessions.replay_summary(sessions[0].id)
print(f"{summary.event_count} events over {summary.duration_ms}ms")
```

A session's spend arrives as two halves and their sum: `llm_cost` (model
tokens) plus `compute_cost` (this session's share of its sandbox's machine
time) equals `total_cost`. `cost_usd` is the same blended total under the
older name.

## Events Ingestion

```python
from caged import Caged, EventPayload

caged = Caged(api_key="caged_sk_...")

response = caged.events.ingest([
    EventPayload(
        type="llm_call",
        sandbox_id="sandbox-id",
        # The server reads `payload`. Anything sent as `data` was discarded.
        payload={"model": "claude-4", "tokens_in": 500, "tokens_out": 200},
    ),
])
print(f"Accepted: {response.accepted}, Errors: {response.errors}")
```

Max 1000 events per batch — the SDK refuses a larger one rather than letting
the API reject the lot. `account_id` is taken from the API key. An omitted
`timestamp` is stamped as "now" in UTC, because the server rejects an event
without one.

## Alerts & Notifications

```python
from caged import Caged, RuleConfig

caged = Caged(api_key="caged_sk_...")

page = caged.alerts.list(limit=50)           # an object, not a bare list
for alert in page.alerts:
    print(f"[{alert.severity}] {alert.title}: {alert.message}")
print(f"{page.total} alerts in total")

caged.alerts.resolve(page.alerts[0].id)

# Rules: the tunables live in `config`, and only what you pass is changed.
for rule in caged.alerts.list_rules():
    print(rule.type, rule.enabled, rule.config.threshold_percent)
    caged.alerts.update_rule(rule.id, config=RuleConfig(threshold_percent=80))

print(f"Unread: {caged.notifications.unread_count()}")
inbox = caged.notifications.list(limit=20)
for note in inbox.notifications:
    print(f"{note.channel}: {note.title} — {note.message}")
caged.notifications.mark_all_read()
```

A notification config read never returns a credential — for a webhook the
URL *is* the credential — so each is reported as a `*_configured` boolean
plus a hint. Write them with `NotificationConfigUpdate`, where an omitted
field is left alone and `CLEAR_CREDENTIAL` removes one.

## Billing

```python
caged = Caged(api_key="caged_sk_...")

sub = caged.billing.get_subscription()
print(f"Plan: {sub.tier}, Status: {sub.status}")   # the API calls it `tier`

usage = caged.billing.get_usage()
print(f"{usage.compute_minutes} compute minutes this period")

print(f"Upgrade: {caged.billing.create_checkout('pro')}")
```

## API Reference

### Sandboxes

| Method | Endpoint |
|--------|----------|
| `caged.sandboxes.create(template, **params)` | `POST /v1/sandboxes` |
| `caged.sandboxes.list()` | `GET /v1/sandboxes` |
| `caged.sandboxes.get(id)` | `GET /v1/sandboxes/{id}` |
| `caged.sandboxes.exec(id, command, timeout=300.0)` | `POST /v1/sandboxes/{id}/exec` |
| `await caged.sandboxes.exec_stream(id, command)` | `WS /v1/sandboxes/{id}/terminal` |
| `await caged.sandboxes.terminal(id, rows=24, cols=80)` | `WS /v1/sandboxes/{id}/terminal` |
| `await caged.sandboxes.mcp(id)` | `WS /v1/sandboxes/{id}/mcp` |
| `caged.sandboxes.destroy(id)` | `DELETE /v1/sandboxes/{id}` |
| `caged.sandboxes.pause(id)` | `POST /v1/sandboxes/{id}/pause` |
| `caged.sandboxes.resume(id)` | `POST /v1/sandboxes/{id}/resume` |
| `caged.sandboxes.ports(id)` | `GET /v1/sandboxes/{id}/ports` |
| `caged.sandboxes.logs(id, tail=None)` | `GET /v1/sandboxes/{id}/logs` |
| `caged.sandboxes.trust_scores(sandbox_id)` | `GET /v1/trust/sandboxes/{id}` |

Any field of `SandboxCreateParams` may be passed to `create` as a keyword:
`cpus`, `memory_mb`, `disk_gb`, `network_mode`, `allowlist`, `env`, `repo`,
`repo_branch`, `repo_commit`, `repo_subdir`, `repo_token`, `budget`,
`init_script`, `secrets`, `timeout`, `packages`, `agents`, `persona_id`,
`harness_id`. Unset fields are omitted so the server's defaults apply.

### Files

| Method | Endpoint |
|--------|----------|
| `caged.files.list(sandbox_id, path="/workspace")` | `GET /v1/sandboxes/{id}/files` |
| `caged.files.read(sandbox_id, path)` | `GET /v1/sandboxes/{id}/files/content` |
| `caged.files.write(sandbox_id, path, content)` | `PUT /v1/sandboxes/{id}/files/content` |
| `caged.files.git_diff(sandbox_id, path=None)` | `GET /v1/sandboxes/{id}/git/diff` |

`read` returns the file's text (the endpoint answers `text/plain`); files
over 1MB are rejected by the API. `git_diff` returns a `GitDiff` with
`files`, `diff` and `staged_diff`, not a bare string.

### Snapshots

| Method | Endpoint |
|--------|----------|
| `caged.snapshots.list(sandbox_id)` | `GET /v1/sandboxes/{id}/snapshots` |
| `caged.snapshots.create(sandbox_id, name=None, description=None)` | `POST /v1/sandboxes/{id}/snapshots` |
| `caged.snapshots.get(snapshot_id)` | `GET /v1/snapshots/{id}` |
| `caged.snapshots.delete(snapshot_id)` | `DELETE /v1/snapshots/{id}` |
| `caged.snapshots.download(snapshot_id)` | `GET /v1/snapshots/{id}/download` |
| `caged.snapshots.restore(snapshot_id, target_sandbox_id)` | `POST /v1/snapshots/{id}/restore` |

`restore` needs the sandbox to restore *into* — a snapshot is not
automatically put back where it came from.

### Sessions

| Method | Endpoint |
|--------|----------|
| `caged.sessions.list(page=1, per_page=None)` | `GET /v1/sessions` |
| `caged.sessions.list_by_sandbox(sandbox_id)` | `GET /v1/sandboxes/{id}/sessions` |
| `caged.sessions.get(session_id)` | `GET /v1/sessions/{id}` |
| `caged.sessions.replay(session_id, after_seq=None, limit=None, type=None)` | `GET /v1/sessions/{id}/replay` |
| `caged.sessions.replay_summary(session_id)` | `GET /v1/sessions/{id}/replay/summary` |

### Events

| Method | Endpoint |
|--------|----------|
| `caged.events.ingest(events)` | `POST /v1/events/ingest` |

### Alerts

| Method | Endpoint |
|--------|----------|
| `caged.alerts.list(limit=None, offset=None)` | `GET /v1/alerts` |
| `caged.alerts.get(id)` | `GET /v1/alerts/{id}` |
| `caged.alerts.resolve(id)` | `POST /v1/alerts/{id}/resolve` |
| `caged.alerts.list_rules()` | `GET /v1/alerts/rules` |
| `caged.alerts.update_rule(id, enabled=None, config=None)` | `PUT /v1/alerts/rules/{id}` |

### Notifications

| Method | Endpoint |
|--------|----------|
| `caged.notifications.list(unread_only=False, limit=None)` | `GET /v1/notifications` |
| `caged.notifications.list_unread(limit=None)` | `GET /v1/notifications?unread=true` |
| `caged.notifications.unread_count()` | `GET /v1/notifications/unread-count` |
| `caged.notifications.mark_read(id)` | `POST /v1/notifications/{id}/read` |
| `caged.notifications.mark_all_read()` | `POST /v1/notifications/read-all` |
| `caged.notifications.get_config()` | `GET /v1/notifications/config` |
| `caged.notifications.update_config(update)` | `PUT /v1/notifications/config` |

### Account

| Method | Endpoint |
|--------|----------|
| `caged.account.get()` | `GET /v1/account` |
| `caged.account.list_keys()` | `GET /v1/account/keys` |
| `caged.account.create_key(name, scope="full")` | `POST /v1/account/keys` |
| `caged.account.revoke_key(id)` | `DELETE /v1/account/keys/{id}` |
| `caged.account.list_sessions()` | `GET /v1/account/sessions` |
| `caged.account.revoke_session(id)` | `DELETE /v1/account/sessions/{id}` |

`create_key` returns a `CreatedAPIKey`: `.key` is the secret, shown exactly
once, and `.info` is the metadata `list_keys` also returns.

### Billing

| Method | Endpoint |
|--------|----------|
| `caged.billing.get_subscription()` | `GET /v1/billing/subscription` |
| `caged.billing.get_usage()` | `GET /v1/billing/usage` |
| `caged.billing.create_checkout(plan)` | `POST /v1/billing/checkout` |
| `caged.billing.create_portal()` | `POST /v1/billing/portal` |
| `caged.billing.cancel()` | `POST /v1/billing/cancel` |

### WebSockets

| Method | Endpoint |
|--------|----------|
| `caged.socket_ticket()` | `POST /v1/auth/socket-ticket` |

## Error Handling

Every failure is a `CagedError`. API failures are `CagedAPIError` or one of
its subclasses, and carry the server's own RFC 7807 problem detail as the
message.

```python
from caged import (
    Caged,
    CagedAPIError,
    CagedNotFoundError,
    CagedRateLimitError,
    CagedTimeoutError,
    CagedValidationError,
)

try:
    caged.sandboxes.get("sbx_does_not_exist")
except CagedNotFoundError:
    print("no such sandbox")
except CagedValidationError as e:
    print(f"rejected: {e}")
except CagedRateLimitError:
    print("slow down")
except CagedTimeoutError as e:
    print(f"timed out after {e.timeout}s")
except CagedAPIError as e:
    print(f"HTTP {e.status}: {e} ({e.detail})")
```

| Class | Raised for |
|-------|-----------|
| `CagedValidationError` | 400, 422 |
| `CagedAuthError` | 401, 403 |
| `CagedNotFoundError` | 404 |
| `CagedPlanLimitError` | 403 with `reason.code == "plan_limit_reached"` |
| `CagedRateLimitError` | 429 |
| `CagedServerError` | 5xx |
| `CagedAPIError` | any other non-2xx (base class of the above) |
| `CagedTimeoutError` | the request exceeded its timeout |
| `CagedConnectionError` | the transport failed before a response arrived |
| `MCPError` | a JSON-RPC error from the sandbox's MCP server |
| `CagedError` | base class of everything above |

Refusals the API classified also carry a machine-readable `reason` (`code`,
`message`, `action`, `subject_type`, `subject_id`). Branch on `reason.code` —
the prose message may be reworded, the code will not.

## Development

```bash
pip install -e '.[dev]'
ruff check caged/ tests/ scripts/   # lint
mypy                                # type check (strict)
pytest                              # tests
```

Tests use `httpx.MockTransport` and a fake WebSocket; nothing in the suite
touches the network.

Releasing also means proving the artifact carries the code, not just the
version number:

```bash
python -m build
python -m venv /tmp/verify && /tmp/verify/bin/pip install dist/*.whl
/tmp/verify/bin/python scripts/verify_wheel.py 0.3.0
```

## License

MIT
