---
name: uplink-benchmark
description: Run and regenerate Uplink's evidence-backed Norllama benchmark matrix through personal AWS Bedrock. Use when asked to generate or refresh the Uplink/Norllama benchmark SVG, compare local models with Bedrock GPT-5.4 and GPT-5.6 Terra, repair missing benchmark evidence, inspect benchmark cost or coverage, improve matrix readability, or validate an existing matrix before discussing model-routing changes.
---

# Uplink Benchmark

Operate in `/home/debian/networking/radio/phobos_hunt`. Treat the matrix as
measured routing evidence, not a status report or a decorative artifact.

## Guardrails

- Use local Norllama only for planning, filtering, and evidence preparation.
  Send artifact generation and benchmark execution to a tool-capable Bedrock
  route.
- Use `bedrock_gpt54_standard` and `bedrock_gpt56_standard_board` for
  Bedrock baseline comparisons. Do not use OpenAI direct/API routes for this
  benchmark.
- Run the runner as root because the approved `kk-personal` AWS profile is
  root-owned. Do not copy credentials or add plaintext secret files.
- Never add a model to the SVG without a completed `.score.json` artifact.
  Preserve runtime failures and partial coverage as measured results.

## Preflight

1. Confirm the runner exposes both Bedrock profiles and compile it:

   ```bash
   sudo python3 -m py_compile scripts/run_norman_planner_packet.py
   sudo python3 scripts/run_norman_planner_packet.py --help |
     grep -Eq 'bedrock_gpt54_standard.*bedrock_gpt56_standard_board'
   ```

2. Confirm `scripts/benchmark_ollama_workflows.py` prices
   `openai.gpt-5.4` and `openai.gpt-5.6-terra`; an unknown rate must remain
   explicitly unpriced, never be presented as free.
3. Run one bounded smoke for each profile before spending on a board:

   ```bash
   sudo python3 scripts/run_norman_planner_packet.py \
     --packet-json tmp/norman_from_bbs/planner_llm_benchmark_packet.json \
     --profiles bedrock_gpt54_standard bedrock_gpt56_standard_board \
     --limit 1 --max-new-cases 1 --timeout 180 \
     --out-dir evidence/norman_planner_packet_runs_bedrock_smoke
   ```

## Refresh The Matrix

Run the matching benchmark packet for each requested suite. Keep the standard
output layout so the packet builder can infer the suite:

- `evidence/norman_planner_packet_runs_188_full_*` for Code Flow
- `evidence/norman_planner_packet_runs_188_scout_*` for LLM Prep
- `evidence/norman_microbench_*/*/{specialist_board,web_crawl_static,product_information,runbook_scenarios,decompose_final,optimizer_receipts,control_plane_runbooks}` for the microbench lanes

Use `--resume-answers-json` and `--max-new-cases` when a long lane needs to
continue; do not discard partial evidence. After every completed lane:

```bash
sudo python3 scripts/build_norllama_benchmark_packet.py
sudo python3 scripts/plot_norllama_benchmark_matrix.py --theme light
sudo python3 scripts/plot_norllama_benchmark_matrix.py \
  --theme dark \
  --out-stem evidence/norllama_benchmark_packet_latest/benchmark_matrix_dark
```

When a prior Bedrock 5.4 score shows raw coverage but reduced coverage, inspect
the per-answer `runtime_health_status`, token fields, and explicit error fields
before rerunning prompts. Benchmark text that merely discusses a runtime
failure is not a runtime outage. Preserve the original score artifact, retry
only a genuine unavailable/zero-token case from a copied answer packet, then
rebuild the aggregate.

## Visual Quality

- Keep the primary routing board to the three selected local routing profiles
  plus Bedrock GPT-5.4, GPT-5.5, and GPT-5.6. Keep direct/API and specialist
  evidence in focused panels, not in the decision board.
- Render candidate light and dark PNGs before replacing the published SVGs.
  The header legend, health note, and stat cards must not overlap.
- Main-board cells show grade, score, coverage/runtime, and spend. Focused
  microbench cells use a single-line grade/score readout so labels remain
  legible.
- Runtime outages stay neutral and explicitly labeled. Never convert them
  into a low-quality score or hide them to make the board look better.

## Verify And Report

- Confirm both SVGs are nonempty and that `shareable_view.display_cloud_profiles`
  includes `bedrock_gpt54_standard` and `bedrock_gpt56_standard_board`.
- Confirm every displayed Bedrock 5.4 cell has full coverage or report the
  exact remaining runtime failure and its retry artifact.
- Report model, route, scored/attempted prompts, coverage, runtime failures,
  critical failures, and estimated Bedrock spend.
- Call out any failed safety or precision lanes. Do not describe a failed
  benchmark as a production promotion.
- For a request such as "regenerate the SVG", perform the work or state the
  exact blocker. Do not answer it with a status-only summary.
