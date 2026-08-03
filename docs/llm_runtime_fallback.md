# Provider And Routing Resilience

This document replaces the old single-host "primary plus Ollama fallback"
description. The filename is retained for existing links, but Norman now uses
provider-neutral, policy-backed routing with local-first capability selection.

Norman is designed to remain useful when a cloud model, a local worker, Codex,
or all inference is unavailable. It does not promise equal quality in every
mode. Instead, it makes capability, egress, and safety limits explicit before
work is attempted.

## Provider Classes

| Class | Purpose | Examples |
| --- | --- | --- |
| Deterministic | Exact work without a model | Repository inspection, validators, tests, command policy |
| Local inference | Low-latency local text and code | Norllama text, planner, scout, summarizer, verifier |
| Local specialist | Non-chat capabilities and evidence reduction | OCR, ASR/STT, embeddings, rerank, safety |
| Cloud inference | Higher-capability execution | Bedrock, compatible endpoints, Codex adapters |
| Control only | State and recovery without inference | Queueing, checkpoints, status, approval, notifications |

OpenAI is one cloud provider class. It is neither required for local-first
operation nor the implicit default for a task. Cloud credentials belong in the
approved secret path; clients should not embed a provider key in their own
configuration.

## Route Decision Order

For each runtime step, Norman applies this order:

1. Enforce safety, approval, and operating-mode blocks.
2. Apply egress and realm restrictions.
3. Use a deterministic tool when it is sufficient.
4. Select an eligible local Norllama capability or specialist lane.
5. If the local lane is cold or unavailable, decide whether to wait, prefetch,
   use a healthy peer, or defer.
6. Escalate to a cloud provider only when policy explicitly permits it.
7. Record the chosen route and outcome, then verify higher-impact results with
   an independent check when required.

The request does not silently switch from local to cloud merely because a
local model is slow or unavailable. A cloud escalation requires a route
receipt with the local reason, expected benefit, egress class, and policy
context.

## Operating Modes

Norman composes its operating mode from separate planes. This lets the system
distinguish an inference outage from a runner quarantine or a network policy
change.

| Named Mode | Cloud LLM | Local Norllama | Web | Shell And Tools | Expected Behavior |
| --- | --- | --- | --- | --- | --- |
| `primary_online` | Allowed by policy | Available | Available | Policy-gated | Normal hybrid routing |
| `local_first_online` | Escalation only | Preferred | Available | Policy-gated | Local-first work with receipts |
| `cloud_llm_offline` | Blocked | Preferred | May be available | Policy-gated | Local and deterministic work |
| `codex_quarantine` | Policy-dependent | Preferred | Available | Policy-gated | No Codex runner |
| `lan_only` | Blocked | Available | Public egress blocked | Policy-gated | Local and LAN services |
| `airgap_local` | Blocked | Local-only | Blocked | Policy-gated | Isolated local operation |
| `control_only` | Blocked | Health only | Optional read-only | Disabled | Queue, observe, recover |

The individual planes are `llm_plane`, `runner_plane`, `network_plane`,
`tool_plane`, and `egress_policy`. The Console Runtime exposes the resulting
state to operators rather than hiding it behind a generic provider error.

## Egress Policy

Outbound work is classified before execution:

- `local`: loopback, local sockets, and local processes.
- `lan`: internal hosts and the Norllama front door.
- `web_research`: public web retrieval without cloud model inference.
- `cloud_llm`: hosted inference such as Bedrock, OpenAI, Anthropic, or a
  cloud-backed Codex path.
- `cloud_tool`: non-LLM external APIs.
- `telemetry`: logs, metrics, and update checks.
- `unknown_external`: denied in restricted modes unless explicitly allowed.

For example, `cloud_llm_offline` can permit web research while blocking hosted
inference. `lan_only` can use the Norllama mesh while blocking public internet
access. A local OpenAI-compatible endpoint is classified by its endpoint, not
only its protocol name.

## Norllama As The Local Contract

Applications should use Norllama as the local inference and capability
contract. It provides an OpenAI- and Ollama-compatible front door alongside
capability, model, health, prefetch, activity, and specialist endpoints.

Norllama is responsible for local mesh awareness: model inventory, healthy
peer selection, model residency, warm/prefetch behavior, and local specialist
lanes. Norman remains responsible for deciding whether a route is permitted
for an operator's work and for recording the result in the job history.

Direct access to an individual Ollama worker is limited to diagnostics and
bootstrap work. Runtime callers should use the logical front door so peer
failover and attribution are preserved.

## Receipts, Health, And Failover

Every nontrivial inference step should retain:

- The task kind, role, correlation ID, and runtime job or session reference.
- The selected provider, lane, model, endpoint class, and local/cloud status.
- The route-policy identity and authorization result.
- Attempts, fallback reason, selected peer, and relevant health snapshot.
- Token, latency, confidence, and error information when available.

Norllama health and capability inventory identify usable local routes before a
model call. If the selected worker cannot serve the request, the gateway can
select another healthy eligible peer or return a typed failure. Norman then
decides whether to wait, retry, defer, or use an explicitly allowed cloud
route. It does not infer success from transport reachability alone.

Warm-policy and benchmark information are advisory evidence for routing; they
do not override safety, authorization, capability gates, or an operator's
explicit restricted mode.

## Degraded Behavior

| Condition | Norman Behavior |
| --- | --- |
| A local model is unavailable | Try permitted peer or prefetch; otherwise defer or escalate only with policy |
| A cloud provider is unavailable | Keep local and deterministic work available; record a degraded route outcome |
| Codex is unhealthy or quarantined | Use permitted adapters without treating Codex as the parent runtime |
| No inference is available | Queue, retain context, checkpoint, and show recovery state |
| A route policy expires or fails validation | Block defaults; require bounded degraded authorization |
| Resource pressure is high | Reduce or pause background work before it competes with foreground operator work |

Degraded operation must not turn a blocked action into a permitted one. It
should reduce scope, preserve evidence, and surface the next human decision.

## Configuration And Operations

`config.yaml.dist` shows the logical provider fields, local front-door
configuration, mesh roster, route timeouts, Console Runtime controls, and
Kaizen safety defaults. The important operational rules are:

- Configure only the provider lanes approved for the environment.
- Keep clients on the Norllama logical front door instead of direct worker
  addresses.
- Store secrets in the approved broker or short-lived lease path.
- Keep route policy artifacts fresh and fail closed when they are invalid.
- Enable continuous workers, cloud routes, and Kaizen capabilities explicitly.
- Monitor route receipts, capability health, worker saturation, and background
  resource pressure before increasing concurrency.

For the current front-door, warm-policy, and route-attribution details, see
[Norllama Router Guidance](norllama_router_guidance.md). For the TUI and
durable work migration, see [Norman Kernel Program](norman_kernel_program.md).
