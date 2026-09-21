# Changelog

All notable changes to the `caged-sdk` Python package (imported as `caged`).

## 0.3.0 — unreleased

The 0.1.0 client was written against a description of the API rather than
against the API, and 0.2.0 shipped as a rename of it: the distribution moved
from `caged` to `caged-sdk` and nothing else changed. The repairs that were
made lived in an internal copy inside `caged-api`, which ships to nobody, so
**no user has ever had a working `files.write`**. This release brings them
to the package `pip install caged-sdk` actually installs, and extends them
to the terminal, streaming, MCP, session, alert, notification and billing
surfaces that exist only here.

### Fixed — each failed on *every* call, not under some condition

- **`files.write`** — HTTP 400. The API reads the target path from the
  `?path=` query string and only the content from the body; the client sent
  both in the body.
- **`files.read`** — `json.JSONDecodeError`. The endpoint answers
  `text/plain`; the client parsed every response as JSON.
- **`files.list`** — `TypeError: unexpected keyword argument 'mod_time'`.
  The model declared `modified`, and typed directories as `"dir"` where the
  API says `"directory"`.
- **`snapshots.restore`** — HTTP 400. The API requires `target_sandbox_id`
  in the body: a snapshot is restored into a sandbox the caller names.
- **`snapshots.list` / `create` / `get`** — `TypeError: missing 1 required
  positional argument: 'account_id'`. Not a field on the payload.
- **`sandboxes.ports`** — `TypeError: unexpected keyword argument
  'preview_url'`. The model declared `state` and `url`, which this endpoint
  has never returned.
- **`sandboxes.trust_scores`** — `TypeError: missing 2 required positional
  arguments: 'sandbox_id' and 'factors'`. The listing returns
  `{session_id, score, updated_at}` only.
- **`account.list_keys`** — `TypeError: unexpected keyword argument 'scope'`.
- **`account.list_sessions`** — `TypeError: unexpected keyword argument 'ip'`.
- **`alerts.list`** — the endpoint answers
  `{alerts, total, limit, offset}`; the client iterated the response as if
  it were a bare array, so it iterated the *keys* of the object.
- **`alerts.list_rules` / `update_rule`** — `AlertRule` declared a
  top-level `threshold`, `cooldown_minutes` and `channels`; the rule's
  tunables are nested under `config`, and the endpoint accepts only
  `enabled` and `config`. `update_rule(**kwargs)` sent whatever it was
  handed.
- **`notifications.unread_count`** — `KeyError: 'count'`. The body is
  `{"unread_count": n}`.
- **`notifications.list`** — same bare-array mistake as `alerts.list`; the
  body is `{notifications, unread_count}`.
- **`sessions.replay`** — the body is `{events, has_more, next_seq, total}`,
  not an array of events, so paging was impossible and iteration was wrong.
- **`sessions.replay_summary`** — declared `cost_usd`, which this endpoint
  does not return; cost is on the session.
- **`billing.get_subscription`** — `Subscription.plan` could never be
  populated: the API has always called it `tier`.
- **`events.ingest`** — the server reads `payload`; everything sent under
  `data` was silently discarded, and an event without a `timestamp` was
  rejected with a 400 because it decodes into a non-nullable `time.Time`.
- **A duplicated `_AccountAPI`.** The shipped file defined the class twice;
  the second definition won, and it was the older one — `create_key`
  returned a raw dict and `list_sessions` splatted straight into a
  dataclass. A stray `_BillingAPI.restore` posting to a snapshot route was
  defined in the same stretch.
- **Every API error message was discarded.** The API answers RFC 7807
  problem details (`{type, title, status, detail}`); the client looked for a
  non-existent `error` key and rendered `"API error: 404"` instead of
  `"sandbox not found"`. Messages are now the server's own sentence, with
  `.detail` and the raw body on `.text`. The legacy `{"error": "..."}`
  shape is still understood.
- **`CagedTimeoutError` reported the wrong budget** for calls with a
  per-call timeout: `exec(..., timeout=7)` said 30s, the client default.
- **Every WebSocket asked for the `mcp` subprotocol**, including the
  terminal, leaving the handshake with no agreed subprotocol — tolerated by
  today's server and by nothing else.
- **`exec_stream` could never report an exit code.** It waited for a
  message type the terminal endpoint does not emit, so `exit_code` stayed
  `None` and the iterator ended only when the sandbox idled out; the output
  included the login banner, the shell's echo and the prompt.
- **A dropped socket lost the tail of the output.** The marker filter holds
  back a window so a marker split across two frames is still found, and
  nothing ever emptied it; a command whose entire output was shorter than
  the window produced nothing at all.

### Security

- **WebSockets no longer carry your API key in the URL.** A handshake
  cannot set an `Authorization` header, so the credential travels in the
  query string, where every proxy that logs a request line records it. The
  SDK now mints a single-use, one-minute ticket per socket
  (`POST /v1/auth/socket-ticket`, exposed as `caged.socket_ticket()`) and
  falls back to the key only against an API too old to serve tickets.
- URL path segments are quoted, so an unusual ID cannot escape its route.

### Changed — breaking

- `snapshots.restore(snapshot_id)` → `restore(snapshot_id, target_sandbox_id)`.
- `alerts.list()` returns `AlertPage` (`.alerts`, `.total`, `.limit`, `.offset`).
- `alerts.update_rule(id, **kwargs)` → `update_rule(id, enabled=None, config=None)`.
- `notifications.list()` returns `NotificationPage` (`.notifications`,
  `.unread_count`). `list_unread()` is the plain list.
- `notifications.update_config(**kwargs)` → `update_config(NotificationConfigUpdate(...))`.
- `sessions.replay()` returns `ReplayPage` (`.events`, `.has_more`, `.next_seq`).
- `files.git_diff` returns `GitDiff` (`files`, `diff`, `staged_diff`), not `str`.
- `account.create_key` returns `CreatedAPIKey` (`.key`, `.info`), not a dict.
- `files.list` defaults to `/workspace`, matching the API, instead of `/`.
- `sandboxes.create` no longer forces `cpus=2, memory_mb=512` into every
  request; unset fields are omitted so the server's defaults apply. An
  unknown keyword raises `CagedError` instead of `TypeError`.
- `Session` → `AccountSession`, `TrustScore` → `TrustScoreSummary`. Both old
  names remain importable and will not be removed before 0.5.0.
- `Caged("")` raises `CagedError`, not `ValueError`.
- `requires-python` is now `>=3.10`. 3.9 is end-of-life, and mypy will no
  longer type-check it — a declared floor that no gate can verify is not
  support.

### Deprecated

Warned, not removed; all of these stay until at least 0.5.0.

- `snapshots.download_url()` → `snapshots.download()`, which also returns
  the expiry.
- `Subscription.plan` → `Subscription.tier`.
- `EventPayload.data` → `EventPayload.payload`.

### Added

- `CagedPlanLimitError` and `CagedAPIError.reason` (a `Refusal` with `code`,
  `message`, `action`, `subject_type`, `subject_id`). A plan limit is a 403
  and used to arrive as `CagedAuthError` — telling a caller their key was
  wrong when the key was fine.
- Error hierarchy under `CagedError`: `CagedValidationError`,
  `CagedAuthError`, `CagedNotFoundError`, `CagedRateLimitError`,
  `CagedServerError`, `CagedConnectionError`, `CagedTimeoutError`. The API
  ones subclass `CagedAPIError`, so an existing `except CagedAPIError` still
  catches them.
- `sandboxes.logs(id, tail=None)`, `account.get()`, `sessions.list(page)`,
  `snapshots.download()`, `billing.get_usage()`,
  `notifications.list_unread()`, `caged.socket_ticket()`.
- Session cost arrives split: `llm_cost` + `compute_cost` = `total_cost`.
- Every response model is built through `from_api`, which ignores unknown
  keys and defaults absent ones, so a field added server-side can never
  again raise in a shipped client. The same applies to MCP tool, resource
  and prompt definitions.
- `transport=` on the constructor, for injecting an `httpx` transport; that
  is how the test suite avoids the network.
- A test suite: 155 cases, including one per public method that calls it as
  the first call on a freshly constructed client, and a fake WebSocket for
  the three socket clients. CI runs them without `|| true` — it previously
  ran `pytest tests/ -v || true` against a `tests/` directory that did not
  exist, which is how all of the above stayed invisible behind a green run.
- `scripts/verify_wheel.py`, run in CI against the *installed* wheel. Every
  previous check read the working tree, which is why 0.2.0 could be a
  repackage of 0.1.0 and pass.
- `ruff` and `mypy --strict`; both are clean, and neither uses
  `--ignore-missing-imports`.

## 0.2.0

- Renamed the distribution from `caged` to `caged-sdk`. PyPI's `caged`
  belongs to an unrelated project. No code changes: the `caged_sdk-0.2.0`
  wheel is byte-identical to the 0.1.0 source.

## 0.1.0

- Initial release.
