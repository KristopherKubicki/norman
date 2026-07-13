# Norman Keys V1 Plan

`Norman Keys` should ship as a brokered secret-access control plane inside
Norman. V1 should be intentionally narrow: enough to replace direct secret file
reads for home/personal and shared-infra bots, without trying to become a full
vault product.

This plan turns the higher-level design in
[`docs/norman_keys.md`](./norman_keys.md) into an implementation sequence that
fits Norman's existing approval, editor, and estate model.

## V1 Outcome

By the end of v1, this flow should work:

1. A bot or job asks Norman for `networking/prox_root`.
2. Norman resolves the requester identity and policy lane.
3. Norman either:
   - grants a short lease immediately, or
   - creates a pending approval in Norman.
4. The operator approves or rejects in Norman.
5. Norman injects the secret into an allowed execution path or returns it only
   when policy explicitly allows raw reveal.
6. The access is auditable, renewable, and revocable.

V1 should support the networking resolver as the first real consumer.

## Non-Goals For V1

- Norman as the primary encrypted secret database
- multi-party approval or quorum approval
- generalized workstation login brokering
- automatic rotation for every backend type
- broad human password-manager replacement

## V1 Product Shape

### Operator Surfaces

- `Norman Prime`
  - new inbox cards for pending secret approvals and active secret risk
- `Editor`
  - structured handoff and review flow for secret-related work
- `Directory`
  - provider and policy visibility later, but not the main approval surface
- `Secret Requests`
  - a dedicated subpage for requests, leases, and audit history

### Runtime Surfaces

- HTTP broker for machine-to-machine use
- CLI shim for repos like `networking`
- injection-oriented service layer for Norman-managed executions

## Policy Model

V1 should treat secret policy as a Norman-owned access layer, separate from the
secret backend.

Minimum policy dimensions:

- `requester_type`
  - `operator`
  - `agent`
  - `subagent`
  - `job`
- `requester_id`
- `lane`
  - `personal`
  - `shared_infra`
  - `work`
  - `openbrand`
- `secret_prefix`
  - examples:
    - `networking/`
    - `house/`
    - `camera/`
- `allowed_modes`
  - `inject`
  - `execute_with_secret`
  - `read`
- `max_ttl_seconds`
- `approval_required`
- `raw_reveal_allowed`
- `allowed_hosts`
- `reuse_window_seconds`

### Initial Policy Defaults

- `read` denied by default
- `inject` preferred by default
- `operator` may request `read`, but usually still requires approval
- `agent` and `subagent` require approval unless explicitly pre-authorized
- `work` and `openbrand` lanes should be excluded from the first rollout unless
  explicitly whitelisted

## Secret Naming

Norman should own a canonical alias registry instead of letting every caller
invent ad hoc names.

Initial aliases should include:

- `networking/firewall`
- `networking/netgear`
- `networking/dot10`
- `networking/camera`
- `networking/synology`
- `networking/modem`
- `networking/sudo_pass`
- `networking/prox_root`

Each alias should map to provider-specific metadata such as:

- provider kind
- backend path or key name
- lane
- default TTL
- whether raw reveal is ever allowed
- operator note

## Data Model

V1 should add first-class Norman models instead of overloading command
approvals.

### `secret_providers`

Represents configured backends.

Suggested fields:

- `id`
- `name`
- `kind` (`file`, `cred`, `openbao`, `infisical`)
- `enabled`
- `config_json`
- `created_at`
- `updated_at`

### `secret_aliases`

Maps logical names to provider-specific references.

Suggested fields:

- `id`
- `name`
- `provider_id`
- `backend_ref`
- `lane`
- `risk_tier`
- `default_ttl_seconds`
- `allow_raw_reveal`
- `metadata_json`
- `created_at`
- `updated_at`

### `secret_policies`

Suggested fields:

- `id`
- `name`
- `requester_type`
- `requester_id`
- `lane`
- `secret_prefix`
- `allowed_modes`
- `max_ttl_seconds`
- `approval_required`
- `allowed_hosts`
- `reuse_window_seconds`
- `enabled`
- `created_at`
- `updated_at`

### `secret_requests`

Suggested fields:

- `id`
- `request_uuid`
- `requester_type`
- `requester_id`
- `session_id`
- `parent_request_id`
- `secret_alias`
- `requested_mode`
- `requested_ttl_seconds`
- `intent`
- `reason`
- `target_host`
- `status`
- `approval_id` nullable
- `created_at`
- `decided_at`
- `decided_by`

### `secret_leases`

Suggested fields:

- `id`
- `lease_uuid`
- `request_id`
- `provider_id`
- `provider_lease_id`
- `issued_to`
- `secret_alias`
- `granted_mode`
- `granted_ttl_seconds`
- `expires_at`
- `renewable`
- `status`
- `last_used_at`
- `revoked_at`
- `revoked_by`

### `secret_audit_events`

Suggested fields:

- `id`
- `request_id`
- `lease_id`
- `event_type`
- `actor_type`
- `actor_id`
- `summary`
- `metadata_json`
- `created_at`

## Provider Abstraction

V1 should implement a narrow `SecretProvider` interface:

- `describe_secret(alias)`
- `get_secret(alias, subject, ttl_seconds)`
- `renew_lease(lease_id, ttl_seconds)`
- `revoke_lease(lease_id)`

### Initial Providers

#### `cred`

Wrap the existing machine-local `cred` command as the safest migration bridge.

Why:

- avoids reinforcing plaintext dotfile reads
- already exists in the networking migration path
- lowers the first implementation cost

#### `file`

Only for transitional fallback where Norman must read an existing path directly.

Rules:

- disabled by default
- lane-limited
- noisy in audit logs
- only for migration

### Deferred Providers

- `openbao`
- `infisical`

The interfaces should make these pluggable, but they do not need to ship in
the first slice.

## Request And Lease Service

Add a new service layer, for example:

- `app/services/secret_broker.py`
- `app/services/secret_policy.py`
- `app/services/secret_providers/`

Responsibilities:

- request validation
- alias resolution
- policy evaluation
- approval creation
- provider interaction
- lease creation and expiry logic
- audit event emission

This should be a separate path from command execution controls, but it should
reuse Norman's identity, approval, and notification primitives.

## Approval Integration

Secret approvals should be their own request type, but should render through
the same Norman approval UX patterns already used for commands.

V1 approach:

- either add a generic approval substrate that can carry multiple approval
  kinds, or
- add a parallel `secret_approvals` flow that reuses the same inbox and card UI

Recommended v1 compromise:

- keep `command_approval` unchanged
- create `secret_requests`
- create a `secret approval` UI card set in the same Norman Prime inbox and
  approvals page patterns

Approval actions:

- `approve once`
- `approve for 15m`
- `approve for 1h`
- `reject`
- `revoke active lease`

Approval payload should show:

- requester
- lane
- session/thread
- target secret alias
- requested mode
- target host
- justification
- last access summary

It must never show the plaintext secret.

## HTTP And CLI Surfaces

### HTTP

V1 endpoints:

- `POST /api/v1/keys/requests`
  - create a request and possibly issue a lease immediately
- `POST /api/v1/keys/requests/{id}/approve`
- `POST /api/v1/keys/requests/{id}/reject`
- `POST /api/v1/keys/leases/{id}/renew`
- `POST /api/v1/keys/leases/{id}/revoke`
- `GET /api/v1/keys/leases/active`
- `GET /api/v1/keys/audit`

Compatibility shim for current resolver expectations:

- `POST /v1/secrets/get`
  - accepts `{"name":"networking/firewall"}`
  - internally creates a structured secret request
  - should only return raw `secret` or `value` when policy allows
  - otherwise should prefer a wrapped lease or injected execution path

### CLI

Add a simple Norman-owned CLI wrapper, for example:

- `scripts/norman_keys_cli.py`
- exposed as `norman-keys`

Expected shape:

```bash
norman-keys get networking/firewall --reason "ssh proxmox" --ttl 900
```

For v1 it may call the local HTTP API, but the user-facing interface should be
stable.

## Delivery Modes

V1 should implement:

### `inject`

Default mode. Norman obtains the secret and injects it into a command or
connector execution path without displaying plaintext back to the model.

### `read`

Allowed only by explicit policy. Norman returns plaintext to a trusted caller.
This should be rare and noisy.

### `execute_with_secret`

May be stubbed in v1 for later, but the service model should reserve a place
for it because it is the preferred long-term pattern for high-risk systems.

## UI Plan

### Norman Prime

Add:

- `Secret approvals waiting`
- `Active leases`
- `Expiring soon`
- `Legacy fallback still in use`

Norman Prime should also treat security and access review as part of its normal
coordination loop, not a separate specialist workflow. When a task implies
privileged access, Norman Prime should automatically raise:

- whether secret access is required
- whether an active lease already exists
- whether a fresh approval is required
- whether the requester is crossing a lane boundary
- whether the safer path is `inject` or `execute_with_secret` instead of raw
  reveal
- whether the action should be blocked or escalated

This should show up the same way Norman already surfaces other operational
concerns: concise warnings, approval prompts, lane-aware risk markers, and
recommended next steps.

Prime actions:

- `Review secret requests`
- `Revoke expiring lease`
- `Open Norman Keys`

### Secret Requests Page

New page or tab with:

- pending requests
- active leases
- recent audit events
- provider health
- fallback usage warnings

### Editor Integration

When Norman is coordinating work, the editor should be able to launch a
pre-filled review like:

`Review secret request: networking/prox_root for Keystone on 192.168.2.242`

When the operator is talking directly to Norman Prime, the assistant should run
these checks implicitly before suggesting or launching privileged work:

- detect whether the next action needs a secret, lease, or approval
- explain the minimum access required
- prefer non-reveal execution paths
- call out lane or policy conflicts early
- offer the smallest safe next step instead of assuming unrestricted access

## Migration Sequence

### Slice 0: Documentation And Alias Inventory

- add v1 plan
- add alias registry seed file
- document the approved initial aliases

### Slice 1: Data Model And Provider Interface

- add SQLAlchemy models
- add Alembic migration
- implement provider abstraction
- implement `cred` provider

### Slice 2: Request Evaluation And Lease Issuance

- implement policy evaluation
- implement request creation
- implement lease creation
- implement audit events

### Slice 3: Norman Approval Integration

- add secret approval inbox cards
- approve/reject/revoke flows
- connect request status transitions

### Slice 4: HTTP And CLI Compatibility

- ship `/v1/secrets/get`
- ship `norman-keys get <name>`
- validate networking repo integration against the resolver hooks

### Slice 5: UI And Norman Prime

- active leases page
- expiring lease alerts
- legacy fallback warnings

### Slice 6: Networking Migration Cutover

- set `NORMAN_SECRET_CMD` or `NORMAN_KEYS_URL`
- verify successful secret resolution through Norman
- keep `cred` as fallback briefly
- remove direct plaintext repo-dotfile dependency

## First Real Consumer

The first consumer should be the networking resolver, because it already has a
logical secret vocabulary and a migration fallback story.

Success criteria:

- networking asks Norman first
- Norman logs the request
- approval works when needed
- a short lease is issued
- the secret is usable
- the action completes
- the secret does not land in prompt or transcript plaintext

## Operational Guardrails

V1 should enforce:

- no plaintext secret values in logs
- no plaintext secret values in model transcripts by default
- raw reveal requires explicit policy
- leases expire automatically
- revocation is possible from UI
- fallback file-provider usage is visible and noisy

## Open Questions For Implementation

- Should secret approvals reuse the existing `command_approval` table through a
  shared approval superclass, or stay separate in v1?
- Should alias seeds live in YAML beside the estate registry, or in database
  bootstrap code?
- Is `cred` sufficient as the first provider, or do we need the file provider
  immediately for specific migration cases?
- Should `execute_with_secret` ship in v1 or be deferred to v1.1?

## Recommended Immediate Next Step

Implement `Slice 1` and `Slice 2` first:

- models
- Alembic migration
- provider abstraction
- `cred` provider
- request and lease service

That gives Norman a real secret-access core quickly, and the approvals and UI
can then sit on top of a working broker instead of a stub.
