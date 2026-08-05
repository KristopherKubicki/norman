# Norman Architecture

Norman is an operator control plane for AI-assisted work. It accepts work from
people and systems, records it as durable work, applies safety and approval
policy, and selects bounded providers or tools to execute each step.

The prior connector-and-chatbot view is still part of Norman, but it is no
longer the architectural center. Connectors are inputs and outputs to the
control plane; OpenAI is one provider lane, not the system definition.

## Design Rules

1. Norman owns work, policy, and operator state. Providers execute bounded
   steps.
2. A provider route never grants authority to make a change or access a secret.
3. Local and deterministic paths are preferred when they are adequate and
   permitted.
4. Cloud use is explicit, policy-gated, and attributable.
5. Durable work survives a browser refresh, provider failure, or worker lease
   handoff through jobs, checkpoints, and event history.
6. Degraded operation is a visible state, not a silent quality or safety
   change.

## System Map

```text
Operator And Client Surfaces
  Web TUIs | terminal TUIs | CLI | BBS/SMS | API | connectors | schedulers
                                      |
                                      v
Norman Control Plane
  FastAPI | authentication | estate/realm boundaries | persistence
  BBS/SMS and connector adapters | operator workflows | reporting
                                      |
                                      v
Console Runtime / Kernel
  jobs | workstreams | worker leases | checkpoints | ordered events | SSE
  planner/worker/verifier progression | approvals | shell supervision
  route, egress, cost, and degraded-mode policy
                                      |
                    +-----------------+-----------------+
                    |                                   |
                    v                                   v
         Deterministic And Shell Tools           Norllama Gateway / Mesh
         policy-gated commands, tests,           capability inventory, local
         repositories, service adapters          routing, residency, health,
                                                  failover, specialist lanes
                                                            |
                                                            v
                                                Local And Cloud Execution
                                                local models | OCR | ASR/STT
                                                embeddings | rerank | safety
                                                Bedrock | OpenAI-compatible
                                                Codex adapters | other tools
```

## Ownership Boundaries

| Area | Norman Owns | Norllama Owns |
| --- | --- | --- |
| Operator work | Job state, workflows, approvals, audit, and UI state | Nothing |
| Policy | Authority, egress, cost posture, approval, and route constraints | Enforcing accepted route constraints |
| Inference | Selecting a permitted capability for a runtime step | Routing across local lanes and permitted proxies |
| Local mesh | Recording route evidence in runtime history | Health, model inventory, peer selection, and residency |
| Provider APIs | Adapter lifecycle and user-visible outcomes | OpenAI/Ollama-compatible inference gateway behavior |
| Proactive work | KPI definitions, candidate lifecycle, and approval handoff | Bounded local analysis when admitted |

Norllama is currently implemented inside this repository, principally under
`scripts/norllama/` and `app/services/norllama/`. It has enough independent
runtime behavior to become its own repository, but Norman remains the owner of
the operator control plane. The separation must be contract-first; see
[Norllama Repository Plan](norllama_repository_plan.md).

## Work Flow

1. A TUI, CLI, BBS message, connector, API caller, or scheduler creates or
   updates a work request.
2. Norman classifies the request's source, realm, risk, required artifacts,
   budget, and completion criteria.
3. The Console Runtime creates a durable job or workstream and records ordered
   events. A worker leases only work it is eligible to execute.
4. Policy applies hard safety and approval blocks, operating mode, egress
   rules, and provider constraints before an action is attempted.
5. The worker uses a deterministic tool where possible. When inference is
   needed, it asks Norllama for a permitted local capability or route.
6. Norllama returns route and invocation evidence. A cloud route requires
   explicit authorization and is still subject to Norman policy.
7. The worker stores outputs, checkpoints, verification evidence, and a final
   result. It waits for approval instead of performing a blocked effect.
8. Clients observe progress through the runtime event stream and resume from
   durable state rather than owning hidden work in a browser process.

## Human Approval Boundary

The system is not autonomous merely because work can be scheduled or
proactively analyzed. The following remain controlled effects:

- Writing outside an approved workspace or applying a patch.
- Running mutating shell commands, changing services, or deploying.
- Sending a connector, BBS/SMS, email, or other external message.
- Requesting or using a secret lease.
- Changing a provider route, policy, MCP permission, credential, or endpoint.

Norman policy and the Console Runtime approval flow decide whether these steps
can proceed. A model may supply a draft, classification, evidence summary, or
verification input, but cannot bypass that boundary.

## Provider And Routing Model

Norman supports several provider classes:

- Deterministic local tools, including repository inspection and policy checks.
- Norllama local text, code, planning, and specialist capability lanes.
- Local mesh services for OCR, transcription, embeddings, reranking, and
  safety.
- Policy-approved cloud providers, including Bedrock, OpenAI-compatible
  endpoints, and Codex through an adapter or gateway.

The route order is safety and egress policy, deterministic work, local
Norllama capability, local mesh wait/prefetch/failover, then an explicitly
authorized cloud route. A route receipt records the selection, model or tool,
endpoint class, fallback outcome, and policy context.

### Deterministic TUI Read Lane

The web TUI may answer an exact status request from durable state without
calling a model. It may also execute one exact command from a small read-only
allowlist: `pwd`, `date`, `date -Is`, `git status --short`, `git branch
--show-current`, `git diff --stat`, and `git log -1 --oneline`. Commands are
parsed as fixed argv only, run with `shell=False`, and have a short timeout.

This is not a natural-language command interface. A route lock, attachment,
or active prompt disables the lane, as do unlisted or compound commands.
Mutations, deploys, secret access, network/external calls, and policy changes
remain governed by the Console Runtime approval path. Deterministic receipts
record zero tokens plus the avoided local and frontier calls so reporting can
separate actual inference from work answered without it.

For detailed modes, egress classes, and failure handling, see
[Provider And Routing Resilience](llm_runtime_fallback.md).

## Operating Modes

Runtime posture is represented by independent planes rather than one provider
flag:

| Plane | Examples |
| --- | --- |
| LLM | `cloud_ok`, `cloud_llm_offline`, `lan_local_only`, `no_inference` |
| Runner | `kernel_shell`, `codex_available`, `codex_quarantined`, `control_only` |
| Network | `internet_ok`, `web_only_no_cloud_llm`, `lan_only`, `airgap` |
| Tool | `full_tools`, `read_only_tools`, `deterministic_only`, `disabled` |
| Egress | `normal`, `cloud_llm_blocked`, `third_party_blocked`, `lan_only`, `deny_all` |

Named modes such as `local_first_online`, `cloud_llm_offline`, and
`control_only` are derived from those planes. This avoids pretending that a
cloud outage, a Codex quarantine, and a LAN-only deployment are the same
failure.

## Observability And Recovery

The architecture records enough state to answer what ran, why it was selected,
and what needs operator attention:

- Runtime events and SSE show planner, model, tool, shell, verification, and
  approval progress.
- Route receipts capture route selection, model/tool attribution, egress, and
  fallback information.
- Worker leases and checkpoints support resumption after a process or client
  failure.
- Health, capability, warm-policy, and mesh reports make local availability
  visible before a cloud escalation is attempted.
- KPI and Kaizen collectors use deterministic evidence first and have separate
  candidate and job lifecycles.

The Kaizen loop is disabled and observe-only by default. It must pass idle,
resource, evidence, realm, budget, and cooldown gates before it can request a
local analysis. It cannot independently change code, infrastructure, skills,
MCP permissions, or a user workflow. See
[Norllama Kaizen And KPI Control Loop](norllama_kaizen_control_loop_plan.md).

## Current Implementation And Direction

The Console Runtime, Norllama adapter, local routing, provider facade, route
receipts, worker controls, and Kaizen evidence/candidate foundations exist in
this repository. Some rollout paths remain explicitly disabled or staged:

- Continuous Console Runtime execution requires opt-in configuration and is
  dry-run by default.
- Kaizen reporting and shadow candidates require explicit opt-in and default
  to no model token budget, no notifications, and no edits.
- Not every legacy TUI is a full Console Runtime client yet.
- Norllama is still repository-owned code while the extraction contracts are
  being defined.

The active migration program is documented in
[Norman Kernel Program](norman_kernel_program.md), with current routing
guidance in [Norllama Router Guidance](norllama_router_guidance.md).
