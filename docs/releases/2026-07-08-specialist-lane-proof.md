# Specialist Lane Proof Pass

Norman now turns the SpecialistLane registry into request-visible proof instead
of only declared intent.

## Added

- `norman.norllama.specialist-proof.v1` lane proof payloads.
- Warm-policy-backed proof for specialist lanes using Uplink benchmark evidence,
  route guardrail lanes, selected models, and target workers.
- Route-receipt fallback proof when global warm-policy evidence is unavailable.
- Cascade fields for `proof_state`, `live_smoke_test`, lane route mapping, and
  lane-specific benchmark evidence.
- Local-first proof counters for specialist smoke status, proof state,
  benchmark-fresh lanes, and production-ready lanes.
- Capabilities payload exposure so TUIs can see specialist proof readiness.

## Validation

- Specialist proof resolver tests.
- Norllama route receipt cascade tests.
- Console runtime capabilities proof exposure tests.
