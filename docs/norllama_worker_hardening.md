# Norllama Worker Hardening

The ASR path must reject overload before an audio body is downloaded, parsed,
or replayed to another peer. These controls are designed to keep a failed
worker recoverable through its service manager rather than a host power cycle.

## Fleet alert delivery

Fleet health and policy-refresh alert paths use a dedicated `norllama-fleet`
Switchboard actor. Its token is kept in
`/etc/norman/credentials/norllama-fleet-bbs.token` and is exposed only through
the root-owned `norman-bbs-token-broker` for the logical
`bbs.norllama-fleet.post-token` alias. Do not borrow the `norman` actor token
or another service's credential.

Install `/etc/norman/tui-fleet-alerts.env` with the non-secret configuration
from `scripts/systemd/norman-tui-fleet-alerts.env.example`. The fleet actor
watches `netops`; existing TUI alert defaults remain unchanged.

## Application controls

The gateway source enforces the following defaults:

- One active ASR request and no ASR request queue.
- A 512 MiB upload limit, checked from `Content-Length` before the body is read.
- A `429` response with `Retry-After` when the ASR lane is busy.
- One local transcription candidate per request.
- No implicit peer forwarding for audio uploads.
- `/asr-readyz`, which is ready only when a local ASR worker is selected and
  the ASR admission slot is available.

The Caddy renderer gives transcription routes their own 512 MiB edge limit.
It currently sends ASR only to the verified worker at `192.168.2.151:18151`.
General model requests retain their normal pool.

## Service controls

The staged systemd drop-ins are:

- `scripts/systemd/norllama-gateway.service.d/zz-resource-guardrails.conf`
- `scripts/systemd/spark-audio-transcribe-core.service.d/zz-resource-guardrails.conf`

They add cgroup memory limits, disable service swap, bound task counts, and
stop restart loops after three failures. The deploy script stages the installer
and both drop-ins in the Spark gateway directory, so the worker does not need a
full Norman checkout. The installer applies the ASR payload to the active
`spark-audio-transcribe-core.service` or legacy
`spark-audio-transcribe.service` unit, so mixed-version workers receive the
same envelope. To stage a Spark worker without restarting it:

```bash
NORLLAMA_SPARK_TARGETS=kristopher@192.168.2.151 \
  ./scripts/norllama/deploy_gateway.sh --sparks-no-restart
```

Then, from an interactive session on that worker, apply the root-owned
service changes and restart only the transcription and gateway services:

```bash
sudo /home/kristopher/norllama/install_resource_guardrails.sh --apply --restart
```

The installer can be dry-run first without `--apply`. It restarts only the ASR
and Norllama services. During activation it switches the staged
`route_policy.next.json` into place while the gateway is stopped, verifies
`/healthz`, `/readyz`, `/asr-readyz`, and `/v1/models`, and restores the prior
policy if the new gateway does not become ready. It does not reboot the host.

## Restoring ASR redundancy

Do not add a worker to the ASR pool until all of the following are true:

1. The gateway source with `/asr-readyz` is deployed and its service has
   restarted successfully.
2. A real multipart transcription probe succeeds repeatedly on that worker.
3. The worker has healthy memory, swap, and process responsiveness.
4. The Caddy renderer lists the worker in `LOCAL_ASR_UPSTREAMS`.

For a multi-worker ASR pool, Caddy will use `/asr-readyz` rather than generic
`/healthz`, preventing a live process without ASR capacity from receiving a
large recording.

## Mac Mini Front Door

The Mac mini uses launchd rather than systemd, so its guardrails are
launchd-native: a 15-second restart throttle, a 30-second stop window,
bounded open files, and a 3/4 GiB resident-set preference. The resident-set
limit is a memory-pressure preference, not a Linux-style cgroup hard cap.

First deploy the matching gateway and installer:

```bash
./scripts/norllama/deploy_gateway.sh --mac-only
```

Then, from the `k` user session on the Mac mini:

```bash
/Users/k/norllama/install_macos_launchd_guardrails.py --apply --restart
```

The installer preserves the existing launchd wrapper and environment, creates
a timestamped plist backup, restarts only `org.lollie.norllama`, and verifies
`/healthz`, `/readyz`, `/asr-readyz`, and `/v1/models`.

## Network boundary

Keep the Spark gateway port (`18151`) reachable only from the Caddy front door
and approved worker peers. Keep the local transcription port (`8095`) limited
to the gateway host whenever the service supports a loopback bind. The edge
limit and gateway admission controls protect valid callers; network filtering
removes unsolicited LAN traffic as a source of load.
