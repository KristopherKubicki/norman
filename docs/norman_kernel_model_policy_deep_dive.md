# Norman Kernel Model And Policy Deep Dive

Date: 2026-07-05
Status: implementation planning
Audience: Norllama, routing, cost-control, and offline-mode maintainers

## Summary

Norman needs model independence and lower cloud spend without losing safety.
Norllama should be the general AI framework for local models, capability
discovery, scout/planner/filter/compact/verify work, OCR, STT, embedding,
rerank, and cloud proxying when policy allows.

The kernel should decide what to use from task type, risk, capability, warm
model state, cost budget, egress policy, and degraded mode. TUIs should not make
those decisions independently.

## Current State

Implemented today:

- `app/services/norllama/routing.py` has task kinds for chat, scout, plan,
  filter, summarize, compact, verify, OCR, STT, embed, and rerank.
- Norllama routes local lanes, local tool lanes, and cloud proxy providers.
- `NorllamaProxy` can invoke local chat, registered tool handlers, and cloud
  handlers.
- `NorllamaModelAdapter` exposes capabilities to the console runtime.
- The TUI local-first path can choose local models for safe self-contained
  prompts.
- The TUI has Norllama planner preflight for cloud/tool turns.
- `llm.home.arpa` is the intended front door, with 2.133 preferred and 2.150/
  2.151 as larger workers/failover peers.

Current gaps:

- Model/cost routing is split between TUI code, Norllama routing, and runtime
  worker behavior.
- The default TUI local model order has stale high-preference Qwen entries.
- Offline mode is not represented as independent axes.
- Cloud escalation is not always accompanied by a central route receipt.
- Norllama cloud proxy is present conceptually, but not fully the default cloud
  abstraction.

## Policy Goals

1. Use local models aggressively for cheap scout/planner/filter/compact/rerank
   and safe self-contained execution.
2. Use higher models only when the task needs them.
3. Block cloud LLM spend when cloud LLM mode is disabled.
4. Keep web research independent from cloud LLM egress.
5. Prefer local waiting/failback over surprise cloud escalation.
6. Make every escalation auditable.
7. Keep safety gates stronger than cost gates.

## How Norman Knows What To Use

The kernel should route from these inputs:

- task classification
  - summarize, classify, extract, rewrite, inspect, code edit, deploy,
    long-horizon, verification, research, OCR, STT, embed, rerank
- risk classification
  - read-only, writes files, runs tests, mutates services, deploys, touches
    secrets, external action, high-stakes domain
- context needs
  - local repo, attachments, web, LAN service, cloud service, long context
- capability snapshot
  - Norllama `/v1/capabilities`
  - model list
  - tool lanes
  - peer failover support
  - prefetch/evict support
  - cloud proxy support
- model residency
  - warm
  - cold but available
  - unavailable
  - benchmark-backed priority
- operator budget
  - quick, normal, deep, overnight
  - explicit local/cloud preference
- egress policy
  - cloud LLM allowed
  - web allowed
  - LAN allowed
  - all third-party blocked
- historical outcomes
  - recent failures
  - latency
  - timeout count
  - verifier disagreement

The output is a `RouteDecision` event and receipt, not a hidden branch.

## Route Decision Order

Recommended order:

1. Apply hard safety blocks.
2. Apply egress and offline-mode blocks.
3. Determine whether a deterministic tool can answer.
4. Use Norllama local scout/planner/filter if useful and allowed.
5. Pick the cheapest adequate local model/tool lane.
6. If local is cold/unavailable, decide whether to wait, prefetch, fail over to
   another spark, or escalate.
7. Escalate to cloud only if policy allows and a receipt explains why.
8. Verify high-impact outputs with a separate model/tool path when possible.

## Operating Mode Matrix

| Mode | Cloud LLM | Web | LAN Norllama | Shell | Codex | Expected behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `primary_online` | allowed | allowed | allowed | policy-gated | allowed | normal hybrid routing |
| `local_first_online` | allowed with receipt | allowed | preferred | policy-gated | allowed | local scout/filter first, minimal cloud |
| `cloud_llm_offline` | blocked | allowed | preferred | policy-gated | blocked unless local-only adapter | web and local can work; no cloud models |
| `codex_quarantine` | policy-dependent | allowed | preferred | policy-gated | blocked | use shell/Norllama/cloud adapters without Codex CLI |
| `lan_only` | blocked | blocked except LAN | allowed | policy-gated | blocked if cloud-backed | local/LAN only |
| `airgap_local` | blocked | blocked | local only | policy-gated | blocked | local/offline work only |
| `control_only` | blocked | optional read-only | optional health only | disabled | blocked | queue, checkpoint, display, recover |

## Egress Classes

Classify every outbound action:

- `lan`
  - `*.home.arpa`, RFC1918, loopback, local Unix sockets
- `web_research`
  - public web fetch/search with no LLM inference
- `cloud_llm`
  - OpenAI, Bedrock, Anthropic, hosted HF inference, Codex cloud path
- `cloud_tool`
  - non-LLM cloud APIs such as GitHub, Google, AWS service APIs
- `telemetry`
  - logs, metrics, update checks
- `unknown_external`
  - default deny in restricted modes

Policy examples:

- `cloud_llm_offline`: block `cloud_llm`, allow `web_research` if network plane
  is `internet_ok`.
- `lan_only`: allow `lan`, block all public internet classes.
- `airgap_local`: allow loopback/local only; block LAN if the operator chooses
  strict airgap.
- `codex_quarantine`: block Codex runner even if cloud LLMs are otherwise
  allowed.

## Norllama Role

Norllama is the AI framework and broker.

Kernel should ask Norllama for:

- capabilities
- model list
- task lanes
- local model route
- tool lane route
- cloud proxy route
- receipt metadata
- prefetch/evict availability
- peer failover availability

Norllama should support:

- local chat
- planner
- scout
- filter
- summarizer
- compactor
- verifier
- OCR
- STT
- embedding
- reranking
- cloud proxy to Bedrock/OpenAI/Codex-compatible lanes where policy allows

The kernel should not call Ollama directly except for diagnostics. Norllama is
the contract.

## Warm Model Policy

Benchmark-backed production warm set:

- P0 `gemma4:26b-a4b-it-q4_K_M`
  - main local generalist for Norman status, checkpoints, receipts, web/static
    synthesis, and cloud-gap verifier behavior
- P0 `qwen3-coder:30b-a3b-q4_K_M`
  - code and structured draft lane
- P0 `qwen3-coder-next:q4_K_M`
  - scout, route prep, code risk lane
- P1 `gemma4:31b`
  - safety, privacy, documentation, runbook, work decomposition specialist
- P1 `bge-m3`, `qllama/bge-reranker-v2-m3`, `nomic-embed-text`
  - retrieval/rerank/embed when those lanes are active
- Canary only `llama3.2:1b`, `llama3.2:3b`, `gemma3:1b`, or `gemma3:4b`
  - transport health, local degraded notices, and smoke tests only

Do not keep always warm without fresh evidence:

- `gpt-oss:120b`
- `llama4:maverick`
- `llama4:scout`
- `qwen3.5:122b`
- `qwen3.6` variants
- `devstral-small-2`
- `nemotron`
- OpenFugu variants unless a fresh benchmark packet promotes them

Policy:

- 2.133 is the front door and fallback node with tiny models.
- 2.150 and 2.151 are large-model workers.
- Clients use `https://llm.home.arpa`, not direct worker addresses.
- Norllama mesh decides peer routing and model location.
- If a P0 model is cold but appropriate, the kernel may wait/prefetch instead
  of escalating to cloud when the task is not urgent.

Current implementation boundary:

- Norman's warm-policy service reads the Uplink benchmark packet and the
  Norllama frontdoor/mesh snapshot.
- The shared TUI execution path still has an independent local model selector
  based on environment/default model order and frontdoor health probes.
- That means the system can display benchmark-backed guidance while still
  trying a stale cold default if the TUI env says to use it.
- The next routing slice should make benchmark-backed warm policy executable by
  exposing one shared selector for TUI local-first, kernel worker, and prefetch
  decisions.

## Cost Controls

Kernel should emit a cost decision for every model route:

- `local_token_estimate`
- `cloud_token_estimate`
- `cloud_credit_estimate`
- `free_deterministic`
- `control_only_queue`

Default cost policy:

- safe self-contained text tasks -> local
- planner/scout/filter/compact/rerank -> local Norllama
- repo inspection -> shell plus local summarizer first
- mutating code work -> shell/Codex/cloud only after policy and approval
- long/high-impact work -> local preflight, then cloud only if justified
- final synthesis -> cheapest adequate model that passed verifier policy

Escalation receipt must include:

- why local was insufficient
- which local models/tools were tried or skipped
- expected benefit of higher model
- expected cost basis
- egress class
- operator mode

## Failover And Failback

Local route failure handling:

1. Try the selected Norllama front door.
2. If front door routes to peer, accept peer route.
3. If model is cold and prefetch supported, request prefetch.
4. If task can wait, checkpoint and wait rather than cloud escalate.
5. If task is urgent and policy allows cloud, escalate with receipt.
6. If policy blocks cloud, degrade to local smaller model or control-only.

Failback:

- When preferred local model returns healthy, route safe/local tasks back to it.
- Do not keep using cloud because it succeeded once.
- Keep recent local failure cooldowns to avoid oscillation.

Dire situations:

- If all local inference fails and cloud LLMs are blocked, enter
  `control_only`.
- If local model is too weak for a risky mutation, hold for approval or queue.
- If network is partially available, web research may continue while cloud LLM
  synthesis remains blocked.

## Norllama Cloud Proxy Plan

Norllama can be the cloud proxy, but it needs to be made operationally explicit.

Required proxy capabilities:

- provider registry
  - Bedrock
  - OpenAI-compatible
  - Codex adapter lane if applicable
- credential lookup through Norman Keys
- egress policy enforcement before provider call
- route receipt for every cloud call
- model capability declarations
- cost metadata
- request id propagation
- timeout/retry policy
- streaming event forwarding

Important boundary:

Norllama cloud proxy is not a way to hide cloud usage. It is a way to make cloud
usage uniform, receipted, and policy controlled.

## Implementation Slices

### Slice 1: Policy Types

Files:

- `app/services/console_runtime/policy.py`
- `tests/test_console_runtime_policy.py`

Work:

- Add operating-mode axes.
- Add egress classifications.
- Add provider/runner allow decisions.
- Add degraded notices.

### Slice 2: Route Receipts

Files:

- `app/services/console_runtime/types.py`
- `app/services/console_runtime/kernel.py`
- `app/services/console_runtime/store.py`
- `app/services/norllama/routing.py`
- `tests/test_console_runtime_kernel.py`
- `tests/test_norllama_routing.py`

Work:

- Add `RouteDecision`.
- Emit `route.decided`.
- Include capability snapshot and egress class.
- Preserve Norllama receipt metadata.

### Slice 3: Benchmark-Backed Model Defaults

Files:

- `scripts/agent_console_template/agent_console_web.py`
- `docs/local_llm_node.md`
- `tests/test_agent_console_runtime_bridge.py`

Work:

- Move default local model order to benchmark-backed P0/P1 set.
- Stop preferring stale `qwen3.6` variants.
- Keep tiny models for health/canary/fallback on 2.133.

### Slice 4: Norllama Cloud Proxy Hardening

Files:

- `app/services/norllama/proxy.py`
- `app/services/norllama/routing.py`
- `app/services/console_runtime/adapters/norllama.py`
- `tests/test_norllama_proxy.py`
- `tests/test_norllama_routing.py`

Work:

- Add policy enforcement hooks.
- Add provider registry shape.
- Add cost/egress metadata.
- Add streaming/receipt plan if endpoint supports it.

### Slice 5: Kernel Cost Router

Files:

- `app/services/console_runtime/policy.py`
- `app/services/console_runtime/worker.py`
- `tests/test_console_runtime_worker.py`

Work:

- Route by task/risk/capability/cost.
- Require local preflight receipt for cloud escalation.
- Add wait/prefetch behavior for cold local models.

## Test Plan

Required tests:

- `cloud_llm_offline` blocks OpenAI/Bedrock/Codex cloud lanes.
- `cloud_llm_offline` still allows web research egress when network mode
  allows it.
- `lan_only` allows `llm.home.arpa` and RFC1918 addresses.
- `lan_only` blocks public web and cloud LLMs.
- Codex quarantine blocks Codex adapter while allowing shell/Norllama.
- Local-first route chooses benchmark P0 model when healthy.
- Cold P0 model can request prefetch/wait instead of escalating.
- Cloud escalation requires route receipt.
- Tool tasks route to local Norllama tool lanes unless explicitly allowed.
- Missing local inference degrades to control-only when cloud LLMs are blocked.

Live checks:

- `https://llm.home.arpa/v1/capabilities`
- `/api/version` on front door
- model catalog contains P0 models
- 2.133 front door reachable after reboot
- 2.150/2.151 workers reachable through mesh
- direct Ollama not exposed publicly

## Acceptance Criteria

- Norman has one route policy for TUIs and runtime workers.
- Norllama is the default broker for model/tool/capability tasks.
- Cloud LLM spend is blocked or minimized according to mode.
- Every cloud escalation has a local receipt or explicit exception.
- Benchmarked warm models are preferred.
- Offline/degraded modes are visible and safe.
