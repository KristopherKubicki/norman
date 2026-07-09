# Norllama Route Attribution TUI

Date: 2026-07-06
Scope: Norman console runtime, shared TUI template, Norllama worker gateways
Status: deployed to Norman, toy-box, networking-host, and the three Norllama workers

## Summary

The Norman runtime and TUIs can now see which Norllama worker actually handled
a local model route. Frontdoor requests through `llm.home.arpa` now return a
worker endpoint header, and Norman maps that to the configured worker roster so
route summaries can count `mac-mini-133`, `spark-150`, and `spark-151`.

## Changes

- Added structured Norllama route attribution to model receipts.
- Preserved sanitized `X-Norllama-*` routing headers in the Norman Norllama
  gateway client.
- Added `workers.by_id`, `route.by_worker`, and `planner.by_worker` to runtime
  route summaries.
- Surfaced worker counts in the Norman console and shared agent TUI route line.
- Enabled upstream detail headers on the three live Norllama gateways.
- Patched the live gateway scripts to emit `X-Norllama-Worker-Endpoint`.

## Live Verification

- All three workers healthy with `upstream_details_public: true`.
- `gemma3:1b` through `llm.home.arpa` attributes to `mac-mini-133`.
- OpenFugu 3B through `llm.home.arpa` attributes to `spark-151`.
- `deepseek-v4-flash` through `llm.home.arpa` attributes to `spark-150`.
- With `2.151` stopped, Mac and `spark-150` routes stayed available and the
  `spark-151`-only model failed fast.
- With `2.150` stopped, Mac and `spark-151` routes stayed available.
- With both sparks stopped, Mac tiny-model fallback stayed available and
  spark-only lanes failed fast with explicit local errors.

## Verification

- `make format`
- `make lint`
- `make test`: `937 passed, 5 warnings`
- `npm test -- --runInBand`: `2 suites passed`, `4 tests passed`
- Remote Norman focused route/runtime suite: `76 passed`

## Follow-Up Notes

- The live Norllama gateway script patch is still an estate patch, not a
  repo-driven Norllama release. Before the next gateway refresh, move the
  `X-Norllama-Worker-Endpoint` behavior and
  `NORLLAMA_EXPOSE_UPSTREAM_DETAILS=1` defaults into the Norllama source of
  truth so a manual gateway deploy cannot erase route attribution.
- Spark prefetching should become a worker-aware residency controller. The
  current Norman warm policy identifies benchmark-backed candidates and can call
  `/v1/prefetch`, but it does not yet pin a target model set per worker, track
  per-worker memory pressure, or continuously maintain a hot set.
- Treat `mac-mini-133` as the tiny/fallback resident set and use the sparks for
  benchmark-backed production residents. The first durable target should be:
  `spark-150` for DS4/deepseek and Qwen 3.5/large coder lanes, `spark-151` for
  OpenFugu/Gemma/alternate production lanes, and the Mac mini for canaries and
  tiny degraded-mode models.
