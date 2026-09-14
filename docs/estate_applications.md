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

Deployment instances imported from AWS are dated inventory snapshots, not continuous AWS health checks.
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
