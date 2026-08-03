# Norman Philosophy

Norman is an operator control plane for AI-assisted work. It coordinates
people, tools, models, and durable jobs without treating any model provider or
automation as the system of record.

## Operator Control

The operator owns intent, authority, and the final decision. Norman can gather
evidence, prepare plans, run bounded work, and propose a next action. It does
not turn a suggestion into permission to modify systems, send a message,
deploy, spend money, or access a secret.

Approval boundaries should be explicit, reviewable, and durable. A useful
automation makes it clear what it wants to do, why it is safe enough to
consider, and how the operator can approve, reject, pause, or recover it.

## Local First, Provider Neutral

Norman starts with deterministic tools and local capability when they satisfy
the task. Norllama provides the current local-first inference and specialist
capability front door; cloud providers, including OpenAI-compatible services,
remain optional, policy-governed lanes.

The application contract belongs to Norman, not to a provider SDK or a direct
model endpoint. Route selection considers task capability, risk, residency,
egress policy, latency, health, and budget. Route receipts make material
selection and fallback decisions inspectable.

## Durable Work

Important work must survive a disconnected TUI, a restarted worker, a failed
model call, or a temporary provider outage. Norman represents work as durable
jobs with plans, leases, checkpoints, events, and recoverable state.

Interactive surfaces are clients of that runtime. They should be able to show
progress, request approval, interrupt work, and reconnect without becoming the
only place that knows what is happening.

## Evidence And Observability

The system should earn trust with evidence rather than confident prose. Each
meaningful job should leave enough context to explain its inputs, policy
decision, route, actions, results, costs, failures, and next recovery step.

Operational health includes host pressure, queue health, route degradation,
budget consumption, and outcome quality. Measurements are used to improve the
system and to tell an operator when intervention is needed.

## Bounded Continuous Improvement

Kaizen is a cautious operating loop, not an autonomous rewrite engine. When
enabled, it can collect deterministic KPI evidence, produce local-model shadow
candidates, and prepare reports or narrowly scoped changes for review.

It starts disabled, has a zero model budget, sends no notifications, and makes
no target edits. Any proposed runbook, skill, MCP, policy, or code change
remains subject to ordinary review, approved runtime execution, and repository
controls. The loop should prefer the smallest reversible change with a clear
success measure.

## Open Development

Norman is open source because the control plane, policy boundaries, and
operational evidence must be inspectable by the people who rely on them.
Contributions should preserve those properties: document behavior accurately,
test shared contracts, avoid silent authority expansion, and leave a practical
rollback path.

The project welcomes improvements that make real operator work clearer, safer,
more reliable, or easier to recover. Current operating guidance lives in the
[documentation index](index.md); design and release records identify their
status so they are not mistaken for current runbooks.
