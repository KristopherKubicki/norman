# Norman Console Runtime Plan

Date: 2026-07-01
Status: planning and first implementation target
Audience: Norman Prime, Subprime, work-special TUIs, local/Spark workers, and future runtime adapters

Update 2026-07-05: this plan is now folded into the kernel-first program. The
runtime remains the execution substrate, but the center of gravity is the
Norman Kernel. See `docs/norman_kernel_program.md` and its runtime, TUI,
model-policy, and deployment deep dives for the current implementation plan.

## Executive Summary

Norman should stop treating a web TUI turn as the unit of work. The current web
TUI can select Codex, Bedrock-backed Codex, and some registered future routes,
but the execution shape is still mostly one bounded model invocation per web
prompt. That is why long work often feels like it stops short: the browser TUI
wraps a single `codex exec` process and asks the model to checkpoint when the
turn budget, queue, or approval boundary gets close.

The next architecture should make Norman own the unit of work. A long request
should become a durable `ConsoleJob` with a lease, shell/session state,
repeated model/tool steps, checkpoints, artifacts, and acceptance checks.
Codex remains useful, but it becomes one adapter inside a Norman-owned runtime.
The same runtime should also call Norllama/Ollama, Bedrock Converse models,
direct OpenAI models, deterministic local tools, and future local/vLLM workers.

The new layer belongs in the normal Norman codebase. It should reuse existing
Norman services for tmux/screen control, command policy, approvals, safety
switches, workforce leases, route policy, local model sensing, and BBS
coordination. This is not a separate product and not a replacement for the
existing TUI fleet. It is the missing execution kernel underneath those TUIs.

## Problem Statement

The current web TUI is too provider-shaped and too turn-shaped.

Observed current behavior on live Norman:

- Web prompts are executed through `scripts/norman_codex_web.py`.
- The Codex path launches `codex exec --json` as a subprocess.
- The web worker tracks one prompt, one process, one timeout, one response.
- The turn control envelope currently sets `max_model_calls` to `1`.
- Long budgets such as 60m, 90m, deep, high-impact, and overnight exist, but
  they still mostly enlarge one turn rather than create a durable job loop.
- Auto-continuation exists for selected cases, but it is a recovery behavior,
  not a first-class job executor.
- The console CLI feels more persistent because tmux and the interactive shell
  own continuity. The web TUI owns a bounded request.

Desired behavior:

- A web request can create a durable job that runs for minutes or hours.
- The job can call multiple models and tools under a single contract.
- The job can checkpoint every 15 minutes, recover after browser loss, and
  resume after service restart.
- The job stops for approval boundaries, not just because a model turn ended.
- The final answer is based on evidence and acceptance checks, not a promise.

## Non-Goals

- Do not rebuild a full model reasoning engine.
- Do not remove Codex.
- Do not make local models final authority by default.
- Do not bypass Norman Keys, BBS actor boundaries, command policy, or approval
  gates.
- Do not give raw non-Codex models broad shell or filesystem write access.
- Do not replace all TUIs in one cutover.

## Guiding Principles

1. Norman owns work. Providers only perform steps.
2. Shell/session continuity is a backend primitive, not an accident of tmux.
3. Local deterministic work comes before model work.
4. Norllama is the local advisory lane for classification, compaction, draft
   planning, evidence reduction, and verifier inputs.
5. Bedrock-first remains the preferred work-special cloud policy.
6. Direct OpenAI remains a fallback or comparison lane, not the default.
7. Expensive frontier models own authority, verification, and final synthesis,
   not every token of routine work.
8. Every long job has explicit `done_when`, required artifacts, checkpoint
   cadence, and stop conditions.
9. Commands and external actions go through deterministic policy and approvals.
10. The UI shows live work, evidence, and blockers instead of only chat text.

## How This Ties Into The Normal Norman Codebase

This should live inside the existing Norman repo and reuse existing surfaces.

Likely code locations:

- `app/services/console_runtime/`
  - New runtime kernel, job state machine, provider adapters, evidence store.
- `app/api/api_v1/routers/console_runtime.py`
  - API endpoints for jobs, events, artifacts, checkpoints, approvals, and
    cancellation.
- `app/models/console_runtime.py`
  - SQLAlchemy models for jobs, steps, provider calls, tool calls, artifacts,
    and checkpoints.
- `app/schemas/console_runtime.py`
  - Pydantic contracts for API and worker messages.
- `app/static/js/console_runtime.js`
  - Browser cockpit behavior for live jobs.
- `app/templates/console_runtime.html` or extensions to the current workforce
  and console templates.
- `scripts/norman_runtime_worker.py`
  - First background worker process for advancing jobs.
- `scripts/tui_workforce_daemon.py`
  - Later dispatches leased work into runtime jobs instead of stopping at
    `would_execute: false`.
- `scripts/norman_codex_web.py`
  - Initially acts as compatibility client. Later it delegates to the runtime
    for long work while keeping the existing simple prompt path.

Existing code to reuse:

- `app/services/tmux_inspector.py`
  - Read-only tmux inventory and capture.
- `app/api/api_v1/routers/tmux.py`
  - Session adoption, start/stop/lock/operator mode, protected sessions.
- `app/services/screen_hypervisor.py`
  - Screen lifecycle, queue, lock, inflight, log pull primitives.
- `app/core/command_policy.py`
  - Deterministic allow/approval/block decisions for shell and chat payloads.
- `app/core/safety_controls.py`
  - Kill switch, read-only mode, execution block reasons.
- `app/services/planner_prefilter.py`
  - Norllama specialist first-pass and prefilter receipts.
- `app/services/planner_cloud_gate.py`
  - Cloud call gate requiring local prefilter or exception receipts.
- `scripts/local_model_route_policy.py`
  - Local-first and Norllama route policy.
- `scripts/tui_provider_readiness_benchmark.py`
  - Hybrid planner/worker/verifier policy and promotion gates.
- `scripts/tui_workforce_loop.py`
  - Ticket to worker-contract normalization.
- `scripts/tui_workforce_daemon.py`
  - Lease/checkpoint state and approval holds.
- `app/api/api_v1/routers/estate.py`
  - Existing workforce dashboard state.
- `scripts/spark_background_kpi_receipts.py`
  - Local/Spark receipt pattern for bounded background work.
- Norman Keys services and routes
  - Secret aliases, requests, leases, stash, and audit.

## Core Abstractions

### ConsoleSession

A durable handle for an interactive execution environment.

Fields:

- `session_id`
- `owner_tui`
- `host`
- `backend`: `tmux`, `screen`, `pty`, or `subprocess`
- `session_name`
- `target`
- `workdir`
- `env_profile`
- `state`: `starting`, `ready`, `busy`, `locked`, `stopped`, `failed`
- `protected`
- `operator_mode`: `observe`, `take`, `co_pilot`
- `last_capture`
- `created_at`, `updated_at`, `last_heartbeat_at`

Responsibilities:

- Start or reuse a shell/session.
- Capture output incrementally.
- Send input only through policy.
- Lock and unlock safely.
- Survive browser refresh.
- Preserve enough state to recover after service restart.

### ConsoleJob

The durable unit of work.

Fields:

- `job_id`
- `source_kind`: `operator`, `bbs`, `jira`, `github`, `manual`, `timer`
- `source_ref`
- `owner_tui`
- `created_by`
- `title`
- `prompt`
- `contract`
- `done_when`
- `success_metrics`
- `required_artifacts`
- `approval_required_for`
- `question_budget`
- `max_runtime_seconds`
- `checkpoint_interval_seconds`
- `lease_expires_at`
- `state`
- `blocked_reason`
- `final_summary`
- `created_at`, `started_at`, `finished_at`, `updated_at`

States:

- `queued`
- `leased`
- `planning`
- `running`
- `verifying`
- `checkpointed`
- `waiting_approval`
- `blocked`
- `done`
- `canceled`
- `failed`

### JobStep

One bounded piece of work under a job.

Fields:

- `step_id`
- `job_id`
- `sequence`
- `role`: `planner`, `worker`, `tool`, `verifier`, `finalizer`
- `lane`: `deterministic`, `norllama`, `codex`, `bedrock`, `openai`, `shell`
- `input_ref`
- `output_ref`
- `state`
- `started_at`, `finished_at`
- `timeout_seconds`
- `attempt`
- `decision`
- `confidence`

### ModelInvocation

Provider-neutral record for a model call.

Fields:

- `invocation_id`
- `job_id`
- `step_id`
- `adapter`
- `provider_surface`
- `runtime`
- `model`
- `service_tier`
- `role`
- `request_schema`
- `response_schema`
- `input_tokens`
- `cached_input_tokens`
- `output_tokens`
- `reasoning_output_tokens`
- `total_tokens`
- `cost_estimate`
- `charge_basis`
- `provider_request_ids`
- `status`
- `error_kind`
- `started_at`, `finished_at`

### ToolInvocation

Brokered command or action record.

Fields:

- `tool_invocation_id`
- `job_id`
- `step_id`
- `tool_kind`: `shell`, `tmux`, `screen`, `aws`, `ssh`, `file`, `bbs`,
  `norman_keys`, `browser`, `test`
- `command_text`
- `policy_decision`
- `approval_id`
- `returncode`
- `stdout_ref`
- `stderr_ref`
- `artifact_refs`
- `timeout_seconds`
- `started_at`, `finished_at`

### Artifact

Durable evidence produced or consumed by the job.

Fields:

- `artifact_id`
- `job_id`
- `step_id`
- `kind`: `plan`, `patch`, `diff`, `test_output`, `log`, `receipt`,
  `checkpoint`, `final_summary`, `screenshot`, `metrics`
- `path`
- `sha256`
- `label`
- `content_type`
- `created_at`

## Provider Adapter Interface

Every model provider should implement one narrow interface.

```python
class ModelAdapter(Protocol):
    key: str
    capabilities: ModelCapabilities

    def invoke(
        self,
        request: ModelRequest,
        *,
        timeout_seconds: int,
        budget: ModelBudget,
    ) -> ModelResult:
        ...
```

ModelRequest:

- `messages`
- `role`
- `system_contract`
- `json_schema`
- `tools`
- `evidence_refs`
- `job_context`
- `stop_conditions`

ModelResult:

- `status`: `ok`, `blocked`, `timeout`, `provider_error`, `invalid_output`
- `content`
- `parsed_json`
- `tool_requests`
- `confidence`
- `usage`
- `provider_metadata`
- `error_kind`
- `artifact_refs`

Initial adapters:

1. `CodexCliAdapter`
   - Wraps existing `codex exec --json`.
   - Preserves `stdin=DEVNULL`, hard timeout, JSON event parsing, usage capture.
   - Used for compatibility and code-edit authority where Codex remains best.

2. `BedrockConverseAdapter`
   - Generalizes the existing Claude Bedrock Converse broker.
   - Supports read-only shell, read-only AWS, limited file write, limited SSH
     only when policy enables those tools.
   - Can host Claude, Kimi, Qwen, DeepSeek, and GPT OSS scout lanes once
     model-specific canaries pass.

3. `OllamaNorllamaAdapter`
   - Calls Ollama `/api/chat` or `/api/generate`.
   - Used for local classification, compaction, draft planning, evidence
     summaries, and verifier inputs.
   - No live mutation authority by default.

4. `OpenAICompatibleAdapter`
   - Future generic adapter for vLLM, local OpenAI-compatible endpoints, or
     other hosted endpoints.

5. `DeterministicAdapter`
   - No model call. Runs local parsers, counters, status probes, artifact
     reads, and policy checks.

## Job Execution Loop

The runtime worker advances one job at a time under a lease.

Loop:

1. Load job and contract.
2. Refresh safety state.
3. Refresh session state.
4. Check budget, lease, queue, and cancel flags.
5. If no plan exists, run deterministic preflight.
6. Use Norllama or cloud planner only if deterministic preflight is not enough.
7. Emit a strict step contract:
   - allowed files
   - allowed commands
   - forbidden actions
   - required evidence
   - acceptance test
   - timeout
   - escalation rule
8. Execute the step through the tool broker or model worker.
9. Capture stdout/stderr/artifacts.
10. Verify the step.
11. Decide:
    - continue
    - checkpoint
    - wait for approval
    - block
    - done
12. Write job event.
13. Heartbeat and update UI.

Stop conditions:

- `done_when` passes.
- Required artifact cannot be produced after bounded retry.
- Approval boundary is reached.
- Secret/key material is needed and no approved lease exists.
- Tests fail after bounded retry.
- Runtime budget expires.
- Operator cancels or takes over.
- Safety kill switch blocks execution.

## Route Policy

Default route ladder:

1. Local deterministic.
2. Norllama/Ollama scout or compactor.
3. Codex/worker model for bounded patch or execution.
4. Bedrock 5.4 verifier for normal authority.
5. Bedrock 5.5 or human for final authority or high-risk gates.
6. Direct OpenAI only as explicit fallback/comparison/last resort.

Workload mapping:

- Status, inventory, row counting, freshness checks:
  - deterministic only.
- Log clustering, duplicate detection, table cleanup:
  - Norllama or cheap worker, strict JSON, sampled verifier.
- Context compaction:
  - deterministic extraction plus Norllama summary, evidence refs preserved.
- Bounded patch draft:
  - planner contract, coder worker or Codex, allowed files only, tests, verifier.
- Operator-facing decision:
  - Bedrock 5.4 or 5.5 depending on authority.
- Purse, seal, key, sword, deploy, external write:
  - stop for human approval or frontier authority gate before live action.

## Tool Broker Policy

The tool broker is the only path from model text to live action.

Rules:

- Commands are denied by default unless classified as safe read or explicitly
  allowed by session policy.
- Mutating commands require approval.
- Destructive commands require approval and confirmation.
- Shell metacharacters require approval unless explicitly allowed by profile.
- SSH and AWS commands use allowlists.
- File writes require allowed path prefixes and size limits.
- Secrets are never requested as raw values in prompts or BBS messages.
- Norman Keys aliases and leases are the secret path.
- Every command produces a `ToolInvocation` event.

## Runtime Event Log

The runtime should be event-sourced enough for replay and debugging.

Events:

- `job.created`
- `job.leased`
- `job.started`
- `job.heartbeat`
- `job.checkpointed`
- `job.waiting_approval`
- `job.blocked`
- `job.done`
- `job.failed`
- `job.canceled`
- `step.started`
- `step.completed`
- `step.failed`
- `model.invoked`
- `model.completed`
- `model.failed`
- `tool.requested`
- `tool.approved`
- `tool.denied`
- `tool.completed`
- `artifact.created`
- `verification.passed`
- `verification.failed`

Every event should include:

- `event_id`
- `job_id`
- `step_id` when applicable
- `actor`
- `owner_tui`
- `timestamp`
- `severity`
- `summary`
- `payload`

## Browser TUI Changes

The UI should become a job cockpit, not only a chat box.

Views:

- Active job header:
  - title, owner, state, lease, budget, next checkpoint, route plan.
- Live console pane:
  - tmux/screen/PTY capture, recent command output, current process.
- Timeline:
  - model calls, tool calls, checkpoints, artifacts, approvals, errors.
- Artifacts:
  - plan, diff, test output, receipts, final summary.
- Approvals:
  - pending approval requests with reason, command/action, confirm token if
    destructive.
- Controls:
  - cancel, pause, resume, checkpoint now, take over, queue follow-up, lock.
- Provider telemetry:
  - runtime, model, service tier, tokens, cost estimate, route class, verifier.

Important UX rule:

- Long jobs should show active progress through events and artifacts. They
  should not rely on a final assistant paragraph to prove that work happened.

## Workforce Integration

Existing workforce contracts already define most of the job contract.

`scripts/tui_workforce_loop.py` emits:

- `done_when`
- `success_metrics`
- `required_artifacts`
- `question_budget`
- `max_runtime_seconds`
- `checkpoint_interval_seconds`
- `approval_required_for`
- `authority_flags`
- `route_policy`

`scripts/tui_workforce_daemon.py` currently acquires leases and records
receipts, but intentionally does not execute. The runtime should become the
execution target for those leases.

Dispatch rule:

- If a ticket is leased and `autonomy_mode == offline_execute_with_receipts`,
  create or resume a `ConsoleJob`.
- If a ticket is approval-gated, create an offline draft/verification job only
  if the contract allows it, then stop at approval.
- If a lease expires, the runtime must checkpoint, release, or reacquire
  explicitly.

## BBS Integration

BBS remains the durable coordination surface.

Runtime should be able to:

- Read source threads only through the actor's allowed scope.
- Attach artifacts to a BBS thread after job completion.
- Post checkpoints for long BBS-owned jobs.
- Mark a thread done only when `done_when` and required artifacts pass.
- Mark blocked with exact blocker and next owner.
- Never post raw secrets.
- Never ACK an empty or missing-context thread just to clear it.

For this plan itself:

- Use an information-only BBS notice.
- Tag it as governance/runtime/TUI architecture.
- Mark it done or otherwise closed so it does not appear as open pickup work.

## Implementation Phases

### Phase 0: Source Of Truth And Alignment

Deliverables:

- This plan in `docs/norman_console_runtime_plan.md`.
- Information-only BBS notice to Norman/Subprime/fleet.
- Short glossary:
  - Console Runtime
  - Console Job
  - Session
  - Step
  - Adapter
  - Broker
  - Evidence
  - Verifier

Acceptance:

- BBS notice exists and is closed/info-only.
- Plan is in the normal Norman repo.
- No runtime behavior changed yet.

### Phase 1: Web Short-Stop Mitigation

Goal:

- Improve current web TUI behavior while the new runtime is being built.

Work:

- Change the turn envelope budget so long work does not always mean
  `max_model_calls: 1`.
- Add a long-work acceptance gate:
  - final reply cannot be only a promise.
  - final reply must include evidence, test output, artifact refs, or an
    explicit blocker.
- Auto-continue CHECKPOINT/thin-output replies while budget remains and no
  operator queue is waiting.
- Preserve current queue/interruption safety.
- Record a `short_stop_detected` event when a long-budget turn ends too early
  without evidence.

Acceptance:

- 60m/90m/deep turns either complete with evidence or leave a durable
  checkpoint.
- Low-yield short-stop rate falls in the benchmark.
- No approval boundaries are weakened.

### Phase 2: Provider Adapter Extraction

Goal:

- Move provider-specific invocation code behind a stable interface.

Work:

- Create `app/services/console_runtime/adapters/base.py`.
- Create `CodexCliAdapter` from the current Codex exec path.
- Create `BedrockConverseAdapter` from the current brokered Converse path.
- Create `OllamaNorllamaAdapter` for `/api/chat` and `/api/generate`.
- Create `DeterministicAdapter`.
- Normalize usage and provider metadata across adapters.

Acceptance:

- Existing Codex web path can call through `CodexCliAdapter`.
- Norllama can produce a bounded strict JSON classification in a unit test with
  a fake endpoint.
- Adapter tests use fake providers by default.

### Phase 3: Console Job Data Model

Goal:

- Add durable job, step, invocation, tool, artifact, and checkpoint records.

Work:

- Add SQLAlchemy models.
- Add Alembic migration.
- Add schemas.
- Add CRUD helpers.
- Add event writer.
- Keep artifacts as filesystem paths plus DB metadata, not giant DB blobs.

Acceptance:

- Unit tests cover create, lease, heartbeat, checkpoint, block, complete.
- Restart can recover a running job as checkpointed or abandoned with evidence.

### Phase 4: Tool Broker And Session Backend

Goal:

- Run commands through one brokered path.

Work:

- Wrap `command_policy.evaluate_tmux_payload`.
- Add shell command runner with timeout and captured output.
- Add tmux/screen send/capture adapters.
- Add file write helper using allowed path policy.
- Add read-only AWS/SSH helpers by reusing existing Bedrock Converse policy.
- Add approval request creation for gated actions.

Acceptance:

- Read-only commands run without approval.
- Mutating/destructive commands produce approval records.
- Kill switch blocks execution.
- Protected sessions cannot be stopped by default.

### Phase 5: Runtime Worker

Goal:

- Create the first job executor.

Work:

- Add `scripts/norman_runtime_worker.py`.
- Worker polls queued/leased jobs.
- Worker advances one job at a time.
- Worker emits events and heartbeats.
- Worker can pause, resume, cancel, and checkpoint.
- Worker starts with deterministic and Codex adapter support, then Norllama.

Acceptance:

- A fake job can run deterministic steps and finish.
- A fake provider job can make multiple model calls under one job.
- A forced timeout produces checkpoint, not silent failure.

### Phase 6: Planner/Worker/Verifier Loop

Goal:

- Make model mixing normal.

Work:

- Add strict JSON plan schema.
- Add worker step schema.
- Add verifier schema.
- Use Norllama prefilter before cloud calls where policy requires it.
- Use Bedrock verifier for cloud/final authority gates.
- Enforce `verifier_owned_final` for worker lanes.

Acceptance:

- Worker output cannot become final without verifier acceptance unless route
  policy explicitly allows validator-bounded local final.
- Scope drift is rejected.
- Missing tests are rejected or reported as blocker.

### Phase 7: Web Cockpit API And UI

Goal:

- Let the browser observe and control jobs.

Work:

- Add runtime API:
  - `GET /api/v1/runtime/jobs`
  - `POST /api/v1/runtime/jobs`
  - `GET /api/v1/runtime/jobs/{job_id}`
  - `GET /api/v1/runtime/jobs/{job_id}/events`
  - `POST /api/v1/runtime/jobs/{job_id}/cancel`
  - `POST /api/v1/runtime/jobs/{job_id}/checkpoint`
  - `POST /api/v1/runtime/jobs/{job_id}/resume`
  - `GET /api/v1/runtime/jobs/{job_id}/artifacts`
- Add UI timeline and job detail view.
- Connect current prompt submission to runtime for long-work mode.

Acceptance:

- Operator can watch a long job progress without refreshing.
- Operator can cancel or take over.
- Checkpoints survive browser reload.

### Phase 8: Workforce Dispatch

Goal:

- Turn leases into jobs.

Work:

- Add execution flag for workforce daemon.
- When enabled, create jobs for offline-ready leased contracts.
- Attach final artifacts back to source thread when available.
- Keep approval-gated contracts in draft/verify only mode.

Acceptance:

- One routine BBS/manual ticket can be leased, executed, checkpointed, verified,
  and closed with artifacts.
- No external write happens without approval.

### Phase 9: Canary And Promotion

Initial canary:

- One non-critical Norman/work-special TUI.
- One routine local repo task.
- One read-only status/inventory task.
- One Norllama compaction task.
- One bounded patch draft with verifier.

Promotion gates:

- Zero unapproved authority use.
- Zero worker scope violations.
- Required artifacts present for completed jobs.
- No final answer based only on a promise.
- Checkpoint/resume works after web restart.
- Low-yield short-stop rate improves.
- Worker escalation rate at or below 20 percent for eligible lanes.
- Cost and route ledger records are present.

## Test Plan

Unit tests:

- Job state transitions.
- Lease expiry.
- Checkpoint interval.
- Adapter request/response normalization.
- Fake Codex adapter.
- Fake Bedrock adapter.
- Fake Ollama adapter.
- Command policy integration.
- Approval creation.
- Artifact hashing.
- Event log ordering.

Integration tests:

- Fake provider plus fake shell completes a job.
- Fake provider times out and job checkpoints.
- Worker output with scope drift is rejected by verifier.
- Approval boundary stops execution.
- Restart recovery marks stale active job checkpointed.

Live canaries:

- Deterministic status job.
- Norllama context compaction job.
- Codex compatibility job.
- Bedrock verifier job.
- BBS ticket closure job.

Required repo checks for code changes:

- `make format`
- `make lint`
- `make test`
- `npm test` if frontend files change

## Risks And Controls

Risk: rebuilding too much.

Control:

- Keep provider adapters thin.
- Build the job kernel first.
- Reuse existing tmux/screen, command policy, approvals, and route policy.

Risk: local models overstep.

Control:

- Norllama default is advisory.
- Verifier owns final unless explicit validator-bounded local final exists.
- Purse/seal/key/sword boundaries stop for human or frontier authority.

Risk: secrets leak into prompts or BBS.

Control:

- Use Norman Keys aliases and leases.
- Never put raw secret values in job prompts, artifacts, or BBS posts.
- Treat missing secret material as a blocker with a logical alias request.

Risk: context explosion.

Control:

- Evidence refs over pasted logs.
- Deterministic compaction before cloud.
- Vector/SQL history retrieval only when needed.

Risk: web UI becomes complicated.

Control:

- Start with backend events and a simple timeline.
- Keep the current chat path for short prompts.
- Only route long-work mode to jobs at first.

Risk: dirty live repo and stale local repo diverge.

Control:

- Treat live `staging` as current architecture source until local is synced.
- Make small additive changes first.
- Do not overwrite unrelated dirty files.

## First Concrete Build Slice

The first real implementation should be narrow:

1. Add `docs/norman_console_runtime_plan.md`.
2. Add `app/services/console_runtime/` package with:
   - `types.py`
   - `events.py`
   - `adapters/base.py`
   - `adapters/fake.py`
   - `kernel.py`
3. Add tests for the fake adapter and job state machine.
4. Add no production execution yet.
5. Add BBS info post and link/attach the plan.

After that:

1. Extract `CodexCliAdapter`.
2. Add fake shell/tool broker.
3. Add first real deterministic job path.
4. Add UI read-only job timeline.

## Design Decision

The correct architecture is:

```text
Browser TUI
  -> Norman Console Runtime API
    -> ConsoleJob lease/state machine
      -> Session backend: shell/tmux/screen/PTY
      -> Tool broker: command policy, approvals, safety, keys
      -> Model router: deterministic, Norllama, Codex, Bedrock, OpenAI, future
      -> Evidence store: artifacts, logs, receipts, checkpoints
      -> Verifier/final authority
    -> BBS/workforce artifacts and closure
```

The wrong architecture is:

```text
Browser TUI -> one provider-specific model process -> final text
```

The important shift is that Norman becomes the durable operator runtime. Models
become interchangeable workers inside that runtime.
