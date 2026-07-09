# Specialist Lane Registry And Route Receipts

Date: 2026-07-08
Scope: Norman console runtime, Norllama route receipts, local-first proof
Status: deployed to `norman.home.arpa`

## Summary

Norman route receipts now carry a `specialist_cascade` that shows which local
specialist lanes and deterministic experts are required, available, skipped,
pending, passed, or failed for a run.

## Changes

- Added the `norman.norllama.specialist-lanes.v1` registry.
- Added production lane contracts for:
  - `receipt_auditor`
  - `tool_call_risk_classifier`
  - `difficulty_estimator`
  - `regret_predictor`
  - `browser_trace_compressor`
  - `screenshot_state_classifier`
  - `non_answer_detector`
  - `patch_blast_radius_estimator`
  - `memory_write_gate`
  - `local_hallucination_firewall`
- Added deterministic experts to the same cascade:
  `codeql`, `semgrep`, `gitleaks`, `trufflehog`, `syft`, `grype`,
  `osv_scanner`, `xgrammar`, `pytest`, `mypy`, and `ruff`.
- Kept Qwen3.6/Qwen3.5-class as the floor for general reasoning, coding, and
  VLM lanes.
- Route receipts now include specialist lane state, schema requirements,
  benchmark requirements, worker attribution, and local/cloud/search usage
  buckets.
- Console runtime local-first proof now aggregates specialist required/evidence
  counts, lane status counts, and deterministic expert attribution.
- Norllama adapter receipts now include real response text and usage so
  `non_answer_detector`, receipt auditing, difficulty, and regret checks can
  run against completed output.

## Verification

- `make format`
- `make lint`
- Focused specialist/runtime tests: `7 passed`
- `npm test`: `2 suites passed`, `4 tests passed`
- `make test`: `1010 passed`, `5 warnings`
