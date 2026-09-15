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
The overnight sentinel will use the fix on its existing schedule; its next run remains unverified.

The pfSense management target `192.168.2.1` still refuses HTTPS from both Housebot and NetOps.
Both authoritative internal names still resolve there. No guessed address or credential redirect was used.

## Earlybird

Logs identified MP4 format rejection followed by backend timeouts and target-wide cooldown.
Added conversion of non-WAV media to mono 16 kHz PCM WAV before remote upload, using a bounded
ffmpeg subprocess and automatic temporary-file cleanup. Original recordings remain untouched.
Invalid media fails before contacting the backend; the existing WAV preflight remains direct.
Three tests passed, including real conversion of a synthetic MP4 and rejection of invalid media.

Installed the change in `/home/kristopher/code/earlybird/eb.py` on work-special and restarted its user service
while it was between cycles. The service is active/running.
Rollback: `eb.py.before-remote-wav-20260915` beside the deployed file.

The separate backend outage remains: Norman's ASR route uses only `192.168.2.151:18151`,
while general gateway health can pass through other hosts. A synthetic one-second WAV returned 503.
Spark's root-owned `norllama-gateway.service` reported running, but health requests timed out
and its TCP listener showed a full accept queue. Logs contained broken-pipe errors; these do not establish
why the gateway stopped accepting promptly. The current SSH account lacks passwordless sudo on Spark,
so the root service was not restarted. Recover that gateway and validate ASR before claiming transcription recovery.

Scout remains paused. Business KPI bindings and the remaining unknown app checks are unchanged.
