# Norllama / Model Architecture Audit Handoff

Date: 2026-07-07
Status: handoff packet for independent technical audit
Audience: senior/pro agent auditing Norman local-first AI runtime, model stack, Norllama mesh, TUI routing, and Uplink benchmark integration

## Executive Brief

Norman is being moved from a Codex/cloud-first TUI wrapper toward a provider-neutral runtime where TUIs route through a Norman kernel, prefer Norllama/local Spark models, and escalate to cloud LLMs only when policy, confidence, or task risk requires it.

The current implementation has the main pieces in place:

- Console runtime kernel with DB-backed job/event stream.
- TUI shadow/primary kernel paths that record route, planner, model, tool, shell, and goal-loop events.
- Norllama model adapter and task router.
- Norllama front door at `https://llm.home.arpa`.
- Spark mesh: `2.133` fallback, `2.150` production, `2.151` production.
- Capability catalog for model/task lanes.
- Benchmark-backed warm policy that reads Uplink benchmark packets.
- Usage ledger and `local_first_kpi` to track offline/local vs OpenAI/Codex vs Bedrock/Amazon vs Perplexity/web tokens.

The audit should determine whether this is only architecturally plausible or actually correct under live conditions.

## Primary Audit Questions

1. Are TUIs really using Norllama/Sparks for daily local-first planner, scout, filter, draft, and verification work?
2. Does the route policy select the right model for the task, or does it still fall back to stale/default environment models?
3. Do benchmarks on Uplink match the model catalog and warm-policy decisions in Norman?
4. Are large models being warmed only where they fit, especially avoiding `2.133` for heavy models?
5. Does `llm.home.arpa` route efficiently across peers and fail over cleanly when a node is down?
6. Does the local-first KPI prove lower cloud LLM usage, separated from Perplexity/search usage?
7. Are safety/specialist models actually available and routed, or only present in the catalog?
8. Are routing receipts, worker attribution headers, and usage events enough to debug bad decisions?

## System Map

```text
Web TUI / agent console
  |
  | turn shadow, planner receipts, run requests
  v
Norman console runtime API
  |
  | DB-backed jobs/events, local-first policy, usage ledger
  v
Console runtime worker / kernel
  |
  | NorllamaModelAdapter, route_task(), route receipts
  v
Norllama front door: https://llm.home.arpa
  |
  | Caddy / Norllama peer routing / route headers / prefetch
  v
+----------------------+   +----------------------+   +----------------------+
| mac-mini-133         |   | spark-150            |   | spark-151            |
| 192.168.2.133:18151  |   | 192.168.2.150:18151  |   | 192.168.2.151:18151  |
| 16 GB fallback       |   | 128 GB production    |   | 128 GB production    |
| tiny/canary models   |   | router/code/rerank   |   | judge/perception/doc |
+----------------------+   +----------------------+   +----------------------+
  ^
  |
Uplink benchmark packet
  |
  v
Norman warm policy / residency / route guardrails
```

Important design point: clients should use `https://llm.home.arpa`. Direct worker URLs are diagnostic/backend addresses. This is frontdoor/mesh failover, not DNS multi-A client failover.

## Key Repo Files

Runtime/kernel:

- `app/services/console_runtime/policy.py`
  - `with_local_first_catalog_defaults()` applies local-first Norllama/catalog route defaults.
  - `resolve_runtime_mode()` controls primary online, local-first, cloud-LLM-offline, LAN-only, airgap, and control-only behavior.
- `app/services/console_runtime/store.py`
  - DB job/event store.
  - Route summary, usage ledger, `local_first_kpi`.
  - Separates offline/local, OpenAI/Codex, Bedrock/Amazon, Perplexity, other cloud.
- `app/services/console_runtime/worker.py`
  - Bounded/continuous goal loop.
  - Plan/work/verify phase sequencing.
  - Emits route decisions, planner receipts, model events, shell/tool events.
- `app/services/console_runtime/adapters/norllama.py`
  - Provider-neutral adapter into Norllama.
  - Carries Norllama route/receipt metadata onto model results.
- `app/api/api_v1/routers/console_runtime.py`
  - `/console-runtime/capabilities`
  - `/console-runtime/route-summary`
  - `/console-runtime/local-first-proof`
  - `/console-runtime/worker/status`
  - `/console-runtime/jobs/{job_id}/planner/receipts`
  - `/console-runtime/jobs/{job_id}/runs`

Norllama:

- `app/services/norllama/capability_catalog.py`
  - Canonical local model/task catalog.
  - Default model by task kind.
  - Warm-policy recommendations from catalog.
- `app/services/norllama/routing.py`
  - Task kind to lane/capability routing.
  - Local vs cloud proxy route decision.
  - Supports `model_selection=warm_policy` for benchmark/residency-backed model selection.
  - Emits `norman.norllama.route-receipt.v1` proof payloads with provider, model, worker, policy, benchmark, token bucket, verifier, and output-shape fields.
  - Route receipts include warm-policy pool evidence when dynamic model selection is used.
  - Frontdoor/worker attribution.
  - Response header attribution from Norllama gateway.
- `app/services/norllama/model_reality.py`
  - Reconciles catalog desire against mesh inventory, worker fit, fresh Uplink benchmark evidence, residency, and recent route outcomes.
  - States include aspirational, installed/servable-unproven, routable, resident, degraded, and blocked.
- `app/services/norllama/warm_policy.py`
  - Loads Uplink benchmark packet.
  - Builds warm/residency policy.
  - Applies benchmark quality gates.
  - Emits route guardrail matrix.
  - Selects task models by primary lane first and fails closed when the lane is cooled down or blocked.
  - Blocks catalog-only models from default warm/routing eligibility until reality proof exists.
  - Ranks eligible pools dynamically by lane fit, residency, worker pressure, benchmark score/coverage, model size, and recent route outcomes.
- `app/services/norllama/gateway.py`
  - Calls Norllama endpoints.
  - Fetches capabilities, mesh overview, activity.
  - Handles prefetch and OpenAI-compatible chat invocation.
- `app/services/norllama/route_outcomes.py`
  - Local route outcome ledger and cooldown evidence.
  - Cooldown checks can be scoped by model and worker.

TUI:

- `scripts/agent_console_template/agent_console_web.py`
  - Shared web TUI template.
  - Creates per-turn console-runtime shadow jobs.
  - Posts planner receipts and mirrors audit events.
  - Sends local-first kernel run requests.
- `app/static/js/consoles.js`
  - Norman runtime console UI.
  - Displays Norllama status, mesh posture, local-first KPI, usage split, events.

Tests to inspect:

- `tests/test_norllama_routing.py`
- `tests/test_norllama_warm_policy.py`
- `tests/test_norllama_gateway.py`
- `tests/test_norllama_proxy.py`
- `tests/test_console_runtime_policy.py`
- `tests/test_console_runtime_store.py`
- `tests/test_console_runtime_worker.py`
- `tests/test_console_runtime_api.py`
- `tests/test_console_runtime_tui_source.py`
- `tests/test_agent_console_runtime_bridge.py`

## Current Model Catalog To Audit

The catalog currently includes the following role assignments. The auditor should verify whether each model is actually available on the mesh, benchmarked, routable, and worth keeping.

| Lane | Model | Intended worker | Residency | Audit focus |
| --- | --- | --- | --- | --- |
| Fast agent/router/planner | `nvidia/Qwen3.6-35B-A3B-NVFP4` | `spark-150` | resident | Is this real/available, fast enough, and better than current benchmark-backed defaults? |
| Coding operator | `nvidia/Qwen3.6-27B-NVFP4` | `spark-150` | resident | Validate as default local coding brain. |
| Heavy local judge | `nvidia/Qwen3.5-122B-A10B-NVFP4` | `spark-151` | warm on demand | Validate latency, memory pressure, and judge quality. |
| Text embeddings heavy | `Qwen/Qwen3-Embedding-8B` | `spark-150` | resident | Verify embedding service support and index integration. |
| Text embeddings fast | `Qwen/Qwen3-Embedding-0.6B` | `mac-mini-133` | resident | Fallback only; check usefulness. |
| Text rerank heavy | `Qwen/Qwen3-Reranker-8B` | `spark-150` | resident | Should sit before expensive planner/judge/cloud calls. |
| Text rerank fast | `Qwen/Qwen3-Reranker-0.6B` | `mac-mini-133` | resident | Fast/degraded path. |
| Visual embedding | `Qwen/Qwen3-VL-Embedding-8B` | `spark-151` | warm on demand | Verify multimodal memory pipeline exists. |
| Visual rerank | `Qwen/Qwen3-VL-Reranker-8B` | `spark-151` | warm on demand | Verify screenshot/PDF ranking pipeline. |
| Visual doc retrieval | `nvidia/nemotron-colembed-vl-8b-v2` | `spark-151` | warm on demand | Audit whether installed/served anywhere. |
| OCR | `PaddlePaddle/PaddleOCR-VL-1.6` | `spark-151` | warm on demand | Verify real OCR serving path. |
| PDF Markdown | `opendatalab/MinerU2.5-Pro-2605-1.2B` | `spark-151` | warm on demand | Verify document ingestion path. |
| GUI grounding | `ServiceNow/GroundNext-7B-V0` | `spark-151` | warm on demand | Verify screen-coordinate action path. |
| ASR quality | `Qwen/Qwen3-ASR-1.7B-hf` | `spark-150` | warm on demand | Verify STT service path. |
| ASR fast | `Qwen/Qwen3-ASR-0.6B-hf` | `mac-mini-133` | resident | Verify low-latency command capture. |
| TTS | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | `spark-150` | cold only | Non-critical lane. |
| Safety generation | `Qwen/Qwen3Guard-Gen-8B` | `spark-150` | resident | Validate policy check integration. |
| Safety streaming | `Qwen/Qwen3Guard-Stream-0.6B` | `mac-mini-133` | resident | Validate pre-tool/browser streaming check. |
| Prompt injection | `qualifire/prompt-injection-sentinel` | `mac-mini-133` | resident | Validate hostile-context gate. |
| Observability forecasting | `Datadog/Toto-2.0-1B` | `spark-151` | cold only | Lab lane unless integrated with telemetry. |
| General forecasting | `amazon/chronos-2` | `spark-151` | cold only | Baseline/lab lane. |
| Estate graph | `GraphPFN-1.3` | `spark-151` | cold only | Lab lane. |
| Packet embeddings | `PacketCLIP` | `spark-151` | cold only | Lab lane. |
| DNS model | `DNS-GT` | `spark-151` | cold only | Lab lane. |

Important caveat: this catalog is a desired capability map, not proof that every model is installed, benchmarked, or supported by the current Norllama serving layer. Audit live availability separately.

## Existing Benchmark Path

Norman expects Uplink benchmark evidence through:

- Path: `/var/lib/norman/norllama/benchmark_packet.json`
- Optional URL: `settings.llm_benchmark_packet_url`
- Reader: `app/services/norllama/warm_policy.py::load_benchmark_packet`
- Recommendation parser: `benchmark_recommendations()`
- Warm policy builder: `build_warm_policy()`

Current benchmark quality gates in settings:

- `llm_warm_policy_min_benchmark_score = 0.6`
- `llm_warm_policy_min_coverage_ratio = 0.5`
- `llm_warm_policy_fallback_prefetch = False`
- `llm_warm_policy_prefetch_limit = 3`
- `llm_warm_policy_prefetch_timeout_seconds = 5`

The packet parser looks at:

- `shareable_view.recommended_roles`
- `shareable_view.model_scores`
- `shareable_view.model_rankings`
- `shareable_view.benchmark_results`
- `shareable_view.results`
- top-level equivalents for benchmark results/rankings when present

Audit questions for benchmarks:

1. Is the packet fresh?
2. Is it generated by Uplink from current Spark hardware and current Norllama versions?
3. Does it distinguish cold-start latency from warm latency?
4. Does it separate accepted answers from quick failures/timeouts?
5. Does it score per lane, not just average model quality?
6. Does it include TUI-sized caps and short-context prompts?
7. Does it include safety-sensitive exactness tests for identifiers, commands, configs, dates, and prices?
8. Does it mark OpenFugu/weak candidates as skipped instead of accidentally warmable?
9. Does it include worker placement recommendations?
10. Does it include output-shape checks, especially empty responses and progress-only answers?

## Live Endpoints To Check

Primary:

- Norman app: `https://norman.home.arpa`
- Uplink TUI/benchmark context: `https://uplink.home.arpa`
- Norllama front door: `https://llm.home.arpa`

Expected Norllama/frontdoor surfaces used by code/tests:

- `https://llm.home.arpa/v1/capabilities`
- `https://llm.home.arpa/v1/models`
- `https://llm.home.arpa/v1/overview`
- `https://llm.home.arpa/v1/activity?limit=200`
- `https://llm.home.arpa/v1/prefetch`
- `https://llm.home.arpa/api/tags`
- `https://llm.home.arpa/api/ps`
- `https://llm.home.arpa/api/generate`

Worker diagnostics:

- `http://192.168.2.133:18151`
- `http://192.168.2.150:18151`
- `http://192.168.2.151:18151`

Do not reconfigure TUIs to direct worker URLs for normal operation. Use direct worker URLs only to diagnose routing, inventory, pressure, and failure behavior.

## Runtime / API Checks

From Norman, inspect:

```bash
curl -fsS https://llm.home.arpa/v1/capabilities
curl -fsS https://llm.home.arpa/v1/models
curl -fsS https://llm.home.arpa/v1/overview
curl -fsS 'https://llm.home.arpa/v1/activity?limit=50'
```

From repo/runtime context, run:

```bash
make lint
make test
npm test
```

Focused tests:

```bash
./.venv/bin/pytest \
  tests/test_norllama_routing.py \
  tests/test_norllama_warm_policy.py \
  tests/test_norllama_gateway.py \
  tests/test_norllama_proxy.py \
  tests/test_console_runtime_policy.py \
  tests/test_console_runtime_store.py \
  tests/test_console_runtime_worker.py \
  tests/test_console_runtime_api.py \
  tests/test_console_runtime_tui_source.py \
  tests/test_agent_console_runtime_bridge.py \
  -q
```

Known latest local verification from this branch:

- focused proof/dynamic-pool tests: 57 passed.
- `make lint`: passed.
- `npm test`: 2 suites / 4 tests passed.
- `make test`: 1005 passed, 5 warnings.

Warnings were existing FastAPI/httpx deprecations, not Norllama-specific failures.

## Live Scenario Matrix

The pro agent should run real prompts and inspect route summaries/KPIs after each scenario.

1. All nodes up
   - Expected: planner/filter/scout route local via `llm.home.arpa`; Spark evidence present.
2. `2.133` only
   - Expected: tiny/canary/degraded notices; no heavy-model warm attempts.
3. `2.150` only
   - Expected: router/code/rerank lanes work; frontdoor worker attribution points at `spark-150`.
4. `2.151` only
   - Expected: judge/perception/document lanes work or degrade honestly.
5. `2.150` + `2.151`, no `2.133`
   - Expected: production local-first behavior remains healthy.
6. All Sparks down, `2.133` up
   - Expected: degraded local mode; cloud escalation only if policy allows.
7. Cloud LLM disabled
   - Expected: local-only operation, explicit degraded notices, no OpenAI/Bedrock tokens.
8. Internet available but cloud LLM disabled
   - Expected: web research/Perplexity may still be allowed depending policy; cloud LLMs blocked.
9. Uplink benchmark packet missing/stale
   - Expected: warm policy marks fallback/default status and does not blindly promote stale models.
10. Model cold-start pressure
   - Expected: prefetch/wait/skip decisions are visible in receipts and do not wedge TUI.

## Metrics To Capture

For each test prompt/session:

- TUI name/session.
- Prompt class: status, coding, scout, document, GUI, safety, verification.
- Selected provider/model/worker.
- `local_first_kpi.status`.
- `local_first_kpi.readiness_percent`.
- Offline/local token count.
- Cloud LLM token count.
- Perplexity/web token count.
- Spark evidence count.
- Worker attribution and peer path.
- Latency: route, cold start, first token, completion.
- Failure class: timeout, empty response, verifier rejection, progress-only answer, unavailable worker.

Where to find this:

- `/api/v1/console-runtime/route-summary`
- `/api/v1/console-runtime/worker/status`
- per-job `/api/v1/console-runtime/jobs/{job_id}`
- Norllama `/v1/activity`
- Uplink benchmark packet/shareable output

## Architecture Risks To Audit

1. Catalog vs benchmark conflict
   - The catalog currently contains next-gen desired models.
   - `docs/norllama_router_guidance.md` still mentions older benchmark-backed defaults such as `qwen3-coder-next:q4_K_M` and `gemma4:26b-a4b-it-q4_K_M`.
   - Audit should decide whether catalog entries are installed reality, future target, or wrong.

2. Benchmark promotion criteria
   - Benchmark average may reward quick failures.
   - Promotion needs accepted rows, coverage, verifier rejection rate, cold/warm latency, and TUI-cap smoke tests.

3. `2.133` overload risk
   - It has 16 GB memory.
   - It should host tiny/canary/fallback lanes only.
   - Audit warm policy and live resident models to ensure large models are not landing there.

4. Cloud proxy ambiguity
   - Norllama may eventually proxy OpenAI/Bedrock.
   - Usage ledger must distinguish local Norllama from Norllama-cloud-proxy.
   - Confirm `cloud_proxy=true` paths are correctly counted as cloud LLM.

5. Perplexity/scout ambiguity
   - Perplexity/search should be tracked separately from cloud LLM model spend.
   - Audit scout service vs Ranger TUI behavior.

6. Specialist models not wired
   - OCR, ASR, rerank, injection detection, safety, GUI grounding may exist in catalog before serving paths exist.
   - Classify each as live, partially wired, or aspirational.

7. Route receipt completeness
   - Every local/cloud/fallback decision should include reason, model, endpoint, worker/peer path, benchmark source, and policy state.
   - Audit `route_receipt` on planner and model events, not only raw route objects.
   - For warm-policy routes, audit the `model_selection.pool` and score reasons, not only the winner.

8. Goal-loop quality
   - Web TUIs should behave more like long-running terminal Codex: plan/work/verify continuously within budget.
   - Audit whether kernel goal loops actually finish work or still checkpoint too early.

## Desired Audit Output

Ask the pro agent to return:

1. Model inventory table
   - model, worker, resident/cold, memory fit, benchmark status, route lane, verdict.
2. Architecture verdict
   - green/yellow/red for frontdoor, mesh, runtime, TUI, benchmarks, cost ledger.
3. Benchmark critique
   - missing suites, overly strict/loose criteria, timeout handling, promotion rules.
4. Routing critique
   - exact cases where wrong model/provider is selected.
   - verify that `warm_policy` selection prefers the primary task lane and does not silently downgrade to a fallback lane after a recent local route timeout.
5. Cost/offline proof
   - last few sessions by TUI/session, local vs OpenAI vs Bedrock vs Perplexity.
6. Concrete patch plan
   - top 10 changes to move from mostly implemented to production-grade.
7. Rollback/degraded-mode plan
   - what happens if Norllama, Uplink, a Spark, OpenAI, or Bedrock is unavailable.

## Repo State Notes

This local checkout has many untracked/dirty files from the ongoing Norman runtime work. Do not assume `git status` reflects only this handoff. The auditor should inspect the deployed Norman/Uplink estate and compare it to this repo.

Recent implementation highlights to verify:

- Local-first catalog defaults are applied when creating console-runtime jobs and runs.
- Norllama route metadata is propagated into `model.completed`.
- Route summary includes `usage_ledger`.
- Route summary includes `local_first_kpi`.
- Worker status includes aggregate `usage_ledger` and `local_first_kpi`.
- TUI runtime console displays local-first and cloud-LLM posture.

## Bottom Line

Norman now has the structures required for local-first, model-independent operation. The highest-value audit is to determine whether the live estate is obeying those structures:

- Are benchmark-backed local models actually selected?
- Are Sparks being used enough?
- Are cloud LLM tokens dropping?
- Are specialist lanes real or aspirational?
- Does failover/degraded mode work without hidden cloud dependency?

If the answer is yes with live evidence, this is near release quality. If not, prioritize benchmark-driven model selection, warm residency enforcement, and route receipt correctness before expanding the model catalog further.
