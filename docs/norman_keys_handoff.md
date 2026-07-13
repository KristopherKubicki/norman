# Norman Keys Handoff

This is the short handoff version for Norman. The detailed design lives in
[`docs/norman_keys.md`](./norman_keys.md), and the concrete implementation
sequence lives in [`docs/norman_keys_v1_plan.md`](./norman_keys_v1_plan.md).

## What Changed On The Networking Side

The networking repo now routes operational secret access through a shared
resolver instead of reading plaintext repo dotfiles directly.

Current resolver order:

1. Norman Keys, if configured
2. local encrypted `cred` vault
3. legacy repo dotfiles as migration fallback only

Current Norman integration hooks already supported by the networking resolver:

- `NORMAN_SECRET_CMD`
- `NORMAN_KEYS_URL`
- `NORMAN_KEYS_TOKEN`

Current logical secret names in use:

- `networking/firewall`
- `networking/netgear`
- `networking/dot10`
- `networking/camera`
- `networking/synology`
- `networking/modem`
- `networking/sudo_pass`
- `networking/prox_root`

The important constraint is:

- ordinary agents and scripts should not talk to a raw secret backend directly
- they should ask Norman Keys, or the local resolver during migration

## What Norman Should Build

Build `Norman Keys` as a brokered secret-access service for personal/home and
shared-infra bots.

Requirements:

- deny by default
- use approval workflows when access is not pre-authorized
- issue short-lived leases
- support renew and revoke
- keep an audit trail
- prefer secret injection over raw secret reveal
- keep work/OpenBrand bot policy separate from personal/home policy

Norman should own:

- secret access requests
- approval routing
- lease issuance
- lease expiry and revocation
- audit events
- backend provider abstraction

Norman should not require every caller to understand backend details.

## Backend Shape

Phase 1:

- implement a `SecretProvider` abstraction
- start with a transitional file-backed provider so Norman can operate before a
  full vault cutover

Phase 2:

- add a real backend such as OpenBao or Infisical

The secret provider interface should support:

- `get_secret(name, subject, ttl)`
- `renew_lease(lease_id, ttl)`
- `revoke_lease(lease_id)`
- `list_active_leases()`

## How Networking Expects To Call Norman

Two acceptable patterns exist right now:

### CLI Broker

Expose a command compatible with:

```bash
norman-keys get networking/firewall
```

Then set:

```bash
export NORMAN_SECRET_CMD="norman-keys"
```

### HTTP Broker

Expose an endpoint compatible with:

- `POST /v1/secrets/get`
- JSON body: `{"name":"networking/firewall"}`
- response body containing either `secret` or `value`

Then set:

```bash
export NORMAN_KEYS_URL="http://<norman-host>:<port>"
export NORMAN_KEYS_TOKEN="<token-if-needed>"
```

## Immediate Goal

Get Norman to become the first lookup path for personal/home and shared-infra
secret access, while keeping the local `cred` vault as a temporary fallback
during migration.

## Current Local Fallback

The networking repo already has a machine-local encrypted vault command:

```bash
cred
```

The one-shot migration command is:

```bash
cred migrate-networking-dotfiles /home/[REDACTED_NAME]/code/networking
```

That is a temporary bridge, not the intended long-term control plane.

## Copy-Paste Version

> Build `Norman Keys` as a brokered secret-access service for personal/home and
> shared-infra bots. Reuse Norman's approval and safety systems. Keep work and
> OpenBrand bot policy separate. Support secret requests, approvals,
> short-lived leases, renew, revoke, and audit logs. Expose either a CLI form
> compatible with `norman-keys get <name>` or an HTTP form compatible with
> `POST /v1/secrets/get` returning `secret` or `value`. Treat direct plaintext
> repo dotfile reads as legacy migration fallback only.
