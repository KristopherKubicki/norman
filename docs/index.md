# Norman Documentation

Welcome to the Norman documentation! Here you'll find everything you need to know about setting up, using, and extending
Norman.

## Table of Contents

- [Usage](usage.md) - Learn how to set up and use Norman.
- [Examples](examples.md) - Step-by-step usage examples and API calls.
- [Deployment](deployment.md) - Instructions on how to deploy Norman on various platforms.
- [Docker Deployment](docker.md) - Containerized setup using Docker and docker-compose.
- [Extending Norman](extending.md) - A guide on how to extend Norman with new connectors, actions, and filters.
- [Architecture](architecture.md) - An explanation of Norman's architecture and design principles.
- [Estate Schema](estate_schema.md) - Concrete object model for principals, bots, workers, services, and the twin.
- [Fleet Charter](fleet_charter.md) - Operator-first definition of Norman, Prime, lanes, and governance direction.
- [Naming Policy](naming_policy.md) - Canonical hostname, alias, and namespace rules for work, internal, home, and site-specific surfaces.
- [Access Matrix](access_matrix.md) - Draft client, lane, host, and bot reachability model before networking hardening.
- [Bot-to-Bot ACL](bot_acl.md) - Direct, brokered, and forbidden cross-bot communication rules with Norman Prime as the default broker.
- [Private Enclave Plan](private_enclave.md) - Dedicated host and isolation model for finance, health, and other confidential bots.
- [Private Auth Handoff](private_auth_handoff.md) - Why remote private-bot browser sign-in is currently incomplete and how the private host should own the callback path.
- [Norman Keys](norman_keys.md) - Secret-broker design for approvals, leases, audit, and backend abstraction.
- [Norman Keys V1 Plan](norman_keys_v1_plan.md) - Concrete build plan for the first Norman Keys rollout.
- [Endless Perplexity V1](endless_perplexity_v1.md) - Perplexity-backed scout and signal-mining operating model for
  routing cited findings into Norman.
- [Norman Kernel Program](norman_kernel_program.md) - Kernel-first plan for making TUIs model-independent, offline-capable, and driven by a durable Norman execution layer.
- [Norman Kernel Runtime Deep Dive](norman_kernel_runtime_deep_dive.md) - Concrete runtime contracts, event taxonomy, adapters, shell execution plan, and worker sequencing for the kernel.
- [Norman Kernel TUI Deep Dive](norman_kernel_tui_deep_dive.md) - Plan for moving web TUIs and console CLIs from Codex wrappers to kernel clients with behavior streaming.
- [Norman Kernel Model And Policy Deep Dive](norman_kernel_model_policy_deep_dive.md) - Norllama-first model routing, offline modes, egress policy, cost control, and warm model guidance.
- [Norllama Router Guidance](norllama_router_guidance.md) - Current frontdoor/router shape, benchmark-backed model guidance, and reliability upgrades for local-first routing.
- [Norman Kernel Deployment And Test Plan](norman_kernel_deployment_test_plan.md) - Staged rollout, test matrix, live smoke checks, BBS coordination, and rollback.
- [Model Durability Plan](model_durability_plan.md) - Failure-mode, fallback, checkpoint, and offline-mode plan for keeping Norman usable when Codex/OpenAI is degraded or unavailable.
- [Philosophy](philosophy.md) - Learn about the philosophy behind Norman and our project goals.
- [Contributing](../contributing.md) - A guide on how to contribute to the Norman project.
- [Community](community.md) - Information about the Norman community and how to get involved.
- [Connectors](connectors.md) - An overview of the available connectors and how to use them.

## Getting Started

If you're new to Norman, we recommend starting with the [Usage](usage.md) guide to learn how to set up and use the
application. From there, you can explore the other sections of the documentation to learn more about Norman's features
and how to extend its capabilities.
