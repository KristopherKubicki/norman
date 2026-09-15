# Workflow Coverage — September 15, 2026

## Measurements And Responsibilities

The five-minute collector now reads Earlybird run history, known retry records and the running worker's
ASR preflight. It emits counts and timestamps only, never recordings, transcripts, source file IDs or business text.
Completed recordings and failed attempts use retained history within 24 hours. Known retries are not the entire
eligible Drive backlog. Last-success age remains unknown if retained history contains no successful recording.

Both Spark gateways expose ASR readiness, admission counts, socket backlog and a bounded request-log sample.
Secondary requests indicate worker use, including direct requests; they do not establish the cause of failover.
A separate failover-required signal is inferred from both readiness results and Caddy's first-worker policy.
No automatic service restart was added. The original accept-queue stall's cause remains undetermined.

Leadership KPIs, Gold Book and Control Plane now bind their canonical publication receipts. Their business
calculations remain with the existing producers. Initial receipts identify KPI Core and KPI sync failures,
a published Gold Book report and a controller snapshot with a source error.

Cloud observation now covers 58 ECS services, 18 autoscaling groups and 46 explicitly mapped EC2 instances.
For apps with autoscaling groups, group capacity replaces historical instance IDs as the runtime check.
Terminated/shutting-down instances remain inventory history, not active check targets.
Runtime state does not establish application output health. Missing resources remain explicit.

KPI bindings specify an observation ID and metric ID. Configured bindings, fresh values, stale history and
unknown values are distinct. Each metric retains its producer timestamp; refreshing a parent report cannot
make an old measurement fresh. Browser refresh failures clear displayed KPI freshness.

Scout is explicitly paused. Retired projects stay retired. Norman is the interim steward for personal
CostCrawler and Wafermancer; no dedicated TUI or live deployment is inferred. NetOps owns JA3 proxy
reconciliation, while its operating account remains unassigned.

## Earlybird Repairs And Limits

Real recordings exposed problems that short synthetic tests did not: the core's source defaults to a 16 MiB
upload limit, whereas the gateway permits 512 MB. Core rejection closed an upload connection and caused a
broken pipe / 502. Earlybird now normalizes media into bounded one-minute mono 16 kHz PCM chunks,
combines transcripts in order, preserves original media and cleans temporary chunks on success or failure.
A failed chunk fails the recording; a partial transcript is not reported as completed.

A 620-second synthetic WAV passed the chunked public ASR path. A normal recording attempt using the initial
five-minute chunks then timed out at the configured 180 seconds. Chunks were reduced to one minute.
A normal production run completed at 2026-09-15 13:26:57 UTC with one transcription and zero Whisper errors.

Caddy also recorded both ASR readiness probes timing out at two seconds and rejected a preflight with 503.
The ASR-only health interval is now 15 seconds with an eight-second timeout, reducing probe load and allowing
bounded slower readiness responses. Other Caddy routes were not regenerated.

Periodic silent-audio preflight now bypasses an old target cooldown so it can detect recovery; real media
uploads still honor cooldown. The recovery probe passed with a deliberately populated cooldown in an isolated
process. Service reloads occur between cycles. Two one-time cadence resets allowed normal recovery attempts;
per-recording retry history and the existing per-cycle media limit were retained.

Earlybird rollback: `eb.py.before-chunks-20260915` beside the deployed source on work-special.
Private state before-images remain on that host with mode 0600; they are not copied into the estate catalog.
Caddy before-image: `norman-bot-hosts.caddy.before-asr-probe-budget-20260915` beside the live include.

## Housebot Repairs And Remaining Device Work

Argyle's next live refresh succeeded. Beach cloud login, remote session, devices and apps succeeded, but
runtime statistics took about 95 seconds and failed. Optional runtime and log reads now have independent
20-second process limits. A failed optional check retains fresh device/app inventory and remains a warning.
Missing log counts are unknown, never zero. Some Halsted log reads also exceed that budget.

Gateway device 772, driver 1070, was polling the pfSense HTTP login page. It now mirrors the authenticated
WAN observation from the existing `pfsense-sync --device io --apply` job. The driver's new `setStatus` command
updates display attributes only; existing periodic polling checks for telemetry expiry after 15 minutes.
It no longer polls the login page once managed telemetry arrives. The sync and native driver compilation passed.
No additional management firewall access or physical-device command was introduced.

Rollback files on toy-box:

- `scripts/hubitat_site_health_check.py.before-optional-20260915`
- `housebot/main.py.before-wan-mirror-20260915`
- `out/pfsense-wan-driver-1070.before-mirror-20260915.groovy`

Remaining Knox diagnostics concern sensor 92 / app 856 command verification and Kitchen Ubuntu device 986
at 192.168.2.95:8096. The hub reports the latter unreachable; no matching Kitchen Ubuntu static DHCP entry was
found. Do not suppress these warnings or guess a replacement address. Beach runtime/log telemetry remains
unavailable even though its inventory now refreshes.

## Deployment And Validation

Install `estate_workflow_probes.py` beside `/usr/local/libexec/norman-estate-observe`.
The collector service timeout is 240 seconds, within its five-minute cadence and above bounded SSH/AWS work.
The old collector, target manifest and unit have before-images on Norman.

Focused validation covers KPI source identity/freshness, paused lifecycle, metric privacy, missing history,
optional Housebot telemetry failure, long audio chunk limits/order/cleanup, ASG capacity and failover inference.
Caddy configuration validation and reload passed. Browser tests cover stale/unknown KPI values after fetch failure.

## Confirmed Endpoint Gaps

Norman's application `/health` response is checked separately from its TUI. YHIX's expected public-key URL
currently fails DNS resolution from the collector; the YHIX owner action is to verify the intended DNS and
publication. No DNS change or key publication was performed.

Other projects retain explicit deployment gaps where only a checkout or operator console could be verified.
See `estate_coverage_queue_20260915.md` for the complete per-TUI work queue. Source presence is not promoted
to application health, and unbound business KPI contracts remain unknown.

Gateway collection uses a dedicated Norman SSH key restricted to a fixed metadata-probe command on each Spark.
The installed probe is `~/.local/libexec/estate_gateway_probe.py`; forwarding and interactive access are disabled.
