# Norman

[![CI](https://github.com/KristopherKubicki/norman/actions/workflows/ci_cd.yml/badge.svg)](https://github.com/KristopherKubicki/norman/actions/workflows/ci_cd.yml)
[![Codecov](https://codecov.io/gh/KristopherKubicki/norman/branch/main/graph/badge.svg)](https://codecov.io/gh/KristopherKubicki/norman)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/KristopherKubicki/norman/badge)](https://securityscorecards.dev/viewer/?uri=github.com/KristopherKubicki/norman)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)
[![GitHub release](https://img.shields.io/github/v/release/KristopherKubicki/norman.svg)](https://github.com/KristopherKubicki/norman/releases)

Norman is an operator control plane for AI-assisted work. It accepts work from
web and terminal TUIs, CLI tools, BBS/SMS, connectors, schedules, and APIs;
applies policy and human approval boundaries; then coordinates models, tools,
shell runners, and durable background jobs.

It is no longer a single-provider chatbot. OpenAI support and an
OpenAI-compatible facade remain available, but they are optional provider
lanes. Norman can use Norllama-hosted local models and specialist services,
Bedrock, compatible cloud providers, Codex through an adapter or gateway, and
deterministic tools. Provider choice is policy-backed and observable rather
than a client-side assumption.

## What Norman Owns

- Durable Console Runtime jobs, leases, checkpoints, event streams, and SSE.
- Operator-facing TUIs, CLI/runtime bridges, BBS/SMS, connectors, and APIs.
- Route, egress, cost, safety, command, and approval policy.
- Model and tool adapter selection, provider-independent receipts, and
  degraded-mode handling.
- KPI reporting and the bounded, local-first Kaizen control loop.
- Persistence, audit history, identity boundaries, and operator workflows.

Norllama is Norman's inference and capability gateway today. It presents a
local-first mesh behind a stable front door and can serve text, code, planning,
OCR, transcription, embeddings, reranking, safety, and other specialist
lanes. Its extraction into an independent repository is planned, but it is not
a separate live repository yet. See the
[Norllama Repository Plan](docs/norllama_repository_plan.md).

## System Model

```text
Operators, TUIs, CLI, BBS/SMS, connectors, schedules, APIs
                         |
                         v
                  Norman Control Plane
      policy, approvals, jobs, events, persistence, reporting
                         |
                         v
                 Console Runtime / Kernel
    plan -> run -> verify -> checkpoint -> resume or await approval
                         |
                         v
             Norllama Gateway And Capability Mesh
     local models, specialist lanes, health, residency, failover
                         |
                         v
  deterministic tools | local services | policy-approved cloud providers
```

Norman owns the work and its safety boundaries. Providers execute bounded
steps; they do not independently approve commands, deployments, external
actions, or secret access.

## Model And Tool Routing

Routing starts with task type, risk, required capabilities, residency, current
operating mode, egress policy, and budget. The default direction is:

1. Apply safety, approval, and egress policy.
2. Use a deterministic tool when it can answer the request.
3. Use a suitable local Norllama model or specialist lane.
4. Wait, prefetch, or fail over within the local mesh when appropriate.
5. Escalate to a cloud provider only when the policy permits it and the route
   receipt explains why.

Every meaningful route should produce evidence of the chosen lane, model,
endpoint class, fallback decision, and policy context. Direct Ollama access is
for diagnostics, not the Norman application contract.

OpenAI is therefore one possible cloud lane, not a required installation
choice. A local-only deployment can use the Norllama front door without an
OpenAI key. A cloud-enabled deployment should configure only the approved
provider credentials through its secret broker and policy.

### Zero-Model TUI Reads

The web TUI has a deliberately narrow no-model lane for exact state reads and
fixed read-only commands. Exact status prompts can report durable TUI state.
The command form is either a command wrapped in backticks, such as `` `pwd` ``,
or `run pwd`. It is limited to `pwd`, `date`, `date -Is`,
`git status --short`, `git branch --show-current`, `git diff --stat`, and
`git log -1 --oneline`.

These commands execute as fixed argv with `shell=False` and a short timeout;
there is no natural-language shell interpretation. Attachments, route locks,
and an active prompt disable this lane. Writes, deploys, secret access,
network/external actions, and every command outside the allowlist return to
the normal policy, approval, and model-routing flow. Zero-model receipts carry
zero tokens and record the avoided local and frontier calls in the KPI ledger.

For the complete operating model, see
[Architecture](docs/architecture.md) and
[Provider And Routing Resilience](docs/llm_runtime_fallback.md).

## Human Control And Kaizen

The Console Runtime retains the human in the loop. A model suggestion does not
grant authority to write files, run a mutating command, deploy, contact an
external system, or access a secret. Those actions remain behind the existing
policy and approval path.

Kaizen is intentionally narrow. It can collect deterministic KPI evidence and
produce local-model shadow candidates only when explicitly enabled. The default
configuration disables it, sets a zero Norllama token budget, sends no
notifications, and permits no target edits or automatic actions. Proposed
runbook, skill, and MCP documentation changes require human review and an
ordinary approved runtime job before they can take effect.

Read [Norllama Kaizen And KPI Control Loop](docs/norllama_kaizen_control_loop_plan.md)
for the authority model, admission gates, reporting contract, and rollout
stages.

## Quick Start

Use the distribution configuration as a starting point, then configure the
database, authentication, connectors, and only the model lanes required for
the environment. Do not commit credentials or place provider tokens in the
repository.

```bash
git clone https://github.com/KristopherKubicki/norman.git
cd norman
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp config.yaml.dist config.yaml
uvicorn main:app --host 0.0.0.0 --port 8000
```

The service exposes API documentation at `http://localhost:8000/docs` and a
health endpoint at `http://localhost:8000/health`. Start with
[Deployment](docs/deployment.md) for service deployment and route setup.

The Console Runtime worker is disabled and dry-run by default. The Kaizen
broker is also disabled by default. Enable either only after the relevant
policy, service account, resource limits, and approval workflow are in place.

## Documentation

- [Documentation Index](docs/index.md) - current operating and design docs.
- [Architecture](docs/architecture.md) - ownership, control flow, approvals,
  routing, and observability.
- [Provider And Routing Resilience](docs/llm_runtime_fallback.md) - operating
  modes, local-first order, egress, and route receipts.
- [Norllama Repository Plan](docs/norllama_repository_plan.md) - contract-first
  path to an independent Norllama repository.
- [Norman Kernel Program](docs/norman_kernel_program.md) - durable work model
  and the TUI migration program.
- [Norllama Router Guidance](docs/norllama_router_guidance.md) - front door,
  mesh, warm-policy, and route-attribution guidance.
- [Deployment](docs/deployment.md) - production units, gateways, host pressure
  guard, and operational rollback.
- [Changelog](CHANGELOG.md) - current documentation and release-direction
  notes.

## Development

Run the repository checks before submitting code changes:

```bash
make format
make lint
make test
```

When changing `frontend/`, also run:

```bash
npm test
```

See [Contributing](CONTRIBUTING.md) for contribution guidance and
[License](LICENSE.md) for licensing.
