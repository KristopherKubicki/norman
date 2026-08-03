# Norman Documentation

Norman is an operator control plane for AI-assisted work. These documents
describe the current control-plane, runtime, routing, and operator model.
Older design records remain useful context, but their status and date matter;
they are not all current operating instructions.

## Document Status

Unless a document is explicitly marked otherwise, the sections below identify
its intended use:

- **Current operating docs** define supported behavior, deployment, and
  operator procedures.
- **Direction and implementation docs** describe approved designs, migrations,
  or work in progress. They are not a substitute for an operating runbook.
- **Reference and history** records preserve dated decisions, investigations,
  and release context. Verify current behavior against the operating docs.

## Start Here

These are the current operating docs for an initial deployment or operator
orientation.

- [Root README](../README.md) - product scope, provider-neutral routing,
  human-control boundary, and local development start.
- [Architecture](architecture.md) - current system shape, ownership, work flow,
  operating modes, and observability.
- [Deployment](deployment.md) - production units, gateways, host-pressure
  safeguards, and rollback.
- [Provider And Routing Resilience](llm_runtime_fallback.md) - local-first
  route order, egress classes, failure handling, and receipts.

## Runtime And Operator Work

These documents describe the runtime design and migration work. Confirm live
deployment behavior against the current operating docs above.

- [Norman Kernel Program](norman_kernel_program.md) - durable work model and
  the migration from provider-shaped TUIs to kernel clients.
- [Norman Kernel Runtime Deep Dive](norman_kernel_runtime_deep_dive.md) -
  runtime contracts, event taxonomy, adapters, workers, and recovery.
- [Norman Kernel TUI Deep Dive](norman_kernel_tui_deep_dive.md) - TUI client
  behavior, event streaming, approval, degraded mode, and interrupts.
- [Norman Kernel Deployment And Test Plan](norman_kernel_deployment_test_plan.md) -
  staged rollout, smoke checks, BBS coordination, acceptance, and rollback.
- [TUI Operator Workflow Skill Spec](tui_operator_workflow_skill_spec.md) -
  operator and runtime workflow design.
- [Norman Chat](norman_chat.md) - product direction for the communication desk,
  not a current implementation guide.

## Routing, Local Models, And Kaizen

These documents define local-model routing direction, rollout work, and the
bounded improvement program. Follow deployment and policy controls before
enabling any optional capability.

- [Norllama Router Guidance](norllama_router_guidance.md) - front door, mesh,
  warm policy, route attribution, and reliability work.
- [Norman Kernel Model And Policy Deep Dive](norman_kernel_model_policy_deep_dive.md) -
  model selection, egress, cost, local capability, and cloud escalation policy.
- [Norllama Kaizen And KPI Control Loop](norllama_kaizen_control_loop_plan.md) -
  proactive reporting, bounded idle work, candidate lifecycle, and approvals.
- [Norllama Repository Plan](norllama_repository_plan.md) - approved
  contract-first extraction direction for an independent inference gateway and
  mesh repository.
- [Local LLM Node](local_llm_node.md) - local node installation and route
  policy refresh operations.
- [Model Durability Plan](model_durability_plan.md) - earlier failure-mode and
  recovery design context.
- [Norllama Capability Execution Runner Handoff](norllama_capability_execution_runner_handoff.md) -
  specialist capability runner handoff.

## Operations, Security, And Estate

These documents define shared estate, access, and operational control
boundaries. Some plan documents retain work-in-progress status.

- [Estate Schema](estate_schema.md) - principals, bots, workers, services, and
  twin object model.
- [Fleet Charter](fleet_charter.md) - operator-first fleet definition and
  governance direction.
- [Naming Policy](naming_policy.md) - hostname, alias, and namespace rules.
- [Access Matrix](access_matrix.md) - client, lane, host, and bot reachability.
- [Bot-to-Bot ACL](bot_acl.md) - brokered and forbidden cross-bot paths.
- [Norman Keys](norman_keys.md) - secret-broker design and operator controls.
- [Norman Keys V1 Plan](norman_keys_v1_plan.md) - first rollout plan and
  implementation notes.
- [Private Enclave Plan](private_enclave.md) - confidential bot isolation
  model.
- [Private Auth Handoff](private_auth_handoff.md) - private-host sign-in
  boundary and remaining work.

## Integrations And Extension

These documents cover supported interfaces and extension direction. Connector
access still follows the deployment's policy and authentication controls.

- [Usage](usage.md) - deployment, Console Runtime, routing, approvals, and
  connector compatibility guidance.
- [Examples](examples.md) - authenticated runtime, route, and Kaizen API
  examples.
- [Connectors](connectors.md) - connector catalog and extension points.
- [Extending Norman](extending.md) - custom connector, action, and filter
  guidance.
- [Endless Perplexity V1](endless_perplexity_v1.md) - cited research and signal
  mining operating model.
- [Docker Deployment](docker.md) - containerized deployment reference.

## Reference And History

These records provide useful context but are not current runbooks unless their
own status says otherwise.

- [Changelog](../CHANGELOG.md) - current release-direction and documentation
  notes.
- [Philosophy](philosophy.md) - project principles.
- [Community](community.md) - project community information.
- [Contributing](../CONTRIBUTING.md) - contribution process.
- [Release Notes](releases/) - dated deployment and routing records.
- [Prompt Intermediary Roadmap](norman_prompt_intermediary_roadmap.md) -
  historical and transitional provider-facade roadmap.
- [Norllama Model Architecture Audit Handoff](norllama_model_architecture_audit_handoff.md) -
  dated model architecture investigation.
- [TUI Queue Resource Meter Decision](tui_queue_resource_meter_decision_2026-05-09.md) -
  dated TUI resource-management decision.
