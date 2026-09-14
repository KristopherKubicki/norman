# Applications And DOHIO Integration

Norman's `/systems.html` Applications view reads `/api/v1/estate/applications` using existing user authentication.
The existing directory remains below it. No schema migration or runtime account switch is required.

## Ownership And Observation

`db/estate/applications.json` extends the estate registry with reviewed app-to-operator assignments,
account preferences, responsibilities, deployment inventory, KPI contracts, and lifecycle intent.
The imported inventory was reviewed with the operator on September 14, 2026.
Proposed owners and account attribution limits remain explicit. Account preference does not prove billing identity.

The server fetches DOHIO `/api/status` and `/api/registry` concurrently with an eight-second timeout.
A process-local cache limits requests to once per minute; open, visible Systems pages refresh once per minute.
Set `NORMAN_DOHIO_URL` to change the server-side origin. TLS verification stays enabled.
On failure the API retains prior observations and displays a source error. Observations older than ten minutes
are stale; missing, invalid, or implausibly future timestamps are unknown.

Explicit `dohio_service_ids` and `dohio_surface_ids` bind observed signals to an app.
Operator heartbeat aliases are resolved separately. A healthy operator never establishes app health.
Reachable means an observed endpoint or service signal is available, not that all user workflows pass.
DOHIO records without explicit bindings appear in the reconciliation list; this can include consoles and devices.
Discovery never writes ownership or lifecycle intent, changes account routing, or reactivates retired apps.

## Maintenance

Update the reviewed catalog when an app changes owner, account policy, lifecycle, or expected signals.
Keep stable application IDs and bind aliases explicitly. Pretty Bird stays retired unless the user changes that intent.
The new catalog supplements the existing estate database, which continues to drive the underlying directory.
It does not create duplicate bot or service database rows.

Deployment instances retain their inventory date. The observation collector separately reads current ECS task counts.
Historic incident notes require rechecking. Local execution does not establish isolation from production data.
KPI contracts are visible but unbound: connect existing canonical producers before setting measured values or targets.
OpenBrand KPI calculations must remain with their existing producers.

## Validation And Rollout

Run the estate API, registry, sync, and applications tests plus the JavaScript applications tests.
Check stale data, failed app with live operator, missing expected signals, discovery conflicts, and retirement.
Use the existing isolated `norman-release@<sha>` canary before switching the production release.
The previous release remains the rollback path; this change requires no database migration.

## Production Static Files

The Norman host's Caddy configuration serves most `/static/` requests from `/var/www/norman-static`.
For this release, install `app/static/js/estate_applications.js` and
`app/static/css/estate_applications.css` into the corresponding `js/` and `css/` directories there.
Verify their public checksums against the candidate release; localhost asset checks alone are insufficient.
The files are additive, so the prior release can be restored without deleting assets.

## Application Evidence Collector

Install `scripts/collect_estate_app_health.py` as `/usr/local/libexec/norman-estate-observe` and the two
`norman-estate-observations` systemd units from `scripts/systemd/`. Install `db/estate/observation-targets.json`
as `/var/lib/norman/state/estate-observation-targets.json`, readable by the `kristopher` service user.
Enable the timer to collect every five minutes. The collector atomically writes
`/var/lib/norman/state/application-observations.json`; no credentials are copied or services restarted.
Existing SSH identities read selected unit properties and two allowlisted output summaries.
Existing AWS profiles on Hal read the explicitly mapped ECS services in bounded batches.

Process and ECS capacity observations show runtime coverage, not end-to-end application success.
Scout and Housebot output reports retain their original timestamps; stale metrics are historical.
The two-hour output freshness threshold is a monitoring default pending confirmation of producer cadence.
Failures to observe a host or AWS are observation gaps, not proof that the application is down.
DOHIO `fail` and `warn` levels remain visible as failed and partial checks.

Each application has a reviewed coverage category, evidence, and next action. Filter by category to work the queue.
On-demand projects do not require an always-on endpoint. Unassigned ownership remains unresolved.
Known operator consoles are reconciled separately from application checks.
Collected operational metrics do not bind the proposed business KPI contracts automatically.
