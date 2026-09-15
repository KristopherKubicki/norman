# Remaining Issue Repairs — September 15, 2026

## Applied Repairs

- YHIX Keys: published `.nojekyll` in commit `27d6cbf`. GitHub Pages completed the build; the key URL
  returned HTTP 200 using the Pages origin with the configured host header. Its bytes match `public-key.pem`.
  No private key was read or published. Custom-domain DNS and certificate issuance remain outstanding.
- Housebot: fixed `run_worker` to drain its multiprocessing queue before joining the child. Large results
  otherwise keep the child feeder alive and look like a timeout. A one-megabyte result, hung worker,
  crashed worker and cleanup checks passed. Halsted subsequently returned complete live telemetry.
- Control Plane: load old Gold Book fallbacks only when canonical rows are absent, and pass the reporting
  week to their freshness guards. A present failed row is never replaced. Dependency/freshness checks and
  both existing controller tests passed. The regenerated 13:48:41 UTC controller receipt has zero source
  errors. The canonical calculation and publication contracts remain intact.

## Evidence And Blockers

Leadership core succeeded for 52 of 56 metrics for the September 7–13 week. Three missing-price inputs are
blank in their source worksheet. The fourth requires real category-refresh dates, which the current Gold Book
release does not provide. Publication/download timestamps cannot stand in for category freshness.

Pricing ingestion reports 36 dropped rows. Its ingestion scope differs from the weekly missing-price counts;
those are separate issues. Usage coverage and workload cost allocation also remain incomplete.

Beach inventory and past logs respond from the existing local relay. Its `/logs/json` endpoint timed out
locally after 30 seconds while `/device/list` and `/logs/past/json` returned HTTP 200. Remote Admin is also
intermittent. No hub reboot, log clearing, or firmware upgrade was attempted based on this partial diagnosis.

Hallway sensor 92 reports off and has recent activity. App 856 retains an earlier off-verification failure;
keep that history rather than treating it as proof the light is still on.

Kitchen kiosk device 986 last reported September 14 at 20:40 UTC. The known host is 192.168.2.95,
MAC 50:af:73:24:6a:b0. LAN ARP/ping and SSH failed. One directed Wake-on-LAN packet did not restore it.
A physical power/network check is required; no replacement IP was guessed.

YHIX needs this record in its authoritative DNS account:

| Name | Type | Value |
| --- | --- | --- |
| keys.yhix.com | CNAME | kristopherkubicki.github.io |

After DNS resolves, verify GitHub Pages certificate issuance, enable enforced HTTPS when the certificate
is ready, and check the exact `.well-known/appspecific/com.tesla.3p.public-key.pem` path over HTTPS.
The origin check alone does not establish custom-domain readiness or Tesla vehicle authorization.

## Rollback And Scope

Housebot before-image: `/opt/housebot/scripts/hubitat_site_health_check.py.before-queue-20260915` on toy-box.
Control Plane before-image: `scripts/kpi_controller_snapshot.py.before-estate-20260915` on work-special.
YHIX rollback: revert `27d6cbf` if needed; the existing public key is unchanged.

Operational fixes were scoped to the deployed scripts. Existing unrelated worktree changes were preserved.
The latest owner actions and evidence are recorded in Norman's application catalog.
