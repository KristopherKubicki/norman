# Norman Kernel Deployment And Test Plan

Date: 2026-07-05
Status: implementation planning
Audience: release, estate, QA, and operator maintainers

## Summary

The Norman Kernel rollout should be staged. The goal is not to flip every TUI at
once. The goal is to prove that kernel-backed TUIs can work without Codex,
without cloud LLMs, and with clear event streams before expanding the release.

## Release Principles

- Start with docs and tests.
- Ship kernel-compatible behavior behind flags.
- Keep Codex direct as rollback until kernel backend is proven.
- Prefer shadow mode before default kernel execution.
- Use Norman's DB event stream as the audit source.
- Use BBS posts to coordinate changes across TUIs and operators.
- Never hide degraded/offline mode from the operator.

## Feature Flags

Recommended flags:

```text
NORMAN_TUI_BACKEND=codex_direct|kernel_shadow|kernel|control_only
NORMAN_CODEX_DISABLED=0|1
NORMAN_CLOUD_LLM_DISABLED=0|1
NORMAN_THIRD_PARTY_EGRESS_DISABLED=0|1
NORMAN_NETWORK_MODE=internet_ok|web_only_no_cloud_llm|lan_only|airgap
NORMAN_CONSOLE_RUNTIME_WORKER_ENABLED=0|1
NORMAN_CONSOLE_RUNTIME_WORKER_DRY_RUN=1|0
NORMAN_CONSOLE_RUNTIME_WORKER_LIVE_EXECUTION_ENABLED=0|1
NORMAN_LOCAL_LLM_FRONTDOORS=https://llm.home.arpa
NORMAN_LOCAL_LLM_AUTOSENSE_ENABLED=1
```

Safety default:

- `codex_direct` remains default until tests and smoke pass.
- kernel worker remains dry-run unless live execution is explicitly confirmed.
- cloud LLM blocking wins over runtime preferences.

## Rollout Stages

### Stage 0: Planning Docs

Deliverables:

- kernel program doc
- runtime deep dive
- TUI deep dive
- model/policy deep dive
- deployment/test plan
- doc index updated

Tests:

- no runtime tests required for docs-only change
- inspect markdown links and file presence

### Stage 1: Kernel Event Compatibility

Scope:

- add new event categories
- add route/policy event helpers
- keep old snapshots compatible

Tests:

- `pytest tests/test_console_runtime_kernel.py`
- `pytest tests/test_console_runtime_store.py`
- `pytest tests/test_console_runtime_api.py`
- `pytest tests/test_agent_console_runtime_bridge.py`

Acceptance:

- old TUI runtime activity still renders
- new event categories appear in snapshots
- SSE remains ordered and cursorable

### Stage 2: Policy And Mode Engine

Scope:

- add mode axes
- add egress classification
- add route allow/deny decisions
- add degraded notices

Tests:

- `pytest tests/test_console_runtime_policy.py`
- focused TUI tests for degraded notices
- Norllama routing tests

Acceptance:

- cloud LLM blocking is enforced centrally
- Codex quarantine is enforced centrally
- web research can be allowed while cloud LLMs are blocked
- LAN Norllama remains available in restricted modes

### Stage 3: Kernel Shadow TUI

Scope:

- TUIs keep direct Codex execution
- TUIs create/mirror kernel jobs/events
- route/policy/degraded notices are visible

Targets:

- one low-risk Norman local TUI
- one toy-box TUI after local smoke

Tests:

- TUI source tests
- bridge tests
- live smoke prompt
- live runtime event stream check

Acceptance:

- no regression in current prompt flow
- kernel event stream captures behavior
- operator can see mode and route decisions

### Stage 4: Kernel Safe-Task Execution

Scope:

- route safe self-contained tasks through kernel
- use Norllama local models for summaries/classification/extraction/rewrite
- keep mutating/tool-heavy work on existing path unless explicitly enabled

Tests:

- Codex disabled safe task smoke
- cloud LLM disabled safe task smoke
- local model unhealthy fallback
- control-only queue behavior

Acceptance:

- a TUI can answer safe local tasks without Codex
- a TUI can answer safe local tasks without cloud LLMs
- failures create clear degraded notices

### Stage 5: Shell Runner

Scope:

- bounded shell adapter
- command policy
- shell event streaming
- approval holds for mutation

Tests:

- shell adapter unit tests
- command policy integration tests
- worker approval tests
- live read-only shell smoke
- live mutating command approval smoke

Acceptance:

- shell output appears in TUI runtime stream
- unsafe commands hold for approval
- kernel can do read-only repo inspection without Codex

### Stage 6: Codex As Kernel Adapter

Scope:

- Codex moves behind kernel adapter
- Codex auth/version/CLI failures are runtime adapter events
- Codex quarantine does not kill the TUI

Tests:

- Codex adapter unit tests with fake process output
- route policy tests
- TUI backend tests
- live smoke with Codex enabled
- live smoke with Codex disabled

Acceptance:

- kernel backend can use Codex when allowed
- kernel backend can avoid Codex when blocked
- operator sees exact adapter state

### Stage 7: Wider Estate Rollout

Scope:

- expand to more TUIs
- update release notes
- BBS info post
- estate status reports backend mode

Targets:

- Norman host
- networking host
- Hal test console
- selected toy-box consoles
- broader toy-box only after soak

Acceptance:

- release can be rolled back per TUI
- event stream is healthy
- operator notices are visible
- no unexpected cloud spend spike

## Test Matrix

| Scenario | Expected result |
| --- | --- |
| Codex available, cloud allowed | kernel may use Codex or cloud with receipt |
| Codex disabled, cloud allowed | kernel uses Norllama/shell/cloud adapter, not Codex CLI |
| Codex disabled, cloud LLM disabled | kernel uses Norllama/local/shell/control-only |
| cloud LLM disabled, web allowed | web research can run, cloud model calls blocked |
| LAN only | `llm.home.arpa` allowed, public internet blocked |
| no local model, cloud allowed | cloud escalation allowed only with receipt |
| no local model, cloud blocked | control-only or queue |
| mutating shell command | approval hold unless explicitly authorized |
| long job | checkpoint and continue, not one bounded turn |
| worker restart | job remains in DB and can resume/checkpoint |
| TUI refresh | event stream resumes from cursor |

## Automated Test Sets

Focused while building:

```bash
pytest tests/test_console_runtime_kernel.py
pytest tests/test_console_runtime_store.py
pytest tests/test_console_runtime_api.py
pytest tests/test_console_runtime_worker.py
pytest tests/test_console_runtime_supervisor.py
pytest tests/test_agent_console_runtime_bridge.py
pytest tests/test_norllama_routing.py
pytest tests/test_norllama_proxy.py
```

Required before release:

```bash
make format
make lint
make test
```

Also run if `frontend/` changes:

```bash
npm test
```

## Live Smoke Checklist

### Norman Runtime

- `GET /api/v1/console-runtime/worker/status`
- create a dry-run job
- append route/policy/planner events
- stream `/events/stream`
- approve/reject test hold
- confirm DB event count increments

### Norllama

- `GET https://llm.home.arpa/api/version`
- `GET https://llm.home.arpa/v1/capabilities`
- confirm peer failover metadata
- confirm P0 model catalog
- confirm direct Ollama is not public

### TUI

- open target TUI
- confirm UI version
- confirm backend mode
- submit safe summary prompt
- submit read-only repo inspection prompt
- submit mutating prompt and confirm approval hold
- disable Codex and retry safe prompt
- disable cloud LLMs and retry safe prompt
- confirm degraded notices

## BBS Coordination

Before expanding rollout, post an information-only BBS notice with:

- release name
- affected TUIs
- backend mode
- current flags
- known degraded/offline behavior
- rollback command or env change
- testing requested
- where runtime events can be viewed

Suggested thread id:

```text
th_norman_kernel_tui_rollout_20260705
```

## Rollback

Per TUI rollback:

```text
NORMAN_TUI_BACKEND=codex_direct
NORMAN_CODEX_DISABLED=0
NORMAN_CLOUD_LLM_DISABLED=0
```

Runtime worker rollback:

```text
NORMAN_CONSOLE_RUNTIME_WORKER_ENABLED=0
NORMAN_CONSOLE_RUNTIME_WORKER_DRY_RUN=1
```

Local model route rollback:

```text
NORMAN_CODEX_LOCAL_FIRST_ENABLED=0
NORMAN_LOCAL_PLANNER_PREFLIGHT_ENABLED=0
```

Rollback criteria:

- TUI cannot submit prompts
- runtime event stream breaks common TUI display
- policy incorrectly allows blocked cloud LLM egress
- shell adapter bypasses approval
- local-first route causes repeated wrong or stalled answers

## Release Notes Checklist

Include:

- kernel backend status
- TUI backend flags
- Norllama model defaults
- degraded/offline mode behavior
- test commands and results
- live smoke results
- known limitations
- rollback path

## Acceptance Criteria

The rollout is releasable when:

- docs are complete
- unit tests pass for changed areas
- one test TUI runs in kernel shadow
- one test TUI runs safe tasks in kernel backend
- Codex-disabled smoke passes
- cloud-LLM-disabled smoke passes
- TUI behavior stream shows model/tool/shell/policy events
- rollback is tested
