# AWS Keys Readiness Candidate

This branch adds a tested, read-only executor candidate. It is not registered with the broker,
deployed, or enabled. It does not import credentials into Norman Keys.

## Behavior

`app/services/aws_keys_readiness.py` accepts only `inspect`, a server-bound personal account ID,
and exactly matching account parameters. It uses existing SDK profiles and returns only account ID,
verified-identity status, and root MFA status. No caller-provided profile, command, URL, or AWS operation
is accepted. Account and principal identity are verified before querying IAM. Network retries and
timeouts are bounded, TLS verification is mandatory, and AWS service endpoints are fixed.

Bindings cover Gmail, ACM, and YHIX. OpenBrand and the mothballed account are excluded.
YHIX remains unavailable until its existing bootstrap is run through an authenticated studio session.

## Activation Work Still Required

The existing broker only executes `receipt`. A separately reviewed server-side dispatch must integrate
this candidate behind host enrollment, exact policy/action/account constraints, approvals, and leases.
Do not invoke this module directly from a TUI as a workaround for a denied broker request.

Before activation, cover capability and policy disablement after lease issuance, atomic single-use
lease consumption, cross-account attempts, failure audit receipts, and authenticated gateway identity.
The existing invocation implementation needs review of those boundaries before adding real executors.
Use an explicit typed receipt schema for these three output fields; do not return arbitrary SDK objects.

Credential enrollment is a separate remaining step. This candidate uses the existing runtime profiles;
it neither migrates the Gmail key into the keystore nor replaces that long-lived key. A supported
server-side import path and verified replacement consumers are needed before key rotation.

## Validation

The unit tests mock AWS; no credentials are retrieved and no account changes are made by those tests.
They check account/principal constraints, request rejection, endpoint pinning, output allowlisting,
error redaction, and malformed MFA responses. Existing capability tests exercise the unchanged broker.

Validation on September 24, 2026: `make format` and `make lint` passed; the focused executor and
capability suite passed all 21 tests. A bounded full-suite attempt reached over 21% with no reported
failures before its 60-second timeout; the full suite is not verified. No live executor call was made.
