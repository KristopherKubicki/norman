# Norllama Repository Plan

Date: 2026-08-03
Status: approved direction; contract-first extraction not yet started

## Decision

Norllama should become its own repository. It now has a distinct runtime
surface: an inference gateway, local mesh routing, capability and model
inventory, health, residency and prefetch policy, specialist lanes, and route
attribution. That lifecycle is different from Norman's operator control plane.

The extraction must be gradual. Norman and live TUIs depend on the current
behavior, so this is not a large code move or a synchronized rewrite. First
freeze versioned contracts, then make the Norman dependency directional, then
dual-run a standalone service before changing the production ownership.

Until the migration gates pass, the current implementation under
`scripts/norllama/` and `app/services/norllama/` remains the production source.

## Why Extract Now

- Norllama is more than an Ollama wrapper. It owns gateway and mesh behavior
  that other systems can use without Norman's UI or job database.
- Its gateway is a large, independently deployable service with its own health,
  model inventory, peer routing, compatibility APIs, and specialist services.
- Its release cadence, load tests, worker configuration, and hardware
  deployment differ from Norman's control-plane release cadence.
- Clear ownership prevents inference implementation details from leaking into
  operator policy, and prevents policy/UI changes from forcing gateway changes.

## Ownership After Extraction

| Area | Norman | Norllama |
| --- | --- | --- |
| Operator work | Jobs, workstreams, approvals, BBS/SMS, TUI state, persistence | No ownership |
| Authorization | Realm, egress, risk, budget, approval, cloud authorization | Validate supplied route authorization |
| Inference protocol | Runtime adapters and outcomes | Versioned gateway API and compatibility facades |
| Local routing | Send task constraints and consume receipts | Capability selection, failover, residency, execution |
| Specialist lanes | Request and audit capability use | Operate or proxy OCR, ASR/STT, embeddings, rerank, safety |
| Health and metrics | Control-plane and operator KPIs | Gateway, peer, model, prefetch, and route metrics |
| Deployment | Norman service and client configuration | Gateway releases, workers, mesh config, service operations |

Cloud-provider credentials remain subject to Norman's authorization and secret
policy. Norllama must not become an alternate path that bypasses those controls.

## Non-Goals

- Do not move Console Runtime, BBS/SMS, Kaizen, connector, approval, or
  persistence code into Norllama.
- Do not require every model provider to pass through Norllama on day one.
- Do not expose individual worker addresses as the client contract.
- Do not share Norman's database or import its application package from the
  new repository.
- Do not remove the current gateway until dual-run acceptance and rollback
  evidence exist.
- Do not use the extraction to relax egress, secret, or human-approval rules.

## Contract Set V1

The first deliverable is an independently testable protocol package or schema
repository. Contracts use explicit schema names, versions, validation tests,
fixtures, and compatibility rules. Existing `norman.norllama.*` schema names
remain accepted during migration; the new repository may publish neutral
`norllama.*` aliases only with a documented compatibility mapping.

| Contract | Required Content | Direction |
| --- | --- | --- |
| Capability snapshot | Version, capabilities, models, endpoint classes, tools, mesh health | Norllama -> clients |
| Task request | Task kind, bounded input or artifact refs, correlation IDs, constraints | Norman -> Norllama |
| Task receipt | Route, outcome, output refs, evidence, confidence, timing, error | Norllama -> Norman |
| Route receipt | Policy ID/hash, result, attempts, peer/model, fallback, egress | Norllama -> Norman |
| Route policy artifact | Versioned, integrity-protected authority and constraints with expiry | Norman -> Norllama |
| Warm policy and prefetch | Desired residency, priority, deadline, idempotency key, and result | Norman -> Norllama |
| Health and status | Liveness, readiness, workers, inventory age, saturation, degradation | Norllama -> operators |

The existing task receipt schema,
`norman.norllama.task-receipt.v1`, and route policy artifact schema,
`norman.norllama.route-policy.v1`, are the starting compatibility surfaces.
They need formal JSON schemas, example fixtures, and contract tests before the
service boundary moves.

### Contract Rules

- Every request carries a stable request or task ID and a caller correlation
  reference; retries are idempotent where the capability permits it.
- Receipts never contain credentials, raw secret values, or unbounded private
  transcripts.
- Route policy is data, not a Python import. Norllama validates its integrity,
  version, lifetime, and allowed constraints without importing `app.*`.
- A caller may request a capability or a constrained route, but Norllama may
  not silently broaden that request to a cloud route.
- New fields are additive. Removing or changing meaning requires a new major
  contract version and an overlap period.
- OpenAI- and Ollama-compatible endpoints remain compatibility facades. The
  Norllama contracts are the authoritative gateway protocol.

## Migration Phases

### Phase 0: Contract Freeze And Characterization

Document current request and response shapes, route headers, failure types,
health endpoints, warm/prefetch behavior, and specialist lane behavior. Add
golden fixtures and cross-process contract tests around the existing gateway.

Exit criteria:

- The V1 schemas and compatibility rules are reviewed.
- Existing Norman callers pass against a fixture-backed gateway.
- The actual route policy artifact is validated without hidden process state.
- Baseline latency, failover, and receipt completeness are measured.

### Phase 1: Standalone Repository And Release Surface

Create the `Norllama` repository with the gateway, protocol package, tests,
service definitions, container or deployable artifact, release notes, and
security scanning. Keep the current in-repository implementation authoritative.

Exit criteria:

- A pinned Norllama release can start outside the Norman checkout.
- It serves the V1 capability, health, inference, specialist, and receipt
  contracts in a non-production environment.
- CI runs unit, integration, compatibility, and artifact checks.

### Phase 2: Invert The Policy Dependency

Replace imports from `app.services.norllama.route_policy*` in gateway code with
the V1 route policy artifact and a narrow validator. Norman compiles and signs
or otherwise integrity-protects the artifact; Norllama receives and enforces
it as data.

Exit criteria:

- The standalone gateway has no runtime import of the Norman application.
- Invalid, expired, or unauthorized policy artifacts fail closed.
- Explicit degraded authorization remains bounded, auditable, and tested.

### Phase 3: Compatibility Client And Dual Run

Add a Norman client that speaks the versioned Norllama API. Mirror eligible
read-only local tasks to the standalone gateway, compare normalized receipts,
and keep the existing implementation as the serving route. Start with health,
capability inventory, prefetch, planning, summarization, rerank, and other
non-mutating lanes.

Exit criteria:

- Contract and receipt parity meets the agreed threshold.
- Mesh selection, health behavior, and failure semantics match documented
  behavior.
- No shadow task can cause an external effect or cloud escalation.
- Operators can attribute every result to the embedded or standalone path.

### Phase 4: Controlled Serving Cutover

Route a small opt-in client or realm to the standalone Norllama service through
the same logical front door. Keep an immediate configuration rollback to the
embedded implementation and validate capacity, warm behavior, failover, and
alerts under real workload.

Exit criteria:

- Canary and soak windows meet latency, error, receipt, and rollback targets.
- Normal and degraded modes are proven, including cloud-blocked and
  control-only behavior.
- No policy, approval, or secret-boundary regression is found.

### Phase 5: Ownership Transfer And Removal

Make a released Norllama version the supported runtime dependency. Convert
remaining Norman imports to the client and contract package, retain only
adapter and integration tests in Norman, then remove the in-repository gateway
after the agreed compatibility window.

Exit criteria:

- Norman deploys against a pinned, supported Norllama release.
- Norllama owns its release notes, service operations, and compatibility
  policy.
- The old implementation is removed only after rollback support and migration
  documentation are complete.

## Release, Security, And Rollback Gates

Every cutover phase requires all of the following:

- Version-pinned artifacts and a published compatibility matrix.
- Contract tests run from both repositories against the same fixtures.
- Health, readiness, route receipt, specialist lane, and failover checks.
- Negative tests for expired policy, invalid integrity data, cloud-blocked
  mode, missing capability, and secret redaction.
- A one-step rollback to the prior serving implementation or pinned release.
- Explicit operator sign-off for any change affecting egress, cloud proxying,
  deployment, or credentials.

Norllama service configuration must use normal secret and certificate
infrastructure. Contracts, logs, activity endpoints, and route receipts must
redact tokens, credentials, sensitive headers, and private prompt contents.

## Initial Work Queue

1. Publish V1 JSON schemas and fixtures for capabilities, task request,
   receipt, route receipt, route policy, prefetch, and health.
2. Add contract tests that run against the current in-repository gateway.
3. Extract route-policy validation into a dependency-free package.
4. Scaffold the standalone Norllama repository and CI without switching a
   production caller.
5. Build the Norman compatibility client and receipt comparator.

This sequence creates a safe boundary first. It postpones the disruptive file
move until the protocol, rollout evidence, and rollback path are real.
