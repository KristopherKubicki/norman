# AWS Keys Integration

The `aws-readiness-v1` executor is integrated with Norman Keys lease invocation.
It only checks identity and root MFA for the bound Gmail, ACM, or YHIX account.
It uses existing SDK profiles; this is not credential import or key migration.

## Authorization And Execution

The broker revalidates current capability, policy, approval, action, target, requester, lane,
TTL ceiling, and enrollment before execution. A conditional database update claims the lease before
calling AWS. AWS invocations require single-use leases. Failure consumes the lease and records a
sanitized failure event. Completion does not overwrite a concurrent revocation.
Only typed account ID, verified identity, and root MFA fields can leave the executor.
The executor rejects unbound accounts, arbitrary operations, caller profiles, and custom URLs.
OpenBrand and the mothballed account are excluded.

## Production Activation Complete — September 25

Signed host authentication is deployed and all nine host/account combinations passed live checks.
See [Signed Host Authentication](keys_host_auth.md) for protocol, policies, client usage, and rollback.
AWS execution is enabled only for the three fixed read-only readiness capabilities.
This supersedes the September 24 deployment status below.

## Credential Enrollment And YHIX

Gmail still uses its existing long-lived CloudAgent key. A supported server-side import path and
verified replacement consumers are required before migration or rotation. Do not use raw-secret
broker endpoints from the TUI. ACM uses its existing temporary management-role session.
YHIX management-role bootstrap completed September 25; `kk-yhix` is verified on Hal and Norman.

## Validation

Formatting and lint pass. The focused executor and capability tests pass (32 tests), including
policy changes after issuance, stale lease claims, sanitized failures, replay rejection, typed output,
wrong-account/principal rejection, and default-disabled activation. Tests mock AWS.
Full-suite outcome and production deployment status are recorded in the task handoff.

## September 24 Deployment Receipt

The three runtime files were deployed to release `085a0c0f42acf4d15151a664ac748ee06897c6de`
after verifying that both existing production files matched the unmodified branch baseline.
The service restarted successfully, `/health` returned `ok`, all deployed checksums matched,
and the served OpenAPI schema included the typed AWS receipt.
Rollback copies are at `/home/kristopher/releases/aws-keys-backup-20260924` on Norman.
Only the existing `estate.keys.readiness` receipt capability is enrolled; AWS execution is not active.
No secrets were read, copied, imported, or rotated during deployment.

The full suite stopped after 854 passes on an existing pricing-catalog path:
`test_control_plane_skill_gap_audit_reports_runbook_and_operation_coverage` raised
`missing OpenAI direct price for gpt-5.5/standard`. That pricing implementation was not changed here.
The final focused suite passed all 32 tests; formatting, lint, and diff checks passed.
