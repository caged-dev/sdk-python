# caged

Official Python SDK for the [Caged](https://caged.dev) AI Agent Sandbox Platform.

[![PyPI](https://img.shields.io/pypi/v/caged)](https://pypi.org/project/caged/)
[![Python](https://img.shields.io/pypi/pyversions/caged)](https://pypi.org/project/caged/)

## Installation

```bash
pip install caged
```

## Quick Start

```python
from caged import Caged

caged = Caged(api_key="caged_sk_...")

# Create a sandbox
sandbox = caged.sandboxes.create(template="node-20", memory_mb=1024)
print(f"Sandbox {sandbox.id} is {sandbox.status}")

# Run a command
result = caged.sandboxes.exec(sandbox.id, "echo 'hello world'")
print(result.output)

# Write and read files
caged.files.write(sandbox.id, "/workspace/hello.py", "print('hi')")
content = caged.files.read(sandbox.id, "/workspace/hello.py")

# Create a snapshot
snapshot = caged.snapshots.create(sandbox.id, name="checkpoint-1")

# Clean up
caged.sandboxes.destroy(sandbox.id)
```

## Context Manager

```python
with Caged(api_key="caged_sk_...") as caged:
    sandbox = caged.sandboxes.create(template="python-312")
    result = caged.sandboxes.exec(sandbox.id, "python --version")
    print(result.output)
    caged.sandboxes.destroy(sandbox.id)
```

## Interactive Terminal (WebSocket)

```python
import asyncio
from caged import Caged

async def main():
    caged = Caged(api_key="caged_sk_...")
    sandbox = caged.sandboxes.create(template="node-20")

    terminal = await caged.sandboxes.terminal(sandbox.id)
    terminal.on_output(lambda data: print(data, end=""))
    await terminal.send("ls -la\n")
    await asyncio.sleep(2)
    await terminal.close()

asyncio.run(main())
```

## Streaming Exec

```python
import asyncio
from caged import Caged

async def main():
    caged = Caged(api_key="caged_sk_...")
    sandbox = caged.sandboxes.create(template="node-20")

    stream = await caged.sandboxes.exec_stream(sandbox.id, "npm test")
    async for chunk in stream:
        print(chunk, end="")
    print(f"\nExit code: {stream.exit_code}")

asyncio.run(main())
```

## MCP (Model Context Protocol)

```python
import asyncio
from caged import Caged

async def main():
    caged = Caged(api_key="caged_sk_...")
    sandbox = caged.sandboxes.create(template="node-20")

    mcp = await caged.sandboxes.mcp(sandbox.id)

    # List available tools
    tools = await mcp.list_tools()
    for tool in tools:
        print(f"  {tool.name}: {tool.description}")

    # Call a tool
    result = await mcp.call_tool("terminal_exec", {"command": "npm test"})
    print(result["content"][0]["text"])

    await mcp.close()

asyncio.run(main())
```

## Session Replay

```python
caged = Caged(api_key="caged_sk_...")

# List sessions for a sandbox
sessions = caged.sessions.list_by_sandbox("sandbox-id")
for s in sessions:
    print(f"{s.id}: {s.agent_type} — ${s.cost_usd:.4f}")

# Get replay timeline
events = caged.sessions.replay(sessions[0].id)
for event in events:
    print(f"[{event.timestamp}] {event.type}: {event.data}")

# Get summary
summary = caged.sessions.replay_summary(sessions[0].id)
print(f"Duration: {summary.duration_ms}ms, Cost: ${summary.cost_usd:.4f}")
```

## Events Ingestion

```python
from caged import Caged, EventPayload

caged = Caged(api_key="caged_sk_...")

response = caged.events.ingest([
    EventPayload(
        type="llm_call",
        sandbox_id="sandbox-id",
        data={"model": "claude-4", "tokens_in": 500, "tokens_out": 200},
    ),
])
print(f"Accepted: {response.accepted}, Errors: {response.errors}")
```

## Alerts & Notifications

```python
caged = Caged(api_key="caged_sk_...")

# List alerts
alerts = caged.alerts.list()
for alert in alerts:
    print(f"[{alert.severity}] {alert.message}")

# Resolve an alert
caged.alerts.resolve(alerts[0].id)

# Check notifications
count = caged.notifications.unread_count()
print(f"Unread: {count}")

notifications = caged.notifications.list()
caged.notifications.mark_all_read()
```

## Billing

```python
caged = Caged(api_key="caged_sk_...")

sub = caged.billing.get_subscription()
print(f"Plan: {sub.plan}, Status: {sub.status}")

# Get checkout URL for upgrade
url = caged.billing.create_checkout("pro")
print(f"Upgrade: {url}")
```

## Full API Reference

### Sandboxes

| Method | Description |
|--------|-------------|
| `sandboxes.create(template, cpus, memory_mb, ...)` | Create a sandbox |
| `sandboxes.list()` | List all sandboxes |
| `sandboxes.get(id)` | Get sandbox by ID |
| `sandboxes.destroy(id)` | Destroy a sandbox |
| `sandboxes.exec(id, command)` | Run a command (sync) |
| `await sandboxes.exec_stream(id, command)` | Stream command output (async) |
| `await sandboxes.terminal(id)` | Interactive terminal (async) |
| `await sandboxes.mcp(id)` | MCP tool client (async) |
| `sandboxes.pause(id)` | Pause a sandbox |
| `sandboxes.resume(id)` | Resume a paused sandbox |
| `sandboxes.logs(id, tail=N)` | Get sandbox logs |
| `sandboxes.ports(id)` | List open ports |
| `sandboxes.trust_scores(sandbox_id)` | Get trust scores |

### Files

| Method | Description |
|--------|-------------|
| `files.list(sandbox_id, path)` | List directory contents |
| `files.read(sandbox_id, path)` | Read file content |
| `files.write(sandbox_id, path, content)` | Write file content |
| `files.git_diff(sandbox_id)` | Get git diff |

### Snapshots

| Method | Description |
|--------|-------------|
| `snapshots.list(sandbox_id)` | List snapshots |
| `snapshots.create(sandbox_id, name, description)` | Create snapshot |
| `snapshots.get(snapshot_id)` | Get snapshot details |
| `snapshots.delete(snapshot_id)` | Delete snapshot |
| `snapshots.download_url(snapshot_id)` | Get download URL |
| `snapshots.restore(snapshot_id)` | Restore snapshot |

### Sessions (Agent history & replay)

| Method | Description |
|--------|-------------|
| `sessions.list_by_sandbox(sandbox_id)` | List agent sessions |
| `sessions.get(session_id)` | Get session details |
| `sessions.replay(session_id)` | Get replay timeline |
| `sessions.replay_summary(session_id)` | Get replay summary |

### Events

| Method | Description |
|--------|-------------|
| `events.ingest(events)` | Ingest observability events |

### Alerts

| Method | Description |
|--------|-------------|
| `alerts.list()` | List all alerts |
| `alerts.get(id)` | Get alert by ID |
| `alerts.resolve(id)` | Resolve an alert |
| `alerts.list_rules()` | List alert rules |
| `alerts.update_rule(id, **kwargs)` | Update alert rule |

### Notifications

| Method | Description |
|--------|-------------|
| `notifications.list()` | List notifications |
| `notifications.unread_count()` | Get unread count |
| `notifications.mark_read(id)` | Mark as read |
| `notifications.mark_all_read()` | Mark all as read |
| `notifications.get_config()` | Get notification config |
| `notifications.update_config(**kwargs)` | Update config |

### Account

| Method | Description |
|--------|-------------|
| `account.list_keys()` | List API keys |
| `account.create_key(name)` | Create new API key |
| `account.revoke_key(id)` | Revoke an API key |
| `account.list_sessions()` | List active sessions |
| `account.revoke_session(id)` | Revoke a session |

### Billing

| Method | Description |
|--------|-------------|
| `billing.get_subscription()` | Get subscription details |
| `billing.create_checkout(plan)` | Get Stripe checkout URL |
| `billing.create_portal()` | Get billing portal URL |
| `billing.cancel()` | Cancel subscription |

## Error Handling

```python
from caged import Caged, CagedAPIError, CagedTimeoutError

caged = Caged(api_key="caged_sk_...")

try:
    caged.sandboxes.get("nonexistent")
except CagedAPIError as e:
    print(f"API error {e.status}: {e}")
except CagedTimeoutError as e:
    print(f"Timeout: {e}")
```

## License

MIT
