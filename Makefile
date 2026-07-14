.PHONY: lint format test tui-benchmarks historic-shadow-planner-benchmarks tui-route-receipt-harvest tui-bedrock-region-smoke tui-cutover-readiness-live tui-benchmarks-live tui-change-check

PYTEST_ARGS ?= -vv --ignore=tmp/pro_agent_norman_harness_pack
TUI_BENCHMARK_DIR ?= /tmp/norman_tui_benchmarks
TUI_BENCHMARK_SAMPLE ?= db/tui_context_shadow_benchmark_sample.json
TUI_STATE_DB ?= $(HOME)/.codex-work/web-bridge/tui_state.sqlite3
HISTORIC_SESSION_REPORT ?= $(TUI_BENCHMARK_DIR)/work_session_runbook_miner.json
HISTORIC_SHADOW_PLANNER_HOLDOUT_AFTER ?= 2026-06-14
ROUTE_RECEIPT_HARVEST_OWNERS ?=
BEDROCK_REGION_SMOKE_PROFILE ?= traqline-bedrock
BEDROCK_REGION_SMOKE_MODEL ?= openai.gpt-5.4
BEDROCK_REGION_SMOKE_AWS_REGION ?= us-east-2
BEDROCK_REGION_SMOKE_SINCE_HOURS ?= 24

lint:
	./.venv/bin/ruff format --check .
	./.venv/bin/ruff check app main.py setup.py

format:
	./.venv/bin/ruff format .

test:
	./.venv/bin/pytest $(PYTEST_ARGS)

tui-benchmarks:
	mkdir -p $(TUI_BENCHMARK_DIR)
	./.venv/bin/pytest tests/test_tui_context_shadow_benchmark.py tests/test_tui_context_replay_benchmark.py tests/test_tui_quality_benchmark.py tests/test_tui_capability_inventory.py tests/test_tui_microtexture_audit.py tests/test_tui_bedrock_shortstop_benchmark.py tests/test_paired_hybrid_replay_benchmark.py tests/test_tui_auto_mode_benchmark.py tests/test_work_domain_skill_benchmark.py tests/test_local_model_skill_floor.py tests/test_local_model_route_policy.py tests/test_planner_preroute_policy.py tests/test_planner_guardrail_dashboard.py tests/test_planner_time_contract_benchmark.py tests/test_planner_excellence_scorecard.py tests/test_planner_kaizen_loop.py tests/test_planner_llm_benchmark_packet.py tests/test_planner_llm_benchmark_score.py tests/test_planner_benchmark_wrapup.py tests/test_work_loop_canary.py tests/test_historic_shadow_planner_route_benchmark.py
	./.venv/bin/python scripts/tui_context_shadow_benchmark.py --source-json $(TUI_BENCHMARK_SAMPLE) --output-json $(TUI_BENCHMARK_DIR)/context_shadow.json --output-md $(TUI_BENCHMARK_DIR)/context_shadow.md --output-answer-template $(TUI_BENCHMARK_DIR)/quality_shadow_answers.template.json
	./.venv/bin/python scripts/tui_context_replay_benchmark.py --context-report $(TUI_BENCHMARK_DIR)/context_shadow.json --output-json $(TUI_BENCHMARK_DIR)/context_replay.json --output-md $(TUI_BENCHMARK_DIR)/context_replay.md --output-answer-template $(TUI_BENCHMARK_DIR)/context_replay_answers.template.json
	./.venv/bin/python scripts/tui_quality_benchmark.py --output-json $(TUI_BENCHMARK_DIR)/quality.json --output-md $(TUI_BENCHMARK_DIR)/quality.md
	./.venv/bin/python scripts/paired_hybrid_replay_benchmark.py --output-json $(TUI_BENCHMARK_DIR)/paired_hybrid_replay.json --output-md $(TUI_BENCHMARK_DIR)/paired_hybrid_replay.md
	./.venv/bin/python scripts/tui_auto_mode_benchmark.py --output-json $(TUI_BENCHMARK_DIR)/auto_mode.json --output-md $(TUI_BENCHMARK_DIR)/auto_mode.md
	./.venv/bin/python scripts/tui_capability_inventory.py --output-json $(TUI_BENCHMARK_DIR)/capability_inventory.json --output-md $(TUI_BENCHMARK_DIR)/capability_inventory.md
	./.venv/bin/python scripts/tui_microtexture_audit.py --output-json $(TUI_BENCHMARK_DIR)/microtexture_audit.json --output-md $(TUI_BENCHMARK_DIR)/microtexture_audit.md
	./.venv/bin/python scripts/work_domain_skill_benchmark.py --output-json $(TUI_BENCHMARK_DIR)/work_domain_skill_matrix.json --output-md $(TUI_BENCHMARK_DIR)/work_domain_skill_matrix.md
	./.venv/bin/python scripts/local_runtime_health.py --output-json $(TUI_BENCHMARK_DIR)/local_runtime_health.json --output-md $(TUI_BENCHMARK_DIR)/local_runtime_health.md
	./.venv/bin/python scripts/local_model_skill_floor.py --skill-matrix-json $(TUI_BENCHMARK_DIR)/work_domain_skill_matrix.json --ollama-sense-json $(TUI_BENCHMARK_DIR)/ollama_sense_live.json --vllm-sense-json $(TUI_BENCHMARK_DIR)/vllm_sense_live.json --output-json $(TUI_BENCHMARK_DIR)/local_model_skill_floors.json --output-md $(TUI_BENCHMARK_DIR)/local_model_skill_floors.md
	./.venv/bin/python scripts/local_model_route_policy.py --skill-floors-json $(TUI_BENCHMARK_DIR)/local_model_skill_floors.json --skill-matrix-json $(TUI_BENCHMARK_DIR)/work_domain_skill_matrix.json --runtime-health-json $(TUI_BENCHMARK_DIR)/local_runtime_health.json --output-json $(TUI_BENCHMARK_DIR)/local_model_route_policy.json --output-md $(TUI_BENCHMARK_DIR)/local_model_route_policy.md
	./.venv/bin/python scripts/planner_preroute_policy.py --route-policy-json $(TUI_BENCHMARK_DIR)/local_model_route_policy.json --output-json $(TUI_BENCHMARK_DIR)/planner_preroute_policy.json --output-md $(TUI_BENCHMARK_DIR)/planner_preroute_policy.md
	./.venv/bin/python scripts/planner_time_contract_benchmark.py --include-history --state-db $(TUI_STATE_DB) --output-json $(TUI_BENCHMARK_DIR)/planner_time_contract_benchmark.json --output-md $(TUI_BENCHMARK_DIR)/planner_time_contract_benchmark.md
	./.venv/bin/python scripts/work_loop_canary.py --flow-plan-only --skill-matrix-json $(TUI_BENCHMARK_DIR)/work_domain_skill_matrix.json --output-flow-plan-json $(TUI_BENCHMARK_DIR)/tui_flow_canary_plan.json --output-flow-plan-md $(TUI_BENCHMARK_DIR)/tui_flow_canary_plan.md
	./.venv/bin/python scripts/work_loop_canary.py --route-receipt-manifest-only --flow-plan-json $(TUI_BENCHMARK_DIR)/tui_flow_canary_plan.json --route-receipt-dir $(TUI_BENCHMARK_DIR)/route_receipts --route-receipt-template-dir $(TUI_BENCHMARK_DIR)/route_receipt_templates --output-route-receipt-manifest-json $(TUI_BENCHMARK_DIR)/tui_route_receipt_manifest.json --output-route-receipt-manifest-md $(TUI_BENCHMARK_DIR)/tui_route_receipt_manifest.md
	./.venv/bin/python scripts/work_loop_canary.py --route-receipt-launch-plan-only --prepare-route-receipt-sink --output-route-receipt-manifest-json $(TUI_BENCHMARK_DIR)/tui_route_receipt_manifest.json --output-route-receipt-launch-json $(TUI_BENCHMARK_DIR)/tui_route_receipt_launch_plan.json --output-route-receipt-launch-md $(TUI_BENCHMARK_DIR)/tui_route_receipt_launch_plan.md
	./.venv/bin/python scripts/work_loop_canary.py --cutover-readiness-only --flow-plan-json $(TUI_BENCHMARK_DIR)/tui_flow_canary_plan.json --route-receipt-dir $(TUI_BENCHMARK_DIR)/route_receipts --historic-route-benchmark-json $(TUI_BENCHMARK_DIR)/historic_shadow_planner_route_benchmark.json --output-cutover-readiness-json $(TUI_BENCHMARK_DIR)/tui_cutover_readiness.json --output-cutover-readiness-md $(TUI_BENCHMARK_DIR)/tui_cutover_readiness.md
	./.venv/bin/python scripts/planner_guardrail_dashboard.py --cutover-json $(TUI_BENCHMARK_DIR)/tui_cutover_readiness.json --preroute-json $(TUI_BENCHMARK_DIR)/planner_preroute_policy.json --route-policy-json $(TUI_BENCHMARK_DIR)/local_model_route_policy.json --local-floors-json $(TUI_BENCHMARK_DIR)/local_model_skill_floors.json --output-json $(TUI_BENCHMARK_DIR)/planner_guardrail_dashboard.json --output-md $(TUI_BENCHMARK_DIR)/planner_guardrail_dashboard.md
	./.venv/bin/python scripts/planner_excellence_scorecard.py --guardrail-json $(TUI_BENCHMARK_DIR)/planner_guardrail_dashboard.json --preroute-json $(TUI_BENCHMARK_DIR)/planner_preroute_policy.json --time-contract-json $(TUI_BENCHMARK_DIR)/planner_time_contract_benchmark.json --route-policy-json $(TUI_BENCHMARK_DIR)/local_model_route_policy.json --output-json $(TUI_BENCHMARK_DIR)/planner_excellence_scorecard.json --output-md $(TUI_BENCHMARK_DIR)/planner_excellence_scorecard.md
	./.venv/bin/python scripts/planner_kaizen_loop.py --scorecard-json $(TUI_BENCHMARK_DIR)/planner_excellence_scorecard.json --output-json $(TUI_BENCHMARK_DIR)/planner_kaizen_loop.json --output-md $(TUI_BENCHMARK_DIR)/planner_kaizen_loop.md
	./.venv/bin/python scripts/planner_llm_benchmark_packet.py --output-json $(TUI_BENCHMARK_DIR)/planner_llm_benchmark_packet.json --output-md $(TUI_BENCHMARK_DIR)/planner_llm_benchmark_packet.md --prompts-jsonl $(TUI_BENCHMARK_DIR)/planner_llm_benchmark_prompts.jsonl --answers-template-json $(TUI_BENCHMARK_DIR)/planner_llm_benchmark_answers.template.json
	./.venv/bin/python scripts/planner_llm_benchmark_score.py --packet-json $(TUI_BENCHMARK_DIR)/planner_llm_benchmark_packet.json --answers-json $(TUI_BENCHMARK_DIR)/planner_llm_benchmark_answers.template.json --output-json $(TUI_BENCHMARK_DIR)/planner_llm_benchmark_score.json --output-md $(TUI_BENCHMARK_DIR)/planner_llm_benchmark_score.md
	./.venv/bin/python scripts/planner_benchmark_wrapup.py --scorecard-json $(TUI_BENCHMARK_DIR)/planner_excellence_scorecard.json --preroute-json $(TUI_BENCHMARK_DIR)/planner_preroute_policy.json --route-policy-json $(TUI_BENCHMARK_DIR)/local_model_route_policy.json --runtime-health-json $(TUI_BENCHMARK_DIR)/local_runtime_health.json --skill-matrix-json $(TUI_BENCHMARK_DIR)/work_domain_skill_matrix.json --llm-score-json $(TUI_BENCHMARK_DIR)/planner_llm_benchmark_score.json --output-json $(TUI_BENCHMARK_DIR)/planner_benchmark_wrapup.json --output-md $(TUI_BENCHMARK_DIR)/planner_benchmark_wrapup.md

historic-shadow-planner-benchmarks:
	mkdir -p $(TUI_BENCHMARK_DIR)
	test -f $(HISTORIC_SESSION_REPORT) || (echo "Missing HISTORIC_SESSION_REPORT=$(HISTORIC_SESSION_REPORT). Run scripts/work_session_runbook_miner.py or pass HISTORIC_SESSION_REPORT=/path/to/report.json." && exit 2)
	./.venv/bin/pytest tests/test_historic_shadow_planner_cases.py tests/test_historic_shadow_planner_route_benchmark.py
	./.venv/bin/python scripts/historic_shadow_planner_cases.py --input-json $(HISTORIC_SESSION_REPORT) --output-json $(TUI_BENCHMARK_DIR)/historic_shadow_planner_cases.json --output-md $(TUI_BENCHMARK_DIR)/historic_shadow_planner_cases.md --max-patterns 8 --cases-per-pattern 3 --min-evidence 5 --holdout-after $(HISTORIC_SHADOW_PLANNER_HOLDOUT_AFTER)
	./.venv/bin/python scripts/historic_shadow_planner_route_benchmark.py --cases-json $(TUI_BENCHMARK_DIR)/historic_shadow_planner_cases.json --output-json $(TUI_BENCHMARK_DIR)/historic_shadow_planner_route_benchmark.json --output-md $(TUI_BENCHMARK_DIR)/historic_shadow_planner_route_benchmark.md

tui-route-receipt-harvest:
	mkdir -p $(TUI_BENCHMARK_DIR)/route_receipts
	test -f $(TUI_BENCHMARK_DIR)/tui_flow_canary_plan.json || (echo "Missing $(TUI_BENCHMARK_DIR)/tui_flow_canary_plan.json. Run make tui-benchmarks first." && exit 2)
	./.venv/bin/python scripts/work_loop_canary.py --harvest-route-receipts-only --flow-plan-json $(TUI_BENCHMARK_DIR)/tui_flow_canary_plan.json --route-receipt-dir $(TUI_BENCHMARK_DIR)/route_receipts --harvest-route-receipt-owners "$(ROUTE_RECEIPT_HARVEST_OWNERS)" --output-route-receipt-harvest-json $(TUI_BENCHMARK_DIR)/tui_route_receipt_harvest.json --output-route-receipt-harvest-md $(TUI_BENCHMARK_DIR)/tui_route_receipt_harvest.md

tui-bedrock-region-smoke:
	mkdir -p $(TUI_BENCHMARK_DIR)
	./.venv/bin/python scripts/tui_bedrock_region_smoke.py --work-special-defaults --profile-v2 $(BEDROCK_REGION_SMOKE_PROFILE) --model $(BEDROCK_REGION_SMOKE_MODEL) --aws-region $(BEDROCK_REGION_SMOKE_AWS_REGION) --since-hours $(BEDROCK_REGION_SMOKE_SINCE_HOURS) --output-json $(TUI_BENCHMARK_DIR)/bedrock_region_smoke.json

tui-cutover-readiness-live: tui-route-receipt-harvest
	test -f $(TUI_BENCHMARK_DIR)/historic_shadow_planner_route_benchmark.json || (echo "Missing $(TUI_BENCHMARK_DIR)/historic_shadow_planner_route_benchmark.json. Run make historic-shadow-planner-benchmarks first." && exit 2)
	./.venv/bin/python scripts/work_loop_canary.py --cutover-readiness-only --flow-plan-json $(TUI_BENCHMARK_DIR)/tui_flow_canary_plan.json --route-receipt-dir $(TUI_BENCHMARK_DIR)/route_receipts --historic-route-benchmark-json $(TUI_BENCHMARK_DIR)/historic_shadow_planner_route_benchmark.json --output-cutover-readiness-json $(TUI_BENCHMARK_DIR)/tui_cutover_readiness.json --output-cutover-readiness-md $(TUI_BENCHMARK_DIR)/tui_cutover_readiness.md

tui-benchmarks-live:
	mkdir -p $(TUI_BENCHMARK_DIR)
	./.venv/bin/python scripts/tui_context_shadow_benchmark.py --fetch-work-special --output-json $(TUI_BENCHMARK_DIR)/live_context_shadow.json --output-md $(TUI_BENCHMARK_DIR)/live_context_shadow.md --output-answer-template $(TUI_BENCHMARK_DIR)/live_quality_shadow_answers.template.json
	./.venv/bin/python scripts/tui_context_replay_benchmark.py --context-report $(TUI_BENCHMARK_DIR)/live_context_shadow.json --output-json $(TUI_BENCHMARK_DIR)/live_context_replay.json --output-md $(TUI_BENCHMARK_DIR)/live_context_replay.md --output-answer-template $(TUI_BENCHMARK_DIR)/live_context_replay_answers.template.json
	./.venv/bin/python scripts/tui_bedrock_shortstop_benchmark.py --work-special-defaults --output-json $(TUI_BENCHMARK_DIR)/live_bedrock_shortstop.json --output-md $(TUI_BENCHMARK_DIR)/live_bedrock_shortstop.md

tui-change-check: lint tui-benchmarks
	./.venv/bin/pytest tests/test_agent_console_template_masking.py tests/test_norman_codex_model_settings.py
