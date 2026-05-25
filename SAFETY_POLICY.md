# Safety Policy (v1)

This document defines the hard safety boundary between inbound text (phone messages, webhooks, LLM output) and **execution-capable connectors** (for example `tmux`, later `ssh`, `k8s`, etc.).

## Principles

- Deny by default for execution.
- Deterministic evaluation (no LLM in the decision loop).
- Least privilege.
- Full audit trail.

## Command Classes

- `chat`: natural language intended for an agent pane.
- `read`: safe, non-mutating inspection commands.
- `change`: potentially mutating actions (installs, restarts, edits).
- `destructive`: high-risk operations (delete/wipe/reset).

## Decisions

- `allow`: execute immediately.
- `needs_approval`: create a pending approval. No execution until approved.
- `blocked`: do not execute (rare in v1; used for empty payloads).

## tmux Connector Rules

Config keys:

- `mode`: `chat` (default) or `shell`
- `allow_shell_metachar`: boolean (default false)

Behavior:

- In `chat` mode, most text is allowed.
- Dangerous patterns (like `rm -rf`) require approval and generate a confirm token.
- Shell metacharacters (`;`, `|`, `&&`, backticks, redirects) require approval unless explicitly allowed.

## Approval Workflow

- `needs_approval` creates a `command_approvals` record.
- For `destructive` approvals, the approver must supply the `confirm_token`.
- Approving executes immediately and marks the approval `executed`.

API:

- `GET /api/v1/approvals?status=pending`
- `POST /api/v1/approvals/{id}/approve` with optional `{ "confirm_token": "...", "reason": "..." }`
- `POST /api/v1/approvals/{id}/reject` with optional `{ "reason": "..." }`

## Non-Goals (v1)

- Streaming tmux output back into Norman.
- Multi-party approvals.
- Per-agent/per-user policy profiles.

Those are planned next.

## Global Controls

Configured in `config.yaml`:

- `safety_execution_enabled`: when false, approvals can be created/recorded but nothing executes.
- `safety_read_only`: when true, approvals can be created/recorded but nothing executes.

## Per-Connector Policy (tmux)

Add a `policy` object inside the tmux connector config:

```json
{
  "session": "ops",
  "target": "ops:0.0",
  "policy": {
    "mode": "shell",
    "allowed_verbs": ["ls", "cat", "tail", "grep"],
    "blocked_verbs": ["rm"],
    "rate_limit_per_min": 10,
    "max_length": 280
  }
}
```

Notes:
- If `allowed_verbs` is set, any verb not in the allowlist requires approval.
- `blocked_patterns` and `require_approval_patterns` accept regex strings.
