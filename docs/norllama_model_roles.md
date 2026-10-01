# Norllama Model Roles

Norllama routing uses stable roles rather than model names:

- `resident`: local, reversible, low-risk work
- `economy`: inexpensive cloud escalation
- `authority`: consequential or exact work
- `frontier`: rare escalation after authority evidence

The signed registry in `config/norllama/model_roles.json` resolves each role to
the current evaluated model, provider, endpoint placement, aliases, and
transport flags. Routing code must not branch on a model version.

## Upgrade Process

1. Benchmark the candidate against the active model.
2. Update `config/norllama/model_roles.json`.
3. Generate and validate a new signed route-policy artifact.
4. Deploy the gateway bundle.
5. Run:

   ```bash
   scripts/norllama/verify_escalation_rollout.py \
     --insecure \
     --output evidence/norllama_escalation_acceptance_latest.json
   ```

The acceptance harness derives model IDs from the live signed policy. It checks
health, policy readiness, all four role decisions, the frontier fail-closed
gate, model discovery, and one visible resident-model inference.

## Retired Experimental Models

DeepSeek V4 Flash DSpark was retired from active serving on August 16, 2026.
Its benchmark evidence remains historical, but it is not selectable or probed
by default. The serving slot on `spark-150` now hosts the second resident-role
runtime.

Retirement evidence:

- Service: `spark-ds4-q2.service`, inactive through a clean-exit retirement shim
- Original server: `/home/kristopher/ds4/ds4-server.pre-retirement-20260816`
- Removed GGUF payloads:
  - `DeepSeek-V4-Flash-Layers37-42Q4KExperts-OtherExpertLayersIQ2XXSGateUp-Q2KDown-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix-fixed.gguf`
    - size: `97,591,747,456`
    - SHA-256: `edabc92af63ad8b139f00087fbfc10a4072f37b7597f4fd9ad1dfa6f83002396`
  - `DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix.gguf`
    - size: `86,720,111,488`
    - SHA-256: `efc7ed607ff27076e3e501fc3fefefa33c0ed8cf1eff483a2b7fdc0c2e616668`

Reactivation requires restoring a compatible GGUF by verified digest,
restoring the preserved server binary, explicitly enabling the DS4 backend,
and rerunning benchmark plus route-policy acceptance. Historical evidence alone
is not sufficient for reactivation.

## Gateway Policy Transition

The user-owned resident schedulers on ports `18161` run the signed
`registry-driven-v3` policy. The older root-managed Spark gateways on port
`18151` currently run the compatible `explicit-cloud-v1` policy, valid through
August 23, 2026. Their v3 artifact remains staged as `route_policy.next.json`.

Do not promote that staged artifact into `route_policy.json` until the
root-managed gateway binary is upgraded or restarted with v3 schema support.
The legacy gateways fail closed on an unsupported policy version; the resident
role is not dependent on those legacy processes.
