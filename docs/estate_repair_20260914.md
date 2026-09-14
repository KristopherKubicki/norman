# Estate Application Repair — September 14, 2026

## Verified Repairs

- Housebot passive Beach Eufy health sync: NetOps guard rejected source `192.168.2.146` to TCP 8084.
  Added only that source/port to the live rule and `/etc/nftables.d/netops_guard.nft`.
  Housebot then received HTTP 200 and the passive sync exited successfully.
  Before-image: `/etc/nftables.d/netops_guard.nft.before-housebot-20260914` on NetOps.
- Glimpser: DOHIO private aliases pointed to the Tailscale media listener, which rejected private-hostname TLS.
  Verified the LAN endpoint with the existing estate CA, then changed exactly `glimpser.home.arpa` and
  `glimpser.home.lollie.org` to `192.168.2.145` in `/etc/unbound/conf.d/dohio-split-view-overrides.conf`.
  Installed the public Lollie root CA under `/etc/pki/ca-trust/source/anchors/` on DOHIO.
  `unbound-checkconf` passed; Norman resolved the new address and received HTTPS 200.
  Existing Tailscale Funnel media routing was retained. DNS before-image suffix: `.before-estate-20260914`.
- Headnet: EC2 identities, deployed `server_url`, and direct TLS health agree that A-plane is
  `head.valgrind.com` at `3.133.70.173` and B-plane is `head.ziminiar.com` at `3.151.144.86`.
  Corrected canonical DOHIO hosts, surfaces, and service descriptions from the retired `mesh-*` names.
  Refreshed the dashboard snapshot; both services report healthy.
  Registry before-images under `/etc/dohio/registry.d/` have suffix `.before-headnet-20260914`.

## Monitoring Corrections

Earlybird runs in the user systemd manager on work-special. Its disabled system unit is obsolete.
The collector now explicitly queries `user:earlybird.service` with the user's runtime directory.
Recent archive and Avoma cycles reported zero errors; remote Whisper was unavailable, so transcription
coverage is not established by the running process.

Autocamera runs as `autocamera-webcam.service` on Hal. The collector now uses that verified unit.
It remains runtime-only until frame/output checks are bound.

Successful idle oneshot helpers are shown as idle rather than as unexplained failures.
Reviewed app-specific next actions are retained when a process becomes reachable.

## Remaining Work

- Scout's worker and monitor cron entries were explicitly paused by NetOps on May 26.
  The latest recorded worker cycle is July 7. Preserve the pause pending a scheduling decision.
- Housebot pfSense sync targets `192.168.2.1`, which refuses connections from Housebot.
  Confirm the intended management route; do not redirect credentials to a guessed endpoint.
- Housebot power-accounting metadata writes to app 763 children 1573–1577 return Hubitat HTTP 500.
  A bounded retry and alternate argument encoding reproduced the failure; no client patch was justified.
  Overnight summary failures are intermittent. No physical-device control or firmware change was made.
- The deployed DOHIO DNS override file is generator-managed. Its generator checkout was not located in
  this session; preserve the corrected aliases on future DNS deployments rather than restoring stale mappings.
- Runtime capacity and endpoint checks do not establish business KPI correctness, backup restore success,
  or complete client reauthentication. These still need canonical producers and workflow checks.
