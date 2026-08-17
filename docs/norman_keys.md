# Norman Keys

`Norman Keys` is a secret-access broker for Norman. It is not the long-term
system of record for secrets. Its job is to decide when an agent may access a
secret, request human approval when policy requires it, mint or retrieve a
scoped credential for a limited period of time, and keep a clean audit trail.

## Problem

Norman already has command approvals, execution safety controls, notifications,
and a clear operator-control roadmap. What is missing is the same control model
for secrets.

Today, many environments still rely on plaintext local files, long-lived
password reuse, and direct access patterns where an agent or script can read a
secret without a time limit or operator checkpoint. That is the wrong shape for
shared infrastructure and for agent-driven work.

## Goal

Build a first-class secret access layer in Norman with these properties:

- deny by default
- explicit identity for every requester
- policy-driven approvals
- time-bounded leases
- full audit trail
- revocation
- no secret sprawl in logs, prompts, or transcripts

## Design Principles

- Norman is the policy and approval plane.
- A dedicated backend is the secret source of truth.
- Agents should receive the minimum access needed for the minimum time needed.
- Prefer issuing short-lived backend credentials over handing out static
  passwords.
- If a static password must be used, the lease applies to the right to read or
  use it, not to the secret value itself.
- Secrets should be injected into actions when possible, not displayed back to
  the model.

## Existing Norman Features To Reuse

- approval APIs and pending-approval UI
- webhook or phone notifications for operator attention
- per-agent policy profiles
- safety execution controls and read-only mode
- operator modes such as `auto`, `manual`, and `shared`

This work should extend those primitives rather than create a parallel control
system.

## Scope

### In Scope

- secret access requests from agents, subagents, and human-triggered jobs
- per-secret and per-role policy evaluation
- approval workflows with TTL and reason
- lease issuance, renewal, expiry, and revocation
- audit logging
- provider abstraction for one or more secret backends
- migration away from repo-local plaintext secret files

### Out Of Scope For v1

- being the primary encrypted secret database
- multi-party quorum approvals
- complex cryptographic escrow
- broad PAM or workstation login brokering

## Core Objects

### Secret Backend

Provide a backend abstraction with at least these provider types:

- `file`: transitional provider that reads existing local secret files during
  migration
- `openbao`: preferred open-source long-term backend
- `infisical`: optional backend when approval and access workflows are desired
  out of the box

Backend interface:

- `describe_secret(path)`
- `read_secret(path, identity, ttl)`
- `issue_role(role, identity, ttl)`
- `renew_lease(lease_id, ttl)`
- `revoke_lease(lease_id)`

### Secret Request

Represents a single request from an agent or user to access a secret or assume
an access role.

Suggested fields:

- `id`
- `requester_type` (`human`, `agent`, `subagent`, `job`)
- `requester_id`
- `session_id`
- `parent_request_id`
- `secret_path` or `role_name`
- `intent`
- `requested_ttl_seconds`
- `requested_mode` (`read`, `inject`, `execute_with_secret`)
- `status` (`pending`, `approved`, `rejected`, `issued`, `expired`, `revoked`)
- `reason`
- `created_at`
- `decided_at`
- `decided_by`

### Secret Lease

Represents the time-bounded access Norman granted.

Suggested fields:

- `id`
- `request_id`
- `provider`
- `provider_lease_id`
- `issued_to`
- `scope`
- `granted_ttl_seconds`
- `expires_at`
- `renewable`
- `status` (`active`, `expired`, `revoked`)
- `last_used_at`
- `revoked_at`
- `revoked_by`

### Secret Policy

Defines who can request what, under what conditions.

Suggested dimensions:

- requester identity or agent profile
- secret path or secret group
- allowed modes
- max TTL
- whether approval is required
- whether reuse is allowed inside an active lease window
- allowed networks or hosts
- whether raw secret reveal is forbidden

## Request Flow

1. An agent asks Norman for access to a secret path or role.
2. Norman resolves requester identity and session context.
3. Norman evaluates policy.
4. If allowed immediately, Norman issues a lease.
5. If approval is required, Norman creates a pending approval with:
   - requester
   - target secret or role
   - requested TTL
   - reason
   - session and parent-agent context
6. The operator approves or rejects from Norman's existing approvals surface.
7. On approval, Norman issues a lease from the configured backend.
8. The lease is either:
   - injected into a command or connector execution path
   - exposed to a trusted tool runtime
   - returned in a redacted or wrapped form if explicit reveal is allowed
9. On expiry or revoke, Norman deletes cached material and revokes the backend
   lease if supported.

## Approval Model

Secret access approvals should be separate from command approvals, but should
use the same Norman UI patterns and notification paths.

Minimum approval payload:

- requester
- session
- secret path or role
- mode
- requested TTL
- reason
- previous access history summary

Approval actions:

- approve once
- approve for N minutes
- reject
- revoke active lease

The approval record should never include plaintext secret values.

## Lease Model

The lease model is the critical piece.

Rules:

- every grant must have an expiry
- default TTL should be short, such as `15m`
- policy may cap TTL lower or higher
- agents may reuse an active lease only within the same session and only for the
  granted scope
- renewal may require a new approval depending on policy
- lease expiry must be enforced even if the agent is still running

For static secrets, Norman should still create an internal lease and only reveal
or inject the secret while that lease is active.

## Secret Delivery Modes

Support three delivery modes:

### `inject`

Norman passes the secret directly to a connector, job runner, or command
environment. The model does not see the plaintext value.

This should be the default.

### `read`

Norman returns the secret to a trusted caller that is explicitly allowed to see
the raw value.

This should be rare.

### `execute_with_secret`

Norman performs an allowed action using the secret on the caller's behalf and
returns only the result or artifact.

This is preferred for high-risk systems.

## Norman Identities

Add explicit identity classes:

- `operator`
- `agent`
- `subagent`
- `system_job`

Subagents must inherit a parent identity and may only request secrets allowed by
their parent scope and their own profile.

## Norman Guardian

Introduce a dedicated internal service or agent role named `norman-keys` or
`norman-guardian`.

Responsibilities:

- receive secret requests
- evaluate secret policy
- create approvals
- call the backend provider
- maintain lease state
- redact logs and transcripts

No ordinary agent should talk directly to the secret backend.

## UI And Operator Experience

Add a `Keys` surface in Norman with:

- pending secret access requests
- active leases
- recent revocations
- per-agent access history
- policy editor for paths, roles, and TTLs

Operator actions:

- approve for `15m`, `1h`, or custom TTL
- reject with reason
- revoke active lease immediately
- inspect which agent or subagent currently holds access

## Audit Requirements

Record these events:

- request created
- request approved
- request rejected
- lease issued
- lease renewed
- lease expired
- lease revoked
- secret injected into action
- raw secret reveal

Do not log plaintext secret values. Redact secret paths if needed for especially
sensitive entries, but preserve enough context for useful auditing.

## Migration Plan

### Phase 1

Create a file-backed provider that reads current repo-local secret files through
one controlled interface. Do not let agents read those files directly anymore.

Deliverables:

- `SecretProvider` abstraction
- `file` provider
- `secret_requests` and `secret_leases` tables
- approval flow for secret access
- a minimal API

### Phase 2

Move selected secrets into `OpenBao` or `Infisical` and switch policies from
file paths to logical secret paths.

Deliverables:

- backend provider for the chosen system
- lease and revoke support
- migration tooling from local files

### Phase 3

Default high-risk actions to `inject` or `execute_with_secret` so agents stop
seeing raw passwords during normal operations.

Deliverables:

- connector integrations
- environment injection wrappers
- stronger redaction and transcript hygiene

### Phase 4

Add operator lease ownership and escalation routing so an operator can "take"
responsibility for a session or temporarily delegate it.

Deliverables:

- owner and expiry on session control
- "raise to me" routing
- unified inbox for approvals and escalations

## Suggested Initial API

- `POST /api/v1/keys/requests`
- `GET /api/v1/keys/requests?status=pending`
- `POST /api/v1/keys/requests/{id}/approve`
- `POST /api/v1/keys/requests/{id}/reject`
- `GET /api/v1/keys/leases`
- `POST /api/v1/keys/leases/{id}/renew`
- `POST /api/v1/keys/leases/{id}/revoke`

The request payload should include:

- `secret_path` or `role_name`
- `mode`
- `requested_ttl_seconds`
- `reason`
- `session_id`
- `requester_context`

## First Policies To Ship

- any secret access from an agent requires approval by default
- max default TTL is `15m`
- subagents may not request raw-secret reveal
- high-risk paths like network, firewall, camera, and root access require
  explicit approval every time
- low-risk read-only service tokens may be policy-allowed for bounded reuse

## Definition Of Done For v1

- no automation reads repo-local secret files directly
- all secret access goes through Norman Keys
- approvals exist for secret access just as they do for commands
- leases expire automatically
- revocation works
- audit logs are complete and secrets stay redacted

## Implementation Prompt

Use this as the direct build brief:

> Build `Norman Keys`, a secret-access broker for Norman. Reuse Norman's
> existing approval, notification, safety, and operator-mode systems. Add a
> `SecretProvider` abstraction with a transitional file-backed provider first.
> Implement secret access requests, time-bounded leases, approval workflows,
> revocation, and audit logs. Default to deny. Default to short TTLs. Prefer
> secret injection over raw secret reveal. Add a dedicated `norman-keys`
> guardian path so ordinary agents and subagents never talk directly to the
> backend secret store. Ship Phase 1 first with repo-local file migration, then
> add `OpenBao` or `Infisical` as the real backend.

## Estate Capability Delivery (Hal, Norman, and NetOps)

The fleet transition must use **capability delivery**, not the legacy raw-secret
compatibility route. A TUI/CLI requests a named server-side capability, receives
an opaque short-lived lease, then submits that lease to the approved executor.
The client response contains a sanitized receipt only—never a `secret`, `value`,
provider response, or alias material.

### Required enrollment and policy ceremony

Before enabling a TUI/CLI host, an operator must deliberately create and review:

1. an active host enrollment for the stable logical host ID (`hal`, `norman`, or
   `netops`) with its public transport-identity fingerprint;
2. the narrowly scoped requester ID, lane, and capability names for that host;
3. an enabled capability binding with a server-side executor; and
4. an enabled capability policy with exact allowed actions, target constraints,
   short TTL, and an approval requirement where appropriate.

The request and invoke endpoints require the enrolled host ID plus an identity
fingerprint assertion authenticated by the deployment's mTLS gateway. The
server verifies the assertion against the enrollment and binds the opaque lease
to both that host and a canonical hash of the requested action parameters.
Single-use leases cannot be replayed or invoked with changed parameters.

### API separation

- Operator configuration: `/api/v1/keys/enrollments`, `/api/v1/keys/capabilities`,
  and `/api/v1/keys/capability-policies`.
- Fleet capability request: `POST /v1/capabilities/request`.
- Fleet capability invocation: `POST /v1/capabilities/{lease_id}/invoke`.
- Auditing: `/api/v1/keys/capability-audit` records the lifecycle using action
  names, hashes, host IDs, and parameter *keys/counts* only.

`POST /v1/secrets/get` remains a legacy migration compatibility endpoint. It is
not an approved TUI/CLI fleet delivery path and must not be used as a fallback
for a capability denial or executor failure.

### Rollout gate

After applying the capability-delivery migration, run the metadata-only gate:

```bash
./.venv/bin/python scripts/norman_keys_capability_rollout.py \
  --db db/norman.db --output /tmp/norman-keys-capability-rollout.json
```

It exits nonzero until **Hal**, **Norman**, and **NetOps** each have an active
enrollment and at least one enrolled capability with an enabled policy. The
checker reads database metadata only; it does not inspect broker environment
configuration, contact a provider, retrieve a credential, or reveal an alias
value. An enabled `receipt` executor proves the enrollment/policy path but is
not authorization to perform a privileged side effect: install a separately
reviewed server-side executor before enabling such a capability.
