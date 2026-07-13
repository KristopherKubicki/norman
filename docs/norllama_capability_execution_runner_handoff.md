# Norllama Capability Execution Runner Handoff

Date: 2026-07-11

Status: staging handoff for route-proof capability execution.

## What Changed

- Added `scripts/norllama/capability_execution_runner.py`.
- The runner consumes `tmp/capability-execution-manifest-latest.json`.
- It emits `norman.norllama.capability-execution-results.v1` result packets.
- Dry-run rows are always `planned_unexecuted` and never promotion-authoritative.
- Live rows require observed worker attribution for passed cases.
- Specialist rows do not fabricate local token counts. Passed local specialist
  rows may have `local_tokens: null` when endpoint usage is not observed, and
  instead report lane-specific `local_work_units`.
- Capability suites and cases now carry `suite_version`, `suite_hash`,
  `case_revision`, and `case_hash`.
- Execution manifests now include the real `prompt`, `input_spec`, and
  `input_hash`. The runner blocks execution if the manifest case hash or input
  hash no longer matches.
- Execution result rows carry the same suite/case hashes and compositional
  requirements, so a result can be audited against the exact case definition.
- Live rows now build a route receipt and run Norman's production
  `audit_route_receipt()` and completion gate instead of setting synthetic
  pass/fail strings.
- Result packets split `transport_status`, `capability_status`, and
  `overall_status`; a row is only `passed` when transport, capability quality,
  route audit, and completion gate all pass.
- Specialist endpoints no longer synthesize token counts. Missing endpoint
  token reports are represented as `usage_observed: false`, `local_tokens:
  null`, and lane-specific `local_work_units`.
- Route capability contracts now expose separate `transport_gate` and
  `capability_gate` fields. Capability gates remain unproven until executed.
- Norman's warm policy, model-reality view, route receipts, receipt auditor, and
  the Norllama gateway warm-policy view now consume those gates. A transport
  production row with `production_route_requires_capability_gate: true` and an
  unproven capability gate is canary/manual only, not production-default
  eligible.
- Derived benchmark packets preserve parent packet ID/hash and the original
  `source.transport_generated_at`, so capability overlays cannot refresh stale
  transport evidence by changing top-level `generated_at`.
- OCR and ASR cases now use compositional `required_operations` so capture
  variants cannot erase redaction, diarization, UI alignment, language spans,
  confidence, or streaming requirements.
- ASR cases can use an explicit audio fixture or a generated ffmpeg/flite WAV.
  The canary runner now targets the production `faster-whisper:distil-large-v3`
  media lane rather than the older Qwen-ASR aspirational path.
- OCR cases can use generated ImageMagick PNG fixtures.
- Result packets split `transport_passed` from `capability_quality_passed`.
- The Norllama gateway now preserves raw upstream safety classifier labels as
  `raw_label`/`raw_policy_action` and emits normalized Norman policy
  `label`/`policy_action` values from trust-domain and tool-call evidence.

## Current Live Smoke

Latest local artifact:

- `tmp/capability-execution-results-live-smoke-latest.json`

Current live smoke selected six cases each for:

- `asr`
- `safety`
- `reranker`
- `ocr`

Observed result after deploying the gateway to `llm.home.arpa`, `spark-150`,
and `spark-151`:

- `selected_case_count`: 24
- `passed_count`: 24
- `failed_count`: 0
- `capability_failed_count`: 0
- `transport_passed_count`: 24
- `capability_quality_passed_count`: 24
- `skipped_count`: 0
- `validation_failures`: `[]`
- observed worker: `spark-150` for `safety`, `reranker`, and `ocr`
- observed worker: `spark-151` for `asr`
- observed local tokens: `0`
- local work units: `6` audio clips, `18` documents ranked, `12` OCR lines, `6`
  safety classifications
- cloud LLM tokens: `0`
- cloud proxy tokens: `0`
- search tokens: `0`
- result rows include `suite_hash`, `case_hash`, `required_operations`,
  `document_structure`, and `injection_policy`
- packet-level `promotion_authoritative`: `false`
- packet-level `capability_gate.gate`: `unproven`

The ASR fixture is generated locally with ffmpeg/flite:

- path: `tmp/norllama-asr-route-proof.wav`
- text: `norman local canary`
- requested model: `faster-whisper:distil-large-v3`
- raw effective model returned by service: `distil-large-v3`
- canonical receipt model: `faster-whisper:distil-large-v3`
- transcript word overlap: `1.0`

This proves the ASR media lane is reachable through Norllama, attributed to
`spark-151`, and passes the current clean synthetic speech canary. It is still a
canary, not representative ASR production proof.

The OCR fixtures are generated locally with ImageMagick:

- `ocr-clean-route-proof.png`
- `ocr-ledger-id.png`
- `ocr-warning-banner.png`

All six OCR fixture rows passed transport and text-overlap quality.

Safety now runs a stratified canary across benign, secret, privacy,
prompt-injection, read-only tool, and mutating-tool cases. The gateway preserves
the raw upstream classifier response, then emits Norman policy labels/actions;
all six current safety rows pass transport, label/action quality, route audit,
and completion gate.

## Current Dry Run

Latest local artifact:

- `tmp/capability-execution-results-dry-run-latest.json`

Current dry-run packet selected three cases each for:

- `asr`
- `ocr`
- `reranker`
- `safety`

Observed result:

- `selected_case_count`: 12
- `passed_count`: 0
- `dry_run_count`: 12
- `validation_failures`: `[]`

Dry-run rows remain non-authoritative by design.

## Tests Run

- `make format`
- `pytest tests/test_norllama_capability_execution_runner.py tests/test_norllama_route_proof_benchmark_packet.py -q`
- `pytest tests/test_norllama_warm_policy.py tests/test_norllama_route_proof.py tests/test_norllama_gateway_activity.py tests/test_norllama_routing.py tests/test_norllama_capability_execution_runner.py tests/test_norllama_route_proof_benchmark_packet.py`
- `make lint`
- `make test`

Latest full suite result:

- `1197 passed, 5 warnings`

No frontend files were changed, so `npm test` was not run.

## Remaining Work

- Add real human speech ASR fixtures; the generated flite fixture is now a
  passing clean canary, but it is not representative production ASR proof.
- Expand OCR fixtures beyond generated clean banners into scans, screenshots,
  tables, photos, skew, low contrast, and injection overlays.
- Expand labeled reranker and safety datasets beyond the current six-case
  canaries, then add planner, coder, and verifier capability runners.
- Keep transport proof and capability proof separate.
- Do not promote any lane from this runner until representative live cases pass with schema checks, observed workers, and usage accounting.
