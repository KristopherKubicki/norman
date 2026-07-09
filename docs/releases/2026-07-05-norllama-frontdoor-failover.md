# Norllama Frontdoor Failover Matrix

Date: 2026-07-05
Scope: `llm.home.arpa`, Norman frontdoor Caddy, Norllama spark workers
Status: deployed and tested

## Route Contract

Clients and TUIs should use `https://llm.home.arpa`.

DNS points `llm.home.arpa` at Norman (`192.168.2.241`). Norman Caddy then
routes to the Norllama worker mesh:

1. `192.168.2.133:18151` - Mac mini fallback/frontdoor node, tiny models.
2. `192.168.2.150:18151` - production spark, large local models.
3. `192.168.2.151:18151` - production spark, large local models.

This is frontdoor failover, not DNS failover between worker IPs. Direct worker
addresses remain diagnostic/backend addresses. Direct Ollama LAN exposure on
`:11434` was checked and is not exposed on the three worker nodes.

## Caddy Tuning

The LLM frontdoor route now uses:

```caddy
lb_policy first
lb_try_duration 15s
lb_try_interval 250ms
fail_duration 20s
max_fails 1
health_uri /healthz
health_interval 3s
health_timeout 2s
```

The longer try window and shorter active health interval let a recovering spark
rejoin quickly after reboot or power-cycle. `2.133` remains preferred when it is
healthy, while `2.150` and `2.151` can carry work when `2.133` is unavailable.

## Test Method

Temporary Norman-side `iptables` OUTPUT rules blocked selected outbound
connections to worker `:18151` ports. The workers themselves were not stopped.
Each scenario then exercised frontdoor capabilities/model endpoints and small
generation requests through `https://llm.home.arpa`.

## Results

| Scenario | Frontdoor capabilities/model endpoints | Generation |
| --- | --- | --- |
| All workers available | Pass | `llama3.2:1b` passed |
| Mac mini only (`2.150`/`2.151` blocked) | Pass | `llama3.2:1b` passed |
| Production sparks only (`2.133` blocked) | Pass | 150 and 151 small model tests passed |
| `2.150` only (`2.133`/`2.151` blocked) | Pass | 150 small model test passed |
| `2.151` only (`2.133`/`2.150` blocked) | Pass | 151 small model test passed |
| All workers blocked | Expected degraded/offline signal | Generation not attempted |
| Cleanup/all workers restored | Pass | `llama3.2:1b` passed |

The TUI autosense path probes `/v1/capabilities`, `/api/tags`, and `/v1/models`;
those endpoints passed for every non-total-outage scenario, including
`2.151`-only. A raw `/healthz` probe can still show a transient timeout during
an immediate single-spark transition, but the autosense endpoints used by TUIs
remained available.

## Operational Notes

- Keep TUIs pointed at `https://llm.home.arpa`; do not configure direct worker
  URLs as the normal client path.
- Treat all-workers-blocked timeouts as local-model degraded/offline mode.
- Continue using Norllama capabilities/model listings for model selection and
  warm/prefetch policy.
- Next improvement: add a frontdoor-level status endpoint or Norllama mesh
  overview that reports per-worker health without depending on one selected
  upstream route.
