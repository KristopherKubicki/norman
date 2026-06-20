from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_shadow(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "gaphelp_ticket_loop_shadow",
        scripts_dir / "gaphelp_ticket_loop_shadow.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["gaphelp_ticket_loop_shadow"] = module
    spec.loader.exec_module(module)
    return module


def _policy(report, policy_id: str) -> dict:
    return next(row for row in report["policies"] if row["policy_id"] == policy_id)


def test_watch_only_is_zero_model_cost(monkeypatch) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=25, max_do=5, budget_usd=2.0)
    watch = _policy(report, "watch_only")

    assert report["dry_run_only"] is True
    assert report["model_calls_executed"] == 0
    assert watch["estimated_usd"] == 0.0
    assert watch["steady_state_unchanged_usd"] == 0.0
    assert watch["completed_shadow"] == 0


def test_hybrid_top_policy_is_cheaper_than_full_5_5_for_same_work(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=30, max_do=5, budget_usd=10.0)
    hybrid = _policy(report, "cheap_triage_top5")
    full = _policy(report, "full_5_5_all_safe")

    assert hybrid["completed_shadow"] == full["completed_shadow"] == 5
    assert hybrid["estimated_usd"] < full["estimated_usd"]
    assert hybrid["triaged"] == 30
    assert hybrid["within_budget"] is True


def test_bedrock_5_5_baseline_uses_same_safe_work_with_separate_rate_card(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=30, max_do=5, budget_usd=25.0)
    flex = _policy(report, "full_5_5_all_safe")
    bedrock = _policy(report, "full_bedrock_5_5_all_safe")

    assert bedrock["completed_shadow"] == flex["completed_shadow"] == 5
    assert bedrock["estimated_usd"] > flex["estimated_usd"]
    assert bedrock["within_budget"] is True
    assert (
        report["details"]["full_bedrock_5_5_all_safe"]["completed_shadow_ticket_ids"]
        == (report["details"]["full_5_5_all_safe"]["completed_shadow_ticket_ids"])
    )
    assert (
        report["details"]["full_bedrock_5_5_all_safe"]["cost_lines"][0]["price_basis"]
        == "bedrock-us-east-2"
    )


def test_local_prefilter_hybrid_is_live_recommendation(monkeypatch) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=250, max_do=20, budget_usd=5.0)
    prefilter = _policy(report, "local_prefilter_hybrid_top")
    full = _policy(report, "full_5_5_all_safe")

    assert prefilter["completed_shadow"] == full["completed_shadow"] == 20
    assert prefilter["estimated_usd"] < full["estimated_usd"]
    assert prefilter["triaged"] == 0
    assert report["recommendation"]["policy_id"] == "local_prefilter_hybrid_top"


def test_budget_cap_limits_shadow_execution(monkeypatch) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=100, max_do=10, budget_usd=0.5)
    top10 = _policy(report, "cheap_triage_top10")

    assert top10["within_budget"] is True
    assert top10["estimated_usd"] <= 0.5
    assert top10["completed_shadow"] < 10
    assert top10["skipped_budget"] > 0


def test_batch_policy_is_low_cost_but_not_recommended_for_interactive(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=40, max_do=10, budget_usd=10.0)
    batch = _policy(report, "batch_replay_all_safe")
    full = _policy(report, "full_5_5_all_safe")
    markdown = module.render_markdown(report)

    assert batch["completed_shadow"] == full["completed_shadow"] == 10
    assert batch["estimated_usd"] < full["estimated_usd"]
    assert "not suitable for interactive" in " ".join(batch["notes"])
    assert report["recommendation"]["policy_id"] != "batch_replay_all_safe"
    assert report["offline_recommendation"]["policy_id"] == "batch_replay_all_safe"
    assert "Dry-run only" in markdown


def test_helpdesk_runbook_precision_scores_routes_and_resolution(monkeypatch) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=30, max_do=5, budget_usd=10.0)
    precision = report["helpdesk_runbook_precision"]
    rows = {row["ticket_id"]: row for row in precision["rows"]}

    assert precision["schema"] == "norman.gaphelp-helpdesk-runbook-precision.v2"
    assert precision["case_count"] == 36
    assert precision["route_precision"] >= 0.9
    assert precision["resolution_precision"] >= 0.9
    assert precision["same_runbook_as_oracle_rate"] >= 0.9
    assert precision["same_action_as_oracle_rate"] >= 0.9
    assert precision["oracle_result_parity_rate"] >= 0.9
    assert precision["overreach_count"] == 0
    assert precision["unsafe_final_close_count"] == 0
    assert precision["approval_gate"]["precision"] == 1.0
    assert precision["approval_gate"]["recall"] == 1.0
    assert precision["clarify_gate"]["precision"] == 1.0
    assert precision["clarify_gate"]["recall"] == 1.0
    assert precision["runbook_fit_matrix"]["schema"] == (
        "norman.gaphelp-runbook-fit-matrix.v1"
    )
    assert precision["runbook_fit_matrix"]["coverage_rate"] == 1.0
    assert precision["runbook_fit_matrix"]["missing_runbooks"] == []
    assert precision["oracle_limited_count"] >= 10
    assert precision["oracle_5_5_xhigh_usd"] > precision["estimated_hybrid_usd"]
    assert precision["hybrid_vs_oracle_savings_rate"] > 0
    assert rows["GAPHELP-HD-001"]["selected_runbook"] == "MP"
    assert rows["GAPHELP-HD-004"]["selected_runbook"] == "RDF"
    assert rows["GAPHELP-HD-005"]["selected_runbook"] == "DMR"
    assert rows["GAPHELP-HD-011"]["verdict"] == "approval_stop"
    assert rows["GAPHELP-HD-012"]["verdict"] == "abstain_correct"
    assert rows["GAPHELP-HD-012"]["estimated_hybrid_usd"] == 0.0
    assert rows["GAPHELP-HD-013"]["verdict"] == "abstain_correct"
    assert rows["GAPHELP-HD-014"]["selected_runbook"] == "S2B"
    assert rows["GAPHELP-HD-015"]["selected_runbook"] == "CEI"
    assert rows["GAPHELP-HD-016"]["verdict"] == "approval_stop"
    assert rows["GAPHELP-HD-017"]["selected_runbook"] == "DU"
    assert rows["GAPHELP-HD-021"]["verdict"] == "approval_stop"
    assert rows["GAPHELP-HD-029"]["verdict"] == "approval_stop"
    assert rows["GAPHELP-HD-034"]["verdict"] == "abstain_correct"
    assert rows["GAPHELP-HD-035"]["verdict"] == "abstain_correct"
    assert rows["GAPHELP-HD-036"]["verdict"] == "abstain_correct"
    assert all(row["same_runbook_as_oracle"] for row in rows.values())
    assert all(row["action_matches_oracle"] for row in rows.values())


def test_helpdesk_precision_markdown_surfaces_matrix(monkeypatch) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=10, max_do=3, budget_usd=5.0)
    markdown = module.render_markdown(report)

    assert "Help Desk Runbook Precision" in markdown
    assert "GAPHELP-HD-001" in markdown
    assert "Route precision" in markdown
    assert "Resolution precision" in markdown
    assert "Runbook coverage" in markdown
    assert "Runbook Fit Matrix" in markdown
    assert "5.5 xhigh oracle" in markdown
    assert "Oracle Action" in markdown


def test_benchmark_readiness_assessment_names_shadow_gaps(monkeypatch) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=30, max_do=5, budget_usd=10.0)
    readiness = report["benchmark_readiness_assessment"]
    dimensions = readiness["dimensions"]
    markdown = module.render_markdown(report)

    assert readiness["schema"] == "norman.gaphelp-benchmark-readiness.v1"
    assert readiness["figured_out"] is False
    assert readiness["status"] == "shadow_ready_not_live_truth"
    assert dimensions["pricing_catalog"]["status"] == "shadow_ready"
    assert dimensions["bedrock_first_routing"]["status"] == "shadow_ready"
    assert dimensions["runbook_coverage"]["status"] == "shadow_ready"
    assert dimensions["live_latency_reliability"]["status"] == "not_proven"
    assert "real Jira" in readiness["answer"]
    assert "Benchmark Readiness" in markdown
    assert "live latency reliability" in markdown


def test_live_proof_receipt_updates_readiness_and_markdown(monkeypatch) -> None:
    module = _load_shadow(monkeypatch)
    proof = {
        "schema": "norman.gaphelp-live-proof.v1",
        "run_id": "gaphelp-live-bedrock-canary-test",
        "surface": "leadership-kpis TUI /api/ask",
        "route_request": {
            "runtime": "codex",
            "model": "openai.gpt-5.5",
            "service_tier": "default",
            "route_lock": True,
        },
        "after": {
            "last_runtime": "codex",
            "last_model": "openai.gpt-5.5",
            "last_service_tier": "default",
            "last_error": "",
        },
        "live_turn": {
            "state": "done",
            "runtime": "codex",
            "model": "openai.gpt-5.5",
            "service_tier": "default",
            "elapsed_seconds": 38,
            "observed_input_tokens": 15186,
            "observed_output_tokens": 608,
            "observed_reasoning_output_tokens": 474,
            "observed_total_tokens": 15794,
            "tool_event_count": 0,
            "decision_count": 1,
        },
        "response_preview": json.dumps(
            {
                "selected_runbook": "hubitat_cloud_dependency_504",
                "action": "classify_and_request_evidence",
                "needs_approval": False,
                "needs_clarification": True,
                "confidence": 0.78,
                "safe_next_step": "Ask for cloud and local hub evidence.",
            }
        ),
    }

    report = module.build_report(
        ticket_count=30,
        max_do=5,
        budget_usd=10.0,
        live_proofs=[proof],
    )
    live = report["live_proof_report"]
    readiness = report["benchmark_readiness_assessment"]
    markdown = module.render_markdown(report)

    assert live["summary"]["live_runs"] == 1
    assert live["summary"]["successful_runs"] == 1
    assert live["summary"]["expected_behavior_pass_rate"] == 1.0
    assert live["rows"][0]["route_match"] is True
    assert live["rows"][0]["expected_behavior_pass"] is True
    assert readiness["status"] == "shadow_plus_live_canary_not_jira_truth"
    assert readiness["dimensions"]["live_latency_reliability"]["status"] == (
        "single_canary_observed"
    )
    assert readiness["dimensions"]["real_jira_truth_set"]["status"] == "not_proven"
    assert "Live Provider Proof" in markdown
    assert "gaphelp-live-bedrock-canary-test" in markdown


def test_rate_card_comparison_distinguishes_bedrock_on_demand_from_flex(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=10, max_do=3, budget_usd=5.0)
    comparison = report["rate_card_comparison"]
    markdown = module.render_markdown(report)

    assert comparison["rate_cards_usd_per_1m"]["openai_direct_standard"]["input"] == 5.0
    assert comparison["rate_cards_usd_per_1m"]["openai_direct_flex"]["input"] == 2.5
    assert (
        comparison["rate_cards_usd_per_1m"]["openai_direct_gpt_5_5_priority_fast"][
            "input"
        ]
        == 12.5
    )
    assert (
        comparison["rate_cards_usd_per_1m"]["openai_direct_gpt_5_4_priority_fast"][
            "output"
        ]
        == 37.5
    )
    assert (
        comparison["rate_cards_usd_per_1m"]["bedrock_us_east_2_on_demand"]["input"]
        == 5.5
    )
    assert comparison["bedrock_vs_openai_standard"]["input_ratio"] == 1.1
    assert comparison["bedrock_vs_openai_flex"]["input_ratio"] == 2.2
    assert comparison["bedrock_gpt_5_4_vs_5_5"]["input_ratio"] == 0.5
    assert comparison["bedrock_gpt_5_4_vs_5_5"]["output_ratio"] == 0.5
    assert comparison["openai_gpt_5_4_vs_5_5_standard"]["input_ratio"] == 0.5
    assert "Bedrock GPT-5.5 on-demand vs OpenAI Flex" in markdown


def test_model_capability_price_matrix_surfaces_cheaper_bedrock_lanes(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=30, max_do=5, budget_usd=25.0)
    matrix = report["model_capability_price_matrix"]
    markdown = module.render_markdown(report)
    rows = {row["route_id"]: row for row in matrix["rows"]}

    bedrock_5_5 = rows["bedrock_openai_gpt_5_5_ondemand_us_east_2"]
    bedrock_5_4 = rows["bedrock_openai_gpt_5_4_ondemand_us_east_2"]
    openai_5_5_priority = rows["openai_direct_gpt_5_5_priority"]
    openai_5_5_standard = rows["openai_direct_gpt_5_5_standard"]
    openai_5_5_flex = rows["openai_direct_gpt_5_5_flex"]
    gpt_oss_20b_flex = rows["bedrock_gpt_oss_20b_flex_ap_southeast_2"]
    qwen_coder_flex = rows["bedrock_qwen3_coder_30b_flex_ap_southeast_2"]
    kimi = rows["bedrock_moonshot_kimi_k2_5_standard_us"]

    assert matrix["schema"] == "norman.gaphelp-model-capability-price-matrix.v1"
    assert matrix["model_count"] >= 18
    assert (
        matrix["cost_baselines"]["openai_5_5_frontier_fast_100"]["route_id"]
        == "openai_direct_gpt_5_5_priority"
    )
    assert bedrock_5_5["input_usd_per_1m"] == 5.5
    assert bedrock_5_4["input_usd_per_1m"] == 2.75
    assert bedrock_5_5["context_window_tokens"] == 272_000
    assert bedrock_5_4["context_window_tokens"] == 272_000
    assert bedrock_5_4["full_safe_tickets_usd"] < bedrock_5_5["full_safe_tickets_usd"]
    assert bedrock_5_4["full_safe_ratio_vs_bedrock_5_5_ondemand"] == 0.5
    assert openai_5_5_priority["latency_class"] == "fast"
    assert openai_5_5_priority["input_usd_per_1m"] == 12.5
    assert openai_5_5_priority["output_usd_per_1m"] == 75.0
    assert openai_5_5_priority["full_safe_cost_percent_vs_frontier_fast"] == 100.0
    assert openai_5_5_priority["full_safe_savings_percent_vs_frontier_fast"] == 0.0
    assert openai_5_5_standard["full_safe_cost_percent_vs_frontier_fast"] == 40.0
    assert openai_5_5_flex["full_safe_cost_percent_vs_frontier_fast"] == 20.0
    assert 43.0 <= bedrock_5_5["full_safe_cost_percent_vs_frontier_fast"] <= 45.0
    assert 21.0 <= bedrock_5_4["full_safe_cost_percent_vs_frontier_fast"] <= 23.0
    assert gpt_oss_20b_flex["supports_flex"] is True
    assert (
        gpt_oss_20b_flex["full_safe_tickets_usd"] < bedrock_5_4["full_safe_tickets_usd"]
    )
    assert "triage" in gpt_oss_20b_flex["recommended_roles"]
    assert qwen_coder_flex["supports_batch"] is True
    assert kimi["context_window_tokens"] == 256_000
    assert kimi["max_output_tokens"] == 16_000
    assert kimi["final_role"] == "none until tools wired"
    assert kimi["eligible_runbook_scope"] == "route all; safe draft only"
    assert matrix["findings"]["kimi_route"] == "bedrock_moonshot_kimi_k2_5_standard_us"
    assert "openai_direct_gpt_5_5_priority" in matrix["findings"]["fast_routes"]
    assert matrix["findings"]["cheapest_frontier_or_strong_route"] in {
        "openai_direct_gpt_5_4_batch",
        "openai_direct_gpt_5_4_flex",
    }
    assert "Model Capability / Price Matrix" in markdown
    assert "bedrock_gpt_oss_20b_flex_ap_southeast_2" in markdown
    assert "OpenAI GPT-5.5 priority fast is the 100% cost baseline" in markdown
    assert "Fast=100%" in markdown
    assert "Savings vs Fast" in markdown
    assert "OpenAI GPT-5.5 priority fast" in markdown
    assert "Bedrock Moonshot Kimi K2.5 standard" in markdown


def test_control_plane_threshold_matrix_finds_minimum_model_per_issue_class(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=30, max_do=5, budget_usd=25.0)
    matrix = report["control_plane_threshold_matrix"]
    rows = {row["issue_id"]: row for row in matrix["rows"]}
    markdown = module.render_markdown(report)

    assert matrix["schema"] == "norman.control-plane-ticket-threshold-matrix.v1"
    assert matrix["evidence_level"].startswith("shadow_heuristic")
    assert rows["watch_status_inventory"]["minimum_candidate"]["candidate_id"] == (
        "local_deterministic"
    )
    clear_runbook = rows["clear_runbook_selection"]
    assert clear_runbook["minimum_candidate"]["candidate_id"] == (
        "dgx_spark_qwen3_coder_high"
    )
    assert clear_runbook["minimum_candidate"]["provider_surface"] == ("local-dgx-spark")
    assert clear_runbook["minimum_candidate"]["status"] == "shadow"
    assert (
        clear_runbook["minimum_candidate"]["final_role"]
        == "no external final authority"
    )
    assert {row["candidate_id"] for row in clear_runbook["candidate_rows"]} >= {
        "bedrock_gpt_oss_120b_medium",
        "dgx_spark_qwen3_coder_high",
    }
    assert (
        rows["safe_low_risk_ticket_draft"]["gpt_5_4_medium_comparison"][
            "meets_threshold"
        ]
        is True
    )
    assert rows["leaf_code_patch_with_tests"]["minimum_candidate"]["candidate_id"] == (
        "openai_gpt_5_4_medium"
    )
    assert (
        rows["deploy_cloud_or_netops_change"]["gpt_5_4_medium_comparison"][
            "meets_threshold"
        ]
        is False
    )
    assert (
        rows["deploy_cloud_or_netops_change"]["gpt_5_4_medium_comparison"][
            "parity_vs_5_5_xhigh"
        ]
        == "not-enough"
    )
    assert matrix["summary"]["gpt_5_4_medium_not_enough_count"] >= 1
    assert "Control Plane Ticket Threshold Matrix" in markdown


def test_threshold_candidate_profiles_cover_catalog_routes(monkeypatch) -> None:
    module = _load_shadow(monkeypatch)

    catalog_routes = {entry.route_id for entry in module.model_catalog_entries()}
    profiles = module.threshold_candidate_profiles()
    missing = {
        profile.catalog_route_id
        for profile in profiles
        if profile.catalog_route_id and profile.catalog_route_id not in catalog_routes
    }

    assert not missing
    assert len(profiles) >= 28
    assert {profile.reasoning_effort for profile in profiles} >= {
        "low",
        "medium",
        "high",
        "xhigh",
    }


def test_control_plane_threshold_matrix_tracks_5_5_effort_ladder(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=30, max_do=5, budget_usd=25.0)
    matrix = report["control_plane_threshold_matrix"]
    rows = {row["issue_id"]: row for row in matrix["rows"]}
    deploy_ladder = rows["deploy_cloud_or_netops_change"]["gpt_5_5_effort_ladder"][
        "openai_direct_flex"
    ]
    priority_ladder = rows["deploy_cloud_or_netops_change"]["gpt_5_5_effort_ladder"][
        "openai_direct_priority"
    ]
    numeric_ladder = rows["exact_numeric_or_revenue_reconcile"][
        "gpt_5_5_effort_ladder"
    ]["openai_direct_flex"]
    tiers = deploy_ladder["tiers"]

    assert set(tiers) == {"low", "medium", "high", "xhigh"}
    assert tiers["low"]["cost_usd"] < tiers["medium"]["cost_usd"]
    assert tiers["medium"]["cost_usd"] < tiers["high"]["cost_usd"]
    assert tiers["high"]["cost_usd"] < tiers["xhigh"]["cost_usd"]
    assert tiers["low"]["strict_accuracy"] <= tiers["medium"]["strict_accuracy"]
    assert tiers["medium"]["strict_accuracy"] <= tiers["high"]["strict_accuracy"]
    assert tiers["high"]["strict_accuracy"] <= tiers["xhigh"]["strict_accuracy"]
    assert priority_ladder["tiers"]["medium"]["latency_class"] == "fast"
    assert (
        priority_ladder["tiers"]["medium"]["cost_usd"]
        > deploy_ladder["tiers"]["medium"]["cost_usd"]
    )
    assert deploy_ladder["cheapest_passing"]["candidate_id"] in {
        "openai_gpt_5_5_medium",
        "openai_gpt_5_5_high",
        "openai_gpt_5_5_xhigh",
    }
    assert numeric_ladder["tiers"]["low"]["meets_threshold"] is False
    assert "low_effort_not_verifier" in numeric_ladder["tiers"]["low"]["blocked_reason"]
    assert numeric_ladder["cheapest_passing"]["candidate_id"] in {
        "openai_gpt_5_5_medium",
        "openai_gpt_5_5_high",
        "openai_gpt_5_5_xhigh",
    }
    assert (
        sum(matrix["summary"]["gpt_5_5_openai_effort_minimum_counts"].values())
        == matrix["issue_class_count"]
    )
    assert (
        sum(matrix["summary"]["gpt_5_5_openai_priority_effort_minimum_counts"].values())
        == matrix["issue_class_count"]
    )


def test_threshold_matrix_blocks_scouts_from_high_authority_close(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=30, max_do=5, budget_usd=25.0)
    issue_rows = {
        row["issue_id"]: row for row in report["control_plane_threshold_matrix"]["rows"]
    }
    deploy = {
        row["candidate_id"]: row
        for row in issue_rows["deploy_cloud_or_netops_change"]["candidate_rows"]
    }

    assert deploy["bedrock_gpt_oss_120b_high"]["meets_threshold"] is False
    assert (
        "requires_frontier_verifier"
        in deploy["bedrock_gpt_oss_120b_high"]["blocked_reason"]
    )
    assert deploy["openai_gpt_5_5_high"]["meets_threshold"] is True
    assert (
        deploy["openai_gpt_5_5_xhigh"]["cost_usd"]
        > deploy["openai_gpt_5_5_high"]["cost_usd"]
    )


def test_role_split_matrix_separates_subagent_from_final_verifier(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=30, max_do=5, budget_usd=25.0)
    matrix = report["role_split_matrix"]
    bedrock_matrix = report["bedrock_role_split_matrix"]
    rows = {row["issue_id"]: row for row in matrix["rows"]}
    bedrock_rows = {row["issue_id"]: row for row in bedrock_matrix["rows"]}
    runbook = rows["clear_runbook_selection"]
    deploy = rows["deploy_cloud_or_netops_change"]
    bedrock_runbook = bedrock_rows["clear_runbook_selection"]
    bedrock_deploy = bedrock_rows["deploy_cloud_or_netops_change"]
    markdown = module.render_markdown(report)

    assert matrix["schema"] == "norman.control-plane-role-split-matrix.v1"
    assert matrix["issue_class_count"] == len(module.CONTROL_PLANE_ISSUE_CLASSES)
    assert matrix["summary"]["final_required_count"] >= 4
    assert bedrock_matrix["summary"]["provider_preference"] == "bedrock"
    assert runbook["final_candidate"] is None
    assert (
        runbook["subagent_candidate"]["candidate_id"] == "bedrock_gpt_oss_120b_medium"
    )
    assert bedrock_runbook["final_candidate"] is None
    assert bedrock_runbook["subagent_candidate"]["provider_surface"] == "aws-bedrock"
    assert (
        deploy["subagent_candidate"]["candidate_id"]
        != deploy["final_candidate"]["candidate_id"]
    )
    assert deploy["final_candidate"]["can_high_authority"] is True
    assert deploy["final_candidate"]["can_final_close"] is True
    assert bedrock_deploy["final_candidate"]["candidate_id"] == "bedrock_gpt_5_4_high"
    assert bedrock_deploy["final_candidate"]["provider_surface"] == "aws-bedrock"
    for row in bedrock_matrix["rows"]:
        for candidate_key in ("subagent_candidate", "final_candidate"):
            candidate = row.get(candidate_key)
            if candidate:
                assert candidate["provider_surface"] in {"local", "aws-bedrock"}
    assert deploy["combined_cost_usd"] > deploy["subagent_cost_usd"]
    assert "priority only for urgent verifier" in deploy["timing_policy"]
    assert "Role Split / Pipeline Matrix" in markdown
    assert "Bedrock-Preferred Role Split" in markdown
    assert "Bedrock GPT-5.4 high" in markdown
    assert "Cheap / Fast / Safe Implementation Changes" in markdown


def test_foundational_skill_matrix_models_bedrock_delegation_ladder(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=30, max_do=5, budget_usd=25.0)
    matrix = report["foundational_skill_matrix"]
    rows = {row["skill_id"]: row for row in matrix["rows"]}
    local = rows["local_status_inventory"]
    status_answer = rows["tui_operator_status_answer"]
    retrieval = rows["right_data_artifact_lookup"]
    code = rows["simple_code_patch_or_parser_fix"]
    root_cause = rows["multi_source_root_cause_synthesis"]
    governance = rows["approval_boundary_detection"]
    final = rows["high_authority_final_decision"]
    markdown = module.render_markdown(report)

    assert matrix["schema"] == "norman.control-plane-foundational-skill-matrix.v1"
    assert matrix["skill_count"] >= 20
    assert (
        matrix["summary"]["recommended_bedrock_pipeline_total_usd"]
        < (matrix["summary"]["all_bedrock_5_5_xhigh_total_usd"])
    )
    assert matrix["summary"]["savings_vs_all_bedrock_5_5_xhigh"] > 0.25
    assert matrix["summary"]["cheap_worker_count"] >= 6
    assert matrix["summary"]["bedrock_5_4_xhigh_heavy_lift_count"] >= 4
    assert matrix["summary"]["bedrock_5_5_xhigh_final_count"] == 1

    assert local["recommended_pipeline"][0]["candidate_id"] == "local_deterministic"
    assert status_answer["recommended_pipeline"][0]["provider_surface"] == "aws-bedrock"
    assert not status_answer["recommended_pipeline"][0]["candidate_id"].startswith(
        "bedrock_gpt_5"
    )
    assert retrieval["draft_worker"]["provider_surface"] == "aws-bedrock"
    assert not retrieval["draft_worker"]["candidate_id"].startswith("bedrock_gpt_5")
    assert code["recommended_pipeline"][0]["candidate_id"] in {
        "bedrock_gpt_oss_120b_medium",
        "bedrock_qwen3_coder_medium",
        "bedrock_qwen3_coder_high",
    }
    assert root_cause["requires_5_4_heavy_lift"] is True
    assert any(
        step["candidate_id"] == "bedrock_gpt_5_4_xhigh"
        for step in root_cause["recommended_pipeline"]
    )
    assert governance["bedrock_5_4_xhigh_heavy_lift"]["meets_threshold"] is True
    assert any(
        step["candidate_id"] == "bedrock_gpt_5_4_xhigh"
        for step in governance["recommended_pipeline"]
    )
    assert final["requires_5_5_verifier"] is True
    assert any(
        step["candidate_id"] == "bedrock_gpt_5_5_xhigh"
        for step in final["recommended_pipeline"]
    )
    assert (
        final["recommended_pipeline_cost_usd"]
        < final["all_bedrock_5_5_xhigh_cost_usd"] * 2.0
    )
    assert "Foundational Skill Delegation Matrix" in markdown
    assert "TUI Operator Workflow Matrix" in markdown
    assert "Bedrock GPT-5.4 xhigh" in markdown
    assert "Bedrock GPT-5.5 xhigh" in markdown


def test_tui_operator_workflow_matrix_covers_common_undocumented_skills(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=30, max_do=5, budget_usd=25.0)
    matrix = report["tui_operator_workflow_matrix"]
    rows = {row["workflow_id"]: row for row in matrix["rows"]}
    status_answer = rows["tui_operator_status_answer"]
    queue = rows["tui_queue_interrupt_recovery"]
    undo = rows["tui_safe_undo_or_unwind_gate"]
    bbs = rows["tui_bbs_close_loop_decision"]
    tenant = rows["tui_tenant_purse_route_check"]
    markdown = module.render_markdown(report)

    assert matrix["schema"] == "norman.tui-operator-workflow-skill-matrix.v1"
    assert matrix["workflow_count"] >= 10
    assert (
        matrix["summary"]["recommended_bedrock_pipeline_total_usd"]
        < matrix["summary"]["all_bedrock_5_5_xhigh_total_usd"]
    )
    assert matrix["summary"]["cheap_worker_count"] >= 3
    assert matrix["summary"]["bedrock_5_4_gate_count"] >= 4
    assert matrix["summary"]["bedrock_5_5_final_count"] == 0
    assert status_answer["autonomy_status"] == "lower_model_shadow_ok"
    assert queue["autonomy_status"] == "lower_model_shadow_ok"
    assert undo["autonomy_status"] == "worker_only_until_5_4_gate"
    assert bbs["autonomy_status"] == "worker_only_until_5_4_gate"
    assert tenant["autonomy_status"] == "worker_only_until_5_4_gate"
    assert "Operator status answer" in markdown
    assert "Safe undo/unwind gate" in markdown


def test_gaphelp_scenario_deployment_matrix_ranks_tui_rollout_and_gates(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=30, max_do=5, budget_usd=25.0)
    matrix = report["gaphelp_scenario_deployment_matrix"]
    summary = matrix["summary"]
    rows = {row["scenario_id"]: row for row in matrix["rows"]}
    route = rows["gaphelp_clear_route_and_evidence_terms"]
    numeric = rows["gaphelp_numeric_data_fix_reconcile"]
    netops = rows["netops_deploy_or_route_change"]
    compere = rows["compere_keystone_compare_status"]

    assert matrix["schema"] == "norman.gaphelp-scenario-deployment-matrix.v1"
    assert matrix["scenario_count"] >= 12
    assert summary["recommended_first_tui"] == "compere"
    assert summary["first_gaphelp_tui"] == "control-plane"
    assert summary["deploy_candidate_count"] >= 7
    assert summary["lower_model_shadow_canary_count"] >= 4
    assert summary["bedrock_5_5_final_hold_count"] >= 2
    assert summary["savings_vs_all_bedrock_5_5_xhigh"] > 0.0
    assert (
        summary["deploy_candidate_cost_summary"]["savings_vs_all_bedrock_5_5_xhigh"]
        > 0.35
    )
    assert (
        summary["phase_1_canary_cost_summary"]["savings_vs_all_bedrock_5_5_xhigh"]
        > 0.85
    )

    assert compere["recommended_first_tui"] is True
    assert compere["autonomy_status"] == "lower_model_shadow_ok"
    assert compere["deploy_candidate"] is True
    assert "external writes" in compere["blocked_actions"]

    assert route["owner_tui"] == "control-plane"
    assert route["autonomy_status"] == "lower_model_shadow_ok"
    assert route["helpdesk_oracle_parity_rate"] == 1.0
    assert route["pipeline"][0]["provider_surface"] == "aws-bedrock"
    assert not route["pipeline_candidate_ids"][0].startswith("bedrock_gpt_5_5")
    assert "BBS ACK" in route["blocked_actions"]

    assert numeric["autonomy_status"] == "final_authority_hold"
    assert "bedrock_gpt_5_5_xhigh" in numeric["pipeline_candidate_ids"]
    assert "customer-visible number change" in numeric["blocked_actions"]
    assert netops["deploy_candidate"] is False
    assert netops["autonomy_status"] == "final_authority_hold"
    assert "restart" in netops["blocked_actions"]


def test_gaphelp_scenario_deployment_markdown_surfaces_rollout_plan(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    report = module.build_report(ticket_count=30, max_do=5, budget_usd=25.0)
    markdown = module.render_markdown(report)

    assert "Scenario Deployment Matrix" in markdown
    assert "Recommended first TUI: `compere`" in markdown
    assert "First GapHelp TUI: `control-plane`" in markdown
    assert "GapHelp clear runbook route and evidence terms" in markdown
    assert "WebGOAT XPath/search and merchant onboarding" in markdown
    assert "Gold Book attribute fill, validation builder, and category creation" in (
        markdown
    )
    assert "Deploy-candidate savings vs all Bedrock 5.5 xhigh" in markdown
    assert "Phase-1 canary savings vs all Bedrock 5.5 xhigh" in markdown
    assert "phase_4_bedrock_5_5_final_authority_hold" in markdown
    assert "Blind spots before deploy" in markdown


def test_control_plane_threshold_markdown_surfaces_5_5_effort_ladder(
    monkeypatch,
) -> None:
    module = _load_shadow(monkeypatch)

    markdown = module.render_markdown(
        module.build_report(ticket_count=30, max_do=5, budget_usd=25.0)
    )

    assert "### GPT-5.5 Effort Ladder" in markdown
    assert "OpenAI GPT-5.5 high" in markdown
    assert "OpenAI GPT-5.5 priority high" in markdown
    assert "Bedrock GPT-5.5 high" in markdown
    assert "OpenAI 5.5 cheapest passing efforts" in markdown


def test_cli_writes_shadow_artifacts_and_optional_ledger(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_shadow(monkeypatch)
    output_json = tmp_path / "gaphelp.json"
    output_md = tmp_path / "gaphelp.md"
    ledger = tmp_path / "ledger.jsonl"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gaphelp_ticket_loop_shadow.py",
            "--ticket-count",
            "20",
            "--max-do",
            "5",
            "--budget-usd",
            "2.0",
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--ledger-jsonl",
            str(ledger),
            "--ticket-id",
            "shadow-test",
            "--helpdesk-case-count",
            "8",
            "--write-ledger",
        ],
    )

    assert module.main() == 0

    report = json.loads(output_json.read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert report["ticket_count"] == 20
    assert report["helpdesk_runbook_precision"]["case_count"] == 8
    assert output_md.read_text(encoding="utf-8").startswith(
        "# GAPHELP Ticket Loop Shadow Benchmark"
    )
    assert len(records) == 1
    assert records[0]["ticket"]["id"] == "shadow-test"
    assert (
        records[0]["cost"]["estimated_usd"] == report["recommendation"]["estimated_usd"]
    )
    recommended_policy = report["recommendation"]["policy_id"]
    recommended_lines = report["details"][recommended_policy]["cost_lines"]
    assert records[0]["usage"]["input_tokens"] == sum(
        line["input_tokens"] for line in recommended_lines
    )
