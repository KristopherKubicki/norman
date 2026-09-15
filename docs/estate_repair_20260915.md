# Estate Repair — September 15, 2026

## Housebot

Hubitat 2.5.1.174's device UI sends `/device/runmethod` JSON containing `id`, `method`,
and positional `args` objects with `type` and `value`. Housebot used legacy form encoding,
which returned HTTP 500 even when argument types changed.

Patched `/opt/housebot/housebot/hubitat/web_session.py` on toy-box to match the observed UI contract.
Preserved blank argument positions and added no automatic retries for server errors.
Three focused tests passed. A metadata-only trial updated all five power-accounting summary devices;
the installed `housebot-power-accounting-sync.service` then exited successfully.
Rollback: `web_session.py.before-json-commands-20260915` beside the deployed file.
No physical-device command or additional automation was introduced.
The sentinel had a second legacy form encoder in `scripts/sync_overnight_light_sentinel_dashboard.py`.
Patched that helper to the same JSON contract and checked blank arguments and HTTP-error propagation.
Its systemd service, including dashboard metadata sync and the read-only verifier, now exits successfully.
Rollback: `sync_overnight_light_sentinel_dashboard.py.before-json-20260915` beside the deployed script.

pfSense's LAN rules allowed named administrator hosts and rejected other LAN management access.
Using the existing root SSH trust through Hal, inserted one persistent rule before that rejection:
`192.168.2.146` (Housebot) to `192.168.2.1`, TCP 443 only, description
`HOUSEBOT: allow pfSense HTTPS telemetry`, tracker `1789471024`.
Used pfSense native `write_config` and `filter_configure`; retained all other management restrictions.
Both the read-only telemetry command and `housebot-pfsense-sync.service` then succeeded.
Before-image: `/cf/conf/config.xml.before-housebot-https-20260915` on pfSense.
Helper recovery does not clear unrelated warnings in Housebot's site report.

## Earlybird

Logs identified MP4 format rejection followed by backend timeouts and target-wide cooldown.
Added conversion of non-WAV media to mono 16 kHz PCM WAV before remote upload, using a bounded
ffmpeg subprocess and automatic temporary-file cleanup. Original recordings remain untouched.
Invalid media fails before contacting the backend; the existing WAV preflight remains direct.
Three tests passed, including real conversion of a synthetic MP4 and rejection of invalid media.

Installed the change in `/home/kristopher/code/earlybird/eb.py` on work-special and restarted its user service
while it was between cycles. The service is active/running.
Rollback: `eb.py.before-remote-wav-20260915` beside the deployed file.

The public ASR route was pinned to `192.168.2.151:18151`, while general health could pass via other hosts.
The primary gateway's health timed out and its listener had a full accept queue despite an active service.
Broken-pipe logs do not establish the cause. The initial credential attempts failed; subsequent user clarification enabled sudo access.
Restarted `norllama-gateway.service` at 11:35 UTC. Its accept queue cleared and `/asr-readyz` passed.
Used the loaded unit configuration; an existing on-disk unit-change warning remains for separate reconciliation.

The underlying transcription core remained healthy. The secondary gateway `192.168.2.150:18151`
passed `/asr-readyz` and a one-second synthetic WAV upload (HTTP 200, `no_speech_detected`).
Added that worker to the ASR pool, using ASR-specific readiness and the existing 512 MB upload contract.
Changed only the ASR block in the live Caddy include, validated configuration, and reloaded Caddy successfully.
The source generator and route regression test now preserve the same two-worker ASR pool.
Caddy before-image: `/etc/caddy/includes/norman-bot-hosts.caddy.before-asr-failover-20260915` on Norman.

A synthetic WAV sent from work-special through `https://llm.home.arpa/v1/audio/transcriptions`
returned HTTP 200 and `no_speech_detected`. This verifies the public ASR path and silent-audio handling,
not real-recording transcription. Earlybird's own isolated ASR preflight also passed.

The full MP4 test found that work-special lacked `ffmpeg`. Installed the distribution package and dependencies
with `apt-get install --no-install-recommends ffmpeg` (5.1.9). Created a temporary synthetic speech MP4,
then called the deployed `eb.run_whisper_remote`: conversion and public ASR returned the exact sentence
"This is a routine transcription health check." The original remained intact; temporary test media was removed.
Restarted Earlybird at its next sleep interval to clear the previous backend cooldown.
Its running state recorded `whisper_remote_health.ready=true`, probe `asr-upload`, at 11:28 UTC.
Normal recording throughput remains unverified. After primary recovery, synthetic speech returned
the exact sentence both directly from `192.168.2.151:18151` and through the public ASR endpoint.
Both gateway workers are now available; retain failover and monitor for recurrence of the original stall.

Validation: 14 Caddy route tests and 19 estate/API/collector tests passed; format and lint passed.
Norman canary and production health passed, and the estate API continued requiring authentication (401).
The collector reports successful results for all four previously failed Housebot helper units.

Scout remains paused. Business KPI bindings and the remaining unknown app checks are unchanged.
