# caged

Official Python SDK for the [Caged](https://caged.dev) AI Agent Sandbox Platform.

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
    # ... work with sandbox ...
    caged.sandboxes.destroy(sandbox.id)
```

## API Reference

### Sandboxes

| Method | Description |
|--------|-------------|
| `caged.sandboxes.create(template, cpus, memory_mb, ...)` | Create a sandbox |
| `caged.sandboxes.list()` | List all sandboxes |
| `caged.sandboxes.get(id)` | Get sandbox by ID |
| `caged.sandboxes.destroy(id)` | Destroy a sandbox |
| `caged.sandboxes.pause(id)` | Pause a sandbox |
| `caged.sandboxes.resume(id)` | Resume a paused sandbox |
| `caged.sandboxes.ports(id)` | List open ports |

### Files

| Method | Description |
|--------|-------------|
| `caged.files.list(sandbox_id, path)` | List directory contents |
| `caged.files.read(sandbox_id, path)` | Read file content |
| `caged.files.write(sandbox_id, path, content)` | Write file content |
| `caged.files.git_diff(sandbox_id)` | Get git diff |

### Snapshots

| Method | Description |
|--------|-------------|
| `caged.snapshots.list(sandbox_id)` | List snapshots |
| `caged.snapshots.create(sandbox_id, name, description)` | Create snapshot |
| `caged.snapshots.get(snapshot_id)` | Get snapshot details |
| `caged.snapshots.delete(snapshot_id)` | Delete snapshot |
| `caged.snapshots.download_url(snapshot_id)` | Get download URL |
| `caged.snapshots.restore(snapshot_id)` | Restore snapshot |

### Account

| Method | Description |
|--------|-------------|
| `caged.account.list_keys()` | List API keys |
| `caged.account.create_key(name)` | Create new API key |
| `caged.account.revoke_key(id)` | Revoke an API key |
| `caged.account.list_sessions()` | List active sessions |
| `caged.account.revoke_session(id)` | Revoke a session |

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
