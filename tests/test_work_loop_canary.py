from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def _load_work_loop_canary(monkeypatch):
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "work_loop_canary",
        scripts_dir / "work_loop_canary.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["work_loop_canary"] = module
    spec.loader.exec_module(module)
    return module


def test_build_report_marks_cp_and_gold_book_loop_ready(monkeypatch) -> None:
    module = _load_work_loop_canary(monkeypatch)
    statuses = [
        {
            "_loop_slug": "control-plane",
            "_loop_url": "https://cp.kris.openbrand.com/api/status",
            "state": "ok",
            "pending": False,
            "queue_depth": 0,
            "ui_version": "2026.06.11.1",
            "selected_runtime": "codex",
            "selected_model": "openai.gpt-5.5",
            "status_message": "Ready.",
            "last_error": "",
        },
        {
            "_loop_slug": "gold-book",
            "_loop_url": "https://goldbook.kris.openbrand.com/api/status",
            "state": "ok",
            "pending": False,
            "queue_depth": 0,
            "ui_version": "2026.06.11.1",
            "selected_runtime": "codex",
            "selected_model": "openai.gpt-5.5",
            "status_message": "Ready.",
            "last_error": "",
        },
    ]

    report = module.build_report(statuses, source="fixture")
    markdown = module.render_markdown(report)

    assert report["schema"] == "norman.work-loop-canary.v1"
    assert report["summary"]["targets"] == 2
    assert report["summary"]["reachable"] == 2
    assert report["summary"]["route_ok"] == 2
    assert report["summary"]["idle_ready"] == 2
    assert report["summary"]["optimizer_ready"] == 2
    assert report["summary"]["confidence_min"] == 100
    assert report["summary"]["shadow_rollout_recommendation"] == "ready"
    assert report["summary"]["always_on_shadow_gate"] == "ready"
    assert report["summary"]["always_on_live_enable_requires_approval"] is True
    assert report["summary"]["continuous_loop_enabled"] is False
    assert report["summary"]["hal_background_discovery_allowed"] is False
    assert report["architecture_mode"] == "hybrid"
    assert report["always_on_plan"]["unchanged_daily_usd"] == 0.0
    assert report["always_on_plan"]["fast_loop_cycles_per_day"] == 288.0
    assert report["always_on_plan"]["max_changed_tickets_per_cycle"] == 3
    assert report["always_on_plan"]["expected_usd_per_changed_cycle"] == 1.194375
    assert report["always_on_plan"]["p95_usd_per_changed_cycle"] == 2.8665
    assert report["always_on_plan"]["p95_changed_cycles_affordable_per_day"] == 3
    assert (
        report["always_on_plan"]["operator_approval_required_for_live_enable"] is True
    )
    assert report["cost_basis"]["status_loop_model_calls"] == 0
    assert (
        report["cost_basis"]["sample_ticket_cleanup"]["hybrid_ratio_vs_direct_5_5_flex"]
        == 0.49
    )
    assert all(row["loop_ready"] for row in report["rows"])
    assert all(
        "general_error_triage" not in {move["move_id"] for move in row["moves"]}
        for row in report["rows"]
    )
    assert "Control Plane" in markdown
    assert "Gold Book" in markdown
    assert "route_confirmed_expected_model" in markdown
    assert "Hybrid direct estimated sample" in markdown
    assert "Always-On Loop Plan" in markdown


def test_flow_canary_plan_selects_first_targets_and_route_receipt_contract(
    monkeypatch,
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    skill_matrix = work_domain_skill_benchmark.build_report()
    plan = module.build_flow_canary_plan(skill_matrix)
    markdown = module.render_flow_canary_plan_markdown(plan)
    targets = {row["owner_tui"]: row for row in plan["targets"]}

    assert plan["schema"] == "norman.tui-flow-canary-plan.v1"
    assert plan["dry_run_only"] is True
    assert plan["deployment_ready_status"] == "ready_for_shadow_route_receipts"
    assert plan["deployment_requires_operator_approval"] is True
    assert plan["recommended_first_deploy_targets"] == [
        "market-sizing",
    ]
    assert plan["recommended_second_wave_targets"] == ["panelbot", "compere"]
    assert "netops" in plan["held_final_authority_targets"]
    assert "control-plane" in plan["held_final_authority_targets"]
    assert plan["priority_focus"]["domains"] == [
        "control-plane",
        "control-plane-runbooks",
        "confluence-data-ops",
        "runbook-governance",
        "gold-book",
    ]
    assert plan["priority_focus"]["owners"] == ["control-plane", "gold-book"]
    assert plan["priority_focus"]["held_final_authority_owners"] == [
        "control-plane",
        "gold-book",
    ]
    assert "work-special-comms" not in targets
    workload_buckets = {
        row["owner_tui"]: row
        for row in plan["workload_buckets_requiring_owner_mapping"]
    }
    assert workload_buckets["work-special-comms"]["deployable_owner"] is False
    assert (
        "concrete work-special TUI owner"
        in workload_buckets["work-special-comms"]["mapping_required"]
    )
    assert "receipt_source" in plan["route_receipt_contract"]["required_fields"]
    assert "synthetic" in plan["route_receipt_contract"]["required_fields"]
    assert "live_write_attempted" in plan["route_receipt_contract"]["required_fields"]
    assert "selected_model_tier" in plan["route_receipt_contract"]["required_fields"]
    assert "escalation_trigger" in plan["route_receipt_contract"]["required_fields"]
    assert targets["market-sizing"]["launch_gate"] == "ready_for_shadow_route_receipts"
    assert targets["market-sizing"]["wave"] == 1
    assert "live write" in targets["market-sizing"]["blocked_actions"]
    assert targets["panelbot"]["launch_gate"] == "ready_for_5_4_shadow_verifier"
    assert targets["panelbot"]["wave"] == 2
    assert "TUI Flow Canary Plan" in markdown
    assert "Route Receipt Contract" in markdown
    assert "Workload Buckets Needing Owner Mapping" in markdown
    assert "Priority Focus" in markdown
    assert "Priority focus owners: control-plane, gold-book" in markdown
    assert "work-special-comms" in markdown
    assert "panelbot" in markdown


def _good_route_receipt(owner: str, index: int) -> dict:
    return {
        "receipt_id": f"{owner}-{index}",
        "receipt_source": "live_shadow_canary",
        "previous_receipt_hash": "",
        "receipt_hash": "",
        "synthetic": False,
        "created_at": 1_786_000_000 + index,
        "owner_tui": owner,
        "prompt_id": f"prompt-{index}",
        "benchmark_skill_id": "common-status-next-action",
        "requested_action": "draft next-action packet",
        "selected_model_tier": "medium_worker",
        "selected_model": "gpt-5.4-mini",
        "routing_score": 0.94,
        "routing_bands": {"worker": "medium", "verifier": "5.5"},
        "allowed_role": "worker_draft",
        "validator_gate": "pass",
        "escalation_trigger": "",
        "fallback_used": "",
        "estimated_cost_usd": 0.40,
        "baseline_all_5_5_cost_usd": 1.00,
        "validator_passed": True,
        "manual_override": False,
        "boundary_violation": False,
        "latency_ms": 850,
        "operator_approval_required": False,
        "final_authority_required": False,
        "live_write_attempted": False,
        "outcome": "accepted",
        "evidence_refs": ["validator:fixture"],
    }


def _good_verifier_route_receipt(owner: str, index: int) -> dict:
    receipt = _good_route_receipt(owner, index)
    receipt["selected_model_tier"] = "bedrock_5_4_verifier"
    receipt["allowed_role"] = "verifier"
    receipt["selected_model"] = "openai.gpt-5.4"
    receipt["validator_gate"] = "pass"
    return receipt


def _receipt_hash(receipt: dict) -> str:
    previous = str(receipt.get("previous_receipt_hash") or "").strip()
    payload = dict(receipt)
    payload.pop("receipt_hash", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{previous}\n{canonical}".encode("utf-8")).hexdigest()


def _chained_receipts(receipts: list[dict]) -> list[dict]:
    previous = ""
    chained = []
    for receipt in receipts:
        item = dict(receipt)
        item["previous_receipt_hash"] = previous
        item["receipt_hash"] = _receipt_hash(item)
        previous = item["receipt_hash"]
        chained.append(item)
    return chained


def _write_historic_route_benchmark(
    path: Path,
    *,
    gate: str = "pass",
    accuracy_fail_count: int = 0,
    savings: float = 0.91,
    policy_version: str = "work-special-hybrid-routing-policy.v1",
    policy_fail_count: int = 0,
    planner_action_policy_version: str = "planner-action-contract.v1",
    planner_action_case_count: int = 2,
    planner_action_fail_count: int = 0,
    planner_action_score: float = 1.0,
    lower_model_case_count: int = 4,
    five_five_share: float = 0.05,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "norman.historic-shadow-planner-route-benchmark.v1",
                "source": {"source_turn_count": 20, "source_evidence_turn_count": 15},
                "summary": {
                    "planner_shadow_cutover_gate": gate,
                    "case_count": 4,
                    "policy_version": policy_version,
                    "accuracy_gate_pass_count": 4 - accuracy_fail_count,
                    "accuracy_gate_fail_count": accuracy_fail_count,
                    "routing_policy_compliance_pass_count": 4 - policy_fail_count,
                    "routing_policy_compliance_fail_count": policy_fail_count,
                    "planner_action_policy_version": planner_action_policy_version,
                    "planner_action_case_count": planner_action_case_count,
                    "planner_action_pass_count": (
                        planner_action_case_count - planner_action_fail_count
                    ),
                    "planner_action_fail_count": planner_action_fail_count,
                    "median_planner_action_score": planner_action_score,
                    "lower_model_case_count": lower_model_case_count,
                    "savings_vs_all_bedrock_5_5_xhigh": savings,
                    "median_raw_context_compression_rate": 0.9,
                    "median_five_five_token_share_vs_raw": five_five_share,
                    "split_counts": {"holdout": 2, "train": 2},
                },
            }
        ),
        encoding="utf-8",
    )


def test_cutover_readiness_blocks_without_route_receipts(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    plan = module.build_flow_canary_plan(work_domain_skill_benchmark.build_report())
    report = module.build_cutover_readiness_report(
        plan,
        receipt_dir=tmp_path / "route_receipts",
    )
    markdown = module.render_cutover_readiness_markdown(report)
    targets = {row["owner_tui"]: row for row in report["targets"]}

    assert report["schema"] == "norman.tui-cutover-readiness.v1"
    assert report["dry_run_only"] is True
    assert report["cutover_requires_operator_approval"] is True
    assert report["readiness"] == "not_ready_for_cutover"
    assert report["ready_targets"] == []
    assert "market-sizing" in report["blocked_targets"]
    assert "needs at least 50 route receipts" in "; ".join(
        targets["market-sizing"]["blockers"]
    )
    assert "collect 50 more live shadow route receipts" in "; ".join(
        targets["market-sizing"]["next_actions"]
    )
    assert "missing route receipt sink" in "; ".join(
        targets["market-sizing"]["load_errors"]
    )
    assert "TUI Cutover Readiness" in markdown
    assert "not_ready_for_cutover" in markdown


def test_cutover_readiness_promotes_clean_wave_one_receipts(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    receipt_dir = tmp_path / "route_receipts"
    receipt_dir.mkdir()
    owner = "market-sizing"
    (receipt_dir / f"{owner}.jsonl").write_text(
        "\n".join(
            json.dumps(receipt)
            for receipt in _chained_receipts(
                [_good_route_receipt(owner, index) for index in range(50)]
            )
        ),
        encoding="utf-8",
    )
    plan = module.build_flow_canary_plan(work_domain_skill_benchmark.build_report())
    report = module.build_cutover_readiness_report(plan, receipt_dir=receipt_dir)
    targets = {row["owner_tui"]: row for row in report["targets"]}

    assert report["readiness"] == "ready_for_wave_1_limited_cutover"
    assert report["ready_targets"] == ["market-sizing"]
    assert targets["market-sizing"]["cutover_gate"] == (
        "ready_for_limited_guarded_cutover"
    )
    assert targets["market-sizing"]["metrics"]["receipt_count"] == 50
    assert targets["market-sizing"]["metrics"]["route_match_count"] == 50
    assert targets["market-sizing"]["metrics"]["route_drift_count"] == 0
    assert targets["market-sizing"]["metrics"]["validator_pass_rate"] == 1.0
    assert targets["market-sizing"]["metrics"]["manual_override_rate"] == 0.0
    assert targets["market-sizing"]["metrics"]["fallback_rate"] == 0.0
    assert targets["market-sizing"]["metrics"]["cost_savings_vs_all_5_5"] == 0.6
    assert targets["market-sizing"]["next_actions"] == [
        "request operator approval for a limited guarded cutover"
    ]
    assert targets["panelbot"]["cutover_ready"] is False


def test_cutover_readiness_tracks_wave_two_verifier_promotion_separately(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    receipt_dir = tmp_path / "route_receipts"
    receipt_dir.mkdir()
    owner = "panelbot"
    (receipt_dir / f"{owner}.jsonl").write_text(
        "\n".join(
            json.dumps(receipt)
            for receipt in _chained_receipts(
                [_good_verifier_route_receipt(owner, index) for index in range(50)]
            )
        ),
        encoding="utf-8",
    )

    plan = module.build_flow_canary_plan(work_domain_skill_benchmark.build_report())
    report = module.build_cutover_readiness_report(plan, receipt_dir=receipt_dir)
    targets = {row["owner_tui"]: row for row in report["targets"]}
    panelbot = targets["panelbot"]

    assert report["readiness"] == "not_ready_for_cutover"
    assert report["ready_targets"] == []
    assert report["promotion_ready_targets"] == ["panelbot"]
    assert report["summary"]["wave_2_target_count"] == 2
    assert report["summary"]["wave_2_ready_target_count"] == 1
    assert report["summary"]["promotion_ready_target_count"] == 1
    assert panelbot["promotion_phase"] == "wave_2_5_4_shadow_verifier"
    assert panelbot["promotion_gate"] == "ready_for_5_4_verified_shadow_promotion"
    assert panelbot["promotion_ready"] is True
    assert panelbot["cutover_ready"] is False
    assert panelbot["cutover_gate"] == "not_ready"
    assert panelbot["metrics"]["receipt_count"] == 50
    assert panelbot["metrics"]["route_match_count"] == 50
    assert panelbot["metrics"]["route_drift_count"] == 0
    assert panelbot["metrics"]["verifier_receipt_count"] == 50
    assert panelbot["metrics"]["verifier_decision_count"] == 50
    assert panelbot["next_actions"] == [
        "keep the lane in operator-visible shadow with the 5.4 verifier as the acceptance gate"
    ]


def test_cutover_readiness_blocks_route_drift_from_intended_canary_lane(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    receipt_dir = tmp_path / "route_receipts"
    receipt_dir.mkdir()
    owner = "market-sizing"
    drifted = []
    for index in range(50):
        receipt = _good_route_receipt(owner, index)
        receipt["selected_model_tier"] = "bedrock_5_4_verifier"
        receipt["selected_model"] = "openai.gpt-5.4"
        receipt["allowed_role"] = "verifier"
        drifted.append(receipt)
    (receipt_dir / f"{owner}.jsonl").write_text(
        "\n".join(json.dumps(receipt) for receipt in _chained_receipts(drifted)),
        encoding="utf-8",
    )

    plan = module.build_flow_canary_plan(work_domain_skill_benchmark.build_report())
    report = module.build_cutover_readiness_report(plan, receipt_dir=receipt_dir)
    targets = {row["owner_tui"]: row for row in report["targets"]}
    market = targets["market-sizing"]

    assert report["readiness"] == "not_ready_for_cutover"
    assert report["ready_targets"] == []
    assert market["promotion_ready"] is False
    assert market["cutover_ready"] is False
    assert market["metrics"]["route_match_count"] == 0
    assert market["metrics"]["route_drift_count"] == 50
    assert "receipts drifted from lower_or_medium_route_receipts_only" in "; ".join(
        market["blockers"]
    )
    assert "match the intended canary tier" in "; ".join(market["next_actions"])


def test_cutover_readiness_includes_historic_route_benchmark_gate(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    receipt_dir = tmp_path / "route_receipts"
    receipt_dir.mkdir()
    owner = "market-sizing"
    (receipt_dir / f"{owner}.jsonl").write_text(
        "\n".join(
            json.dumps(receipt)
            for receipt in _chained_receipts(
                [_good_route_receipt(owner, index) for index in range(50)]
            )
        ),
        encoding="utf-8",
    )
    historic_path = tmp_path / "historic_route.json"
    _write_historic_route_benchmark(historic_path)

    plan = module.build_flow_canary_plan(work_domain_skill_benchmark.build_report())
    report = module.build_cutover_readiness_report(
        plan,
        receipt_dir=receipt_dir,
        historic_route_benchmark_path=historic_path,
    )
    markdown = module.render_cutover_readiness_markdown(report)

    assert report["readiness"] == "ready_for_wave_1_limited_cutover"
    assert report["historic_route_benchmark"]["gate"] == "pass"
    assert (
        report["historic_route_benchmark"]["policy_version"]
        == "work-special-hybrid-routing-policy.v1"
    )
    assert report["summary"]["historic_route_benchmark_savings"] == 0.91
    assert report["summary"]["historic_route_benchmark_policy_fail_count"] == 0
    assert (
        report["summary"]["historic_route_planner_action_policy_version"]
        == "planner-action-contract.v1"
    )
    assert report["summary"]["historic_route_planner_action_case_count"] == 2
    assert report["summary"]["historic_route_planner_action_fail_count"] == 0
    assert report["summary"]["historic_route_median_planner_action_score"] == 1.0
    assert report["summary"]["historic_route_benchmark_lower_model_case_count"] == 4
    assert "Historic route benchmark: pass" in markdown
    assert "Historic route benchmark savings: 91.0%" in markdown
    assert "Historic planner action cases/failures: 2/0" in markdown
    assert "Historic planner action score: 100.0%" in markdown

    _write_historic_route_benchmark(
        historic_path,
        gate="hold",
        accuracy_fail_count=1,
        savings=0.2,
    )
    blocked_report = module.build_cutover_readiness_report(
        plan,
        receipt_dir=receipt_dir,
        historic_route_benchmark_path=historic_path,
    )
    blocked_markdown = module.render_cutover_readiness_markdown(blocked_report)

    assert blocked_report["readiness"] == "not_ready_for_cutover"
    assert blocked_report["ready_targets"] == []
    assert any(
        "historic route benchmark gate is hold" in blocker
        for blocker in blocked_report["global_blockers"]
    )
    assert any(
        "accuracy gate failures" in blocker
        for blocker in blocked_report["global_blockers"]
    )
    assert "## Global Blockers" in blocked_markdown

    _write_historic_route_benchmark(
        historic_path,
        policy_version="",
        policy_fail_count=1,
        lower_model_case_count=0,
        five_five_share=0.5,
    )
    policy_blocked_report = module.build_cutover_readiness_report(
        plan,
        receipt_dir=receipt_dir,
        historic_route_benchmark_path=historic_path,
    )

    assert policy_blocked_report["readiness"] == "not_ready_for_cutover"
    assert any(
        "policy version is missing" in blocker
        for blocker in policy_blocked_report["global_blockers"]
    )
    assert any(
        "routing policy compliance failures" in blocker
        for blocker in policy_blocked_report["global_blockers"]
    )
    assert any(
        "no lower-model eligible cases" in blocker
        for blocker in policy_blocked_report["global_blockers"]
    )
    assert any(
        "median 5.5 token share" in blocker
        for blocker in policy_blocked_report["global_blockers"]
    )

    stale = json.loads(historic_path.read_text(encoding="utf-8"))
    for key in (
        "planner_action_policy_version",
        "planner_action_case_count",
        "planner_action_pass_count",
        "planner_action_fail_count",
        "median_planner_action_score",
    ):
        stale["summary"].pop(key, None)
    historic_path.write_text(json.dumps(stale), encoding="utf-8")
    stale_report = module.build_cutover_readiness_report(
        plan,
        receipt_dir=receipt_dir,
        historic_route_benchmark_path=historic_path,
    )

    assert stale_report["readiness"] == "not_ready_for_cutover"
    assert any(
        "planner action policy version is missing" in blocker
        for blocker in stale_report["global_blockers"]
    )
    assert any(
        "no planner-action cases" in blocker
        for blocker in stale_report["global_blockers"]
    )


def test_cutover_readiness_rejects_synthetic_receipts(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    receipt_dir = tmp_path / "route_receipts"
    receipt_dir.mkdir()
    owner = "market-sizing"
    synthetic_receipts = []
    for index in range(50):
        receipt = _good_route_receipt(owner, index)
        receipt["receipt_source"] = "template_not_live_observation"
        receipt["synthetic"] = True
        synthetic_receipts.append(receipt)
    (receipt_dir / f"{owner}.jsonl").write_text(
        "\n".join(
            json.dumps(receipt) for receipt in _chained_receipts(synthetic_receipts)
        ),
        encoding="utf-8",
    )
    plan = module.build_flow_canary_plan(work_domain_skill_benchmark.build_report())
    report = module.build_cutover_readiness_report(plan, receipt_dir=receipt_dir)
    target = {row["owner_tui"]: row for row in report["targets"]}[owner]

    assert target["cutover_ready"] is False
    assert target["metrics"]["synthetic_receipt_count"] == 50
    assert "synthetic receipts found" in "; ".join(target["blockers"])


def test_cutover_readiness_rejects_broken_route_receipt_chain(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    receipt_dir = tmp_path / "route_receipts"
    receipt_dir.mkdir()
    owner = "market-sizing"
    receipts = _chained_receipts(
        [_good_route_receipt(owner, index) for index in range(50)]
    )
    receipts[7]["previous_receipt_hash"] = "broken"
    (receipt_dir / f"{owner}.jsonl").write_text(
        "\n".join(json.dumps(receipt) for receipt in receipts),
        encoding="utf-8",
    )

    plan = module.build_flow_canary_plan(work_domain_skill_benchmark.build_report())
    report = module.build_cutover_readiness_report(plan, receipt_dir=receipt_dir)
    target = {row["owner_tui"]: row for row in report["targets"]}[owner]

    assert report["readiness"] == "not_ready_for_cutover"
    assert target["cutover_ready"] is False
    assert target["metrics"]["chain_issue_count"] >= 1
    assert "route receipt hash chain" in "; ".join(target["blockers"])
    assert target["chain_issues"]


def test_route_receipt_harvest_copies_configured_remote_sink(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    plan = {
        "schema": "norman.tui-flow-canary-plan.v1",
        "targets": [
            {
                "owner_tui": "market-sizing",
                "wave": 1,
                "route_receipt_sink": "/tmp/remote/market-sizing.jsonl",
            }
        ],
    }
    calls = []

    def fake_run(cmd, check, capture_output):
        calls.append(cmd)
        assert check is False
        assert capture_output is True
        return module.subprocess.CompletedProcess(
            cmd,
            0,
            stdout=b'{"receipt_id":"r1","owner_tui":"market-sizing"}\n',
            stderr=b"",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    report = module.harvest_route_receipts(plan, receipt_dir=tmp_path)

    assert report["schema"] == "norman.tui-route-receipt-harvest.v1"
    assert report["summary"]["copied_count"] == 1
    assert report["summary"]["line_count"] == 1
    assert report["targets"][0]["status"] == "copied"
    assert (tmp_path / "market-sizing.jsonl").read_text(encoding="utf-8") == (
        '{"receipt_id":"r1","owner_tui":"market-sizing"}\n'
    )
    assert calls
    assert calls[0][0] == "ssh"
    assert "test -f /tmp/remote/market-sizing.jsonl" in calls[0][-1]


def test_route_receipt_manifest_writes_synthetic_templates(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    receipt_dir = tmp_path / "route_receipts"
    template_dir = tmp_path / "templates"
    plan = module.build_flow_canary_plan(work_domain_skill_benchmark.build_report())
    manifest = module.build_route_receipt_manifest(
        plan,
        receipt_dir=receipt_dir,
        template_dir=template_dir,
    )
    markdown = module.render_route_receipt_manifest_markdown(manifest)
    targets = {row["owner_tui"]: row for row in manifest["targets"]}
    template = module.build_route_receipt_template(plan["targets"][0])

    assert manifest["schema"] == "norman.tui-route-receipt-manifest.v1"
    assert manifest["templates_are_synthetic"] is True
    assert manifest["templates_count_toward_cutover"] is False
    assert manifest["summary"]["wave_1_target_count"] == 1
    assert manifest["summary"]["required_wave_1_receipts_total"] == 50
    assert targets["market-sizing"]["receipt_path"] == str(
        receipt_dir / "market-sizing.jsonl"
    )
    assert targets["market-sizing"]["template_path"] == str(
        template_dir / "market-sizing.template.json"
    )
    assert template["synthetic"] is True
    assert template["receipt_source"] == "template_not_live_observation"
    assert "Templates are synthetic" in markdown


def test_bbs_missing_context_holds_optimizer_for_netops(monkeypatch) -> None:
    module = _load_work_loop_canary(monkeypatch)
    report = module.build_report(
        [
            {
                "_loop_slug": "networking",
                "_loop_url": "http://192.168.2.242:8791/api/status",
                "state": "ok",
                "pending": False,
                "queue_depth": 0,
                "selected_runtime": "codex",
                "selected_model": "gpt-5.5",
                "_bbs_summary": {
                    "actor": "netops",
                    "state": "watch",
                    "summary": "2 BBS handoff missing contexts",
                    "activity": "Waiting on creator evidence.",
                    "counts": {
                        "waiting_pickup": 2,
                        "picked_up": 1,
                        "missing_context": 2,
                        "actionable_high": 3,
                        "actionable_urgent": 0,
                    },
                },
            }
        ],
        source="fixture",
    )

    row = report["rows"][0]
    moves = {move["move_id"]: move for move in row["moves"]}

    assert report["summary"]["targets"] == 1
    assert report["summary"]["reachable"] == 1
    assert report["summary"]["route_ok"] == 1
    assert report["summary"]["idle_ready"] == 0
    assert report["summary"]["optimizer_ready"] == 0
    assert report["summary"]["bbs_missing_context_targets"] == 1
    assert report["summary"]["shadow_rollout_recommendation"] == "hold"
    assert row["blocks_new_loop_work"] is True
    assert row["optimizer_confidence_band"] == "yellow"
    assert "bbs_missing_context_guard" in moves
    assert moves["bbs_missing_context_guard"]["automatic"] is True
    assert moves["bbs_missing_context_guard"]["approval_required"] is False
    assert "Do not ACK" in moves["bbs_missing_context_guard"]["next_action"]


def test_bbs_waiting_pickup_holds_until_owner_intends_pickup(monkeypatch) -> None:
    module = _load_work_loop_canary(monkeypatch)
    report = module.build_report(
        [
            {
                "_loop_slug": "phone-ops",
                "state": "ok",
                "pending": False,
                "queue_depth": 0,
                "selected_runtime": "codex",
                "selected_model": "gpt-5.5",
                "_bbs_summary": {
                    "actor": "phoneops",
                    "state": "watch",
                    "summary": "1 BBS handoff waiting pickup",
                    "counts": {
                        "waiting_pickup": 1,
                        "picked_up": 0,
                        "missing_context": 0,
                    },
                },
            }
        ],
        source="fixture",
    )

    row = report["rows"][0]
    moves = {move["move_id"]: move for move in row["moves"]}

    assert report["summary"]["idle_ready"] == 0
    assert report["summary"]["optimizer_ready"] == 0
    assert report["summary"]["bbs_waiting_pickup_targets"] == 1
    assert report["summary"]["shadow_rollout_recommendation"] == "hold"
    assert row["optimizer_confidence_score"] == 85
    assert row["optimizer_confidence_band"] == "green"
    assert row["blocks_new_loop_work"] is True
    assert "bbs_pickup_review_packet" in moves
    assert "owner ACKs only" in moves["bbs_pickup_review_packet"]["next_action"]


def test_build_report_can_select_full_5_5_mode(monkeypatch) -> None:
    module = _load_work_loop_canary(monkeypatch)
    report = module.build_report(
        [
            {
                "_loop_slug": "control-plane",
                "state": "ok",
                "pending": False,
                "queue_depth": 0,
                "selected_runtime": "codex",
                "selected_model": "openai.gpt-5.5",
            }
        ],
        source="fixture",
        mode="full-5-5",
    )

    sample = report["cost_basis"]["sample_ticket_cleanup"]
    assert report["architecture_mode"] == "full-5-5"
    assert report["cost_basis"]["selected_mode"]["label"] == "Full GPT-5.5 loop"
    assert sample["selected_ratio_vs_direct_5_5_flex"] == 1.0
    assert (
        sample["selected_mode_direct_estimated_usd"]
        == sample["full_direct_5_5_flex_usd"]
    )
    assert report["always_on_plan"]["cost_confidence"] == "medium"


def test_always_on_budget_gate_holds_when_p95_cycle_exceeds_budget(
    monkeypatch,
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    report = module.build_report(
        [
            {
                "_loop_slug": "control-plane",
                "state": "ok",
                "pending": False,
                "queue_depth": 0,
                "selected_runtime": "codex",
                "selected_model": "openai.gpt-5.5",
            }
        ],
        source="fixture",
        daily_budget_usd=1.0,
        max_changed_tickets_per_cycle=3,
    )

    assert report["summary"]["shadow_rollout_recommendation"] == "ready"
    assert report["summary"]["always_on_shadow_gate"] == "hold"
    assert report["always_on_plan"]["spend_gate"] == "hold"
    assert (
        "p95 changed-ticket cycle exceeds daily budget"
        in report["always_on_plan"]["spend_gate_reasons"]
    )


def test_route_mismatch_requires_approval(monkeypatch) -> None:
    module = _load_work_loop_canary(monkeypatch)
    report = module.build_report(
        [
            {
                "_loop_slug": "control-plane",
                "state": "ok",
                "pending": False,
                "queue_depth": 0,
                "selected_runtime": "openai",
                "selected_model": "gpt-5.5",
            }
        ],
        source="fixture",
    )

    moves = {move["move_id"]: move for move in report["rows"][0]["moves"]}
    assert report["summary"]["route_ok"] == 0
    assert report["summary"]["idle_ready"] == 0
    assert moves["route_mismatch_to_bedrock_5_5"]["approval_required"] is True
    assert moves["route_mismatch_to_bedrock_5_5"]["automatic"] is False


def test_queue_pressure_blocks_new_loop_work(monkeypatch) -> None:
    module = _load_work_loop_canary(monkeypatch)
    report = module.build_report(
        [
            {
                "_loop_slug": "gold-book",
                "state": "ok",
                "pending": True,
                "queue_depth": 3,
                "selected_runtime": "codex",
                "selected_model": "openai.gpt-5.5",
            }
        ],
        source="fixture",
    )

    moves = {move["move_id"]: move for move in report["rows"][0]["moves"]}
    assert report["rows"][0]["loop_ready"] is False
    assert moves["queue_watch_packet"]["automatic"] is True
    assert "do not enqueue new loop work" in moves["queue_watch_packet"]["next_action"]


def test_usage_error_gets_classified_without_restart(monkeypatch) -> None:
    module = _load_work_loop_canary(monkeypatch)
    report = module.build_report(
        [
            {
                "_loop_slug": "control-plane",
                "state": "degraded",
                "pending": False,
                "queue_depth": 0,
                "selected_runtime": "codex",
                "selected_model": "openai.gpt-5.5",
                "last_error": "OpenAI Flex usage limit reached",
            }
        ],
        source="fixture",
    )

    moves = {move["move_id"]: move for move in report["rows"][0]["moves"]}
    assert "usage_or_quota_triage" in moves
    assert moves["usage_or_quota_triage"]["automatic"] is True
    assert "restart service" in moves["approval_boundary"]["evidence"][1]


def test_unreachable_status_returns_evidence_packet(monkeypatch) -> None:
    module = _load_work_loop_canary(monkeypatch)
    report = module.build_report(
        [
            {
                "_loop_slug": "control-plane",
                "_loop_url": "https://cp.kris.openbrand.com/api/status",
                "_loop_error": "URLError: timed out",
            }
        ],
        source="fixture",
    )

    moves = {move["move_id"]: move for move in report["rows"][0]["moves"]}
    assert report["summary"]["reachable"] == 0
    assert report["summary"]["idle_ready"] == 0
    assert moves["status_unreachable_packet"]["automatic"] is True
    assert moves["status_unreachable_packet"]["approval_required"] is False
    assert "restart blindly" in moves["status_unreachable_packet"]["reason"]


def test_cli_writes_report_from_source_json(tmp_path: Path, monkeypatch) -> None:
    module = _load_work_loop_canary(monkeypatch)
    source = tmp_path / "status.json"
    output_json = tmp_path / "canary.json"
    output_md = tmp_path / "canary.md"
    source.write_text(
        json.dumps(
            {
                "statuses": [
                    {
                        "_loop_slug": "control-plane",
                        "state": "ok",
                        "pending": False,
                        "queue_depth": 0,
                        "selected_runtime": "codex",
                        "selected_model": "openai.gpt-5.5",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "work_loop_canary.py",
            "--mode",
            "full-5-5",
            "--fast-loop-interval-seconds",
            "600",
            "--max-changed-tickets-per-cycle",
            "2",
            "--daily-budget-usd",
            "4",
            "--source-json",
            str(source),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
    )

    assert module.main() == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["schema"] == "norman.work-loop-canary.v1"
    assert data["architecture_mode"] == "full-5-5"
    assert data["summary"]["idle_ready"] == 1
    assert data["always_on_plan"]["fast_loop_interval_seconds"] == 600
    assert data["always_on_plan"]["max_changed_tickets_per_cycle"] == 2
    assert data["always_on_plan"]["daily_budget_usd"] == 4.0
    assert "Work Loop Canary" in output_md.read_text(encoding="utf-8")


def test_cli_flow_plan_only_writes_guarded_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    skill_matrix = tmp_path / "skill_matrix.json"
    output_json = tmp_path / "flow_plan.json"
    output_md = tmp_path / "flow_plan.md"
    skill_matrix.write_text(
        json.dumps(work_domain_skill_benchmark.build_report()),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "work_loop_canary.py",
            "--flow-plan-only",
            "--skill-matrix-json",
            str(skill_matrix),
            "--output-flow-plan-json",
            str(output_json),
            "--output-flow-plan-md",
            str(output_md),
        ],
    )

    assert module.main() == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["schema"] == "norman.tui-flow-canary-plan.v1"
    assert data["recommended_first_deploy_targets"] == ["market-sizing"]
    assert data["summary"]["workload_bucket_count"] == 4
    assert {
        row["owner_tui"] for row in data["workload_buckets_requiring_owner_mapping"]
    } >= {"work-special-comms", "work-special-mail"}
    markdown = output_md.read_text(encoding="utf-8")
    assert "TUI Flow Canary Plan" in markdown
    assert "Workload Buckets Needing Owner Mapping" in markdown


def test_cli_route_receipt_manifest_only_writes_templates(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    flow_plan = tmp_path / "flow_plan.json"
    output_json = tmp_path / "manifest.json"
    output_md = tmp_path / "manifest.md"
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    stale_template = template_dir / "work-special-comms.template.json"
    stale_template.write_text("{}", encoding="utf-8")
    plan = module.build_flow_canary_plan(work_domain_skill_benchmark.build_report())
    flow_plan.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "work_loop_canary.py",
            "--route-receipt-manifest-only",
            "--flow-plan-json",
            str(flow_plan),
            "--route-receipt-dir",
            str(tmp_path / "route_receipts"),
            "--route-receipt-template-dir",
            str(template_dir),
            "--output-route-receipt-manifest-json",
            str(output_json),
            "--output-route-receipt-manifest-md",
            str(output_md),
        ],
    )

    assert module.main() == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    template = json.loads(
        (template_dir / "market-sizing.template.json").read_text(encoding="utf-8")
    )
    assert data["schema"] == "norman.tui-route-receipt-manifest.v1"
    assert data["templates_count_toward_cutover"] is False
    assert data["summary"]["wave_1_target_count"] == 1
    assert template["synthetic"] is True
    assert template["owner_tui"] == "market-sizing"
    assert not stale_template.exists()
    assert "TUI Route Receipt Manifest" in output_md.read_text(encoding="utf-8")


def test_cli_route_receipt_launch_plan_prepares_market_sizing_sink(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    flow_plan = tmp_path / "flow_plan.json"
    manifest_json = tmp_path / "manifest.json"
    manifest_md = tmp_path / "manifest.md"
    launch_json = tmp_path / "launch.json"
    launch_md = tmp_path / "launch.md"
    receipt_dir = tmp_path / "route_receipts"
    template_dir = tmp_path / "templates"
    plan = module.build_flow_canary_plan(work_domain_skill_benchmark.build_report())
    flow_plan.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "work_loop_canary.py",
            "--route-receipt-manifest-only",
            "--flow-plan-json",
            str(flow_plan),
            "--route-receipt-dir",
            str(receipt_dir),
            "--route-receipt-template-dir",
            str(template_dir),
            "--output-route-receipt-manifest-json",
            str(manifest_json),
            "--output-route-receipt-manifest-md",
            str(manifest_md),
        ],
    )
    assert module.main() == 0
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "work_loop_canary.py",
            "--route-receipt-launch-plan-only",
            "--prepare-route-receipt-sink",
            "--output-route-receipt-manifest-json",
            str(manifest_json),
            "--output-route-receipt-launch-json",
            str(launch_json),
            "--output-route-receipt-launch-md",
            str(launch_md),
        ],
    )

    assert module.main() == 0
    data = json.loads(launch_json.read_text(encoding="utf-8"))
    sink = receipt_dir / "market-sizing.jsonl"
    assert data["schema"] == "norman.tui-route-receipt-launch-plan.v1"
    assert data["owner_tui"] == "market-sizing"
    assert data["launch_status"] == "ready_for_operator_approved_shadow_capture"
    assert data["live_mutation_performed"] is False
    assert data["receipt_sink"]["prepared"] is True
    assert data["receipt_sink"]["exists"] is True
    assert data["env"]["NORMAN_CODEX_ROUTE_RECEIPT_PATH"] == str(sink)
    assert sink.exists()
    assert "TUI Route Receipt Launch Plan" in launch_md.read_text(encoding="utf-8")


def test_cli_route_receipt_harvest_only_writes_local_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    flow_plan = tmp_path / "flow_plan.json"
    harvest_json = tmp_path / "harvest.json"
    harvest_md = tmp_path / "harvest.md"
    receipt_dir = tmp_path / "route_receipts"
    plan = module.build_flow_canary_plan(work_domain_skill_benchmark.build_report())
    flow_plan.write_text(json.dumps(plan), encoding="utf-8")

    def fake_run(cmd, check, capture_output):
        assert check is False
        assert capture_output is True
        return module.subprocess.CompletedProcess(
            cmd,
            0,
            stdout=b'{"receipt_id":"r1","owner_tui":"market-sizing"}\n',
            stderr=b"",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "work_loop_canary.py",
            "--harvest-route-receipts-only",
            "--flow-plan-json",
            str(flow_plan),
            "--route-receipt-dir",
            str(receipt_dir),
            "--harvest-route-receipt-owners",
            "market-sizing",
            "--output-route-receipt-harvest-json",
            str(harvest_json),
            "--output-route-receipt-harvest-md",
            str(harvest_md),
        ],
    )

    assert module.main() == 0
    data = json.loads(harvest_json.read_text(encoding="utf-8"))
    assert data["schema"] == "norman.tui-route-receipt-harvest.v1"
    assert data["summary"]["copied_count"] == 1
    assert (receipt_dir / "market-sizing.jsonl").exists()
    assert "TUI Route Receipt Harvest" in harvest_md.read_text(encoding="utf-8")


def test_cli_cutover_readiness_only_writes_guarded_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_work_loop_canary(monkeypatch)
    import work_domain_skill_benchmark

    flow_plan = tmp_path / "flow_plan.json"
    historic_route = tmp_path / "historic_route.json"
    output_json = tmp_path / "cutover.json"
    output_md = tmp_path / "cutover.md"
    plan = module.build_flow_canary_plan(work_domain_skill_benchmark.build_report())
    flow_plan.write_text(json.dumps(plan), encoding="utf-8")
    _write_historic_route_benchmark(historic_route)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "work_loop_canary.py",
            "--cutover-readiness-only",
            "--flow-plan-json",
            str(flow_plan),
            "--route-receipt-dir",
            str(tmp_path / "route_receipts"),
            "--historic-route-benchmark-json",
            str(historic_route),
            "--output-cutover-readiness-json",
            str(output_json),
            "--output-cutover-readiness-md",
            str(output_md),
        ],
    )

    assert module.main() == 0
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["schema"] == "norman.tui-cutover-readiness.v1"
    assert data["readiness"] == "not_ready_for_cutover"
    assert data["historic_route_benchmark"]["gate"] == "pass"
    assert "TUI Cutover Readiness" in output_md.read_text(encoding="utf-8")


def test_cli_loop_mode_writes_cp_journal(tmp_path: Path, monkeypatch) -> None:
    module = _load_work_loop_canary(monkeypatch)
    output_json = tmp_path / "canary.json"
    output_md = tmp_path / "canary.md"
    output_journal = tmp_path / "journal.json"
    calls = []

    def fake_fetch_statuses(targets, timeout):
        calls.append((targets, timeout))
        return [
            {
                "_loop_slug": "control-plane",
                "state": "ok",
                "pending": False,
                "queue_depth": 0,
                "selected_runtime": "codex",
                "selected_model": "openai.gpt-5.5",
            }
        ]

    monkeypatch.setattr(module, "fetch_statuses", fake_fetch_statuses)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "work_loop_canary.py",
            "--targets",
            "control-plane",
            "--loop-count",
            "3",
            "--loop-interval",
            "0",
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--output-journal-json",
            str(output_journal),
        ],
    )

    assert module.main() == 0
    journal = json.loads(output_journal.read_text(encoding="utf-8"))
    assert len(calls) == 3
    assert journal["schema"] == "norman.work-loop-canary-journal.v1"
    assert journal["cycles"] == 3
    assert journal["summary"]["all_cycles_loop_ready"] is True
    assert journal["summary"]["continuous_loop_enabled"] is False
    assert all(
        row["slug"] == "control-plane"
        for cycle in journal["cycles_detail"]
        for row in cycle["rows"]
    )


def test_cli_ticket_id_writes_internal_cost_ledger(tmp_path: Path, monkeypatch) -> None:
    module = _load_work_loop_canary(monkeypatch)
    source = tmp_path / "status.json"
    output_json = tmp_path / "canary.json"
    output_md = tmp_path / "canary.md"
    ledger_jsonl = tmp_path / "ticket_costs.jsonl"
    source.write_text(
        json.dumps(
            {
                "statuses": [
                    {
                        "_loop_slug": "control-plane",
                        "state": "ok",
                        "pending": False,
                        "queue_depth": 0,
                        "selected_runtime": "codex",
                        "selected_model": "openai.gpt-5.5",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "work_loop_canary.py",
            "--mode",
            "hybrid",
            "--source-json",
            str(source),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--ticket-id",
            "CP-DRY-1",
            "--ticket-cost-ledger-jsonl",
            str(ledger_jsonl),
            "--ticket-notes",
            "dry canary",
        ],
    )

    assert module.main() == 0
    records = [
        json.loads(line)
        for line in ledger_jsonl.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    assert records[0]["ticket"]["id"] == "CP-DRY-1"
    assert records[0]["architecture"]["mode"] == "hybrid"
    assert records[0]["source"]["kind"] == "work_loop_canary"
    assert records[0]["usage"]["total_tokens"] == 0
    assert records[0]["cost"]["estimated_usd"] == 0.0
    assert records[0]["metadata"]["dry_run_only"] is True
