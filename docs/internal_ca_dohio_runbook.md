# Internal CA and DOHIO Runbook

Status checked from Norman on 2026-04-29.

## Summary

Smallstep CA is live at `ca.home.arpa` and `ca.home.example.test` on
`192.168.0.149`. It serves the estate trust root named
`Example Internal CA Root CA`.

Lifecycle procedures for adding, parking, retiring, and archiving hosts, bots,
TUIs, DOHIO registry entries, Caddy routes, BBS routing, and heartbeats now live
in [DOHIO Host and Bot Lifecycle Runbook](dohio_host_bot_lifecycle_runbook.md).

DOHIO is live at `dohio.home.arpa` and `dohio.home.example.test` on
`100.99.220.14`, host `cloud-gw-ohio`. DOHIO DNS currently knows the CA names,
but DOHIO HTTPS is still issued from a separate `DOHIO Local CA`, not from the
Example Internal CA chain.

Dashboard image embeds that must render inside Chromium, Hubitat dashboards, or
tablet kiosk paths should stay on LAN HTTP until the Example root is distributed
to those clients and verified in those renderers.

## Confirmed Live Facts

- `ca.home.arpa` resolves to `192.168.0.149`.
- `ca.home.example.test` resolves to `192.168.0.149`.
- `https://ca.home.arpa/health` returns `{"status":"ok"}`.
- `https://ca.home.arpa/version` returns Smallstep `0.30.2`.
- `https://ca.home.arpa/roots.pem` serves `Example Internal CA Root CA`.
- CA provisioners exposed by `https://ca.home.arpa/provisioners` are `admin` JWK and `acme` ACME.
- `glimpser.home.example.test` presents a leaf cert issued by `Example Internal CA Intermediate CA`.
- `dohio.home.arpa` resolves to `100.99.220.14`.
- `dohio.home.example.test` resolves to `100.99.220.14`.
- DOHIO `/api/status` reports brand `DOHIO`, name `dns-ohio`, host `cloud-gw-ohio`.
- DOHIO services report `unbound`, `firewall_guard`, and `dashboard` active.
- DOHIO private probe resolves `norman.home.arpa` to `100.103.34.17`.
- Queries to `@100.99.220.14` resolve `ca.home.arpa` and `ca.home.example.test` to `192.168.0.149`.
- Queries to `@100.99.220.14` resolve Norman-hosted bot names such as `uplink.home.arpa` to Norman tailnet IP `100.103.34.17`.
- Pending as of `2026-05-02`: `artmonster.home.arpa` should resolve to the Norman front door (`100.103.34.17` on the tailnet, LAN split view matching `norman.home.arpa`) but is not yet present in local DNS.

## Certificate Split

There are currently two trust roots in play.

Estate CA:

- Root subject: `O = Example Internal CA, CN = Example Internal CA Root CA`
- Root fingerprint: `2D:C0:CA:51:B9:FA:8A:D3:CE:98:3A:69:63:7E:A4:BC:39:5C:34:2C:DA:3C:D9:FA:9B:C7:E6:80:F3:DC:5D:AF`
- Root URL: `https://ca.home.arpa/roots.pem`
- Intended role: long-term estate trust root for internal HTTPS.

DOHIO local CA:

- Root subject: `CN = DOHIO Local CA`
- Root fingerprint: `17:C3:7F:89:19:92:D3:DE:FF:18:9A:91:97:00:BF:7E:32:8B:A0:55:18:AB:2D:0E:16:C6:F3:59:2C:3D:C7:0D`
- Root URL from DOHIO dashboard: `https://dohio.home.arpa/ca/root.crt`
- Current role: local DOHIO dashboard TLS root.

Current DOHIO leaf:

- Subject: `CN = dohio.home.arpa`
- Issuer: `CN = DOHIO Local CA`
- Validity checked: `2026-04-26` through `2028-07-29`

This means DOHIO DNS appears synchronized for CA names, but DOHIO TLS has not
yet been reissued under the Example Internal CA chain.

## DOHIO Relationship

Confirmed:

- DOHIO is the tailnet DNS view for selected `home.arpa` names.
- DOHIO knows `ca.home.arpa` and `ca.home.example.test`.
- DOHIO dashboard text identifies `ca.home.arpa` / `ca.home.example.test` as the real long-term issuer.
- DOHIO dashboard text says DOHIO should be reissued from the estate CA instead of carrying a one-off local CA.

Not confirmed from Norman:

- The exact sync source for DOHIO DNS records.
- Whether `ca.home.arpa` is populated from pfSense/home authority, a DOHIO registry file, or another CloudAgent sync job.
- The service unit, repository, and deployment owner for DOHIO's DNS record synchronization.
- The record source for newly added Norman-hosted bot names such as `artmonster.home.arpa`.

NetOps/CloudAgent should confirm this on `cloud-gw-ohio` and document the
source of truth for `home.arpa` and `home.example.test` records.

## BBS Access Source

Norman's estate registry now carries the machine-level BBS policy contract in
`bbs` blocks on workers. DOHIO/NetOps should treat those blocks as the
authoritative local intent when enrolling bot machines into Switchboard/BBS
delivery:

- `norman-host`: broker/root coverage, including private and cross-zone access.
- `toy-box`: personal-zone participant only.
- `private-host`: private enclave, explicit cross-zone/private coverage.
- `networking-host`: network-zone full coverage only.
- `openbrand-work-service-node`: work-zone participant only.

The registry helper projects these blocks to Norman connector config keys such
as `bbs_acl_role`, `bbs_zone`, `bbs_full_coverage`, and `bbs_cross_zone`. The
remaining DOHIO-side work is to identify the sync job on `cloud-gw-ohio` and
wire that job to this registry contract instead of relying on hostname
inference.

## Ownership

Confirmed host/service facts:

- Smallstep CA host: `192.168.0.149`.
- Smallstep service endpoint: `https://ca.home.arpa/`.
- DOHIO host: `cloud-gw-ohio`, tailnet IP `100.99.220.14`.
- DOHIO role: recursive/policy resolver and estate DNS portal.
- Norman management access gap checked on `2026-06-07`: Norman can reach
  DOHIO HTTPS and normal SSH reaches `root@100.99.220.14`, but the host does
  not yet accept the Norman deploy key. The access request is tracked in
  Switchboard thread `th_dohio_tailnet_dns_20260427`.

Ownership still needs an explicit assignment:

- Smallstep CA lifecycle owner.
- Smallstep host owner.
- Renewal/provisioner policy owner.
- DOHIO DNS sync owner.
- Client trust distribution owner.

Until assigned, treat this as NetOps/CloudAgent-owned.

## Client Trust Distribution

Required trust target is `Example Internal CA Root CA`, not the DOHIO local root.

Client classes to verify:

- Linux desktops and laptops: install into system trust and Chromium/NSS trust if Chromium does not use the system store in that environment.
- Phones and tablets: import the Example root for browser trust.
- Hubitat dashboard render paths: verify whether the dashboard renderer uses platform trust, embedded Chromium trust, or a separate certificate store.
- Kiosk/tablet Chromium paths: verify actual image loading in the deployed browser profile, not just `curl`.

Trust is not considered complete until the real dashboard renderer can load
`https://glimpser.home.example.test/...` images without `ERR_CERT_AUTHORITY_INVALID`.

## Dashboard Embed Decision

Keep dashboard screenshot/image embeds on LAN HTTP for now.

Return embeds to HTTPS only after:

- `Example Internal CA Root CA` is distributed to the actual render clients.
- Chromium/Hubitat/tablet paths are verified with HTTPS image loads.
- DOHIO's own TLS plan is settled, ideally by reissuing DOHIO from the estate CA.

The temporary LAN HTTP path is acceptable for local dashboard rendering because
it avoids broken images while trust rollout is incomplete. It should not become
the long-term default for surfaces that need end-to-end HTTPS.

## Verification Commands

```bash
getent ahostsv4 ca.home.arpa ca.home.example.test dohio.home.arpa dohio.home.example.test
curl -k https://ca.home.arpa/health
curl -k https://ca.home.arpa/version
curl -k https://ca.home.arpa/provisioners
curl -k https://ca.home.arpa/roots.pem | openssl x509 -noout -subject -issuer -dates -fingerprint -sha256
dig @100.99.220.14 ca.home.arpa A +short
dig @100.99.220.14 ca.home.example.test A +short
curl -k https://dohio.home.arpa/api/status
curl -k https://dohio.home.arpa/ca/root.crt | openssl x509 -noout -subject -issuer -dates -fingerprint -sha256
printf '%s\n' | openssl s_client -connect dohio.home.arpa:443 -servername dohio.home.arpa -showcerts 2>/dev/null | openssl x509 -noout -subject -issuer -dates -fingerprint -sha256
printf '%s\n' | openssl s_client -connect glimpser.home.example.test:443 -servername glimpser.home.example.test -showcerts 2>/dev/null | openssl x509 -noout -subject -issuer -dates
```

## Open Items

- Find and document the DOHIO DNS sync source on `cloud-gw-ohio`.
- Enroll or document Norman's management SSH path for `cloud-gw-ohio`.
- Wire DOHIO/NetOps BBS enrollment to the estate registry `bbs` worker policy
  blocks.
- Assign a named Smallstep CA lifecycle owner.
- Decide whether DOHIO should immediately be reissued by Smallstep CA.
- Define and test trust distribution for Chromium, Hubitat, and tablet dashboard renderers.
- Move Glimpser dashboard embeds back to HTTPS only after renderer trust is proven.

Eyebat referenced these artifacts, but they were not present on Norman during
this check:

- `/opt/housebot/out/dashboard_image_url_fix_2026-04-29/note.md`
- `/opt/housebot/out/dashboard_render_review_2026-04-29/post_url_fix_render_report.json`
