# Norllama Async Prefetch Runtime

Date: 2026-07-06
Scope: Norllama gateway on `2.133`, `2.150`, `2.151`; Norman LLM frontdoor
Status: deployed and tested

## Summary

Norllama `/v1/prefetch` is now an async job API across the Mac mini fallback
node and both production sparks. Prefetch calls return quickly with `202
Accepted`, a `job_id`, and `/v1/prefetch/status`; the actual model warm request
runs in the background. This gives TUIs a visible, pollable behavior stream
instead of making the UI wait on cold model loads.

Peer-delegated prefetch is now honest: a peer `202` response is reported as
delegated work until the peer status endpoint says `warm` or `failed`. It no
longer marks an accepted peer job as warm just because the peer accepted it.

## Changes

- Add in-memory prefetch job tracking with TTL and duplicate suppression.
- Add `/v1/prefetch/status` with GET/HEAD/OPTIONS support.
- Advertise `async_jobs` and `prefetch_jobs` in `/healthz` and
  `/v1/capabilities`.
- Keep chat/generate inference synchronous for now; async support is limited to
  model prefetch jobs.
- Poll delegated peer jobs through the peer status URL before reporting `warm`.
- Preserve a bounded `delegated` state when a peer accepts work but does not
  expose a terminal status before the local deadline.
- Clear per-request model hints at request start so keep-alive connections do
  not leak model context across requests.

## Deployment

- `192.168.2.133` Mac mini: launchd service `org.lollie.norllama`.
- `192.168.2.150` spark: systemd service `norllama-gateway.service`.
- `192.168.2.151` spark: systemd service `norllama-gateway.service`.
- Public client path remains `https://llm.home.arpa`.

Norman Caddy already fronts `llm.home.arpa` with the three Norllama workers and
active `/healthz` checks. This is frontdoor failover through Norman
`192.168.2.241`, not a DNS multi-A failover record.

## Verification

- Local Norllama gateway suite: `9 passed`.
- Mac mini Norllama gateway suite: `9 passed`.
- Spark `2.150` Norllama gateway suite: `9 passed`.
- Spark `2.151` Norllama gateway suite: `9 passed`.
- All-up live health: frontdoor, `2.133`, `2.150`, and `2.151` all returned
  `status: ok`, `async_jobs: true`, and `prefetch_jobs: true`.
- Frontdoor `gemma3:1b` prefetch: returned `202` in about `45ms`, then status
  reported `warm`.
- Spark-delegated prefetch: both sparks returned `202` quickly and reported
  peer-backed `warm` instead of falsely treating the initial peer `202` as warm.
- All-up spark-specific model checks passed through `llm.home.arpa` and direct
  spark gateways using the small OpenFugu 3B model variants.
- With `2.151` gateway stopped: public frontdoor health stayed OK and Mac-local
  tiny prefetch still warmed.
- With both spark gateways stopped: public frontdoor health stayed OK,
  Mac-local tiny prefetch warmed, and spark-only prefetch failed fast with
  `ollama_model_unavailable`.
- Both spark gateways were restored and rechecked healthy after the outage
  scenarios.

## Operational Notes

- TUIs should continue targeting `https://llm.home.arpa`.
- TUIs can now poll `/v1/prefetch/status?job_id=...` for visible warm progress.
- Treat `delegated` as a real in-flight/degraded state, not as success.
- Treat `ollama_model_unavailable` as local-model degraded mode when the sparks
  are down and only the Mac mini fallback set remains.
- Next runtime slice should expose per-worker health in a first-class mesh
  status endpoint so TUIs do not infer worker state from one selected upstream.
