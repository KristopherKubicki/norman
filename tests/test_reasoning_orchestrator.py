from app.services.reasoning_orchestrator import (
    build_reasoning_receipt,
    build_skill_registry,
    kpi_background_loop_plan,
    plan_reasoning_turn,
)


def _classification(**overrides):
    data = {
        "intent": "verify_or_audit",
        "task_kind": "verify",
        "risk_class": "read_only",
        "risk_level": "low",
        "requires_approval": False,
        "external_side_effects_possible": False,
    }
    data.update(overrides)
    return data


def test_skill_registry_contains_kpi_background_skills():
    registry = build_skill_registry()
    skill_ids = {skill["skill_id"] for skill in registry["skills"]}

    assert registry["schema"] == "norman.skill-registry.v1"
    assert registry["skill_count"] >= 10
    assert "kpi.status_snapshot" in skill_ids
    assert "kpi.receipt_integrity" in skill_ids
    assert "kpi.operator_cohort" in skill_ids
    assert "runtime.tool_planner" in skill_ids


def test_quick_status_gets_instant_reasoning_and_status_skill():
    plan = plan_reasoning_turn(
        prompt="status?",
        classification=_classification(
            intent="quick_status",
            task_kind="summarize",
        ),
        source="uplink",
        session="uplink-codex",
    )

    assert plan["schema"] == "norman.reasoning-orchestrator.plan.v1"
    assert plan["reasoning_tier"]["tier"] == "instant"
    assert plan["reasoning_tier"]["max_tool_iterations"] == 1
    assert "kpi.status_snapshot" in plan["selected_skill_ids"]
    assert "tui_status_api" in plan["tool_plan"]["required_tools"]
    assert plan["tool_plan"]["continuous_tool_use"] is False
    assert plan["cloud_policy"]["position"] == "last_resort_after_local_receipt"


def test_release_kpi_prompt_gets_continuous_tool_use_budget():
    plan = plan_reasoning_turn(
        prompt=(
            "Build the release KPI packet with signed receipts, local/cloud "
            "ledger proof, benchmark freshness, and operator cohort evidence."
        ),
        classification=_classification(),
        source="norman",
        session="norman-codex",
    )

    assert plan["reasoning_tier"]["tier"] in {"deep", "extended"}
    assert plan["tool_plan"]["continuous_tool_use"] is True
    assert plan["tool_plan"]["max_tool_iterations"] >= 8
    assert "kpi.receipt_integrity" in plan["selected_skill_ids"]
    assert "kpi.operator_cohort" in plan["selected_skill_ids"]
    assert "kpi.release_packet" in plan["selected_skill_ids"]
    assert "signed_receipt_ledger" in plan["tool_plan"]["required_tools"]
    assert "packet_manifest_validator" in plan["tool_plan"]["verification_tools"]


def test_approval_risk_promotes_to_authority_and_forbids_unbound_actions():
    plan = plan_reasoning_turn(
        prompt="go ahead and ship it",
        classification=_classification(
            intent="ship_or_release",
            task_kind="verify",
            risk_class="external_mutation",
            risk_level="high",
            requires_approval=True,
            external_side_effects_possible=True,
        ),
        context={
            "active_job_count": 1,
            "pending_action_risk": "prod_write",
        },
    )

    assert plan["reasoning_tier"]["tier"] == "authority"
    assert "runtime.approval_guard" in plan["selected_skill_ids"]
    assert "approval_binding_checker" in plan["tool_plan"]["required_tools"]
    assert "unbound_approval_action" in plan["tool_plan"]["forbidden_tools"]
    assert "unapproved_external_mutation" in plan["tool_plan"]["forbidden_tools"]


def test_reasoning_receipt_tracks_skipped_required_tools_until_observed():
    plan = plan_reasoning_turn(
        prompt="status?",
        classification=_classification(
            intent="quick_status",
            task_kind="summarize",
        ),
    )

    planned = build_reasoning_receipt(plan)
    assert planned["completion_state"] == "planned"
    assert planned["receipt_complete"] is False
    assert "tui_status_api" in planned["skipped_required_tools"]

    observed = build_reasoning_receipt(
        plan,
        executed_tools=[
            {"tool": "tui_status_api", "status": "pass"},
            {"tool": "route_receipt_ledger", "status": "pass"},
        ],
        verifier_result="pass",
    )
    assert observed["completion_state"] == "observed"
    assert observed["receipt_complete"] is True
    assert observed["skipped_required_tools"] == []


def test_kpi_background_loop_is_local_only_and_receipted():
    plan = kpi_background_loop_plan()
    skill_ids = {candidate["skill_id"] for candidate in plan["candidates"]}

    assert plan["schema"] == "norman.kpi-background-loop.plan.v1"
    assert plan["model_calls_required"] == 0
    assert plan["loop_policy"]["cloud_allowed"] is False
    assert plan["loop_policy"]["record_signed_receipts"] is True
    assert "kpi.status_snapshot" in skill_ids
    assert "kpi.cost_counterfactual" in skill_ids
