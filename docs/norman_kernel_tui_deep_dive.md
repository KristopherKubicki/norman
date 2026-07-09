# Norman Kernel TUI Deep Dive

Date: 2026-07-05
Status: implementation planning
Audience: web TUI, console CLI, deployment, and operator UX maintainers

## Summary

The TUI should become a Norman Kernel client. It should submit work, stream
kernel events, display route/degraded/tool/model/shell state, and provide
operator controls. It should not own global model policy, run Codex as the
parent process, or decide when cloud escalation is justified.

The console CLIs feel more persistent today because tmux and the interactive
shell own continuity. The web TUIs stop short more often because they wrap a
bounded prompt execution. Kernel-backed TUIs should make web and console
behavior converge.

## Current TUI State

Implemented today:

- Shared web TUI template in `scripts/agent_console_template/agent_console_web.py`.
- Local-first routing for safe self-contained tasks.
- Norllama autosense via `https://llm.home.arpa` and fallback front doors.
- Bounded Norllama planner preflight for cloud/tool turns.
- Audit event mirroring to the console-runtime feed.
- Structured rendering for planner, behavior, model, and tool runtime events.
- Deployment sync tooling with UI version parity checks.

Current limitations:

- The default mental model is still "TUI wraps Codex."
- Local-first is a TUI-local routing optimization, not kernel policy.
- Long work is still mostly one bounded web turn plus optional continuation.
- Codex auth/update/route failures are TUI/runtime issues rather than one
  adapter lane under a common kernel.
- Shell/session continuity is not yet a kernel primitive.
- Degraded/offline mode is visible in pieces but not centrally authoritative.

## Target TUI Contract

The TUI should talk to the kernel through a small console protocol:

- create or resume a session
- submit a turn
- stream events
- approve/reject holds
- interrupt/cancel/resume work
- upload/reference attachments
- read mode and capability status

The TUI display should be a projection of kernel events, not a separate source
of truth.

## TUI Backend Modes

Add explicit backend modes:

- `codex_direct`
  - current compatibility path
  - Codex remains parent runner
  - local-first/preflight behavior remains until migration
- `kernel`
  - prompt becomes a kernel turn/job
  - all model/tool/shell behavior streams from Norman runtime events
  - Codex, Norllama, shell, and cloud are adapters behind the kernel
- `kernel_shadow`
  - Codex direct still executes
  - TUI also creates/mirrors a kernel job for event parity and diagnostics
  - useful for rollout
- `control_only`
  - no model execution
  - TUI queues work and displays recovery/state

Environment shape:

```text
NORMAN_TUI_BACKEND=codex_direct|kernel_shadow|kernel|control_only
NORMAN_CODEX_DISABLED=0|1
NORMAN_CLOUD_LLM_DISABLED=0|1
NORMAN_CONSOLE_RUNTIME_API_BASE=https://norman.home.arpa/api/v1
NORMAN_CONSOLE_RUNTIME_JOB_ID=<job-id>
NORMAN_LOCAL_LLM_FRONTDOORS=https://llm.home.arpa
```

## Kernel Client Flow

### Session Start

1. TUI loads local config.
2. TUI resolves Norman runtime token via env or Norman Keys.
3. TUI calls `GET /console-runtime/capabilities`.
4. TUI calls `POST /console-runtime/sessions` or resumes the last session.
5. TUI starts SSE stream for session/job events.
6. TUI renders mode, model availability, worker status, and degraded notices.

### Prompt Submit

1. User submits prompt and attachments.
2. TUI sends a kernel turn:

```json
{
  "input_text": "user prompt",
  "attachments": [],
  "requested_runtime": "auto",
  "requested_model": "",
  "route_lock": false,
  "operator_preferences": {
    "budget": "deep",
    "service_tier": "auto"
  }
}
```

3. Kernel emits:
   - `turn.received`
   - `turn.normalized`
   - `policy.mode_selected`
   - `route.decided`
4. Worker advances the job.
5. TUI renders ongoing model/tool/shell/planner output from the event stream.

### Completion

Kernel emits one of:

- `job.completed`
- `job.checkpointed`
- `job.approval_required`
- `job.blocked`
- `job.failed`
- `job.canceled`

The TUI final answer should be derived from kernel completion/finalizer events.

## Event Rendering Requirements

The TUI should display these without guessing:

- active mode
- selected runtime/adapter
- selected model
- local vs cloud
- cost basis
- cloud escalation reason
- planner/scout/filter receipts
- model deltas
- tool calls
- shell commands and output
- approval holds
- checkpoint summaries
- verification result
- degraded/offline notices
- queue/worker state

The rendering already has a runtime activity insight area. It should be expanded
to support the new event categories.

## Behavior Stream

The behavior stream should show what Norman is doing, not just text output.

Examples:

```text
#11 policy.mode_selected cloud_llm_offline: cloud LLM providers blocked
#12 route.decided planner -> norllama/openfugu-conductor local
#13 planner.receipt local scout found repo-only task
#14 shell.started rg --files docs app scripts tests
#15 shell.output 48 matching files
#16 model.requested norllama gemma4:26b-a4b-it-q4_K_M
#17 checkpoint.written docs inspected; next step is policy module
```

This addresses the user's concern that the TUI should see behavior and tool
calls "streaming the behavior kind of." The stream should be a first-class
operator surface.

## Degraded-Mode UX

The TUI should show degraded state at three levels:

- banner: current mode and what is unavailable
- per-turn route note: why this turn used local/cloud/control-only
- event feed: exact policy/egress decision

Required notices:

- `Cloud LLMs disabled`: local models/tools/web may still be available.
- `Codex quarantined`: shell/Norllama paths may still work.
- `LAN only`: internet egress blocked; local mesh may work.
- `Airgap local`: no internet; only local/LAN capabilities.
- `Control only`: no inference; prompts are queued and checkpointed.
- `Local model degraded`: model may be weaker; risky mutations need explicit
  approval.

No silent fallback is allowed.

## Approval UX

The TUI should render approval holds from kernel state:

- reason
- requested action
- command/tool/model/provider involved
- current mode
- risk notes
- exact approve/reject controls
- confirmation phrase when live execution is required

Existing runtime approval endpoints can be used first.

## Interrupt And Resume

Minimum operator controls:

- stop current step
- cancel job
- checkpoint now
- resume from checkpoint
- switch to control-only
- retry local route
- allow one cloud escalation
- quarantine Codex for this TUI

The kernel must record every interrupt/control action as an event.

## Attachments And Artifacts

First slice:

- keep existing TUI attachment saving behavior
- pass attachment refs into the kernel turn metadata
- emit `artifact.added` events for saved files

Later:

- move attachment indexing and artifact retention into kernel-owned storage
- give Norllama OCR/STT/embed/rerank lanes explicit artifact refs

## Migration Plan

### Stage 1: Shadow Kernel Feed

Keep Codex direct execution, but make every TUI create or use a kernel stream
job.

Work:

- continue mirroring audit events
- add route/policy/degraded events to mirrored feed
- show kernel event stream in all TUIs
- compare direct-TUI status with kernel stream status

Exit:

- No loss of current Codex behavior.
- TUI can show policy and tool events from Norman.

### Stage 2: Kernel Backend For Read-Only/Safe Tasks

Use kernel execution for safe self-contained tasks:

- summaries
- classification
- extraction
- rewrite
- route planning
- log review
- repo inspection without mutation

Exit:

- Codex disabled does not prevent the TUI from answering safe local tasks.
- Local route decisions are centralized in kernel policy.

### Stage 3: Kernel Shell Runner

Use kernel shell adapter for bounded shell work:

- file search
- read-only inspection
- tests
- diagnostics
- controlled edits after approval

Exit:

- Shell output streams through kernel events.
- Command policy applies before execution.

### Stage 4: Codex As Adapter

Move Codex execution under kernel:

- Codex health/auth/version is adapter status
- Codex JSON events are normalized
- Codex can be quarantined without killing TUI

Exit:

- A TUI can choose `kernel` backend and still use Codex when allowed.
- Same TUI can operate without Codex when blocked.

### Stage 5: Default Kernel Backend

Switch selected TUIs to kernel by default.

Exit:

- release notes posted
- estate status reports backend mode
- rollback to `codex_direct` is tested

## TUI Implementation Surfaces

Primary files:

- `scripts/agent_console_template/agent_console_web.py`
- `scripts/agent_console_template/agent_console_launch.sh`
- `scripts/sync_agent_console_template.py`
- `tests/test_agent_console_runtime_bridge.py`
- `tests/test_console_runtime_tui_source.py`

Likely changes:

- add backend-mode env parsing
- add kernel session/turn client functions
- add mode/capability status snapshot
- add route/policy event rendering
- add shell/checkpoint/verification rendering
- add degraded banner state
- add tests that source contains required kernel-client functions and UI text

## TUI Test Plan

Focused tests:

- `NORMAN_TUI_BACKEND=kernel` submits prompt as kernel turn.
- `NORMAN_TUI_BACKEND=control_only` queues prompt without model invocation.
- `NORMAN_CODEX_DISABLED=1` does not disable local/kernel safe tasks.
- `NORMAN_CLOUD_LLM_DISABLED=1` produces degraded notice and blocks cloud model
  selection.
- Runtime event snapshot includes route/policy/shell/checkpoint categories.
- TUI renders disconnected runtime bridge as degraded but still locally usable.
- Token/runtime status distinguishes local estimate from cloud cost.

Live smoke:

- deploy to one low-risk TUI
- submit a safe summary prompt
- submit a repo inspection prompt
- submit a mutating prompt and confirm approval hold
- disable Codex and confirm local/control behavior
- disable cloud LLMs and confirm Norllama route

## Acceptance Criteria

- Web TUI no longer stops at a single provider-shaped turn for kernel-backed
  work.
- TUI can display the kernel's behavior stream.
- TUI can operate in Codex quarantine.
- TUI can operate when cloud LLMs are disabled.
- TUI makes degraded state obvious.
- TUI can stream shell/tool/model activity from DB events.
- Existing Codex direct behavior remains available as rollback.
