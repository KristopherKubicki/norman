# Personal AWS Key Rotation Implementation

## Status

Development implementation only. No production migration, capability registration, key creation,
credential import, distribution, deactivation, or deletion has been performed by this implementation.
It is not yet a supported live rotation path. Existing signed read-only checks remain unchanged.

## Implemented Boundaries

- Durable encrypted rotation state with no stash expiry and no raw-reveal API.
- Existing runtime cipher injection; no vault initialization or automatic encryption-key generation.
- Ciphertext payload bound to the logical alias, account, rotation ID, and new key ID.
- A unique account reservation committed before CreateAccessKey. An uncertain create response or storage
  failure requires reconciliation; retrying prepare cannot create another key.
- Pinned AWS endpoints, TLS verification, exact IAM identity and source-key checks, and SDK retries
  disabled for the non-idempotent creation call.
- Fixed Gmail account and cloudagent user. ACM and YHIX are verification targets; other accounts are excluded.
- Exclusive host file lock through external operations and durable transitions, plus database revision checks.
  Every production worker must use the same protected lock path on the same executor host.
- Explicit partial-distribution state, fresh checks before retirement, and old-key reactivation on failed
  post-retirement checks. Key deletion is deliberately absent.
- Migration downgrade refuses to drop populated recovery storage.

The storage module's `consume` callback is an internal injection boundary, not an authorization mechanism.
Never expose it as an HTTP callback, expression evaluator, generic command runner, or raw-secret provider.
The live broker must authenticate and authorize each fixed operation before constructing the workflow.
Likewise, `transition` is internal storage plumbing, not a caller-controlled state-change API.

## Remaining Production Requirements

1. Implement authenticated fixed receivers and `HostTransport` for Hal/kristopher, Norman/kristopher,
   and NetOps/root. Both kk-personal and personal-bedrock must be covered. No secret values may appear
   in command arguments, logs, receipts, TUI output, or plaintext staging/rollback files.
2. Establish concrete fresh credential and application-health checks. A cached assumed-role session
   or an active systemd process is insufficient. NetOps runs CloudAgent services under root;
   Hal has long-lived notification and Glimpser alert clients. Inventory coverage remains incomplete.
3. Prove the existing production encryption configuration survives restarts and has a recoverable backup.
   The dummy test cipher is NOT suitable for deployment and is not the production cipher.
4. Connect the workflow to signed, single-use, narrowly authorized broker operations and sanitized typed
   receipts. Do not broaden existing read-only capability policies into credential write policies.
5. Deploy receivers and database migration, then test the complete transport with dummy material before
   enabling live writes. Migration downgrade is not a substitute for credential recovery.
6. Prepare and distribute the replacement while the old key remains active. Verify every known consumer,
   including representative scheduled work, before retiring the old key. Keep a recovery observation period.

The current implementation intentionally has no default HostTransport and no registered write executor.
User authorization to rotate exists; missing transport, verification and integration are engineering work,
not a request for the user to log in again or disclose a credential.

## Failure Recovery

- `creating`: inspect AWS key metadata through the normal management path. A second key may exist even
  when the response was lost. Do not automatically issue another create or delete an unidentified key.
- `stored`: encrypted replacement persisted; distribution has not completed.
- `distributing` or `distribution_failed`: old key stays active. Re-run idempotent distribution only under
  the exclusive operation lock, after resolving the failed receiver.
- `verified`: all adapter checks passed, but retirement repeats those checks and must be a separate action.
- `retiring` or `recovery_required`: use replacement credentials through the supported executor to reactivate
  the old key and read back its status. The exclusive lock prevents racing an active retirement worker.
- `old_reactivated`: both generations can remain usable; reconcile consumers before another cutover.
  The implementation does not yet provide an automatic retry from this state.
- `old_inactive`: preserve the encrypted replacement and old-key recovery option. No deletion is implemented.

Tests use dummy credentials and mocked AWS. They cover ciphertext persistence across a new database engine,
wrong encryption keys, ciphertext context mismatch, partial distribution, stale checks, ambiguous creation,
failed rollback, concurrent-operation locking, exact AWS identity and source key, and no SDK create retries.

## Validation Results

September 25: 75 focused tests passed, including rotation, AWS adapter, readiness, host authentication,
capability policy, and rollout tests. Formatting, lint, and whitespace checks passed.
The full suite stopped after 883 passes at the previously observed, unchanged pricing-catalog failure:
`test_control_plane_skill_gap_audit_reports_runbook_and_operation_coverage`, missing price for
`gpt-5.5/standard`. The full suite is not green. No production tests with replacement credentials were run.
