from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_provider_benchmark(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "tui_provider_readiness_benchmark",
        scripts_dir / "tui_provider_readiness_benchmark.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tui_provider_readiness_benchmark"] = module
    spec.loader.exec_module(module)
    return module


def _write_json_answer(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_candidate_registry_keeps_future_model_watch_slots(monkeypatch) -> None:
    module = _load_provider_benchmark(monkeypatch)

    candidates = {candidate.id: candidate for candidate in module.CANDIDATES}

    assert candidates["codex_openai_5_6_flex_xhigh"].status == "access-tested"
    assert (
        "Direct OpenAI GPT-5.6 candidate"
        in candidates["codex_openai_5_6_flex_xhigh"].notes
    )
    assert candidates["codex_bedrock_5_4_low"].model == "openai.gpt-5.4"
    assert candidates["codex_bedrock_5_4_low"].status == "ready"
    assert candidates["codex_bedrock_5_4_low"].runbook_role.startswith("Default cloud")
    assert candidates["codex_bedrock_5_6_luna_low"].model == "openai.gpt-5.6-luna"
    assert candidates["codex_bedrock_5_6_luna_low"].status == "canary-ready"
    assert candidates["codex_bedrock_5_6_terra_low"].model == "openai.gpt-5.6-terra"
    assert candidates["codex_bedrock_5_6_terra_low"].status == "canary-ready"
    assert candidates["codex_bedrock_5_6_sol_low"].model == "openai.gpt-5.6-sol"
    assert candidates["codex_bedrock_5_6_sol_low"].status == "canary-ready"
    assert all(
        candidate.model != "openai.gpt-5.6"
        for candidate in candidates.values()
        if candidate.provider == "aws-bedrock"
    )
    assert candidates["kimi_k2_6"].status == "future-watch"
    assert (
        "direct OpenAI auth smoke passes"
        in candidates["codex_openai_5_5_flex_xhigh"].activation_signals
    )
    assert candidates["openai_gpt_5_3_codex_xhigh"].model == "gpt-5.3-codex"
    assert candidates["openai_gpt_5_3_codex_spark_preview"].provider == (
        "openai-cerebras"
    )
    assert candidates["openai_gpt_5_3_codex_spark_preview"].access_class == (
        "openai-codex-preview"
    )
    assert candidates["openai_gpt_5_4_mini_high"].model == "gpt-5.4-mini"
    assert candidates["hybrid_5_5_plan_5_4_mini_code"].status == "experiment"
    assert candidates["qwen3_next_80b"].model == "qwen.qwen3-next-80b-a3b"
    assert candidates["qwen3_next_80b"].runbook_role.startswith("Mini scout")
    assert candidates["qwen3_coder_480b"].access_class == (
        "bedrock-serverless-auto-enable"
    )
    assert candidates["qwen3_coder_30b"].runbook_role.startswith("Mini coder")
    assert candidates["mistral_devstral_2_123b"].model == "mistral.devstral-2-123b"
    assert candidates["openai_gpt_oss_20b_bedrock"].model == "openai.gpt-oss-20b-1:0"
    assert candidates["openai_gpt_oss_120b_bedrock"].model == (
        "openai.gpt-oss-120b-1:0"
    )
    assert candidates["amazon_nova_lite"].runbook_role.startswith("Cheap first-pass")
    assert candidates["amazon_nova_micro"].access_class == "bedrock-native"


def test_prompt_registry_covers_all_scored_cases(monkeypatch) -> None:
    module = _load_provider_benchmark(monkeypatch)

    prompts = module.benchmark_prompts()

    assert set(prompts) == module.case_ids()
    assert "970.1 minutes" in prompts["ops_handoff_decision"]
    assert "recognized_gross_total" in prompts["revenue_reconcile"]
    assert "estimated USD" in prompts["cost_metering_caveat"]
    assert "22100" in prompts["numeric_context_compaction_route"]
    assert "Do not paste raw rows" in prompts["numeric_context_compaction_route"]
    assert "closed stdin" in prompts["bounded_code_worker_route"]
    assert (
        "Do not merge kpis with leadership-kpis"
        in prompts["entity_matching_alias_resolution"]
    )
    assert "side quest" in prompts["queue_interrupt_resume_policy"]
    assert "AWS Bedrock profile-v2" in prompts["deploy_devops_cloud_gate"]
    assert "fresh official sources" in prompts["research_compare_websearch_gate"]
    assert "remote clicking is not approved" in prompts["screen_steering_visual_triage"]
    assert "OpenAI Flex" in prompts["control_plane_route_recovery_ticket"]
    assert "GAPHELP-4228" in prompts["gaphelp_4228_runbook_cleanup_ticket"]
    assert "91% used" in prompts["hal_disk_pressure_ticket"]
    assert "Scout/Ranger" in prompts["cross_lane_research_packet_ticket"]
    assert (
        "ACK means the actor is taking ownership"
        in prompts["stale_bbs_handoff_cleanup_ticket"]
    )
    assert "kpis.kris.openbrand.com" in prompts["kpis_route_bedrock_mismatch_ticket"]
    assert "low-yield short stops" in prompts["aws_bedrock_support_evidence_ticket"]
    assert "auto-continuation" in prompts["auto_continuation_resume_ticket"]
    assert "Beach Eufy loading-shell" in prompts["loading_shell_guard_route_ticket"]


def test_score_artifacts_splits_exact_operational_and_route_failures(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_provider_benchmark(monkeypatch)

    _write_json_answer(
        tmp_path / "codex_bedrock_5_5_xhigh__ops_handoff_decision.last.txt",
        {
            "status": "needs_action",
            "primary_actor_alerting": "Switchboard BBS sentinel",
            "why_alerting": "Owner subprime has not acknowledged the task.",
            "why_me": "Norman is an observer/coordinator.",
            "top_action": "FORK_OR_BLOCK",
            "operator_options": ["Fork", "Block", "Done"],
            "fine_print": "ACK means taking ownership.",
        },
    )
    (tmp_path / "codex_openai_5_5_flex_xhigh__ops_handoff_decision.jsonl").write_text(
        "unexpected status 401 Unauthorized: Missing bearer or basic authentication",
        encoding="utf-8",
    )

    report = module.score_artifacts(tmp_path)
    rows = {(row["candidate"]["id"], row["case"]["id"]): row for row in report["rows"]}

    bedrock = rows[("codex_bedrock_5_5_xhigh", "ops_handoff_decision")]
    assert bedrock["run_state"] == "scored"
    assert bedrock["operational_pass"] is True
    assert bedrock["exact_pass"] is False
    assert bedrock["failure_kind"] == "exactness"
    assert "missing exact focus id" in bedrock["reasons"]

    openai = rows[("codex_openai_5_5_flex_xhigh", "ops_handoff_decision")]
    assert openai["run_state"] == "route_failed"
    assert openai["failure_kind"] == "auth"
    assert openai["operational_pass"] is False


def test_release_gate_usage_limit_caveat_is_not_route_failure(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_provider_benchmark(monkeypatch)

    _write_json_answer(
        tmp_path / "codex_bedrock_5_5_xhigh__release_route_gate.last.txt",
        {
            "status": "ok",
            "ship_decision": "SHIP_NOW for work-special; defer home network.",
            "default_route": "Codex Bedrock 5.5",
            "selectable_routes": [
                "Codex OpenAI 5.5",
                "Codex Bedrock 5.5",
                "Codex Local 5.5",
                "Claude Bedrock Opus 4.8",
            ],
            "disabled_or_warned_routes": [
                {
                    "route": "Codex OpenAI 5.5",
                    "reason": "Warn about recent usage limit failures before relying on it.",
                },
                {
                    "route": "Codex Local 5.5",
                    "reason": "Adapter not wired; planned only.",
                },
                {
                    "route": "Claude Bedrock Opus 4.8",
                    "reason": "Brokered read-only tools are limited.",
                },
            ],
            "required_followups": ["Home network later"],
        },
    )

    report = module.score_artifacts(tmp_path)
    row = next(
        row
        for row in report["rows"]
        if row["candidate"]["id"] == "codex_bedrock_5_5_xhigh"
        and row["case"]["id"] == "release_route_gate"
    )

    assert row["run_state"] == "scored"
    assert row["failure_kind"] == ""
    assert row["operational_pass"] is True


def test_hybrid_flow_metrics_quantify_cost_and_gates(monkeypatch) -> None:
    module = _load_provider_benchmark(monkeypatch)

    board = {item["id"]: item for item in module.build_hybrid_flow_board()}

    local = board["local_first_no_model"]
    assert local["estimated_cost_ratio_vs_5_5_flex"] == 0.0
    assert local["requires_verifier"] is False
    assert local["cheap_worker_token_share"] == 0.0

    bedrock_solo = board["solo_bedrock_5_5_default"]
    assert bedrock_solo["cost_known"] is False
    assert bedrock_solo["five_five_token_share"] == 1.0

    planner_worker = board["planner_5_5_worker_5_4_mini_verifier_5_5"]
    assert planner_worker["estimated_cost_ratio_vs_5_5_flex"] == 0.29
    assert planner_worker["five_five_token_share"] == 0.0
    assert planner_worker["cheap_worker_token_share"] == 0.6
    assert planner_worker["requires_verifier"] is True
    assert planner_worker["requires_closed_stdin"] is True
    assert planner_worker["requires_hard_timeout"] is True
    assert planner_worker["runtime_guard_count"] == 4
    assert planner_worker["promotion_metrics"]["required_scope_violations"] == 0
    assert planner_worker["promotion_metrics"]["max_escalation_rate"] == 0.2
    assert "deploy" in planner_worker["forbidden_work"]

    batch = board["batch_5_4_mini_replay_verifier"]
    assert batch["estimated_cost_ratio_vs_5_5_flex"] == 0.235
    assert batch["status"] == "offline-recommended"

    bedrock_qwen = board["bedrock_5_5_plan_qwen_coder_worker"]
    assert bedrock_qwen["estimated_cost_ratio_vs_5_5_flex"] is None
    assert bedrock_qwen["cost_known"] is False
    assert bedrock_qwen["worker_cost_known"] is False
    assert "closed_stdin" in bedrock_qwen["runtime_guards"]


def test_architecture_workload_matrix_recommends_guarded_hybrid_canary(
    monkeypatch,
) -> None:
    module = _load_provider_benchmark(monkeypatch)

    matrix = module.build_architecture_workload_matrix()
    summary = {item["workload_id"]: item for item in matrix["summary_by_workload"]}

    assert matrix["schema"] == "norman.tui.architecture-workload-matrix.v1"
    assert matrix["workload_count"] == 9
    assert matrix["flow_count"] == 7
    assert matrix["row_count"] == 63
    assert summary["local_status_and_inventory"]["top_flow_id"] == (
        "local_first_no_model"
    )
    assert summary["interactive_operator_ambiguity"]["top_flow_id"] == (
        "solo_bedrock_5_5_default"
    )
    assert summary["dense_numeric_context"]["top_flow_id"] == (
        "planner_5_5_worker_5_4_mini_verifier_5_5"
    )
    assert summary["bounded_code_patch"]["top_flow_id"] == (
        "planner_5_5_worker_5_4_mini_verifier_5_5"
    )
    assert summary["deploy_devops_cloud_live"]["top_flow_id"] == (
        "solo_bedrock_5_5_default"
    )
    assert summary["screen_steering_visual"]["top_flow_id"] == (
        "solo_bedrock_5_5_default"
    )
    assert summary["offline_bulk_replay"]["top_flow_id"] == (
        "batch_5_4_mini_replay_verifier"
    )
    assert summary["bedrock_coder_scout"]["top_flow_id"] == (
        "bedrock_5_5_plan_qwen_coder_worker"
    )

    canary = matrix["canary_recommendation"]
    assert canary["status"] == "shadow-canary-ready"
    assert canary["comfortable_to_try"] is True
    assert (
        "worker-owned deploy/restart/cloud actions" in canary["blocked_initial_scope"]
    )
    assert "zero worker scope violations" in canary["promotion_gate"]


def test_valid_answer_can_discuss_route_errors_without_becoming_route_failure(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_provider_benchmark(monkeypatch)

    _write_json_answer(
        tmp_path / "deepseek_v3_2__route_mismatch_error.last.txt",
        {
            "alert_source": "Codex OpenAI route",
            "why_alerting": "The model openai.gpt-5.5 is not supported on direct OpenAI ChatGPT-account Codex; use Bedrock for that prefixed model.",
            "operator_options": [
                "Switch to Codex Bedrock",
                "Use gpt-5.5 on direct OpenAI",
            ],
            "fine_print": {"bedrock_model": "openai.gpt-5.5"},
        },
    )
    (tmp_path / "deepseek_v3_2__route_mismatch_error.jsonl").write_text(
        '{"type":"turn.completed"}\n',
        encoding="utf-8",
    )

    report = module.score_artifacts(tmp_path)
    row = next(
        row
        for row in report["rows"]
        if row["candidate"]["id"] == "deepseek_v3_2"
        and row["case"]["id"] == "route_mismatch_error"
    )

    assert row["run_state"] == "scored"
    assert row["failure_kind"] != "model_unsupported"


def test_cli_writes_provider_readiness_report(tmp_path: Path, monkeypatch) -> None:
    module = _load_provider_benchmark(monkeypatch)
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    output_json = tmp_path / "provider.json"
    output_md = tmp_path / "provider.md"

    _write_json_answer(
        artifact_dir / "codex_bedrock_5_5_xhigh__revenue_reconcile.last.txt",
        {
            "status": "ok",
            "recognized_gross_total": 4465.15,
            "recognized_by_region": {"West": 2759.94, "East": 1705.21},
            "mismatches": [
                {"order_id": "A101", "mismatch_type": "underpaid", "delta": 8.00},
                {
                    "order_id": "A103",
                    "mismatch_type": "cancelled_paid",
                    "delta": 259.80,
                },
            ],
            "order_status": {
                "A100": "ok",
                "A101": "mismatch",
                "A102": "ok",
                "A103": "cancelled_mismatch",
                "A104": "ok",
            },
        },
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tui_provider_readiness_benchmark.py",
            "--artifact-dir",
            str(artifact_dir),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
    )

    assert module.main() == 0
    report = json.loads(output_json.read_text(encoding="utf-8"))
    markdown = output_md.read_text(encoding="utf-8")

    assert report["schema"] == "norman.tui.provider-readiness-benchmark.v1"
    assert report["summary"]["case_count"] == 28
    assert report["summary"]["candidate_count"] == 26
    assert report["summary"]["future_watch_count"] == 1
    assert report["external_audit"]["promotion_authoritative"] is False
    audit_scores = {
        row["scope"]: row["readiness"] for row in report["external_audit"]["scorecard"]
    }
    assert audit_scores["Bedrock model-access and transport proof"] == 86
    assert audit_scores["Strict JSON smoke coverage"] == 88
    assert audit_scores["Latency and token-usage canary"] == 72
    assert audit_scores["Comparative model-quality evidence"] == 45
    assert audit_scores["Architecture recommendation evidence"] == 30
    assert audit_scores["Packet integrity and reproducibility"] == 38
    assert audit_scores["Overall matrix readiness"] == 56
    assert audit_scores["Norman core, unchanged"] == 97
    assert report["promotion_criteria"]["required_operational_passes"] == 28
    assert report["promotion_criteria"]["minimum_exact_passes"] == 26
    assert report["hybrid_strategies"][0]["id"] == "cheap_executor_with_escalation"
    pattern_findings = {
        item["pattern"]: item for item in report["session_pattern_findings"]
    }
    assert pattern_findings["numeric_batch"]["benchmark_response"] == (
        "numeric_context_compaction_route"
    )
    coverage = {item["workflow"]: item for item in report["workflow_coverage_audit"]}
    assert coverage["complicated_matching"]["status"] == "covered"
    assert (
        "entity_matching_alias_resolution"
        in coverage["complicated_matching"]["benchmark_cases"]
    )
    assert coverage["queueing_and_resume"]["benchmark_cases"][0] == (
        "queue_interrupt_resume_policy"
    )
    assert (
        "deploy_devops_cloud_gate"
        in coverage["deploying_devops_cloud"]["benchmark_cases"]
    )
    assert (
        "research_compare_websearch_gate"
        in coverage["research_compare_websearch"]["benchmark_cases"]
    )
    assert (
        "screen_steering_visual_triage"
        in coverage["screen_steering"]["benchmark_cases"]
    )
    context_patterns = {
        item["id"]: item for item in report["hybrid_context_routing_patterns"]
    }
    assert "numeric_context_compaction" in context_patterns
    assert context_patterns["bounded_code_worker"]["benchmark_cases"] == [
        "bounded_code_worker_route"
    ]
    breadth_lanes = {
        item["lane"]: item for item in report["model_breadth_operating_model"]
    }
    assert breadth_lanes["local_first"]["benchmark_cases"] == [
        "numeric_context_compaction_route",
        "status_fast_path_route",
    ]
    assert breadth_lanes["frontier_authority"]["autonomy_limit"].startswith(
        "can decide"
    )
    autonomy_levels = {item["level"]: item for item in report["autonomy_ladder"]}
    assert autonomy_levels["L3 brokered patch"]["gate_to_next"] == (
        "tests pass, diff is reviewed, and 5.5 accepts"
    )
    runtime_guards = {item["id"]: item for item in report["hybrid_runtime_guards"]}
    assert "closed_stdin" in runtime_guards
    assert "hard_step_timeout" in runtime_guards
    assert "stdin=DEVNULL" in runtime_guards["closed_stdin"]["promotion_signal"]
    flow_board = {item["id"]: item for item in report["hybrid_flow_metrics"]}
    assert (
        flow_board["planner_5_5_worker_5_4_mini_verifier_5_5"][
            "estimated_cost_ratio_vs_5_5_flex"
        ]
        == 0.29
    )
    assert report["ideal_codex_flow"][0]["phase"] == "intake"
    access_queue = {item["id"]: item for item in report["marketplace_access_queue"]}
    assert access_queue["kimi_k2_5"]["access_class"] == (
        "bedrock-third-party-agreement"
    )
    assert access_queue["qwen3_next_80b"]["runbook_role"].startswith("Mini scout")
    assert access_queue["qwen3_coder_30b"]["runbook_role"].startswith("Mini coder")
    assert report["runbook_expansion_cases"][0]["id"] == "control_plane_safe_triage"
    synthetic_tickets = {
        item["id"]: item for item in report["synthetic_ticket_scenarios"]
    }
    assert (
        synthetic_tickets["control_plane_route_recovery_ticket"]["expected_owner"]
        == "Control Plane"
    )
    assert (
        "OpenAI Flex usage limit"
        in synthetic_tickets["control_plane_route_recovery_ticket"]["pass_signal"]
    )
    assert (
        synthetic_tickets["stale_bbs_handoff_cleanup_ticket"]["complexity"]
        == "T2 coordination cleanup"
    )
    assert (
        "route mismatch"
        in synthetic_tickets["kpis_route_bedrock_mismatch_ticket"]["pass_signal"]
    )
    assert (
        "low-yield separation"
        in synthetic_tickets["aws_bedrock_support_evidence_ticket"]["pass_signal"]
    )
    assert (
        "newest request"
        in synthetic_tickets["auto_continuation_resume_ticket"]["pass_signal"]
    )
    assert (
        "no-blind-deploy"
        in synthetic_tickets["loading_shell_guard_route_ticket"]["pass_signal"]
    )
    complexity = {
        item["level"]: item for item in report["ticket_complexity_model_matrix"]
    }
    assert complexity["T3"]["model_floor"] == (
        "Bedrock Codex 5.4 planner/verifier; GPT-5.5 only for final mutation authority"
    )
    handoffs = {item["id"]: item for item in report["hybrid_ticket_handoff_prototypes"]}
    assert (
        "credential inspection" in handoffs["ticket_evidence_scout"]["blocked_actions"]
    )
    assert "OpenAI Codex 5.6 Flex" in markdown
    assert "## External Audit Readiness" in markdown
    assert "| Overall matrix readiness | 56% |" in markdown
    assert "production defaults require the additional evidence below" in markdown
    assert "Kimi 2.6" in markdown
    assert "Promotion Playbook" in markdown
    assert "Observed Session Patterns" in markdown
    assert "Workflow Coverage Audit" in markdown
    assert "entity_matching_alias_resolution" in markdown
    assert "queue_interrupt_resume_policy" in markdown
    assert "deploy_devops_cloud_gate" in markdown
    assert "research_compare_websearch_gate" in markdown
    assert "screen_steering_visual_triage" in markdown
    assert "Hybrid Strategy Board" in markdown
    assert "Hybrid Context Routing Patterns" in markdown
    assert "Model Breadth Operating Model" in markdown
    assert "Autonomy Ladder" in markdown
    assert "Hybrid Experiment Ladder" in markdown
    assert "Hybrid Runtime Guards" in markdown
    assert "Hybrid Flow Metrics" in markdown
    assert "Architecture Constraint Matrix" in markdown
    assert "Hybrid TUI canary: `shadow-canary-ready`" in markdown
    assert "Local deterministic no-model" in markdown
    assert "Solo Bedrock Codex 5.5" in markdown
    assert "Ideal Codex Flow" in markdown
    assert (
        "5.4 planner -> 5.4 mini worker -> 5.4 verifier -> 5.5 final if gated"
        in markdown
    )
    assert "AWS Model Access Queue" in markdown
    assert "Control-Plane Runbook Expansion" in markdown
    assert "Synthetic Ticket Scenarios" in markdown
    assert "Control Plane route recovery ticket" in markdown
    assert "GAPHELP-4228 runbook cleanup ticket" in markdown
    assert "HAL disk pressure ticket" in markdown
    assert "Stale BBS handoff cleanup ticket" in markdown
    assert "KPI route Bedrock mismatch ticket" in markdown
    assert "AWS Bedrock support evidence ticket" in markdown
    assert "Auto-continuation resume ticket" in markdown
    assert "Loading-shell guard route ticket" in markdown
    assert "Ticket Complexity Model Matrix" in markdown
    assert "T3" in markdown
    assert "Hybrid Ticket Handoff Prototypes" in markdown
    assert "OpenAI GPT-5.3 Codex xhigh" in markdown
    assert "OpenAI GPT-5.4 Mini high" in markdown
    assert "Numeric compaction" in markdown
    assert "status_fast_path_route" in markdown
    assert "Local-first deterministic lane" in markdown
    assert "L4 guarded live action" in markdown


def test_numeric_context_compaction_scorer_rewards_small_reasoning_context(
    monkeypatch,
) -> None:
    module = _load_provider_benchmark(monkeypatch)
    case = next(
        case for case in module.CASES if case.id == "numeric_context_compaction_route"
    )

    good_answer = json.dumps(
        {
            "status": "ok",
            "routing_decision": "Use local_preprocess first, cheap_worker for bounded labels, and GPT-5.5 for final reasoning.",
            "local_preprocess": [
                "parse with a local script",
                "aggregate counts",
                "dedupe by episode ID",
                "do not paste raw rows into the model context",
            ],
            "cheap_worker_tasks": [
                "cluster source labels only",
                "draft a non-authoritative table",
            ],
            "reasoning_context": {
                "raw_rows": 22100,
                "unique_episode_ids": 16672,
                "duplicate_rows": 5428,
                "age_hours": {"oldest": 167, "newest": 24},
                "top_sources": {
                    "s3.ustatik.com": 4284,
                    "feeds.soundcloud.com": 1608,
                    "dts.podtrac.com": 1465,
                    "anchor.fm": 1142,
                },
            },
            "caveats": ["Retain raw artifact refs for audit."],
            "operator_summary": "GPT-5.5 should decide from aggregates and samples, not the full row dump.",
        }
    )
    score = module.score_case(case, good_answer)

    assert score.operational_pass is True
    assert score.exact_pass is True
    assert score.failure_kind == ""

    bad_answer = json.dumps(
        {
            "status": "ok",
            "routing_decision": "Send all rows to the model.",
            "local_preprocess": [],
            "cheap_worker_tasks": [],
            "reasoning_context": "Paste every row verbatim so the model can inspect it.",
            "caveats": [],
            "operator_summary": "No special route.",
        }
    )
    bad_score = module.score_case(case, bad_answer)

    assert bad_score.operational_pass is False
    assert bad_score.exact_pass is False
    assert bad_score.failure_kind == "semantic"


def test_hybrid_canary_scorer_separates_draft_worker_from_code_execution(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_provider_benchmark(monkeypatch)
    run_dir = tmp_path / "hybrid"
    run_dir.mkdir()

    _write_json_answer(
        run_dir / "hybrid_5_5_planner_contract.last.txt",
        {
            "allowed_files": [
                "scripts/tui_provider_readiness_benchmark.py",
                "tests/test_tui_provider_readiness_benchmark.py",
            ],
            "forbidden_actions": [
                "deploy",
                "external writes",
                "secrets",
                "broad refactor",
            ],
            "acceptance_tests": ["make format", "make lint", "make test"],
        },
    )
    (run_dir / "hybrid_5_5_planner_contract.jsonl").write_text(
        '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":50}}\n',
        encoding="utf-8",
    )
    _write_json_answer(
        run_dir / "hybrid_5_4_mini_worker_closed_stdin_retry.last.txt",
        {
            "status": "proposed",
            "touched_files": [
                "scripts/tui_provider_readiness_benchmark.py",
                "tests/test_tui_provider_readiness_benchmark.py",
            ],
            "commands_to_run": ["make format", "make lint", "make test"],
            "scope_violation": False,
            "needs_escalation": False,
        },
    )
    (run_dir / "hybrid_5_4_mini_worker_closed_stdin_retry.jsonl").write_text(
        '{"type":"turn.completed","usage":{"input_tokens":160000,"output_tokens":1000}}\n',
        encoding="utf-8",
    )
    (run_dir / "hybrid_5_4_mini_worker_medium_retry.stderr.txt").write_text(
        "Reading additional input from stdin...\n",
        encoding="utf-8",
    )
    _write_json_answer(
        run_dir / "hybrid_5_5_verifier_closed_stdin_retry.last.txt",
        {
            "decision": "reject",
            "scope_ok": True,
            "tests_ok": False,
            "authority_ok": True,
            "escalation_required": True,
        },
    )

    report = module.score_hybrid_canary_artifacts(run_dir)
    rows = {row["artifact"]: row for row in report["rows"]}

    assert report["schema"] == "norman.tui.hybrid-canary-score.v1"
    assert report["summary"]["flow_decision"] == "not_promote_for_code_execution"
    assert report["summary"]["worker_draft_only"] == 1
    assert report["summary"]["worker_execution_passes"] == 0
    assert report["summary"]["verifier_accepts"] == 0
    assert report["summary"]["context_budget_exceeded"] is True
    assert rows["hybrid_5_4_mini_worker_medium_retry"]["verdict"] == (
        "stdin_wait_timeout"
    )
    assert rows["hybrid_5_4_mini_worker_closed_stdin_retry"]["verdict"] == (
        "draft_only"
    )
    assert rows["hybrid_5_5_verifier_closed_stdin_retry"]["verdict"] == (
        "verifier_reject"
    )

    markdown = module.render_hybrid_canary_markdown(report)
    assert "Hybrid Canary Score" in markdown
    assert "Contract-only mini worker" in markdown


def test_hybrid_canary_scorer_requires_passing_test_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_provider_benchmark(monkeypatch)
    run_dir = tmp_path / "hybrid_failed_tests"
    run_dir.mkdir()

    _write_json_answer(
        run_dir / "hybrid_5_5_planner_contract.last.txt",
        {
            "allowed_files": [
                "scripts/tui_provider_readiness_benchmark.py",
                "tests/test_tui_provider_readiness_benchmark.py",
            ],
            "forbidden_actions": [
                "deploy",
                "external writes",
                "secrets",
                "broad refactor",
            ],
            "acceptance_tests": ["make format", "make lint", "make test"],
        },
    )
    _write_json_answer(
        run_dir / "hybrid_5_4_mini_worker_closed_stdin_retry.last.txt",
        {
            "status": "completed_with_test_failure",
            "touched_files": ["scripts/tui_provider_readiness_benchmark.py"],
            "commands_to_run": ["make format", "make lint", "make test"],
            "commands_run": [
                {"cmd": "make format", "exit_code": 0},
                {"cmd": "make lint", "exit_code": 0},
                {"cmd": "make test", "exit_code": 2},
            ],
            "test_results": {
                "make format": {"passed": True},
                "make lint": {"passed": True},
                "make test": {"passed": False},
            },
            "scope_violation": False,
            "needs_escalation": False,
        },
    )
    (run_dir / "hybrid_5_4_mini_worker_closed_stdin_retry.jsonl").write_text(
        '{"type":"turn.completed","usage":{"input_tokens":24000,"output_tokens":1500}}\n',
        encoding="utf-8",
    )
    _write_json_answer(
        run_dir / "hybrid_5_5_verifier_closed_stdin_retry.last.txt",
        {
            "decision": "accept",
            "scope_ok": True,
            "tests_ok": True,
            "authority_ok": True,
        },
    )

    report = module.score_hybrid_canary_artifacts(run_dir)
    rows = {row["artifact"]: row for row in report["rows"]}

    assert rows["hybrid_5_4_mini_worker_closed_stdin_retry"]["verdict"] == (
        "draft_only"
    )
    assert (
        rows["hybrid_5_4_mini_worker_closed_stdin_retry"]["test_proof_present"] is False
    )
    assert report["summary"]["worker_execution_passes"] == 0
    assert report["summary"]["worker_draft_only"] == 1
    assert report["summary"]["verifier_accepts"] == 1
    assert report["summary"]["flow_decision"] == "not_promote_for_code_execution"


def test_hybrid_canary_scorer_accepts_brokered_worker_with_verifier_accept(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_provider_benchmark(monkeypatch)
    run_dir = tmp_path / "hybrid_pass"
    run_dir.mkdir()

    _write_json_answer(
        run_dir / "hybrid_5_5_planner_contract.last.txt",
        {
            "allowed_files": [
                "scripts/tui_provider_readiness_benchmark.py",
                "tests/test_tui_provider_readiness_benchmark.py",
            ],
            "forbidden_actions": [
                "deploy",
                "external writes",
                "secrets",
                "broad refactor",
            ],
            "acceptance_tests": ["make format", "make lint", "make test"],
            "stop_conditions": ["scope drift", "test failure", "timeout"],
        },
    )
    (run_dir / "hybrid_5_5_planner_contract.jsonl").write_text(
        '{"type":"turn.completed","usage":{"input_tokens":1000,"output_tokens":500}}\n',
        encoding="utf-8",
    )
    _write_json_answer(
        run_dir / "hybrid_5_4_mini_worker_closed_stdin_retry.last.txt",
        {
            "status": "executed",
            "touched_files": [
                "scripts/tui_provider_readiness_benchmark.py",
                "tests/test_tui_provider_readiness_benchmark.py",
            ],
            "commands_to_run": ["make format", "make lint", "make test"],
            "tests_run": [
                "make format passed",
                "make lint passed",
                "make test passed",
            ],
            "scope_violation": False,
            "needs_escalation": False,
        },
    )
    (run_dir / "hybrid_5_4_mini_worker_closed_stdin_retry.jsonl").write_text(
        '{"type":"turn.completed","usage":{"input_tokens":24000,"output_tokens":1500}}\n',
        encoding="utf-8",
    )
    _write_json_answer(
        run_dir / "hybrid_5_5_verifier_closed_stdin_retry.last.txt",
        {
            "decision": "accept",
            "scope_ok": True,
            "tests_ok": True,
            "authority_ok": True,
            "escalation_required": False,
        },
    )
    (run_dir / "hybrid_5_5_verifier_closed_stdin_retry.jsonl").write_text(
        '{"type":"turn.completed","usage":{"input_tokens":2000,"output_tokens":500}}\n',
        encoding="utf-8",
    )

    report = module.score_hybrid_canary_artifacts(run_dir)

    assert report["summary"]["flow_decision"] == (
        "candidate_for_brokered_code_execution"
    )
    assert report["summary"]["worker_execution_passes"] == 1
    assert report["summary"]["verifier_accepts"] == 1
    assert report["summary"]["verifier_rejections"] == 0
    assert report["summary"]["context_budget_exceeded"] is False


def test_cli_can_dump_benchmark_prompts(tmp_path: Path, monkeypatch) -> None:
    module = _load_provider_benchmark(monkeypatch)
    output_prompts = tmp_path / "prompts.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tui_provider_readiness_benchmark.py",
            "--dump-prompts",
            str(output_prompts),
        ],
    )

    assert module.main() == 0
    prompts = json.loads(output_prompts.read_text(encoding="utf-8"))
    assert set(prompts) == module.case_ids()
