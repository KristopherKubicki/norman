import json
from pathlib import Path

import scripts.tui_auto_mode_benchmark as module


def _sample_kpi_benchmark(path: Path) -> None:
    payload = {
        "runs": [
            {
                "run_id": "kpi-weekly-1-codex_bedrock_5_5",
                "runtime": "codex",
                "model": "openai.gpt-5.5",
                "service_tier": "default",
                "state": "ok",
                "response": (
                    "DONE\n"
                    "- Weekly KPI core sync for 2026-06-01-2026-06-07 succeeded.\n"
                    "- Key SKU availability ended at 98.14%.\n"
                    "- Accuracy landed at 58.0%.\n"
                    "Evidence: audit/kpi_core/run.json"
                ),
                "usage": {
                    "input_tokens": 480000,
                    "cached_input_tokens": 220000,
                    "output_tokens": 5500,
                    "reasoning_output_tokens": 1500,
                    "duration_seconds": 136,
                },
            },
            {
                "run_id": "kpi-weekly-2-codex_openai_flex_5_5",
                "runtime": "codex",
                "model": "gpt-5.5",
                "service_tier": "flex",
                "state": "ok",
                "response": "DONE\n- one\n- two\n- three\nEvidence: audit",
                "usage": {
                    "input_tokens": 1060000,
                    "cached_input_tokens": 970000,
                    "output_tokens": 9300,
                    "reasoning_output_tokens": 2100,
                    "duration_seconds": 147,
                },
            },
            {
                "run_id": "kpi-weekly-forced-claude",
                "runtime": "claude",
                "model": "global.anthropic.claude-opus-4-8",
                "service_tier": "default",
                "state": "ok",
                "response": "BLOCKED - brokered tool budget reached",
                "usage": {
                    "input_tokens": 125000,
                    "cached_input_tokens": 0,
                    "output_tokens": 1800,
                    "reasoning_output_tokens": 0,
                    "duration_seconds": 37,
                },
            },
            {
                "run_id": "kpi-weekly-claude-route-mismatch",
                "runtime": "claude",
                "model": "global.anthropic.claude-opus-4-8",
                "service_tier": "default",
                "state": "ok",
                "response": (
                    "DONE\n"
                    "- Weekly KPI core sync for 2026-06-01-2026-06-07 succeeded.\n"
                    "- Key SKU availability ended at 98.14%.\n"
                    "- Accuracy landed at 58.0%.\n"
                    "Evidence: audit/kpi_core/run.json"
                ),
                "usage": {
                    "runtime": "codex",
                    "model": "openai.gpt-5.5",
                    "service_tier": "default",
                    "input_tokens": 333000,
                    "cached_input_tokens": 202000,
                    "output_tokens": 3900,
                    "reasoning_output_tokens": 1200,
                    "duration_seconds": 92,
                },
            },
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sample_kpi_status(path: Path) -> None:
    payload = {
        "ui_version": "2026.06.12.1",
        "state": "ok",
        "pending": False,
        "default_service_tier": "default",
        "default_optimization_mode": "auto",
        "service_tier_options": [{"key": "auto"}, {"key": "default"}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sample_skill_matrix(path: Path) -> None:
    payload = {
        "schema": "norman.work-domain-skill-benchmark.v1",
        "priority_focus": {
            "domains": ["control-plane", "runbook-governance", "gold-book"],
            "owners": ["control-plane", "gold-book"],
            "domain_skill_count": 50,
            "owner_skill_count": 24,
            "rationale": [
                "Control Plane fronts live routing, dashboards, scripts, and admin surfaces.",
                "Runbook governance decides whether repeated operator work is safe to promote into durable automation.",
                "Gold Book carries source provenance, category governance, and live SpecMaster boundaries.",
            ],
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sample_cutover_readiness(path: Path) -> None:
    payload = {
        "schema": "norman.tui-cutover-readiness.v1",
        "readiness": "ready_for_wave_1_limited_cutover",
        "ready_targets": ["market-sizing"],
        "promotion_ready_targets": ["panelbot"],
        "summary": {
            "receipt_count": 59,
            "ready_target_count": 1,
            "promotion_ready_target_count": 1,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sample_invoice_reconciled_ledger(path: Path) -> None:
    rows = [
        {
            "usage": {"model": "openai.gpt-5.5"},
            "billing": {
                "price_basis": "bedrock-us-east-2",
                "charge_status": "invoice_reconciled",
            },
        },
        {
            "usage": {"model": "gpt-5.4-mini"},
            "billing": {
                "price_basis": "openai-direct-flex",
                "charge_status": "invoice_reconciled",
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_auto_mode_benchmark_projects_auto_cheaper_than_raw(tmp_path) -> None:
    kpi_benchmark = tmp_path / "kpis.json"
    kpi_status = tmp_path / "status.json"
    skill_matrix = tmp_path / "missing-skill-matrix.json"
    cutover_readiness = tmp_path / "missing-cutover.json"
    ticket_cost_ledger = tmp_path / "missing-ledger.jsonl"
    _sample_kpi_benchmark(kpi_benchmark)
    _sample_kpi_status(kpi_status)

    report = module.build_report(
        kpi_benchmark_json=kpi_benchmark,
        kpi_status_json=kpi_status,
        skill_matrix_json=skill_matrix,
        cutover_readiness_json=cutover_readiness,
        ticket_cost_ledger_jsonl=ticket_cost_ledger,
        gaphelp_ticket_count=30,
        gaphelp_max_do=5,
        gaphelp_budget_usd=25.0,
    )

    rows = {(row["operation_id"], row["mode_id"]): row for row in report["kpi_matrix"]}
    auto = rows[("kpi_weekly_3_bullet_quick", "auto_bedrock_5_5")]
    raw = rows[("kpi_weekly_3_bullet_quick", "bedrock_raw_5_5")]
    watch = rows[("kpi_weekly_3_bullet_quick", "watch_only")]

    assert report["dry_run_only"] is True
    assert report["model_calls_executed"] == 0
    assert auto["estimated_usd"] < raw["estimated_usd"]
    assert auto["observed_rate_card_usd"] < auto["expected_usd"] < auto["p95_usd"]
    assert (
        auto["billable_output_tokens"]
        == auto["output_tokens"] + auto["reasoning_output_tokens"]
    )
    assert auto["cost_confidence"] == "medium-low"
    assert len(auto["cost_scenario_estimates"]) == 3
    assert auto["live_auto_route_check"]["default_optimization_mode"] == "auto"
    assert watch["estimated_usd"] == 0.0
    assert watch["reliability_score"] < auto["reliability_score"]
    assert (
        report["gaphelp_easy"]["recommendation"]["expected_usd"]
        > report["gaphelp_easy"]["recommendation"]["observed_rate_card_usd"]
    )
    mismatch = next(
        row
        for row in report["observed_kpi_checks"]
        if row["run_id"] == "kpi-weekly-claude-route-mismatch"
    )
    assert mismatch["content_pass"] is True
    assert mismatch["route_proven"] is False
    assert mismatch["did_right_thing"] is False
    assert report["sources"]["rate_card_checked_on"] == "2026-06-12"
    gate = report["optimizer_efficiency_gate"]
    assert gate["schema"] == "norman.tui.optimizer-efficiency-gate.v1"
    assert gate["shadow_ready"] is True
    assert gate["fully_optimized"] is False
    assert gate["live_default_ready"] is False
    assert gate["auto_default_ready"] is True
    assert gate["status"] == "shadow_ready_budget_guarded"
    assert gate["minimum_expected_savings_rate"] > 0
    assert gate["p95_budget_overrun_count"] >= 1
    assert gate["route_proof"]["ready"] is True
    assert gate["cutover_alignment"]["configured"] is False
    assert gate["priority_focus_alignment"]["ready"] is False
    assert gate["invoice_reconciliation"]["ready"] is False
    assert gate["live_default_blockers"]
    assert any("p95" in item for item in gate["live_default_blockers"])
    assert gate["zero_model_watch_loop"]["estimated_usd"] == 0.0
    assert gate["zero_model_watch_loop"]["model_calls_executed"] == 0
    assert report["summary"]["optimizer_status"] == gate["status"]
    assert report["summary"]["optimizer_shadow_ready"] is True
    assert report["summary"]["optimizer_live_default_ready"] is False
    assert report["gaphelp_easy"]["recommendation"]["policy_id"] in {
        "local_prefilter_hybrid_top",
        "cheap_triage_top5",
        "cheap_triage_top10",
    }


def test_auto_mode_benchmark_cli_writes_artifacts(tmp_path) -> None:
    kpi_benchmark = tmp_path / "kpis.json"
    kpi_status = tmp_path / "status.json"
    skill_matrix = tmp_path / "missing-skill-matrix.json"
    cutover_readiness = tmp_path / "missing-cutover.json"
    ticket_cost_ledger = tmp_path / "missing-ledger.jsonl"
    output_json = tmp_path / "report.json"
    output_md = tmp_path / "report.md"
    _sample_kpi_benchmark(kpi_benchmark)
    _sample_kpi_status(kpi_status)

    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/tui_auto_mode_benchmark.py",
            "--kpi-benchmark-json",
            str(kpi_benchmark),
            "--kpi-status-json",
            str(kpi_status),
            "--skill-matrix-json",
            str(skill_matrix),
            "--cutover-readiness-json",
            str(cutover_readiness),
            "--ticket-cost-ledger-jsonl",
            str(ticket_cost_ledger),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0
    assert output_json.exists()
    assert output_md.exists()
    markdown = output_md.read_text(encoding="utf-8")
    assert "TUI Auto Mode Shadow Benchmark" in markdown
    assert "Optimizer Efficiency Gate" in markdown
    assert "shadow_ready_budget_guarded" in markdown
    assert "Optimizer Holds" in markdown
    assert "Live Default Blockers" in markdown
    assert "Evidence Alignment" in markdown
    assert "local no-model prefilter" in markdown
    assert "KPI Model/Mode Matrix" in markdown
    assert "Observed | Expected | P95" in markdown


def test_auto_mode_benchmark_computes_live_and_full_ready_from_artifacts(
    tmp_path,
) -> None:
    kpi_benchmark = tmp_path / "kpis.json"
    kpi_status = tmp_path / "status.json"
    skill_matrix = tmp_path / "skill-matrix.json"
    cutover_readiness = tmp_path / "cutover.json"
    ticket_cost_ledger = tmp_path / "ledger.jsonl"
    _sample_kpi_benchmark(kpi_benchmark)
    _sample_kpi_status(kpi_status)
    _sample_skill_matrix(skill_matrix)
    _sample_cutover_readiness(cutover_readiness)
    _sample_invoice_reconciled_ledger(ticket_cost_ledger)

    report = module.build_report(
        kpi_benchmark_json=kpi_benchmark,
        kpi_status_json=kpi_status,
        skill_matrix_json=skill_matrix,
        cutover_readiness_json=cutover_readiness,
        ticket_cost_ledger_jsonl=ticket_cost_ledger,
        gaphelp_ticket_count=30,
        gaphelp_max_do=5,
        gaphelp_budget_usd=250.0,
        gaphelp_backlog_ticket_count=100,
        gaphelp_backlog_max_do=10,
        gaphelp_backlog_budget_usd=250.0,
    )

    gate = report["optimizer_efficiency_gate"]
    assert gate["status"] == "fully_optimized"
    assert gate["shadow_ready"] is True
    assert gate["live_default_ready"] is True
    assert gate["fully_optimized"] is True
    assert gate["p95_budget_overrun_count"] == 0
    assert gate["cutover_alignment"]["ready_for_live_default"] is True
    assert gate["cutover_alignment"]["ready_for_broad_optimization"] is True
    assert gate["priority_focus_alignment"]["ready"] is True
    assert gate["invoice_reconciliation"]["ready"] is True
    assert (
        gate["invoice_reconciliation"]["missing_invoice_reconciled_provider_paths"]
        == []
    )
    assert gate["live_default_blockers"] == []
    assert gate["fully_optimized_blockers"] == []
    assert report["summary"]["optimizer_fully_optimized"] is True
