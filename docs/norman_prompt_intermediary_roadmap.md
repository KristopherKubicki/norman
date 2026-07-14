# Norman Prompt Intermediary Roadmap

Date: 2026-07-14
Status: implementation roadmap

## Summary

Norman should become the prompt intermediary for TUI, SDK, and provider-shaped
traffic. The goal is not a covert network MITM. The goal is an explicit,
auditable Norman adapter that can sit in front of Bedrock, OpenAI, Norllama,
Ollama-compatible endpoints, and future local runtimes.

Every mode should answer the same questions before any provider receives the
prompt:

- What did the user ask?
- Is the prompt simple, specialist, standard local reasoning, or high reasoning?
- Is it read-only, local mutation, external mutation, destructive, or secret
  sensitive?
- Can a deterministic check answer or block it?
- Should a local specialist handle it?
- Should a Spark local LLM handle it?
- Should a high-reasoning Spark lane handle it?
- Is web/search evidence needed?
- Is cloud allowed, and why?
- What receipt proves the route?

The intermediary should always keep local and cloud accounting separate. A
Norllama cloud proxy must still count as cloud LLM usage, while Perplexity or
web search stays in the search bucket rather than the cloud-LLM bucket.

## Non-Goals

- Do not silently intercept arbitrary user traffic at the network layer.
- Do not forge provider semantics without an explicit configured adapter.
- Do not let callers supply trusted route-policy authority.
- Do not treat log-only observation as production local-first proof.
- Do not count shadow or dry-run work as operator cloud displacement.

## Integration Surfaces

### Advisory

The client asks Norman for a route decision, then executes the result itself.
This is useful for experiments and dashboards.

Current endpoint:

- `POST /api/v1/prompt-router/route`

### Provider Adapter

The client points an OpenAI/Bedrock/Ollama-shaped request at Norman. Norman
extracts the prompt, classifies it, applies policy, and returns the route
contract. The first implementation is route-only. Later phases can forward the
approved request.

Current endpoints:

- `POST /api/v1/prompt-router/adapters/openai/chat/completions`
- `POST /api/v1/prompt-router/adapters/openai/responses`

### SDK Wrapper

A lightweight client library wraps provider SDK calls and consults Norman before
execution. This is the lowest-friction path for work Bedrock/OpenAI traffic
because it does not require network interception.

### Explicit Forward Proxy

A future HTTP proxy can accept OpenAI-compatible traffic and forward after
policy. This should still be explicit: clients set `base_url` or proxy
configuration to Norman.

## Intermediary Modes

### Route Only

Purpose: Return a route envelope without forwarding or executing.

Behavior:

- classify prompt
- select reasoning tier
- select provider/model/lane
- emit receipt preview
- do not forward
- do not mutate
- do not block

Release role:

- safe default for integration testing
- useful for audit packets and route simulations

### Transparent Log Only

Purpose: Observe provider-shaped traffic and record route receipts while the
client still forwards the original request.

Behavior:

- parse and classify the prompt
- compute the Norman local-first route
- record risk, route, and usage intent
- return `client_action=forward_original_provider_request_after_recording_route_receipt`
- do not mutate the prompt
- do not block the request
- do not claim local-first displacement

Use cases:

- initial rollout for work Bedrock traffic
- outlier detection
- cost attribution
- cloud-spend dashboards
- before/after route analysis

Release gates:

- 100% request correlation
- no trusted caller policy fields
- no prompt/body leakage beyond configured retention
- redaction policy for secrets and PII
- clear label that this is observation, not enforcement

### Guardrail

Purpose: Enforce safety, budget, and authority policy while preserving normal
provider execution when allowed.

Behavior:

- classify risk
- detect prompt injection and secret-sensitive content
- block destructive or unauthorized prompts
- hold external mutation for approval
- require explicit receipt before any cloud escalation
- preserve original provider request for low-risk allowed prompts

Use cases:

- work Bedrock policy boundary
- credential and PII leakage prevention
- destructive command blocking
- cloud spend caps
- route-lock validation

Release gates:

- rejection receipts for every block
- approval receipts for every hold
- critical false-negative safety canary at zero
- no hidden cloud fallback
- deterministic policy has final authority over model classifier output

### Intelligence

Purpose: Actively optimize routing and execution. Norman becomes the prompt load
balancer.

Behavior:

- run deterministic prompt gate
- run local classifiers and specialists
- route simple tasks locally
- route specialist work to local specialist lanes
- route ordinary reasoning to Spark local LLM
- route hard reasoning to Spark high-reasoning lane
- use web/search when required by task freshness
- use cloud only as a receipted last resort or tie breaker
- optionally rewrite/compact evidence before expensive model calls

Use cases:

- TUI default mode
- daily low-risk operator work
- status, logs, summaries, JSON extraction, preflight, and local planning
- cost reduction without losing cloud fallback

Release gates:

- 20 or more representative unlocked operator turns
- eligible fully local rate at least 90%
- receipt audit coverage at 100%
- observed-worker coverage at 100%
- measurable cloud-token avoidance
- degraded-mode matrix passes

### Shadow Compare

Purpose: Let the original provider answer while Norman runs a local shadow route
for comparison.

Behavior:

- forward original request
- run local route asynchronously when allowed
- compare output shape, answer class, latency, and cost estimate
- never block based on shadow result
- never count shadow traffic as local-first completion

Use cases:

- qualifying new local models
- comparing local judge quality
- measuring expected cloud displacement before enforcing routes

Release gates:

- separate shadow usage ledger
- no synthetic proof counted as operator proof
- joinable provider and shadow request IDs
- output comparison stored without leaking secrets

### Strict Local

Purpose: Enforce offline/cloud-disabled behavior.

Behavior:

- cloud LLM disabled
- cloud proxy disabled
- local specialists and Spark models allowed
- web/search may be allowed only if policy says cloud-LLM-offline, not airgap
- explicit degraded response when local capability is unavailable

Use cases:

- offline TUI mode
- cost emergency mode
- provider outage mode
- cloud-policy drills

Release gates:

- cloud-disabled scenario completes real local work
- cloud attempts are blocked with receipts
- no 2.133 heavy-model route
- degraded notices are visible to client and TUI

## Runtime Cascade

```text
provider-shaped request or TUI prompt
  |
  v
Norman prompt intermediary
  |
  +-- deterministic intent/risk gate
  +-- local specialist detection
  +-- local runtime autosense through Norllama policy
  +-- benchmark and capability gate lookup
  +-- route receipt preview
  |
  v
mode policy
  |
  +-- transparent_log_only -> original provider request continues
  +-- guardrail -> block, hold, or allowed provider/local route
  +-- intelligence -> Norman-selected local-first cascade
  +-- shadow_compare -> original provider plus local shadow
  +-- strict_local -> local route or explicit degraded block
```

## Implementation Roadmap

### Phase 1: Route Contract

Status: implemented in staging.

- route-only provider adapter
- OpenAI chat-completions request parsing
- OpenAI responses request parsing
- reasoning tiers
- route strategy
- mode catalog
- caller route policy not trusted
- no forwarding

### Phase 2: Log-Only Recorder

Add durable event records for provider-adapter calls:

- request ID
- session
- source application
- provider endpoint
- requested model
- normalized prompt digest
- classification
- route recommendation
- selected local alternative
- cloud bucket estimate
- retention/redaction state

Acceptance:

- adapter call creates an immutable log record
- no prompt body persisted when redaction policy forbids it
- dashboard can show cloud requests that local could have handled

### Phase 3: Guardrail Enforcement

Add enforcement result types:

- `allowed`
- `blocked`
- `approval_required`
- `degraded_local_only`
- `policy_expired`
- `capability_unproven`

Acceptance:

- destructive prompt blocks before provider call
- external mutation prompt requires approval
- cloud escalation requires explicit policy and receipt
- stale/expired route policy blocks production requests

### Phase 4: Intelligence Execution

Wire the provider adapter to execution:

- local simple answer path
- Norllama specialist calls
- Spark local LLM calls
- Spark high-reasoning calls
- structured receipt persistence
- optional cloud tiebreaker after local evidence

Acceptance:

- status prompts complete locally
- standard local tasks complete locally
- high-reasoning local tasks prefer Spark before cloud
- cloud fallback is visible and ledgered

### Phase 5: Shadow Compare

Run local shadow decisions for provider requests:

- store provider result metadata
- store local shadow result metadata
- compare output shape, confidence, latency, and cost
- never block in shadow mode

Acceptance:

- shadow evidence does not count as local-first production proof
- promotion reports distinguish transport, capability, and shadow evidence

### Phase 6: Strict Local And Offline

Make strict local mode operational:

- cloud disabled
- cloud proxy disabled
- web/search policy explicit
- degraded receipts
- local-only visible notice

Acceptance:

- cloud-disabled matrix passes
- all local unavailable returns an honest degraded block
- local available completes without hidden provider calls

## Open Questions

- Which work Bedrock applications should use SDK wrapper first?
- What retention policy should apply to raw prompts in log-only mode?
- Should Norman expose an OpenAI-compatible response surface, or always return
  Norman envelopes from the adapter endpoint?
- Which mode should be the default for each TUI group: personal, shared-infra,
  work, and research?
- Should Perplexity/search be available in strict local, or only in
  cloud-LLM-offline mode?

## Recommended Defaults

- TUI traffic: `intelligence`
- Work Bedrock first rollout: `transparent_log_only`
- Work Bedrock after observation: `guardrail`
- Model qualification: `shadow_compare`
- Cost emergency or provider outage: `strict_local`
- Developer testing: `route_only`
