# Personal AWS Key Rotation

## Production Status

Completed September 25, 2026 at approximately 21:46 UTC for IAM user `cloudagent` in account `970651210182`.
The original key ending `Q2OX` is inactive. The replacement ending `O74M` is active.
No key was deleted. ACM and YHIX continue to use temporary CloudAgentManagement role sessions.
OpenBrand and the mothballed account were excluded.

The replacement is encrypted using Norman's existing application cipher in `aws_key_rotations`, bound to
logical name `cloudagent/aws/gmail`, account, rotation ID, and key ID. This is an internal executor store,
not a raw-reveal alias. An encrypted-only recovery record also exists outside the database and on Hal.
The existing SDK profiles remain standard AWS credential files; this change does not encrypt those files
or reduce the cloudagent user's administrator permissions.

## Consumers And Verification

Both `kk-personal` and `personal-bedrock` were updated on:

| Host | OS User | Verification |
| --- | --- | --- |
| Hal | kristopher | Fresh credentials, account identities, notification and Glimpser services |
| Norman | kristopher | Fresh credentials, account identities, production health |
| NetOps | root | Fresh credentials, account identities, active CloudAgent services |

Each receiver explicitly authenticated both source profiles and used uncached STS role assumptions for
ACM and YHIX. All nine host/account combinations passed before and after the original key was disabled.
Notification and Glimpser clients on Hal were restarted to refresh their cached SDK credentials.
No test notification was sent. Process/HTTP checks are not proof of end-to-end SMS or camera-event delivery.
CloudTrail also recorded successful NetOps-kernel AWS CLI requests using the replacement after deactivation,
including normal CloudAgent SSM activity. A recent old-key sample was empty; that is not an exhaustive audit.
Unknown or infrequent consumers remain an observation-period risk; retain the inactive key for recovery.

## Delivery And Authorization

- Only the enrolled Hal host can request the personal rotation capability using the existing signed protocol.
- Broker policies bind the requester, lane, action, account, and short-lived single-use lease.
- The write executor has a separate activation gate from the read-only readiness executor.
- SSH delivery used pinned server keys and the existing Norman deployment identity. Secrets traveled only
  in encrypted SSH stdin or a local pipe, never command arguments or output.
- Receivers accepted fixed operations and files, checked the IAM principal before installation, and returned
  only status metadata. On Norman the receiver ran without sudo, preserving `NoNewPrivileges=yes`.
- Replacement of standard credential files was atomic. A private mode-0600 sibling inode was used briefly
  for the atomic rename and removed on failure; no plaintext rollback or audit copies were retained.
- A temporary health failure during the first Hal restart stopped distribution while the old key stayed active.
  Bounded application-readiness polling corrected that issue before cutover proceeded.

After cutover, all three temporary receivers, their sudo rules, and the temporary SSH host-pin file were removed.
The broker policy and Hal client sudo rule now permit only `status`, `cipher-test`, and explicit `recover`.
Creating, distributing, or retiring keys again requires a deliberate deployment and policy update.
This is a fixed-account, fixed-generation workflow, not automatic recurring rotation.

## Durable Storage And Recovery

State is reserved before CreateAccessKey, encrypted before distribution, and protected by a process-shared
file lock plus database revisions. SDK creation retries are disabled. Uncertain creation requires explicit
reconciliation; a retry cannot silently create another key. Migration downgrade refuses populated storage.

Norman's encryption probe was written, then verified after a service restart using the existing configuration.
The production configuration was tightened to mode 0600, and a root-private recovery copy was preserved at:
`/home/kristopher/releases/aws-rotation-backup-20260925/runtime-config.yaml` on Norman.
The configuration is sensitive: never display it or copy it into a transcript or repository.

The encrypted credential recovery record is on Norman at
`/var/lib/norman/state/aws-source-rotation-<rotation-id>.encrypted.json`.
A private encrypted-only copy and nonsecret verification metadata are in Hal's audit directory:
`/home/kristopher/personal-security-audit-20260921/estate/aws-source-key-rotation-20260925/`.
Do not lose the application encryption configuration; an encrypted credential record alone is insufficient.

Current status can be checked on Hal with `sudo -n /usr/local/sbin/norman-aws-rotation status`.
If an unmigrated consumer fails, `sudo -n /usr/local/sbin/norman-aws-rotation recover` reactivates the original
key using the encrypted replacement and reads back the result. It does not restore old profile files or
delete the replacement. Recovery must be explicit; do not run it merely to test the command.
The usual read-only `norman-aws-readiness gmail|acm|yhix` checks remain available.

## Validation

95 focused tests passed, including durable encryption, interrupted creation, partial distribution,
failed rollback, concurrency, fixed AWS bindings, signed capability policy, transport, and service startup waits.
Formatting, lint, and whitespace checks passed. The full suite stopped after 901 passes on the previously
observed unrelated missing `gpt-5.5/standard` price in
`test_control_plane_skill_gap_audit_reports_runbook_and_operation_coverage`; the full suite is not green.

Live evidence includes dummy receiver tests on all three hosts, signed broker dummy delivery, encryption
verification after restart, staged distribution, fresh identity checks before/after retirement, and AWS
readback showing the original key inactive and replacement active. No secret value appeared in tool output.
