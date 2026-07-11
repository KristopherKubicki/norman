# Norllama Router Guidance

Date: 2026-07-06
Status: operator guidance and implementation target

## Summary

The current Norllama/Norman router has the right building blocks, but they are
not yet one fully closed control loop.

What works today:

- TUIs can reach `https://llm.home.arpa`.
- Norman Caddy fails over across `2.133`, `2.150`, and `2.151`.
- Norllama frontdoors expose capabilities, model inventory, async prefetch,
  peer failover, request ids, recent activity, and upstream route headers.
- Norman reads `/var/lib/norman/norllama/benchmark_packet.json` and builds a
  benchmark-backed warm policy.
- The TUI status surface can show local LLM health, mesh posture, warm posture,
  and route attribution.
- Warm-policy prefetch results preserve gateway route evidence and flag
  `target_honored=false` when the gateway accepts a warm request but chooses a
  different upstream than the policy target.

Main gap:

- The benchmark-backed warm policy is mostly advisory/status today. Some TUI
  execution paths still select local models from environment/default model
  order and only use frontdoor health to check whether a candidate exists. That
  means stale defaults such as cold `qwen3.6:27b` can still be attempted even
  though the retained benchmark policy would prefer `gemma4:26b-a4b-it-q4_K_M`
  or a Qwen coder lane.

Current TUI guardrail:

- The automatic TUI route default is `qwen3-coder-next:q4_K_M` as of
  `2026.07.06.10`. Live smoke testing showed it returned usable content through
  the Norllama front door, while `gemma4:26b-a4b-it-q4_K_M` repeatedly returned
  empty content under short TUI-style caps and `qwen3-coder:30b-a3b-q4_K_M`
  timed out. Gemma remains benchmark-visible and warm-policy visible, but it
  should not be the first automatic execution route until the adapter/gateway
  can classify or correct empty-output responses.

## Live Router Shape

```text
TUI / Kernel client
  |
  | route decision, budget, mode, task class
  v
https://llm.home.arpa
  |
  | Norman Caddy frontdoor
  | lb_policy first
  | health_uri /healthz
  | health_interval 3s
  | lb_try_duration 15s
  v
+----------------------+     +----------------------+     +----------------------+
| 2.133 mac-mini       | --> | 2.150 spark          | --> | 2.151 spark          |
| preferred front node |     | production worker    |     | production worker    |
| tiny/canary fallback |     | Qwen/Gemma/code      |     | Gemma/Qwen-next/120B |
+----------------------+     +----------------------+     +----------------------+
        |                            |                            |
        +--------- Norllama peer failover, prefetch, route headers ---------+
```

This is frontdoor failover, not DNS multi-A failover. Clients should keep using
`https://llm.home.arpa`; direct worker URLs are diagnostic/backend addresses.

## Current Model Guidance

Use current benchmark-backed defaults, not older notes.

Keep warm or prefetch for production lanes:

- `qwen3-coder-next:q4_K_M`
  - current automatic TUI execution default for local scout, route prep,
    compact status answers, and code-risk drafting
- `gemma4:26b-a4b-it-q4_K_M`
  - general local worker for status, checkpoint, bounded synthesis, static web
    summaries, governed drafts, and cloud-gap verifier support; currently
    observe output-shape health before using it as first route
- `qwen3-coder:30b-a3b-q4_K_M`
  - code flow and structured patch/draft lane
- `gemma4:31b`
  - documentation, safety/privacy classification, document parse, and work
    decomposition drafts

Keep tiny models for canary/degraded mode only:

- `llama3.2:1b`
- `llama3.2:3b`
- `gemma3:1b`
- `gemma3:4b`

Do not keep always warm without fresh benchmark evidence:

- `qwen3.6` variants
- `qwen3.5:122b-a10b-q4_K_M`
- `gpt-oss:120b`
- `nemotron-3-super:120b`
- `llama4:scout`
- `llama4:maverick`
- `devstral-small-2`
- OpenFugu variants

Large models are experiment or long-running scout lanes until they earn a
current promotion. A low latency average can be misleading when most attempts
fail or reject quickly; promotion should look at accepted rows, verifier
rejections, suite fit, and cold/warm latency separately.

OpenFugu is no longer part of the fallback warm set. It may still appear in a
benchmark packet for historical comparison, but the warm policy should not
prefetch it unless fresh benchmark evidence clears the score and coverage gates.

## What The Router Should Know

The route decision should be based on one merged snapshot:

- benchmark packet freshness and recommendation status
- Norllama frontdoor health
- per-worker model inventory
- per-worker resident models
- per-worker pressure and memory class
- task kind and risk class
- current operating mode, including cloud-LLM-offline and LAN-only modes
- operator budget and route lock
- recent failures, timeouts, and verifier disagreements

The output should be a route receipt, not hidden control flow.

## Reliability Upgrades

### 1. Make Warm Policy Executable

Execution should call a shared selector derived from the warm policy. The shared
selector should return:

- selected model
- selected worker hint
- selected endpoint
- reason
- benchmark source and age
- fallback options
- whether prefetch/wait/cloud escalation is allowed

The TUI local-first path should stop choosing from raw env model order except as
a final fallback when the benchmark packet and frontdoor are unavailable.

### 2. Maintain Residency

Add a small controller that periodically applies the warm policy:

- dry-run by default in development
- background priority prefetch in production
- bounded per-worker resident limits
- no large-model warming on `2.133`
- avoid warming lower-priority models when a spark is under pressure
- report `warm`, `warming`, `cold`, `degraded`, and `unavailable`
- alert on `target_honored=false`, because that means the front door did not
  respect the worker placement selected by the benchmark/mesh policy

This should make quick local routes land on resident models instead of timing
out on cold starts.

### 3. Add Route Cooldowns

Track recent failures by `(model, worker, task_kind)`:

- timeout
- verifier rejection
- empty response
- local progress-only answer
- operator cancel
- worker unavailable

The selector should temporarily avoid a model/worker pair after repeated
failures and emit the cooldown in the route receipt.

### 4. Separate Canary From Work

Tiny models should answer health checks and degraded-mode notices. They should
not become the default answer path for real work just because they are fast.

Policy:

- canary route verifies transport
- scout route does useful cheap reasoning
- worker route produces draft output
- verifier/final route checks or authorizes output

### 5. Improve Status Polling

Add a lightweight prompt-status endpoint for TUIs and tests. `/api/status` is
too broad for frequent polling and can make test harnesses look slow or wedged.

The lightweight endpoint should include:

- pending/running state
- current route
- current model
- current worker, if known
- token estimate
- last error
- latest event cursor

### 6. Treat Benchmarks As Promotion Gates

Promotion should require:

- current packet freshness
- enough accepted rows for the lane
- acceptable verifier rejection rate
- suite-specific fit
- measured cold and warm latency
- usable-content smoke results under TUI-sized caps
- no precision veto for exact identifiers or governed final actions

No local model should be promoted to final authority from a general average
alone.

## Target Behavior

For quick status and TUI self-contained prompts:

1. Prefer a resident benchmark-backed local model.
2. If no resident benchmark-backed model exists, prefetch or wait when the
   prompt can wait.
3. Use tiny canary only to prove local inference is alive or to provide an
   explicit degraded notice.
4. Escalate to cloud only when policy allows and the receipt explains why.

For real coding/planning work:

1. Use shell/repo evidence first.
2. Use local scout/compact/model drafting where safe.
3. Use cloud verifier/final only for authority, high-risk, or locally failed
   cases.
4. Record every model route and fallback in the event stream.

## Immediate Fix List

- Push benchmark-backed `NORMAN_LOCAL_LLM_MODEL` and
  `NORMAN_LOCAL_LLM_MODELS` to the TUI fleet as an interim guardrail.
- Add a shared benchmark-backed selector used by TUI local-first and kernel
  worker routes.
- Make Norllama expose benchmark/warm-policy hints or let Norman expose a
  sanitized, unauthenticated LAN-only policy endpoint for TUIs.
- Start a bounded warm-policy controller for the production sparks.
- Add local route cooldowns and a prompt-status endpoint.
- Re-run quality tests with cold and warm models measured separately.
