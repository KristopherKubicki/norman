# Norman Live Source Reconciliation

## Baseline And Scope

The CT241 production service uses release `085a0c0f42acf4d15151a664ac748ee06897c6de`
with additional source edits. The reconciliation base is staging
`5b31aeb8d51dbabe5baab7d47b7a00f120bf56ae`; production is `main`.
This work prepares source for review. It does not promote a release or change production configuration.

Do not replace the running checkout with staging solely because CI passes.
The release history also diverges from staging; this audit covers the additional working-tree changes,
not complete release parity.

A source-only snapshot, excluding virtual environments and `.before-*` backups, is retained on HAL at
`/data/personal/hal/evidence/norman-live-reconcile-20261007/source/` with a SHA-256 manifest.
It is local evidence, not a remote backup or authorization to delete the live checkout.

## Reconciliation Groups

| Group | Source And Disposition |
| --- | --- |
| Bridge UI, authentication UI, assets, submission model | Most files already match staging exactly. |
| Bridge conversation API, app routes, views | Three-way comparison resolves to existing staging content. |
| Malformed tool envelopes | PR #398 is merged into staging; a tested narrow backport is live. |
| Signed Keys transport and AWS readiness/rotation | Reconciled here from five existing source commits, with tests. |
| Astra, regional bearer tokens, personal billing | PR #400, `reconcile/norman-gateway-20261007`. |
| Keys owner authorization | Ported here from `7277087`, with cross-user denial and administrator tests. |
| Password vault | `fix/keys-security-20261006` has active follow-up edits. |
| VPN, Synology, printer and HP executors | Live-only operational helpers still need scoped source review and tests. |
| Dated Ubuntu maintenance executor | Temporary operation; preserve its owner receipt and establish retirement scope. |
| Estate observation scripts and fleet inventory | Independent operational changes still need source reconciliation. |

The password-vault source is committed as `7277087` in its owning checkout, with additional uncommitted edits.
Do not overwrite those edits or publish an earlier snapshot as the final vault implementation.
Do not turn dated maintenance access into permanent functionality merely to reproduce live drift.

## Signed Keys Candidate

The following existing commits were replayed onto current staging, preserving their authorship:

- `a9acff5`: constrained AWS readiness executor.
- `0e4ebc4`: authorization revalidation and atomic lease claim.
- `287dab8`: signed host authentication and replay protection.
- `eebd448`: encrypted AWS rotation workflow and failure tests.
- `2345510`: signed delivery and verified personal-account rotation.

Execution stays gated by the existing readiness and rotation environment flags. No credentials,
leases, enrollments, receiver configuration or production database state are copied into source.
Integration does not authorize enabling either executor or rotating any account's keys.

Owner/admin checks require privileged policy management and constrain request and lease operations to owners or admins.
Renewal revalidates expiry, renewability, and policy. Signed host transport remains independently authenticated.

Validation: format and lint pass; the final full Python suite reports 3,219 passed and one skipped. Tests exercise signatures, replay rejection, revoked authorization,
single-use lease claims, encrypted transport and rotation failure handling with synthetic data.

## Release Acceptance

Before replacing the deployed release, reconcile the remaining groups, review the complete release diff,
and run the candidate with its declared interpreter and dependencies. Verify authenticated tools,
streamed continuations, native Responses preservation, billing identity, signed Keys requests,
UI behavior and database migrations. Keep the current source and credential/queue state recoverable.

An integration PR, a green suite, or a source snapshot alone does not establish production parity.
