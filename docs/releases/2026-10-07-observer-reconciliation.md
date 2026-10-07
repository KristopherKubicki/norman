# Estate Observer Source Reconciliation

The deployed collector depends on `estate_observe.py`, `estate_metric_history.py`, and
`estate_workflow_probes.py`. All three are required; copying only the collector loses workflow probes and history.
This candidate preserves the deployed scripts on staging `5b31aeb`, with bounded failure-handling corrections.

Observation failure remains unknown instead of healthy. A missing local probe or SSH executable is reported as
unavailable. Routing inference requires both known worker identities. Snapshot replacement is atomic, and failed
replacement retains the previous snapshot. History uses source timestamps, deduplicates samples, separates series,
and bounds retention and display size. Tests use synthetic metadata and do not contact hosts or cloud accounts.

The CT241 deployed files and HAL source copies had matching SHA-256 values at inspection on October 7:

| File | SHA-256 |
| --- | --- |
| `estate_observe.py` | `ec4a6ebd1f1d0cc810472c8d652e259a13755d779c313028a29de1325b36632e` |
| `estate_metric_history.py` | `f33b6db4cfd1c3ea11d1cfe9e2f47e1b42540f82eaa3b9665e85c4acece33572` |
| `estate_workflow_probes.py` | `01a30b7a21b2dd8df5e816dfc81a6f4a9972ee2bf62b013cfd221efb6b1d34fa` |

## Deployment Constraints

This PR installs no units, schedules, credentials, or inventory. Keep exactly one existing collector until a separately
reviewed placement change. The observed timer currently runs on CT241; fleet scheduling policy assigns fleet checks to
Networking VM232. Reconcile placement before deploying a replacement; do not add a scheduler on HAL.

The deployed `toy-box` SSH alias resolves to CT146 as user `netops`, verified from CT241. Preserve or explicitly configure
that identity when moving the collector. AWS observation currently queries HAL profiles on demand and reports unknown
when HAL is unavailable. This does not establish HAL-independent AWS visibility; any credential relocation
requires a separate review. No credentials are included here.

A release must install the three scripts together, preserve the metric SQLite database and target configuration,
and verify application snapshot consumption. Current source parity does not establish complete release parity:
Vault, operational executors, fleet inventory, and the old release's divergent history remain separate work.
