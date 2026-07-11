# Norman Kernel Program

Date: 2026-07-05
Status: implementation planning
Audience: Norman Prime, TUI maintainers, Norllama maintainers, runtime workers, deployment operators

## Purpose

The Norman TUI fleet should stop being a collection of Codex wrappers. The target
shape is a Norman-owned kernel that accepts work from TUIs, CLIs, BBS, timers,
and other operators, then chooses the right runner, model, tool, shell, and
policy for each step.

Codex remains valuable, but it becomes one runtime adapter. The TUI should not
structurally depend on the Codex CLI, OpenAI, Bedrock, or any other cloud LLM.
When the cloud path is unavailable, expensive, or explicitly disabled, Norman
should keep operating through Norllama, local models, deterministic tools,
queueing, and clear degraded-mode notices.

## Current State Confirmed

The repo already contains the beginning of this architecture:

- `app/services/console_runtime/kernel.py` has the in-memory kernel nucleus for
  jobs, leases, checkpoints, approvals, behavior events, tool events, model
  events, planner receipts, and model adapter invocation.
- `app/services/console_runtime/store.py` persists jobs and runtime events in
  the database and exposes ordered cursorable events.
- `app/api/api_v1/routers/console_runtime.py` exposes job creation, event
  append, planner receipt append, job run, approval, worker status, event list,
  and SSE event streaming endpoints.
- `app/services/console_runtime/worker.py` has the first DB-backed worker. It
  leases work, records planner receipts, invokes a model adapter, and writes
  model/tool events.
- `app/services/console_runtime/adapters/norllama.py` lets the console runtime
  invoke Norllama through the provider-neutral model adapter contract.
- `app/services/norllama/routing.py` treats Norllama as a task framework, not
  just a local model. It can route local task lanes, tool lanes, and cloud proxy
  providers while preserving receipts.
- `scripts/agent_console_template/agent_console_web.py` mirrors TUI audit
  events into the console-runtime event feed and already renders structured
  planner, behavior, model, and tool activity.

This is enough to avoid starting over. The work now is to promote the runtime
nucleus into the Norman Kernel and move the TUIs onto it.

## Target Architecture

```text
TUI / Web TUI / CLI / BBS / scheduler
        |
        v
Norman Console Protocol
        |
        v
Norman Kernel
  - durable jobs, turns, sessions, steps, checkpoints
  - DB-backed event stream and SSE fanout
  - planner, scout, filter, verifier, and finalizer loop
  - route, cost, egress, offline, and approval policy
  - shell/job lifecycle and command supervision
  - model and tool capability selection through Norllama
  - degraded-mode notices and operator interrupts
        |
        v
Runtime Adapters
  - shell / tmux / pty runner
  - Codex adapter
  - Norllama local model adapter
  - Norllama cloud proxy adapter
  - Bedrock/OpenAI/direct cloud adapters
  - OCR/STT/embed/rerank/tool adapters
```

## Program Goals

1. Make the kernel the unit of work for TUI turns.
2. Make Codex optional by pushing it behind an adapter.
3. Make Norllama the model and capability broker for local, tool, and cloud
   proxy tasks.
4. Make offline and degraded operation explicit, visible, and testable.
5. Reduce cloud spend by using local scout/planner/filter/compact/rerank and
   lower-cost models before escalating.
6. Preserve long-running work through DB jobs, checkpoints, worker leases, and
   resumable sessions.
7. Let TUIs display behavior, tool calls, route decisions, model choices,
   cost/egress decisions, and blockers from the kernel event stream.

## Non-Goals

- Do not remove Codex from the fleet.
- Do not let raw local models silently perform unsafe mutations.
- Do not pretend local/offline mode has the same capability as frontier cloud
  models.
- Do not make each TUI invent its own fallback policy.
- Do not bypass Norman Keys, command policy, safety controls, or approvals.
- Do not make direct Ollama the public contract. Norllama is the front door.

## Operating Modes

The old four-mode model is not expressive enough. Norman needs independent axes:

- `llm_plane`: `cloud_ok`, `cloud_llm_offline`, `lan_local_only`,
  `no_inference`
- `runner_plane`: `kernel_shell`, `codex_available`, `codex_quarantined`,
  `control_only`
- `network_plane`: `internet_ok`, `web_only_no_cloud_llm`, `lan_only`,
  `airgap`
- `tool_plane`: `full_tools`, `read_only_tools`, `deterministic_only`,
  `disabled`
- `egress_policy`: `normal`, `cloud_llm_blocked`, `third_party_blocked`,
  `lan_only`, `deny_all`

Named operator modes should be derived from those axes:

- `primary_online`: normal cloud/local mix.
- `local_first_online`: internet available, but local models/tools are preferred
  unless escalation is justified.
- `cloud_llm_offline`: web research and LAN tools may work, but OpenAI,
  Bedrock, Anthropic, Hugging Face inference, and other cloud LLMs are blocked.
- `codex_quarantine`: Codex CLI is disabled because of auth, bad update,
  runner instability, or policy.
- `lan_only`: LAN services and local models work, internet egress is blocked.
- `airgap_local`: no internet; only local/LAN inference and deterministic tools.
- `control_only`: inference unavailable; Norman queues, checkpoints, displays,
  and recovers state without producing model-written answers.

## Workstreams

The detailed implementation plans live in the companion docs:

- `docs/norman_kernel_runtime_deep_dive.md`
  Kernel contracts, DB shape, event taxonomy, control loop, shell runner, Codex
  adapter boundary, and worker progression.
- `docs/norman_kernel_tui_deep_dive.md`
  How web TUIs and console CLIs become kernel clients, how streaming behavior is
  displayed, and how degraded/approval/interrupt UX works.
- `docs/norman_kernel_model_policy_deep_dive.md`
  Norllama-first model routing, offline modes, cost controls, warm model policy,
  cloud escalation, failover, and egress policy.
- `docs/norman_kernel_deployment_test_plan.md`
  Release sequence, test matrix, estate rollout, BBS coordination, acceptance
  criteria, and rollback.

## Implementation Sequence

### Phase 0: Documentation and Current-State Pinning

Deliverables:

- Complete kernel-first markdown plan set.
- Update doc index and existing runtime plan pointers.
- No runtime behavior change.

Exit criteria:

- The plan clearly names the Norman Kernel as the center.
- Each major component has an implementation surface and test plan.
- Existing runtime pieces are accounted for instead of duplicated.

### Phase 1: Kernel Contract Hardening

Deliverables:

- Add first-class kernel mode and route decision types.
- Add event types for `route.decided`, `egress.blocked`,
  `policy.degraded_mode`, `shell.started`, `shell.output`, `shell.completed`,
  `checkpoint.written`, and `verification.completed`.
- Add a policy module that can decide whether cloud LLMs, Codex, web egress,
  shell mutation, and local models are allowed.
- Add tests proving the TUI can create and observe a kernel job when Codex is
  disabled and cloud LLM egress is blocked.

Exit criteria:

- Kernel can represent a job's execution mode without relying on TUI-local
  assumptions.
- Runtime events show why a route was selected or blocked.
- The current DB-backed event stream remains backward compatible.

### Phase 2: Shell-Native Runtime Adapter

Deliverables:

- Add a shell/pty runtime adapter underneath the kernel.
- Route shell commands through command policy and approval gates.
- Stream stdout/stderr chunks as runtime events.
- Write checkpoints after bounded shell/model/tool steps.
- Keep Codex as an optional tool-capable adapter, not the parent process.

Exit criteria:

- A kernel job can run a bounded shell task without Codex.
- TUI can observe shell output from the DB event stream.
- Mutating commands require the same approval path regardless of model provider.

### Phase 3: TUI Kernel Client Mode

Deliverables:

- Add `NORMAN_TUI_BACKEND=kernel` or equivalent.
- Turn user prompts into kernel jobs/turns.
- Poll or stream job activity from Norman's runtime endpoints.
- Render route, model, planner, tool, shell, cost, and degraded-mode state from
  kernel events.
- Keep the existing Codex direct path as compatibility fallback.

Exit criteria:

- One test TUI can use the kernel backend for normal prompts.
- The same TUI works in `codex_quarantine` and `cloud_llm_offline` modes.
- A user can see whether work is local, cloud, queued, blocked, or waiting.

### Phase 4: Norllama-First Planning and Cost Control

Deliverables:

- Use Norllama capabilities for scout/planner/filter/compact/verify/rerank.
- Shift safe self-contained work to local models by default.
- Escalate to higher/cloud models only with a receipt explaining why.
- Keep benchmark-backed warm models preferred on the production spark mesh.

Exit criteria:

- Kernel route decisions include cost and capability reasons.
- Cloud calls have a local preflight receipt except for explicit exceptions.
- Local model failures degrade to wait/fallback rules rather than silent cloud
  spend.

### Phase 5: Estate Rollout

Deliverables:

- Deploy kernel backend to a small TUI group.
- Confirm DB event streams, approvals, worker status, and degraded notices.
- Expand to toy-box and other fleets after smoke and soak tests.

Exit criteria:

- Release notes and BBS notices are posted.
- Rollback to Codex direct path is documented and tested.
- Estate status can report which TUIs are kernel-backed.

## Done Definition

This program is done when:

- A web TUI can operate without Codex CLI installed or authenticated.
- A web TUI can operate with cloud LLM egress disabled.
- Norman can still queue, checkpoint, summarize state, and show recovery actions
  when no model is available.
- Model choice is visible and policy-backed.
- Shell and tool calls are supervised by the kernel and streamed to the TUI.
- Long work advances through durable jobs instead of one bounded browser turn.
- Cloud escalation is minimal, explicit, and auditable.
