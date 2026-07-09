# Norllama Benchmark Residency TUI

Date: 2026-07-06
Scope: Norman warm policy, Norllama prefetch routing, console runtime status, and
shared TUI visibility
Status: ready for Norman deployment

## Summary

Norman's local-first model layer now builds a worker-aware residency plan from
Uplink benchmark evidence instead of treating the warm set as a static list.
Weak benchmark candidates are not warmed just because they are present, the Mac
mini fallback stays focused on tiny/canary models, and spark prefetch requests
carry target-worker hints for direct routing when the Norllama gateway supports
them.

## Changes

- Add benchmark quality gates for score, coverage, and explicit rejected/weak
  statuses.
- Rank same-priority benchmark models by score before choosing prefetch
  candidates.
- Add worker-fit logic for Mac mini fallback versus production sparks.
- Estimate worker pressure from active resident models and avoid lower-priority
  warming on pressured workers.
- Add `residency_posture`, `residency`, and per-worker warm plans to
  `/api/llm/warm-policy`.
- Pass `target_worker` and `target_endpoint` hints through Norman's Norllama
  prefetch client.
- Surface compact Norllama mesh and warm posture in
  `/api/v1/console-runtime/worker/status`.
- Show Norllama warm posture and mesh health in Norman's runtime console.
- Add shared TUI `local_llm_health` status and a `Local LLM` system metric when
  endpoints expose warm-policy data.

## Operator Notes

- `mac-mini-133` remains a fallback/canary resident target by default. It should
  not accumulate large warm models during normal production routing.
- `spark-150` is preferred for Qwen/coder and DeepSeek-family production lanes.
- `spark-151` is preferred for Gemma and alternate production lanes.
- OpenFugu or any other small planner model must earn residency through current
  benchmark scores; low-score candidates are observed or skipped instead of
  warmed.
- Prefetch remains explicit and bounded. Dry-run output includes the intended
  worker before any live warm request is sent.

## Verification

- Focused local suite:
  `tests/test_norllama_warm_policy.py`,
  `tests/test_norllama_gateway.py`,
  `tests/test_console_runtime_api.py::test_console_runtime_api_exposes_worker_status`,
  and `tests/test_console_runtime_tui_source.py`: `20 passed`.
