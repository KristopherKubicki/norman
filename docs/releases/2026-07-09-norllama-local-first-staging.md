# Norllama Local-First Staging Candidate

Date: 2026-07-09
Scope: Norman web TUIs, console-runtime kernel, Norllama mesh routing, and
local-first proof surfaces
Status: staging candidate, pending pro-agent audit

## Summary

This staging candidate moves Norman closer to a Codex-independent web TUI
runtime by making Norllama a first-class local model provider, exposing
route/usage proof in the console runtime, and pinning the live Norllama gateway
source into the repo.

## Changes

- Add the console-runtime kernel, worker, store, policy, adapters, streaming,
  supervisor, and acceptance support used by long-running TUI tasks.
- Add Norllama routing, gateway client helpers, model reality reconciliation,
  warm policy, mesh cache, route outcome tracking, proxy dispatch, and
  SpecialistLane proof/cascade support.
- Route Norman chat provider attempts through primary, backup, and offline
  lanes, with Norllama/OpenAI-compatible fallback accounting.
- Update the shared web TUI template to autosense `https://llm.home.arpa`, show
  Norllama health/warm policy/specialist proof, emit local-first receipts, and
  use benchmark-backed local planner/specialist preflights.
- Add repo-owned Norllama gateway/transcription/warmer scripts and a deploy
  helper for the Mac front door and Spark peers.
- Fix the `llm.home.arpa` fleet UI wording so Spark rows report Ollama-backed
  models as `via Norllama / N models` when raw Ollama is intentionally private.
- Include local-first architecture docs, router guidance, local node runbook,
  and benchmark/residency release notes.

## Live State At Staging Prep

- `https://llm.home.arpa` reports Norllama `worker-frontdoor-unified`
  `0.1.20260702`.
- Spark model entries are available through Norllama peer gateways:
  - `192.168.2.150`: 15 Ollama-backed model entries.
  - `192.168.2.151`: 18 Ollama-backed model entries.
  - `127.0.0.1`: 7 fallback/tiny model entries.
- Uplink benchmark packet copied for audit:
  `tmp/norllama-pro-agent-handoff-20260709-last8/benchmarks/uplink/packet.json`
  generated `2026-07-06T23:49:28Z`.

## Known Audit Focus

- The retained Uplink benchmark packet still favors older Gemma/Qwen3-coder-next
  warm defaults, while the live capability endpoint has a Qwen-first policy
  override. Uplink should regenerate benchmarks against the current model set.
- The pro-agent audit should verify that every TUI task produces route receipts
  with selected model, worker, policy mode, benchmark freshness, usage bucket,
  fallback class, verifier result, and output shape.
- The handoff tarball is intentionally not part of the commit; it is a
  shareable audit artifact under `tmp/`.

## Verification

- `python3 -m py_compile` for Norllama gateway, resident warmer, and transcribe
  service.
- `bash -n scripts/norllama/deploy_gateway.sh`.
- Handoff packet rebuilt with manifest/checksums and no bytecode files.
- Focused runtime/Norllama pytest suite should be rerun before the final staging
  commit if additional files change.
