# Norman Kernel Runtime Deep Dive

Date: 2026-07-05
Status: implementation planning
Audience: kernel/runtime implementers

## Summary

The kernel is the durable execution layer under the Norman TUI fleet. It should
own sessions, jobs, turns, steps, route decisions, model invocations, tool calls,
shell activity, approvals, checkpoints, and completion checks.

The existing `console_runtime` package is the starting point, not throwaway
work. It already has the core vocabulary and event stream. The next step is to
make it the execution authority instead of a mirror next to the Codex-shaped
TUI.

## Existing Runtime Nucleus

Implemented today:

- `ConsoleRuntimeKernel`
  - in-memory jobs
  - leases
  - start/checkpoint/complete/block/fail/cancel transitions
  - approval holds
  - behavior/tool/model/planner events
  - provider-neutral model adapter invocation
- `DbConsoleRuntimeStore`
  - DB-backed jobs
  - ordered runtime events
  - cursorable activity snapshots
  - approval state transitions
  - planner receipt persistence
- `console_runtime` API
  - create/list/read jobs
  - append events
  - append planner receipts
  - run one job step
  - approve/reject approval holds
  - stream job events by SSE
- `DbConsoleRuntimeWorker`
  - leases one runnable job
  - records worker behavior
  - records Norllama route/planner receipt
  - invokes one model adapter
  - records model and tool completion events
  - completes or checkpoints the job
- `NorllamaModelAdapter`
  - fetches live Norllama capabilities
  - invokes local/openai-compatible chat through Norllama
  - returns route and receipt metadata

Primary gap:

The runtime is still a one-step worker. It does not yet run a multi-step,
policy-driven control loop with shell/session lifecycle, route decisions,
verification, and checkpoint cadence.

## Kernel Responsibilities

The kernel must own these concerns centrally:

- Work intake and contract normalization.
- Durable job and turn state.
- Runtime mode and degraded-mode state.
- Model route decisions.
- Tool and shell execution supervision.
- Command policy and approval boundaries.
- Cost, egress, and provider policy.
- Checkpoint cadence.
- Verification and done checks.
- Event emission for all observable behavior.
- Interrupt, cancel, resume, and handoff behavior.

The TUI should not decide whether a prompt is local-safe, cloud-allowed,
Codex-required, or shell-mutable. The TUI should submit work and display kernel
state.

## Core Contracts

### KernelSession

Represents durable interaction continuity.

Fields:

- `session_id`
- `owner_tui`
- `actor`
- `host`
- `backend`: `kernel`, `shell`, `tmux`, `screen`, `codex`, `control_only`
- `workdir`
- `env_profile`
- `mode`
- `state`: `starting`, `ready`, `busy`, `waiting_approval`, `blocked`,
  `stopped`, `failed`
- `last_job_id`
- `last_turn_id`
- `last_checkpoint_id`
- `last_heartbeat_at`
- `metadata`

First implementation:

- Store session metadata in job `metadata` if a dedicated table is too much for
  the first slice.
- Add a real `console_runtime_sessions` table once multiple TUIs are moved to
  kernel backend.

### KernelJob

Extends the existing `ConsoleJob` concept.

Required contract fields:

- objective
- done_when
- success_metrics
- required_artifacts
- max_runtime_seconds
- checkpoint_interval_seconds
- question_budget
- approval_required_for
- route_policy
- authority_flags
- mode_policy
- egress_policy

Additional runtime fields:

- `active_mode`
- `selected_runner`
- `selected_model`
- `planner_model`
- `route_decision_id`
- `current_step_id`
- `checkpoint_due_at`
- `deadline_at`
- `cost_budget`
- `cost_spent_estimate`
- `degraded_reasons`

### KernelTurn

One user-facing input under a session or job.

Fields:

- `turn_id`
- `job_id`
- `session_id`
- `actor`
- `input_text`
- `attachments`
- `requested_runtime`
- `requested_model`
- `requested_service_tier`
- `route_lock`
- `created_at`
- `normalized_contract`

First implementation:

- Encode turns as runtime events plus job metadata.
- Add a table only when multi-turn kernel sessions become standard.

### KernelStep

One bounded action in the kernel loop.

Fields:

- `step_id`
- `job_id`
- `sequence`
- `role`: `classify`, `plan`, `scout`, `filter`, `compact`, `model`,
  `shell`, `tool`, `verify`, `finalize`, `checkpoint`
- `adapter`
- `status`
- `input_ref`
- `output_ref`
- `started_at`
- `finished_at`
- `timeout_seconds`
- `attempt`
- `route_decision_id`
- `approval_id`

Storage plan:

- Phase 1 can continue using runtime events only.
- Phase 2 should add `console_runtime_steps` once shell/tool execution needs
  durable retries and per-step timeout accounting.

### RouteDecision

Provider-neutral routing receipt.

Fields:

- `decision_id`
- `job_id`
- `turn_id`
- `task_kind`
- `selected_lane`
- `selected_provider`
- `selected_runner`
- `selected_model`
- `selected_endpoint`
- `local`
- `cloud_proxy`
- `cost_basis`
- `egress_class`
- `degraded`
- `reasons`
- `blocked_reasons`
- `fallback_order`
- `capability_snapshot`
- `benchmark_snapshot_ref`

Event:

- `route.decided`

### KernelCheckpoint

Runner-independent handoff state.

Minimum contents:

- current objective
- current mode
- current route decision
- workdir and repo status summary
- files touched or referenced
- commands run
- model/tool calls made
- approvals requested or received
- latest facts/evidence
- current blockers
- next action
- confidence and risk notes

Checkpoint events:

- `checkpoint.written`
- `checkpoint.restored`
- `checkpoint.rejected`

### RuntimeEvent

The existing event object is good. Extend the taxonomy without breaking old
events.

Categories to support:

- `job`
- `turn`
- `behavior`
- `route`
- `policy`
- `model`
- `planner`
- `tool`
- `shell`
- `approval`
- `checkpoint`
- `artifact`
- `verification`
- `runtime`

Important new event types:

- `turn.received`
- `turn.normalized`
- `route.decided`
- `route.fallback_selected`
- `policy.mode_selected`
- `policy.egress_blocked`
- `policy.degraded_mode`
- `model.requested`
- `model.delta`
- `model.completed`
- `model.failed`
- `tool.started`
- `tool.output`
- `tool.completed`
- `tool.failed`
- `shell.started`
- `shell.output`
- `shell.completed`
- `shell.failed`
- `checkpoint.written`
- `verification.started`
- `verification.completed`

## Kernel Control Loop

The kernel loop should run until the job is done, blocked, failed, canceled,
waiting for approval, out of budget, or due for a checkpoint.

```text
1. Load job, session, and current mode.
2. Normalize the turn/job contract.
3. Classify task kind, risk, needed tools, and likely context.
4. Ask Norllama for scout/planner/filter guidance when allowed.
5. Decide route using mode, capability, cost, egress, and approval policy.
6. Execute one bounded step through the selected adapter.
7. Stream behavior/model/tool/shell events.
8. Verify whether done_when and required artifacts are satisfied.
9. Write checkpoint if interval or risk threshold is reached.
10. Continue, complete, or hold for approval/operator input.
```

First production behavior should be conservative:

- one bounded shell/model/tool step per worker tick
- checkpoint after each mutating shell/tool step
- checkpoint after each model step longer than the configured interval
- never silently cross from local/offline to cloud

## Adapter Interfaces

### ModelAdapter

Already exists:

- `name`
- `capabilities`
- `invoke(ModelRequest) -> ModelResult`

Needed additions:

- streaming support with `model.delta`
- explicit `egress_class`
- explicit `cost_basis`
- capability flags for tools, files, long context, structured output, and
  confidence/verification suitability

### ShellAdapter

New interface:

- `capabilities()`
- `start_session(session_spec)`
- `run(command, timeout, cwd, env, policy_context)`
- `stream_output(cursor)`
- `interrupt(invocation_id)`
- `terminate(session_id)`

Rules:

- All commands go through `app/core/command_policy.py`.
- Mutating commands go through approvals unless the job contract authorizes
  them.
- Shell output is chunked into `shell.output` events.
- Large output is summarized and stored as artifact refs, not copied endlessly
  into events.

### CodexAdapter

Codex should become an adapter behind the kernel.

Responsibilities:

- launch/resume Codex when allowed
- expose Codex auth/version/health state
- stream Codex JSON events into kernel events
- convert Codex tool calls into normalized `tool.*` and `shell.*` events where
  possible
- fail closed when Codex is quarantined or cloud LLM policy blocks it

It should not:

- own the TUI session
- decide global route policy
- hide tool or shell behavior from the kernel
- be required for local/offline work

### NorllamaAdapter

Norllama should be the default model broker for:

- scout
- planner
- filter
- summarize
- compact
- verify
- OCR
- STT
- embed
- rerank
- local chat
- cloud proxy when policy allows

The kernel should use Norllama capabilities endpoints before selecting models.

## DB Evolution

Keep the current tables working:

- `console_runtime_jobs`
- `console_runtime_events`

Add only when needed:

- `console_runtime_sessions`
- `console_runtime_steps`
- `console_runtime_route_decisions`
- `console_runtime_checkpoints`
- `console_runtime_artifacts`

Implementation guidance:

- Phase 1 should avoid a broad migration if events and metadata are enough.
- Phase 2 shell execution likely needs steps and sessions.
- Phase 3 multi-turn TUI kernel backend likely needs sessions and turns.
- Artifacts can initially be path refs in events and job artifact lists.

## API Evolution

Existing endpoints stay.

Add:

- `POST /api/v1/console-runtime/sessions`
- `GET /api/v1/console-runtime/sessions/{session_id}`
- `POST /api/v1/console-runtime/sessions/{session_id}/turns`
- `POST /api/v1/console-runtime/jobs/{job_id}/advance`
- `POST /api/v1/console-runtime/jobs/{job_id}/interrupt`
- `POST /api/v1/console-runtime/jobs/{job_id}/checkpoint`
- `GET /api/v1/console-runtime/jobs/{job_id}/mode`
- `GET /api/v1/console-runtime/capabilities`

Compatibility:

- Existing TUI event mirroring continues.
- Existing `/jobs/{job_id}/events/stream` remains the primary live feed.

## Safety Rules

- Control plane must run without model access.
- No mutating shell/tool step without policy approval.
- No cloud LLM egress if `cloud_llm_offline`, `lan_only`, or `airgap_local` is
  active.
- No Codex invocation if Codex is quarantined.
- No direct secret file reads added. Use Norman Keys or brokered secrets.
- No direct Ollama LAN contract. Use Norllama.
- Local models may draft and inspect, but risky final authority requires policy
  approval or explicit degraded-mode acceptance.

## Implementation Slices

### Slice 1: Kernel Mode And Route Events

Files:

- `app/services/console_runtime/types.py`
- `app/services/console_runtime/events.py`
- `app/services/console_runtime/kernel.py`
- `app/services/console_runtime/store.py`
- `tests/test_console_runtime_kernel.py`
- `tests/test_console_runtime_store.py`

Work:

- Add mode/route decision dataclasses.
- Add event category support for `route`, `policy`, `shell`, `checkpoint`,
  `verification`, and `turn`.
- Add kernel/store helpers to append route and policy events.
- Add tests for route/policy event ordering and snapshots.

### Slice 2: Policy Module

Files:

- `app/services/console_runtime/policy.py`
- `tests/test_console_runtime_policy.py`

Work:

- Add mode axis parsing from env and job route policy.
- Add egress classification.
- Add provider and runner allow/deny decisions.
- Add degraded-mode notice generation.

### Slice 3: Shell Adapter

Files:

- `app/services/console_runtime/adapters/shell.py`
- `app/services/console_runtime/worker.py`
- `tests/test_console_runtime_shell_adapter.py`
- `tests/test_console_runtime_worker.py`

Work:

- Add bounded subprocess/pty execution.
- Route commands through command policy.
- Emit shell events.
- Add dry-run and approval behavior.

### Slice 4: Codex Adapter Boundary

Files:

- `app/services/console_runtime/adapters/codex.py`
- `scripts/agent_console_template/agent_console_web.py`
- `tests/test_console_runtime_codex_adapter.py`
- `tests/test_agent_console_runtime_bridge.py`

Work:

- Wrap Codex invocation behind kernel adapter.
- Surface auth/version/update failures as runtime events.
- Support Codex quarantine mode.

### Slice 5: Multi-Step Worker Loop

Files:

- `app/services/console_runtime/worker.py`
- `app/services/console_runtime/supervisor.py`
- `tests/test_console_runtime_worker.py`
- `tests/test_console_runtime_supervisor.py`

Work:

- Advance one bounded kernel step per tick.
- Continue until checkpoint/done/blocked/approval/deadline.
- Add checkpoint cadence.
- Add verification before completion.

## Test Plan

Required focused tests:

- Kernel can create, lease, start, checkpoint, approve, complete, and stream
  with new event categories.
- Store persists route and policy events.
- Worker refuses live shell execution without approval.
- Shell output streams as `shell.output`.
- Codex quarantine blocks Codex adapter without blocking shell/local lanes.
- Cloud LLM offline blocks cloud providers but allows LAN Norllama and web
  research if network mode allows it.
- Control-only mode queues and displays work without model invocation.
- SSE feed remains ordered and cursorable.

Regression tests:

- `tests/test_console_runtime_kernel.py`
- `tests/test_console_runtime_store.py`
- `tests/test_console_runtime_api.py`
- `tests/test_console_runtime_worker.py`
- `tests/test_agent_console_runtime_bridge.py`
- `tests/test_norllama_routing.py`
- `tests/test_norllama_proxy.py`

Acceptance:

- A kernel job can run without Codex.
- A kernel job can run without cloud LLM egress.
- TUI can display kernel events for model, shell, tool, route, policy, and
  planner behavior.
- Job state survives API process restart because authoritative state is in DB.
