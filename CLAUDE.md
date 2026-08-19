# Caged Python SDK — Claude Code Instructions

This is the published Python client (`caged` on PyPI) for **Caged** (caged.dev), an AI Agent Sandbox Platform by Bytangle Ltd. It corresponds to `apps/core/sdk/python/` when checked out inside the `caged-dev/workspace` workspace, but this repo also works standalone (e.g. Claude Code on the web opened directly here).

**Source of truth for shared conventions is `caged-dev/workspace`.** This repo's `.claude/skills/` and `.claude/agents/` are re-synced from there at the start of every Claude Code web session (see `.claude/hooks/session-start.sh`) — edit skills/agents in `workspace`, not here; local edits here are overwritten on the next session start.

## SDK Design Principles
1. **Thin wrapper** — 1:1 mapping to the REST API, no business logic
2. **Type-safe** — full Python type hints
3. **Async-first**, with sync support
4. **Zero deps (almost)** — only `httpx` + `websockets`
5. **Error hierarchy** — specific error classes per failure mode

## Critical Rules
- NEVER hardcode API URLs — accept `base_url` in the client constructor
- NEVER store API keys in memory longer than needed
- ALWAYS test against a mocked HTTP layer (no real API calls in tests)
- SDK version is INDEPENDENT from the backend (`caged-api`) version
- Deprecate with warnings before removing (minimum 2 minor versions)
- Types here must track `caged-api`'s API contract — verify against it before adding/changing a method
- Ship without tests for the changed code — never

## Quality Gate
Not done until: types match the current API spec; all methods have tests; README updated with examples; CHANGELOG updated; works on Python 3.10+; error messages are helpful to developers.

## Skills & Subagents
- `.claude/skills/<name>/SKILL.md` — auto-discovered by the Skill tool; most relevant here: `sdk-development`, `api-design`, `interface-contracts`, `testing`, `code-review`.
- `.claude/agents/<name>.md` — dispatch via the Agent tool: `sdk-engineer`, `qa-engineer`.
- Full workspace-level context (product specs, roadmap, branding): `caged-dev/workspace` repo.
