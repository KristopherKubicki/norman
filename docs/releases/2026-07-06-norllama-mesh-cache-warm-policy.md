# Norllama Mesh Cache And Warm Policy

Date: 2026-07-06
Scope: Norman LLM status APIs, console runtime capabilities, Norllama gateway,
Uplink benchmark packet consumption, and explicit model prefetch controls
Status: ready for Norman deployment

## Summary

This release makes the local-first model layer more durable and cheaper to run.
Norman now caches Norllama mesh snapshots, reads the Uplink benchmark packet, and
builds a visible warm-model policy for the TUIs and runtime. Passive status calls
do not trigger model loads; actual warming stays behind an explicit bounded
prefetch action.

## Changes

- Add a cached Norllama mesh snapshot with TTL and stale-on-error behavior.
- Fix Norllama frontdoor URL construction so a base URL ending in `/v1` does not
  call native `/api/*` endpoints under `/v1/api/*`.
- Add a gateway prefetch helper for the Norllama `/v1/prefetch` frontdoor API.
- Load the Uplink benchmark packet from `/var/lib/norman/norllama/benchmark_packet.json`
  or an optional URL.
- Build a benchmark-backed warm policy that classifies recommended models as
  `keep_warm`, `prefetch`, `skip_unavailable`, or `observe`.
- Expose the warm policy through `/api/llm/status`,
  `/api/llm/warm-policy`, `/api/llm/warm-policy/prefetch`, and
  `/api/v1/console-runtime/capabilities`.
- Keep prefetch dry-run by default at the API boundary.
- Update defaults toward the benchmark-backed Gemma 4 local lane.

## Verification

- `make format`
- `make lint`
- `make test`
- Focused local suite:
  `tests/test_norllama_gateway.py`,
  `tests/test_norllama_mesh_cache.py`,
  `tests/test_norllama_warm_policy.py`,
  `tests/test_llm_status_api.py`, and
  `tests/test_console_runtime_api.py::test_console_runtime_api_exposes_kernel_capabilities`
- Full local test suite: `928 passed, 5 warnings`.
