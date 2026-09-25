# Signed Host Authentication

## Live Status — September 25, 2026

Hal, Norman, and NetOps authenticate capability requests with OpenSSH signatures made by their
existing Ed25519 host keys. Their public-key fingerprints match the pre-existing enrollment records.
Private host keys remain on their originating machines. No bearer token or AWS credential is sent
by the client. HTTPS remains mandatory for the client and uses normal certificate validation.

This replaces the earlier proposed mTLS gateway as the capability host-authentication mechanism.
The application verifies signatures itself, so access directly to backend port 8000 cannot bypass
host authentication. Unauthenticated fingerprint-header requests were rejected with HTTP 401 through
both the HTTPS front door and the direct backend. No Caddy or network-listener changes were required.

## Protocol And Limits

The OpenSSH namespace is `norman-keys-v1`. The signed message binds the fixed audience
`norman.home.arpa`, POST method, exact route, SHA256 of the exact body, timestamp, and nonce.
The broker pins the signing key to an active host enrollment and derives the trusted fingerprint
from verification; the old caller-supplied fingerprint header has no authority.

Timestamps have a 60-second tolerance. A database primary key atomically rejects reused nonces
across workers and restarts. Stale entries expire after their signatures become unusable.
Capability authorization, target/account constraints, and single-use leases are checked separately.
Revoked hosts, modified requests, replayed signatures, and unsigned requests are rejected.
Host key rotation requires deliberate enrollment fingerprint updates. Maintain synchronized clocks.

## Installed Client

On each enrolled host:

```bash
sudo -n /usr/local/sbin/norman-aws-readiness gmail
sudo -n /usr/local/sbin/norman-aws-readiness acm
sudo -n /usr/local/sbin/norman-aws-readiness yhix
```

The root-owned client accepts only these three account labels and the fixed read-only `inspect`
action. The launcher uses isolated Python mode. Its sudoers entry permits only these exact commands.
It rejects HTTP redirects and prints the final sanitized receipt. It cannot import or reveal secrets,
run arbitrary commands, change an AWS resource, or select an alternative endpoint.

Host metadata is in `/etc/norman-keys-host.json`; the implementation is installed as
`/usr/local/libexec/norman_aws_readiness.py`. No private-key bytes are returned by the signing command.

## Active Policies

Capabilities: `aws.gmail.readiness`, `aws.acm.readiness`, `aws.yhix.readiness`.
Each is bound to its fixed account ID and `aws-readiness-v1` executor.
Nine policies bind each capability to one exact host requester and its existing lane.
The existing requester IDs are `estate-keys-hal`, `estate-keys-norman`, and `estate-keys-netops`.
Allowed action is `inspect`, target is the exact AWS account ID, and lease TTL is 60 seconds.
These explicitly authorized read-only checks do not need per-invocation manual approval.
No general administrative or secret-import capability was enabled.

All nine live host/account combinations completed and confirmed root MFA enabled.
The executor uses existing AWS SDK profiles on Norman; ACM and YHIX assume management roles.
Gmail's long-lived source key has NOT been migrated into encrypted keystore storage or rotated.
Working capability delivery must not be reported as completion of that separate migration.

## Deployment And Recovery

Production release: `085a0c0f42acf4d15151a664ac748ee06897c6de`.
Migration: `e1f2a3b4c5d6`, adding only `keys_transport_nonces`.
Backup: `/home/kristopher/releases/keys-host-auth-backup-20260925` on Norman.
The backup includes original runtime files and the original host-enrollment metadata.
AWS execution is enabled by `60-aws-readiness.conf` in the production unit's systemd drop-in directory.

To suspend AWS checks, disable the AWS capabilities/policies or remove that drop-in, reload systemd,
and restart the production unit. Keep signature verification and nonce history intact.
Do not restore bearer-only/fingerprint-header authentication as a convenient fallback.
Host client removal does not require deleting or rotating the machine's SSH host key.

## Validation

43 focused tests passed, including actual OpenSSH signing/verification and a signed API
request/invoke round trip. Formatting, lint, and diff checks passed. The full suite reached
854 passes and then failed in the unchanged pricing-catalog test for missing `gpt-5.5/standard`
pricing. Production health passed after both deployment and executor activation.
