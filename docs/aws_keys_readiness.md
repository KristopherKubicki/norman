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

## Production Activation Blocked

AWS dispatch is disabled unless `NORMAN_KEYS_AWS_EXECUTOR_ENABLED=1` is explicitly configured.
Do not set it before authenticating fleet host identities at the transport layer.

On September 24, the live Caddy configuration forwarded `/v1/*` to port 8000 without client-certificate
verification or replacement of the host fingerprint header. The app listened on `0.0.0.0:8000`.
A shared service bearer token plus a client-supplied fingerprint does not prove enrolled host identity.
Real AWS capabilities must remain disabled until the gateway authenticates the enrolled client,
sets the fingerprint from that authentication, removes caller-supplied identity assertions, and
prevents direct backend bypass. Verify all three enrolled hosts with their actual transport identities.

After that gate, deliberately enroll exact account capabilities and policies through the operator API,
validate short-lived request/invoke/revoke flows, and enable only the reviewed read-only executor.
No fleet enrollments, capability records, or provider secrets were altered by this implementation.

## Credential Enrollment And YHIX

Gmail still uses its existing long-lived CloudAgent key. A supported server-side import path and
verified replacement consumers are required before migration or rotation. Do not use raw-secret
broker endpoints from the TUI. ACM uses its existing temporary management-role session.
YHIX requires an authenticated studio session to run the prepared bootstrap:
`code/cloudagent/projects/account-guardrails/bootstrap-yhix-management.sh`.

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
