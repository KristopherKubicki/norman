# Norman Model Durability Plan

Date: 2026-04-05

## Goal

Make Norman durable when OpenAI or Codex is degraded, unavailable, rate-limited,
or fully offline.

This plan is not just "add another model." The real objective is to separate
Norman's control plane from its inference plane so the system can keep operating
when one provider or runner disappears.

## Current State

Norman currently has two hard AI dependencies:

1. App-side bot chat is OpenAI-specific.
   - [openai_handler.py](/home/[REDACTED_NAME]/code/norman/app/handlers/openai_handler.py)
2. The TUI fleet is Codex-CLI-specific.
   - [agent_console_launch.sh](/home/[REDACTED_NAME]/code/norman/scripts/agent_console_template/agent_console_launch.sh)

Norman already has useful monitoring primitives we should build on instead of
replacing:

- per-console status and auth/usage inspection in
  [console_status.py](/home/[REDACTED_NAME]/code/norman/app/services/console_status.py)
- fleet-wide health/credit monitoring in
  [fleet_credit_monitor.py](/home/[REDACTED_NAME]/code/norman/app/services/fleet_credit_monitor.py)

The current failure posture is too binary:

- OpenAI app path fails hard if the API is unavailable.
- Codex/TUI bots fail hard if the Codex session path is unavailable.
- There is no explicit degraded or offline mode.
- There is no local checkpoint/handoff layer robust enough to switch runners
  cleanly.

## What Durable Should Mean

Norman should have four operating modes:

1. `primary`
   - OpenAI/Codex fully available.
2. `backup_online`
   - primary unavailable, but another remote model/provider is available.
3. `offline_local`
   - no remote provider is available; use a local model in a degraded mode.
4. `control_only`
   - inference is unavailable; Norman still stores events, queues prompts,
     preserves context, and exposes state/recovery actions.

Durability means:

- Norman itself remains reachable and understandable.
- prompts, attachments, recent summaries, and handoff context stay local
- each bot knows whether it can continue, degrade, or queue work
- the UI tells the operator which mode is active and what capability has been
  lost
- failover does not depend on inheriting proprietary provider thread state

## Failure Modes We Need To Handle

### Primary model/provider failures

- OpenAI API outage
- Codex session failures
- auth required / browser reauth loops
- usage limits / credit exhaustion
- repeated 5xx or websocket failures

### Network failures

- internet outage
- partial outbound failure
- DNS or TLS breakage

### Local-runtime failures

- local model service down
- runner bridge unhealthy
- checkpoint corruption

### False confidence failures

- system silently falls back but pretends nothing changed
- offline model is asked to do work it cannot actually do
- a degraded bot writes unsafe or low-confidence changes without surfacing the
  mode shift

## Design Principles

1. Norman's control plane must outlive any one model vendor.
2. Fallback must be explicit, visible, and policy-driven.
3. Local checkpoints matter more than provider-specific threads.
4. Offline mode is continuity mode, not parity mode.
5. Different bots/lane types should have different failure policies.

## Recommended Architecture

### 1. Provider Abstraction For App Bots

Replace the direct OpenAI call in
[openai_handler.py](/home/[REDACTED_NAME]/code/norman/app/handlers/openai_handler.py)
with a provider chain.

Proposed shape:

- `primary_provider`
- `backup_provider`
- `offline_provider`

Each provider should expose one common interface:

- `chat(messages, model, max_tokens, tools=None)`
- `health()`
- `capabilities()`

The important point is not to standardize on one vendor. It is to standardize on
Norman's own internal contract.

### 2. Runner Abstraction For TUI Bots

The TUI fleet currently assumes `runner == codex`.

We should split that into:

- `CodexRunner`
- `BackupRunner`
- `LocalRunner`

The current launch path in
[agent_console_launch.sh](/home/[REDACTED_NAME]/code/norman/scripts/agent_console_template/agent_console_launch.sh)
becomes just one runner implementation.

That runner abstraction should own:

- how a prompt is started
- how a prior session is resumed
- how health is checked
- how checkpoint context is injected
- what capabilities the runner supports

### 3. Local Checkpoints / Handoff State

This is the critical durability layer.

Every TUI bot should continuously write a local checkpoint bundle that is
runner-independent.

Minimum checkpoint contents:

- active task summary
- workdir
- repo status summary
- key files touched recently
- recent decisions
- current blockers
- next actions
- short rolling thread summary
- active attachments / referenced artifacts
- current mode and provider

This should be designed so a backup or offline runner can restart from the
checkpoint without needing OpenAI/Codex thread continuity.

### 4. Capability Profiles

Fallback modes should be honest about what they can do.

`primary`
- full reasoning
- full tool use
- best long-context behavior
- web-heavy research and complex agentic work

`backup_online`
- substantial reasoning
- most tool use
- maybe weaker coding / agentic reliability
- still viable for most work

`offline_local`
- local file reading
- drafting
- summaries
- triage
- code inspection
- queue building
- safe, bounded edits
- no assumption of strong web research or high-end agentic behavior

`control_only`
- queue prompts
- inspect last checkpoints
- expose recovery steps
- no inference

### 5. Failover Controller

Norman should own failover decisions, not each bot individually.

Inputs:

- provider health
- console auth state
- credit/usage alerts
- runner health
- local model availability
- bot policy

Outputs:

- active mode
- active provider/runner
- reason for failover
- user-visible capability downgrade

### 6. Durable UI Status

The TUI and Norman front door should always show:

- `Mode`: Primary / Backup / Offline / Control only
- `Provider`: OpenAI / backup / local
- `Runner`: Codex / backup / local
- `Capabilities`: full / degraded / queue only

The operator should never have to guess whether they are on the real lane or the
backup lane.

## Recommended Provider Strategy

### Primary

- keep Codex/OpenAI as the premium path

Reason:
- it already works
- it is deeply integrated into the current operator workflow

### Backup Online

Use a separate provider path behind Norman's provider abstraction, ideally
through an OpenAI-compatible API surface so the app-side swap is operationally
simple.

Key requirement:
- this path should be different enough from the primary that the same OpenAI
  outage does not kill both lanes

### Offline Local

Use a local OpenAI-compatible endpoint backed by a Qwen3-class model.

Likely serving options:

- `vLLM`
- `Ollama`

The exact local server is less important than these properties:

- stable local HTTP API
- predictable model startup/restart behavior
- easy health checks
- explicit model identity

The offline lane should be treated as a degraded worker, not a stealth primary.

## Recommended Bot Policies

Not every bot should fail over the same way.

### `strict`

Use for lanes where degraded inference is more dangerous than delay.

Examples:

- high-stakes finance or legal review lanes
- destructive automation lanes

Behavior:

- queue work if primary unavailable
- do not auto-fail over

### `auto_online`

Use for most work bots.

Examples:

- Control Plane
- Gold Book
- Platinum
- Scout

Behavior:

- fail over to backup online provider
- only enter offline mode if explicitly allowed

### `auto_offline`

Use for bots where continuity is more important than parity.

Examples:

- Norman general drafting/triage
- personal/home summary lanes
- local repo summarization

Behavior:

- fail over to local runner automatically
- clearly mark degraded mode

### `control_only`

Use for surfaces that should stay alive but not hallucinate work.

Examples:

- routing / switchboard / queue consoles

Behavior:

- preserve checkpoints
- accept prompts into queue
- show recovery actions

## What We Actually Want To Build

The right build order is:

### Phase 0: Visibility

Add explicit mode/provider/runner status everywhere before we add a new model.

Why:
- if fallback is invisible, it will create confusion and bad decisions

### Phase 1: App Provider Abstraction

Refactor app-side chat away from direct OpenAI calls.

Target files:

- [openai_handler.py](/home/[REDACTED_NAME]/code/norman/app/handlers/openai_handler.py)
- [config.py](/home/[REDACTED_NAME]/code/norman/app/core/config.py)

Likely additions:

- `app/services/llm/providers.py`
- `app/services/llm/router.py`

### Phase 2: TUI Checkpoints

Add local runner-independent checkpoint files for every TUI bot.

Target files:

- [agent_console_web.py](/home/[REDACTED_NAME]/code/norman/scripts/agent_console_template/agent_console_web.py)
- [agent_console_launch.sh](/home/[REDACTED_NAME]/code/norman/scripts/agent_console_template/agent_console_launch.sh)

Likely additions:

- local checkpoint writer
- checkpoint summary in `/api/status`
- UI mode indicator

### Phase 3: Backup Online Runner

Add a non-Codex backup runner for TUI bots.

This does not need to be parity-complete on day one. It needs to be able to:

- read checkpoint state
- accept prompts
- produce responses
- write back local history

### Phase 4: Offline Local Qwen Lane

Add a local model service and a `LocalRunner`.

This lane should initially be limited to:

- Norman
- selected home/personal bots
- maybe a small subset of work bots for drafting/inspection only

### Phase 5: Queue And Replay

If all inference is down:

- accept prompts
- store them durably
- replay automatically when a runner returns

## Practical First Scope

If we want the smallest real win, do this first:

1. Add provider/runner/mode status to Norman + TUI status payloads.
2. Add checkpoint files to TUI bots.
3. Add a backup provider for app-side Norman.
4. Only then wire a local Qwen3 path.

That gives us real durability early without pretending the offline story is
complete.

## Proposed Config Shape

App-side:

- `llm_primary_provider=openai`
- `llm_backup_provider=<other>`
- `llm_offline_provider=openai_compatible`
- `llm_failover_mode=auto|strict|disabled`

TUI-side:

- `HOUSEBOT_CODEX_RUNNER=codex|backup|local`
- `HOUSEBOT_CODEX_FALLBACK_POLICY=strict|auto_online|auto_offline|control_only`
- `HOUSEBOT_CODEX_CHECKPOINT_PATH=...`

Local model:

- `NORMAN_LOCAL_LLM_BASE_URL=https://llm.[INTERNAL_DOMAIN]/v1`
- `NORMAN_LOCAL_LLM_MODEL=qwen3:<variant>`

For Knox, the local LLM shortcut is the durable API base URL. Caddy and
Norllama own worker selection and failover behind that logical endpoint.

These names are illustrative. The important thing is that provider and runner
become explicit first-class concepts.

## Risks

- pretending offline mode is better than it is
- trying to preserve vendor-specific thread semantics across providers
- adding a local model before adding checkpoints
- mixing failover policy with security policy
- silently changing behavior without operator visibility

## Recommended Decision

We should do this.

But the first build should be:

- control-plane durability
- explicit fallback state
- local checkpoints
- app-side provider abstraction

We should not start by just dropping a local Qwen3 model into the stack and
calling it done.

The durable Norman is:

- Norman as control plane
- inference as swappable substrate
- checkpoints as the continuity layer
- local models as degraded continuity, not fake parity
