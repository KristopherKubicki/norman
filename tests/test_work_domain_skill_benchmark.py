from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_benchmark(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "work_domain_skill_benchmark",
        scripts_dir / "work_domain_skill_benchmark.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["work_domain_skill_benchmark"] = module
    spec.loader.exec_module(module)
    return module


def _rows_by_id(report: dict) -> dict[str, dict]:
    return {str(row["skill_id"]): row for row in report["rows"]}


def test_work_domain_skill_matrix_covers_core_work_domains(monkeypatch) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report()

    assert report["schema"] == "norman.work-domain-skill-benchmark.v1"
    assert report["dry_run_only"] is True
    assert report["model_calls_executed"] == 0
    assert report["skill_count"] >= 360
    assert set(report["summary_by_domain"]) == {
        "bbs",
        "coding",
        "comms",
        "confluence-data-ops",
        "connectivity",
        "control-plane",
        "control-plane-gap-audit",
        "control-plane-runbooks",
        "cost-control",
        "customer-dashboard-ops",
        "data-fix",
        "data-operations",
        "data-pipelines",
        "file-comprehension",
        "gold-book",
        "golem-policy",
        "hal",
        "hal-workflows",
        "helpdesk",
        "iridium-code",
        "keystone",
        "model-routing",
        "netops",
        "network-topology",
        "runbook-governance",
        "source-reconstruction",
        "tui-ops",
        "webgoat",
        "workbook-data-ops",
    }
    assert (
        report["summary"]["recommended_bedrock_pipeline_total_usd"]
        < report["summary"]["all_bedrock_5_5_xhigh_total_usd"]
    )
    assert report["summary"]["bedrock_5_4_xhigh_heavy_lift_count"] >= 8
    assert report["summary"]["bedrock_5_5_xhigh_final_count"] >= 10
    assert report["summary"]["lower_model_final_count"] >= 10
    assert (
        report["lower_model_comfort"]["comfortable_shadow_lower_model_final_count"]
        >= 90
    )
    assert (
        report["hybrid_assurance"]["accepted_hybrid_skill_count"]
        == report["skill_count"]
    )
    assert (
        report["hybrid_assurance"]["quality_equivalent_or_guarded_count"]
        == report["skill_count"]
    )
    assert report["hybrid_assurance"]["cheaper_than_all_5_5_count"] >= 200
    assert report["hybrid_assurance"]["not_ready_skill_ids"] == []
    assert report["hybrid_assurance"]["unguarded_lower_model_final_count"] == 0
    assert "code" in report["summary_by_family"]
    assert "compere" in report["summary_by_owner_tui"]
    assert report["priority_focus"]["domains"] == [
        "control-plane",
        "control-plane-runbooks",
        "confluence-data-ops",
        "runbook-governance",
        "gold-book",
    ]
    assert report["priority_focus"]["owners"] == ["control-plane", "gold-book"]
    assert report["priority_focus"]["domain_skill_count"] >= 30
    assert report["priority_focus"]["owner_skill_count"] >= 20
    assert "phase_4_final_authority_hold" in report["rollout_gates"]["phase_counts"]


def test_regular_workload_pack_covers_runbooks_topology_code_and_data_ops(
    monkeypatch,
) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report()
    rows = _rows_by_id(report)
    generated = [
        row for row in report["rows"] if row["skill_id"].startswith("regular_")
    ]

    assert len(generated) == 144
    for domain in {
        "coding",
        "confluence-data-ops",
        "connectivity",
        "control-plane-runbooks",
        "customer-dashboard-ops",
        "data-operations",
        "file-comprehension",
        "golem-policy",
        "iridium-code",
        "network-topology",
        "source-reconstruction",
        "workbook-data-ops",
    }:
        assert report["summary_by_domain"][domain]["skill_count"] == 12

    topology = rows["regular_network_topology_connectivity_probe"]
    golem = rows["regular_golem_policy_inventory_lookup"]
    iridium = rows["regular_iridium_code_contract_extraction"]
    coding = rows["regular_coding_benchmarks_coding_patch"]
    file_read = rows["regular_file_comprehension_file_comprehension"]
    confluence = rows["regular_confluence_data_ops_data_reconciliation"]
    data_apply = rows["regular_data_operations_final_apply_decision"]
    workbook = rows["regular_workbook_data_ops_diff_validation"]

    assert topology["owner_tui"] == "netops"
    assert "topology" in " ".join(topology["tools"]).lower()
    assert "GOLEM.md" in " ".join(golem["runbooks"])
    assert "fabricating" in " ".join(golem["examples"])
    assert "Iridium Corporate Content Rules" in " ".join(iridium["runbooks"])
    assert "conflict detector" in iridium["tools"]
    assert coding["family"] == "code"
    assert "pytest" in coding["tools"]
    assert file_read["lower_model_readiness"]["has_deterministic_validator"] is True
    assert "source citation validator" in file_read["tools"]
    assert confluence["uses_bedrock_5_4_xhigh"] is True
    assert "runbook contract pack" in confluence["tools"]
    assert data_apply["uses_bedrock_5_5_xhigh"] is True
    assert data_apply["lower_model_readiness"]["status"] == "frontier_final_required"
    assert workbook["uses_bedrock_5_4_xhigh"] is True
    assert "row-count reconciliation" in workbook["tools"]


def test_simple_work_delegates_to_cheaper_bedrock_workers(monkeypatch) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report()
    rows = _rows_by_id(report)
    selector = rows["webgoat_basic_xpath_selector"]
    attribute = rows["goldbook_simple_attribute_fill"]

    assert selector["uses_cheap_worker"] is True
    assert attribute["uses_cheap_worker"] is True
    assert not selector["uses_bedrock_5_5_xhigh"]
    assert not attribute["uses_bedrock_5_5_xhigh"]
    assert (
        selector["lower_model_readiness"]["status"]
        == "comfortable_shadow_lower_model_final"
    )
    assert (
        attribute["lower_model_readiness"]["status"]
        == "comfortable_shadow_lower_model_final"
    )
    assert (
        selector["recommended_pipeline_cost_usd"]
        < selector["all_bedrock_5_5_xhigh_cost_usd"]
    )
    assert (
        attribute["recommended_pipeline_cost_usd"]
        < attribute["all_bedrock_5_5_xhigh_cost_usd"]
    )
    assert (
        selector["hybrid_vs_all_5_5"]["verdict"]
        == "accept_cost_superior_guarded_quality"
    )
    assert (
        attribute["hybrid_vs_all_5_5"]["quality_equivalence"]
        == "bounded_guarded_equivalent"
    )


def test_hybrid_assurance_requires_guarded_quality_not_just_savings(
    monkeypatch,
) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report()
    rows = _rows_by_id(report)
    assurance = report["hybrid_assurance"]
    evidence = rows["goldbook_source_evidence_lookup"]
    final_close = rows["helpdesk_final_ticket_close_authority"]

    assert assurance["schema"] == "norman.hybrid-assurance-vs-all-5-5.v1"
    assert assurance["accepted_hybrid_skill_count"] == report["skill_count"]
    assert assurance["not_ready_skill_ids"] == []
    assert (
        assurance["raw_strict_accuracy_below_5_5_but_guarded_count"]
        == assurance["raw_strict_accuracy_below_5_5_count"]
    )
    assert "accept_cost_superior_guarded_quality" in assurance["verdict_counts"]
    assert "accept_safety_first_frontier_hold" in assurance["verdict_counts"]

    assert (
        evidence["lower_model_readiness"]["status"]
        == "comfortable_shadow_lower_model_final"
    )
    assert evidence["lower_model_readiness"]["has_deterministic_validator"] is True
    assert evidence["rollout_gate"]["phase"] == "phase_1_lower_model_shadow_canary"
    assert (
        evidence["hybrid_vs_all_5_5"]["verdict"]
        == "accept_cost_superior_guarded_quality"
    )

    assert final_close["hybrid_vs_all_5_5"]["cheaper_than_all_5_5"] is False
    assert (
        final_close["hybrid_vs_all_5_5"]["verdict"]
        == "accept_safety_first_frontier_hold"
    )
    assert final_close["hybrid_vs_all_5_5"]["assurance_mode"] == "frontier_final_hold"


def test_model_routing_rubric_explains_small_medium_5_4_and_5_5(
    monkeypatch,
) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report()
    rows = _rows_by_id(report)
    rubric = report["model_routing_rubric"]
    selector = rows["webgoat_basic_xpath_selector"]
    attribute = rows["goldbook_simple_attribute_fill"]
    status = rows["tui_core_status_answer_contract"]
    validator = rows["goldbook_cross_field_validator"]
    final_apply = rows["netops_live_caddy_apply_final"]
    undo = rows["tui_core_undo_backtrack_scope_gate"]
    script_lookup = rows["control_plane_script_catalog_lookup"]

    assert rubric["schema"] == "norman.model-routing-rubric.v1"
    assert rubric["skill_count"] == report["skill_count"]
    assert rubric["tier_counts"]["small_bedrock_worker"] > 0
    assert rubric["tier_counts"]["medium_bedrock_worker"] > 0
    assert rubric["tier_counts"]["bedrock_gpt_5_4_xhigh_verifier"] > 0
    assert rubric["tier_counts"]["bedrock_gpt_5_5_xhigh_final"] > 0
    assert rubric["small_or_local_count"] < rubric["medium_or_below_count"]
    assert report["summary"]["model_routing_tier_counts"] == rubric["tier_counts"]
    assert (
        report["summary"]["requires_5_4_verifier_count"]
        == rubric["requires_5_4_verifier_count"]
    )
    assert (
        report["summary"]["requires_5_5_final_count"]
        == rubric["requires_5_5_final_count"]
    )

    assert (
        selector["model_routing_decision"]["minimum_model_tier"]
        == "small_bedrock_worker"
    )
    assert (
        attribute["model_routing_decision"]["minimum_model_tier"]
        == "small_bedrock_worker"
    )
    assert (
        status["model_routing_decision"]["minimum_model_tier"]
        == "medium_bedrock_worker"
    )
    assert status["model_routing_decision"]["small_model_allowed"] is False
    assert status["model_routing_decision"]["medium_model_allowed"] is True
    assert (
        validator["model_routing_decision"]["minimum_model_tier"]
        == "bedrock_gpt_5_4_xhigh_verifier"
    )
    assert (
        "deterministic validator fails or is missing"
        in validator["model_routing_decision"]["escalate_to_5_4_when"]
    )
    assert (
        final_apply["model_routing_decision"]["minimum_model_tier"]
        == "bedrock_gpt_5_5_xhigh_final"
    )
    assert final_apply["model_routing_decision"]["requires_5_5_final"] is True
    assert undo["model_routing_decision"]["requires_5_5_final"] is True
    assert (
        "undo/back requires external rollback, reopen, or mutation"
        in undo["model_routing_decision"]["escalate_to_5_5_when"]
    )
    assert script_lookup["model_routing_decision"]["small_model_allowed"] is True


def test_model_capability_probe_matrix_compares_reasoning_tools_and_handoffs(
    monkeypatch,
) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report()
    matrix = report["model_capability_probe_matrix"]
    candidates = matrix["candidate_summary"]
    probes = matrix["probe_summary"]

    assert matrix["schema"] == "norman.model-capability-probe-matrix.v1"
    assert matrix["dry_run_only"] is True
    assert matrix["model_calls_executed"] == 0
    assert matrix["probe_count"] == 40
    assert matrix["candidate_count"] == 15
    assert matrix["cell_count"] == 600
    assert set(matrix["capabilities"]) == {
        "bbs-handoffs",
        "coding",
        "connectors",
        "file-comprehension",
        "planning",
        "time-estimation",
        "tools",
        "truthiness",
    }
    assert report["summary"]["capability_probe_cell_count"] == 600

    mini = candidates["openai_gpt_5_4_mini_high"]
    gpt_54 = candidates["openai_gpt_5_4_xhigh"]
    gpt_55 = candidates["openai_gpt_5_5_xhigh"]
    claude_47 = candidates["anthropic_claude_opus_4_7_high"]
    claude_48 = candidates["anthropic_claude_opus_4_8_high"]
    claude_48_xhigh = candidates["anthropic_claude_opus_4_8_xhigh"]
    bedrock_55 = candidates["bedrock_gpt_5_5_xhigh"]
    qwen = candidates["bedrock_qwen3_coder_high"]
    spark_qwen = candidates["dgx_spark_qwen3_coder_high"]
    spark_120b = candidates["dgx_spark2_gpt_oss_120b_high"]

    assert mini["draft_worker_count"] >= 12
    assert mini["verifier_count"] == 0
    assert mini["final_authority_count"] == 0
    assert gpt_54["verifier_count"] > mini["draft_worker_count"]
    assert gpt_54["final_authority_count"] == 0
    assert gpt_55["final_authority_count"] > 0
    assert claude_47["verifier_count"] > 0
    assert claude_48["final_authority_count"] > 0
    assert claude_48_xhigh["average_score"] >= claude_48["average_score"]
    assert bedrock_55["final_authority_count"] == gpt_55["final_authority_count"]
    assert bedrock_55["estimated_total_usd"] > gpt_55["estimated_total_usd"]
    assert qwen["missing_tool_support_count"] > 0
    assert spark_qwen["provider_surface"] == "local-dgx-spark"
    assert spark_qwen["estimated_total_usd"] == 0.0
    assert spark_qwen["draft_worker_count"] > qwen["draft_worker_count"]
    assert spark_qwen["final_authority_count"] == 0
    assert spark_120b["estimated_total_usd"] == 0.0
    assert spark_120b["draft_worker_count"] > mini["draft_worker_count"]
    assert spark_120b["verifier_count"] == 0
    assert spark_120b["final_authority_count"] == 0

    connector_scope = probes["connectors_scope_selection"]
    confluence = probes["connectors_atlassian_runbook_extraction"]
    github_review = probes["connectors_github_pr_review_thread"]
    bbs_reassign = probes["bbs_reassign_wrong_owner"]
    official_ref = probes["bbs_thread_message_official_reference"]
    checkpoint = probes["planning_checkpoint_continue"]
    fork_contract = probes["planning_multi_agent_fork_contract"]
    numeric_truth = probes["truth_numeric_claim_verification"]
    fixture_completeness = probes["coding_generated_fixture_completeness"]
    topology_trace = probes["file_network_topology_runbook_trace"]
    sql_logs = probes["file_sql_log_comprehension"]

    assert connector_scope["cheapest_draft_candidate"] == "dgx_spark2_gpt_oss_120b_high"
    assert connector_scope["cheapest_verified_candidate"] == "openai_gpt_5_4_high"
    assert confluence["expected_minimum_role"] == "verifier"
    assert github_review["expected_minimum_role"] == "verifier"
    assert bbs_reassign["expected_minimum_role"] == "final_authority"
    assert bbs_reassign["cheapest_final_candidate"] == "openai_gpt_5_5_xhigh"
    assert official_ref["expected_minimum_role"] == "verifier"
    assert checkpoint["cheapest_verified_candidate"].startswith("openai_gpt_5_4")
    assert fork_contract["expected_minimum_role"] == "verifier"
    assert numeric_truth["expected_minimum_role"] == "verifier"
    assert fixture_completeness["expected_minimum_role"] == "verifier"
    assert topology_trace["expected_minimum_role"] == "verifier"
    assert sql_logs["cheapest_verified_candidate"].startswith("openai_gpt_5_4")


def test_spark_offload_matrix_keeps_frontier_gates_for_authority(
    monkeypatch,
) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report()
    rows = _rows_by_id(report)
    spark = report["spark_offload"]

    assert spark["schema"] == "norman.spark-offload-summary.v1"
    assert spark["eligible_count"] > 250
    assert spark["shadow_final_with_validator_count"] > 100
    assert spark["worker_with_5_4_verifier_count"] > 100
    assert spark["replaces_bedrock_worker_count"] > 250
    assert (
        spark["guarded_spark_pipeline_total_usd"]
        < spark["current_recommended_pipeline_total_usd"]
    )
    assert spark["savings_vs_current_recommended_usd"] > 0
    assert "dgx_spark2_gpt_oss_120b_high" in spark["candidate_counts"]

    selector = rows["webgoat_basic_xpath_selector"]["spark_offload"]
    final_apply = rows["netops_live_caddy_apply_final"]["spark_offload"]
    validator = rows["goldbook_cross_field_validator"]["spark_offload"]

    assert selector["mode"] == "spark_shadow_final_with_validator"
    assert selector["guarded_spark_pipeline_cost_usd"] == 0.0
    assert selector["requires_bedrock_5_4_gate"] is False
    assert selector["requires_bedrock_5_5_final"] is False

    assert validator["mode"] == "spark_worker_with_5_4_verifier"
    assert validator["requires_bedrock_5_4_gate"] is True
    assert validator["requires_bedrock_5_5_final"] is False

    assert final_apply["mode"] in {
        "not_eligible",
        "spark_worker_with_5_5_final",
    }
    if final_apply["eligible"]:
        assert final_apply["requires_bedrock_5_5_final"] is True


def test_expanded_workflow_domains_cover_mined_sessions_and_control_plane_scripts(
    monkeypatch,
) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report()
    rows = _rows_by_id(report)

    assert report["summary_by_domain"]["helpdesk"]["skill_count"] == 14
    assert report["summary_by_domain"]["tui-ops"]["skill_count"] == 18
    assert report["summary_by_domain"]["model-routing"]["skill_count"] == 10
    assert report["summary_by_domain"]["runbook-governance"]["skill_count"] == 10
    assert report["summary_by_domain"]["netops"]["skill_count"] == 8
    assert report["summary_by_domain"]["bbs"]["skill_count"] == 8
    assert report["summary_by_domain"]["cost-control"]["skill_count"] == 8
    assert report["summary_by_domain"]["control-plane"]["skill_count"] == 12
    assert report["summary_by_domain"]["control-plane-gap-audit"]["skill_count"] == 28
    assert report["summary_by_domain"]["data-pipelines"]["skill_count"] == 18

    first_canary = rows["tui_status_snapshot_answer"]
    gaphelp_close = rows["helpdesk_final_ticket_close_authority"]
    script_lookup = rows["control_plane_script_catalog_lookup"]
    dace = rows["pipeline_dace_cert_fasttext_softfail_check"]
    caddy_apply = rows["netops_live_caddy_apply_final"]
    no_ack = rows["bbs_observer_no_ack_guard"]
    purse = rows["cost_purse_route_policy_decision"]

    assert first_canary["rollout_gate"]["first_canary_candidate"] is True
    assert first_canary["uses_cheap_worker"] is True
    assert first_canary["uses_bedrock_5_5_xhigh"] is False
    assert "status snapshot" in " ".join(first_canary["tools"]).lower()

    for row in (script_lookup, no_ack):
        assert row["uses_cheap_worker"] is True
        assert row["uses_bedrock_5_5_xhigh"] is False
        assert (
            row["lower_model_readiness"]["status"]
            == "comfortable_shadow_lower_model_final"
        )

    for row in (dace,):
        pipeline_ids = [
            step["candidate_id"] for step in row["recommended_pipeline"] if step
        ]
        assert "bedrock_gpt_5_4_xhigh" in pipeline_ids
        assert "bedrock_gpt_5_5_xhigh" not in pipeline_ids
        assert (
            row["lower_model_readiness"]["status"] == "lower_worker_with_5_4_verifier"
        )

    for row in (gaphelp_close, caddy_apply, purse):
        pipeline_ids = [
            step["candidate_id"] for step in row["recommended_pipeline"] if step
        ]
        assert "bedrock_gpt_5_4_xhigh" in pipeline_ids
        assert "bedrock_gpt_5_5_xhigh" in pipeline_ids
        assert row["lower_model_readiness"]["status"] == "frontier_final_required"
        assert row["rollout_gate"]["phase"] == "phase_4_final_authority_hold"


def test_comms_and_data_fix_skills_cover_email_transcripts_and_repair_ladder(
    monkeypatch,
) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report()
    rows = _rows_by_id(report)
    email = rows["comms_email_thread_triage"]
    transcript = rows["comms_transcript_summary"]
    action_items = rows["comms_transcript_decision_action_items"]
    enum_fix = rows["data_fix_enum_canonicalization"]
    duplicate = rows["data_fix_duplicate_entity_detection"]
    merge = rows["data_fix_fuzzy_entity_merge_plan"]
    backfill = rows["data_fix_bulk_backfill_dry_run"]
    final_apply = rows["data_fix_final_governed_apply"]

    for row in (email, transcript, action_items, enum_fix, duplicate):
        assert row["uses_cheap_worker"] is True
        assert row["uses_bedrock_5_5_xhigh"] is False
        assert (
            row["recommended_pipeline_cost_usd"] < row["all_bedrock_5_5_xhigh_cost_usd"]
        )

    for row in (merge, backfill):
        pipeline_ids = [
            step["candidate_id"] for step in row["recommended_pipeline"] if step
        ]
        assert "bedrock_gpt_5_4_xhigh" in pipeline_ids
        assert row["uses_bedrock_5_5_xhigh"] is False
        assert (
            row["lower_model_readiness"]["status"] == "lower_worker_with_5_4_verifier"
        )

    final_pipeline_ids = [
        step["candidate_id"] for step in final_apply["recommended_pipeline"] if step
    ]
    assert "bedrock_gpt_5_4_xhigh" in final_pipeline_ids
    assert "bedrock_gpt_5_5_xhigh" in final_pipeline_ids
    assert final_apply["lower_model_readiness"]["status"] == "frontier_final_required"
    assert "not eligible" in final_apply["personal_tui_role"]


def test_owner_filter_and_rollout_gates_support_tui_canary_planning(
    monkeypatch,
) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report(owner_tui="compere")
    rows = _rows_by_id(report)

    assert report["owner_tui_filter"] == "compere"
    assert set(report["summary_by_domain"]) == {"keystone"}
    assert set(report["summary_by_owner_tui"]) == {"compere"}
    assert all(row["owner_tui"] == "compere" for row in report["rows"])
    assert report["rollout_gates"]["final_authority_hold_count"] == 0
    assert report["rollout_gates"]["phase_counts"] == {
        "phase_1_lower_model_shadow_canary": 3,
        "phase_2_5_4_verified_dry_run": 5,
        "phase_3_operator_approved_apply_plan": 1,
    }
    assert (
        rows["keystone_intake_normalization"]["rollout_gate"]["phase"]
        == "phase_1_lower_model_shadow_canary"
    )
    assert (
        rows["keystone_final_close_loop_decision"]["rollout_gate"]["phase"]
        == "phase_3_operator_approved_apply_plan"
    )


def test_keystone_compere_skills_are_5_4_gated_coordination(monkeypatch) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report(domain="keystone")
    rows = _rows_by_id(report)
    intake = rows["keystone_intake_normalization"]
    handoff = rows["keystone_handoff_routing_decision"]
    runbook = rows["keystone_runbook_promotion_candidate"]
    approval = rows["keystone_operator_approval_packet"]
    close_loop = rows["keystone_final_close_loop_decision"]
    owner = report["summary_by_owner_tui"]["compere"]

    assert report["summary_by_domain"]["keystone"]["skill_count"] == 9
    assert owner["recommended_canary_tier"] == "shadow_with_5_4_verifier"
    assert owner["bedrock_5_5_xhigh_count"] == 0
    assert intake["uses_cheap_worker"] is True
    assert (
        intake["lower_model_readiness"]["status"]
        == "comfortable_shadow_lower_model_final"
    )

    for row in (handoff, runbook):
        pipeline_ids = [
            step["candidate_id"] for step in row["recommended_pipeline"] if step
        ]
        assert "bedrock_gpt_5_4_xhigh" in pipeline_ids
        assert "bedrock_gpt_5_5_xhigh" not in pipeline_ids
        assert row["uses_bedrock_5_5_xhigh"] is False
        assert (
            row["lower_model_readiness"]["status"] == "lower_worker_with_5_4_verifier"
        )
        assert (
            "work-special" in row["personal_tui_role"]
            or "not eligible" in row["personal_tui_role"]
        )

    for row in (approval, close_loop):
        pipeline_ids = [
            step["candidate_id"] for step in row["recommended_pipeline"] if step
        ]
        assert "bedrock_gpt_5_4_xhigh" in pipeline_ids
        assert "bedrock_gpt_5_5_xhigh" not in pipeline_ids
        assert row["lower_model_readiness"]["status"] == "bedrock_5_4_verifier_required"
    assert "not eligible" in row["personal_tui_role"]


def test_hal_skills_preserve_personal_non_interference_boundary(
    monkeypatch,
) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report(domain="hal")
    rows = _rows_by_id(report)
    boundary = rows["hal_boundary_policy_lookup"]
    secret = rows["hal_secret_artifact_presence_check"]
    disk = rows["hal_disk_pressure_triage"]
    camera = rows["hal_autocamera_privacy_safe_capture_report"]
    routing = rows["hal_personal_work_boundary_routing"]
    final_apply = rows["hal_final_maintenance_apply_decision"]

    assert report["summary_by_domain"]["hal"]["skill_count"] == 13
    assert set(report["summary_by_owner_tui"]) == {"autocamera", "theseus"}
    assert report["summary"]["bedrock_5_5_xhigh_final_count"] == 1
    assert report["rollout_gates"]["final_authority_hold_count"] == 1
    assert report["summary"]["cheap_worker_count"] >= 8

    assert boundary["uses_cheap_worker"] is True
    assert boundary["uses_bedrock_5_5_xhigh"] is False
    assert "no HAL inspection" in boundary["work_special_role"]

    assert secret["local_only_allowed"] is True
    assert secret["recommended_pipeline"][0]["candidate_id"] == "local_deterministic"
    assert secret["recommended_pipeline_cost_usd"] == 0.0
    assert "never inspect" in secret["personal_tui_role"]

    for row in (disk, camera, routing):
        pipeline_ids = [
            step["candidate_id"] for step in row["recommended_pipeline"] if step
        ]
        assert "bedrock_gpt_5_4_xhigh" in pipeline_ids
        assert "bedrock_gpt_5_5_xhigh" not in pipeline_ids
        assert (
            row["lower_model_readiness"]["status"] == "lower_worker_with_5_4_verifier"
        )
        assert row["uses_bedrock_5_5_xhigh"] is False

    final_pipeline_ids = [
        step["candidate_id"] for step in final_apply["recommended_pipeline"] if step
    ]
    assert "bedrock_gpt_5_4_xhigh" in final_pipeline_ids
    assert "bedrock_gpt_5_5_xhigh" in final_pipeline_ids
    assert final_apply["lower_model_readiness"]["status"] == "frontier_final_required"
    assert "explicit operator approval" in final_apply["personal_tui_role"]


def test_hal_workflow_scripts_cover_control_plane_acast_dace_and_tmi(
    monkeypatch,
) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report(domain="hal-workflows")
    rows = _rows_by_id(report)
    routing = rows["halwf_control_plane_project_index_routing"]
    sync = rows["halwf_durable_runbook_sync_candidate"]
    retail_queue = rows["halwf_retailer_category_walk_queue"]
    webgoat = rows["halwf_webgoat_watchlist_repair_packet"]
    acast = rows["halwf_acast_tester_dace_source_guard"]
    dace = rows["halwf_dace_planogram_ocr_handoff"]
    tmi = rows["halwf_tmi_dashboard_proof_capture"]
    final_promotion = rows["halwf_live_script_promotion_apply_decision"]

    assert report["summary_by_domain"]["hal-workflows"]["skill_count"] == 16
    assert set(report["summary_by_owner_tui"]) == {
        "control-plane",
        "market-sizing",
        "panelbot",
        "tmi-dashboards",
    }
    assert report["summary"]["cheap_worker_count"] >= 11
    assert report["summary"]["bedrock_5_4_xhigh_heavy_lift_count"] >= 9
    assert report["summary"]["bedrock_5_5_xhigh_final_count"] == 1

    assert routing["uses_cheap_worker"] is True
    assert routing["uses_bedrock_5_5_xhigh"] is False
    assert "project index" in routing["tools"][0].lower()

    assert retail_queue["uses_cheap_worker"] is True
    assert retail_queue["uses_bedrock_5_5_xhigh"] is False

    for row in (sync, webgoat, acast, dace):
        pipeline_ids = [
            step["candidate_id"] for step in row["recommended_pipeline"] if step
        ]
        assert "bedrock_gpt_5_4_xhigh" in pipeline_ids
        assert "bedrock_gpt_5_5_xhigh" not in pipeline_ids
        assert (
            row["lower_model_readiness"]["status"] == "lower_worker_with_5_4_verifier"
        )

    assert tmi["owner_tui"] == "tmi-dashboards"
    assert tmi["uses_cheap_worker"] is True
    assert "dashboard" in " ".join(tmi["runbooks"]).lower()

    final_pipeline_ids = [
        step["candidate_id"] for step in final_promotion["recommended_pipeline"] if step
    ]
    assert "bedrock_gpt_5_4_xhigh" in final_pipeline_ids
    assert "bedrock_gpt_5_5_xhigh" in final_pipeline_ids
    assert (
        final_promotion["lower_model_readiness"]["status"] == "frontier_final_required"
    )
    assert "not eligible" in final_promotion["personal_tui_role"]


def test_core_tui_operator_skills_cover_status_proceed_next_undo_and_drift(
    monkeypatch,
) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report(domain="tui-ops")
    rows = _rows_by_id(report)
    drift = report["drift_controls"]
    status = rows["tui_core_status_answer_contract"]
    proceed = rows["tui_core_proceed_decision_contract"]
    what_next = rows["tui_core_whats_next_checkpoint"]
    undo = rows["tui_core_undo_backtrack_scope_gate"]
    drift_detect = rows["tui_core_drift_detection_preflight"]
    drift_ledger = rows["tui_core_drift_prevention_estimate_ledger"]

    assert drift["covered_core_operator_skill_count"] == 6
    assert drift["missing_core_operator_skill_ids"] == {}
    assert drift["core_operator_skill_ids"] == {
        "status": "tui_core_status_answer_contract",
        "proceed": "tui_core_proceed_decision_contract",
        "what_next": "tui_core_whats_next_checkpoint",
        "undo_back": "tui_core_undo_backtrack_scope_gate",
        "drift_detect": "tui_core_drift_detection_preflight",
        "drift_prevent": "tui_core_drift_prevention_estimate_ledger",
    }
    assert "mission/context/scope/power preflight labels" in drift["measurement_fields"]
    assert (
        "split local undo from external rollback/reopen/mutation"
        in drift["prevention_controls"]
    )

    for row in (status, what_next, drift_ledger):
        assert row["uses_cheap_worker"] is True
        assert row["uses_bedrock_5_5_xhigh"] is False
        assert (
            row["lower_model_readiness"]["status"]
            == "comfortable_shadow_lower_model_final"
        )

    for row in (proceed, drift_detect):
        pipeline_ids = [
            step["candidate_id"] for step in row["recommended_pipeline"] if step
        ]
        assert "bedrock_gpt_5_4_xhigh" in pipeline_ids
        assert "bedrock_gpt_5_5_xhigh" not in pipeline_ids
        assert (
            row["lower_model_readiness"]["status"] == "lower_worker_with_5_4_verifier"
        )

    undo_pipeline_ids = [
        step["candidate_id"] for step in undo["recommended_pipeline"] if step
    ]
    assert "bedrock_gpt_5_4_xhigh" in undo_pipeline_ids
    assert "bedrock_gpt_5_5_xhigh" in undo_pipeline_ids
    assert undo["lower_model_readiness"]["status"] == "frontier_final_required"
    assert "external rollback" in undo["personal_tui_role"]


def test_control_plane_gap_audit_rows_cover_missing_runbooks_and_apply_contracts(
    monkeypatch,
) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report(domain="control-plane-gap-audit")
    rows = _rows_by_id(report)
    runbook_text = "\n".join(
        " ".join(str(item) for item in row["runbooks"]) for row in report["rows"]
    )

    for runbook_id in {
        "AAE",
        "AWO",
        "CDH",
        "CDMS",
        "CFS",
        "EPF",
        "HCL",
        "HRB",
        "MC",
        "MID",
        "MRI",
        "NPM",
        "NWO",
        "PDR",
        "PFG",
        "PSM",
        "RDF",
        "RML",
        "RRS",
        "S2B",
        "SDC",
        "SDI",
        "SQC",
        "TRC",
        "WPL",
    }:
        assert runbook_id in runbook_text

    postcheck = rows["control_gap_apply_postcheck_contract"]
    resume = rows["control_gap_idempotent_resume_contract"]
    mutation = rows["control_gap_exact_mutation_gate"]
    cfs = rows["control_gap_cfs_category_fill_status_route"]

    for row in (postcheck, resume):
        pipeline_ids = [
            step["candidate_id"] for step in row["recommended_pipeline"] if step
        ]
        assert "bedrock_gpt_5_4_xhigh" in pipeline_ids
        assert "bedrock_gpt_5_5_xhigh" not in pipeline_ids
        assert (
            row["lower_model_readiness"]["status"] == "lower_worker_with_5_4_verifier"
        )

    mutation_pipeline_ids = [
        step["candidate_id"] for step in mutation["recommended_pipeline"] if step
    ]
    assert "bedrock_gpt_5_4_xhigh" in mutation_pipeline_ids
    assert "bedrock_gpt_5_5_xhigh" in mutation_pipeline_ids
    assert mutation["lower_model_readiness"]["status"] == "frontier_final_required"

    assert cfs["uses_cheap_worker"] is True
    assert cfs["uses_bedrock_5_5_xhigh"] is False


def test_live_governance_closes_escalate_to_bedrock_5_5(monkeypatch) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report()
    rows = _rows_by_id(report)
    gold_release = rows["goldbook_release_final_decision"]
    webgoat_close = rows["webgoat_final_governance_close"]

    for row in (gold_release, webgoat_close):
        pipeline_ids = [
            step["candidate_id"] for step in row["recommended_pipeline"] if step
        ]
        assert "bedrock_gpt_5_4_xhigh" in pipeline_ids
        assert "bedrock_gpt_5_5_xhigh" in pipeline_ids
        assert row["uses_bedrock_5_5_xhigh"] is True
        assert "not eligible" in row["personal_tui_role"]
        assert row["lower_model_readiness"]["status"] == "frontier_final_required"


def test_auth_artifact_check_is_local_only_and_secret_safe(monkeypatch) -> None:
    module = _load_benchmark(monkeypatch)

    report = module.build_report(domain="webgoat")
    row = _rows_by_id(report)["webgoat_auth_artifact_presence"]

    assert row["local_only_allowed"] is True
    assert row["recommended_pipeline"][0]["candidate_id"] == "local_deterministic"
    assert row["recommended_pipeline_cost_usd"] == 0.0
    assert "without printing it" in row["examples"][0]
    assert (
        row["lower_model_readiness"]["status"] == "comfortable_shadow_lower_model_final"
    )


def test_markdown_renders_domain_and_skill_tables(monkeypatch) -> None:
    module = _load_benchmark(monkeypatch)

    markdown = module.render_markdown(module.build_report())

    assert "## Domain Summary" in markdown
    assert "## Model Routing Rubric" in markdown
    assert "small_bedrock_worker" in markdown
    assert "medium_bedrock_worker" in markdown
    assert "bedrock_gpt_5_4_xhigh_verifier" in markdown
    assert "bedrock_gpt_5_5_xhigh_final" in markdown
    assert "Small model criteria" in markdown
    assert "5.5 criteria" in markdown
    assert "## Model Capability Probe Matrix" in markdown
    assert "OpenAI GPT-5.4 mini high" in markdown
    assert "Claude Opus 4.8 high" in markdown
    assert "Connector scope selection" in markdown
    assert "Atlassian runbook extraction" in markdown
    assert "GitHub PR review thread handling" in markdown
    assert "Network topology and runbook trace" in markdown
    assert "Observer no-ACK guard" in markdown
    assert "SQLite log comprehension" in markdown
    assert "## Lower-Model Comfort" in markdown
    assert "## Hybrid Assurance vs All Bedrock 5.5 XHigh" in markdown
    assert "Accepted hybrid skills" in markdown
    assert "accept_cost_superior_guarded_quality" in markdown
    assert "## Family Summary" in markdown
    assert "## Skill Matrix" in markdown
    assert "comfortable_shadow_lower_model_final" in markdown
    assert "Gold Book" in markdown or "gold-book" in markdown
    assert "JMESPath" in markdown
    assert "Transcript" in markdown
    assert "data-fix" in markdown
    assert "Keystone/Compere" in markdown
    assert "HAL/Theseus/Autocamera" in markdown
    assert "HAL workflow scripts" in markdown
    assert "Acast Tester/DACE" in markdown
    assert "## Drift Controls" in markdown
    assert "Core operator skills covered: 6 / 6" in markdown
    assert "tui_core_proceed_decision_contract" in markdown
    assert "non-interference" in markdown
    assert "## TUI Canary Order" in markdown
    assert "## Rollout Gates" in markdown
    assert "phase_4_final_authority_hold" in markdown
    assert "Personal TUIs can draft" in markdown


def test_cli_writes_json_and_markdown(monkeypatch, tmp_path) -> None:
    module = _load_benchmark(monkeypatch)
    output_json = tmp_path / "matrix.json"
    output_md = tmp_path / "matrix.md"
    output_csv = tmp_path / "capability.csv"
    output_prompts = tmp_path / "capability_prompts.jsonl"

    report = module.build_report(domain="gold-book")
    module.write_report(report, output_json, output_md, output_csv, output_prompts)

    data = json.loads(output_json.read_text())
    assert data["domain_filter"] == "gold-book"
    assert data["owner_tui_filter"] == "all"
    assert set(data["summary_by_domain"]) == {"gold-book"}
    assert "summary_by_owner_tui" in data
    assert "rollout_gates" in data
    assert "hybrid_assurance" in data
    assert "model_routing_rubric" in data
    assert "spark_offload" in data
    assert "model_capability_probe_matrix" in data
    assert data["model_capability_probe_matrix"]["cell_count"] == 600
    assert data["spark_offload"]["eligible_count"] > 0
    assert "Work Domain Skill Benchmark" in output_md.read_text()
    assert "DGX Spark Offload" in output_md.read_text()
    csv_lines = output_csv.read_text().splitlines()
    assert csv_lines[0].startswith("probe_id,capability,candidate_id")
    assert len(csv_lines) == 601
    prompt_records = [
        json.loads(line) for line in output_prompts.read_text().splitlines()
    ]
    assert len(prompt_records) == 600
    assert prompt_records[0]["schema"] == "norman.model-capability-live-probe.v1"
    assert "Required behaviors" in prompt_records[0]["prompt"]
    assert "Do not claim tool results you do not have" in prompt_records[0]["prompt"]
