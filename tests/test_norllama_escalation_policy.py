from copy import deepcopy

from app.services.norllama.escalation_policy import (
    ESCALATION_CONTROLLER_CONTRACT,
    MODEL_BY_ROLE,
    build_production_escalation_decision,
    build_shadow_escalation_decision,
    selected_cloud_model,
    selected_cloud_reason,
)


def test_qwen_is_the_default_resident_route() -> None:
    decision = build_shadow_escalation_decision(
        {"lane": "helpdesk", "risk": "low", "complexity": "simple"}
    )

    assert decision["proposed_role"] == "resident"
    assert decision["proposed_model"] == MODEL_BY_ROLE["resident"]
    assert decision["cloud_required"] is False
    assert decision["execution_model_unchanged"] is True
    assert decision["execution_authority_changed"] is False


def test_production_decision_changes_execution_model() -> None:
    decision = build_production_escalation_decision(
        {"lane": "llm_prep", "complexity": "moderate", "qwen_confidence": 0.9}
    )

    assert decision["mode"] == "production"
    assert decision["status"] == "selected"
    assert decision["proposed_model"] == MODEL_BY_ROLE["economy"]
    assert decision["execution_model_unchanged"] is False
    assert decision["execution_authority_changed"] is True


def test_resident_decision_never_becomes_a_cloud_model() -> None:
    resident = build_production_escalation_decision(
        {"lane": "helpdesk", "risk": "low", "complexity": "simple"}
    )
    economy = build_production_escalation_decision(
        {"lane": "llm_prep", "complexity": "moderate"}
    )

    assert resident["proposed_role"] == "resident"
    assert selected_cloud_model(resident) == ""
    assert selected_cloud_model(resident, direct=True) == ""
    assert selected_cloud_reason(resident) == ""
    assert selected_cloud_model(economy) == MODEL_BY_ROLE["economy"]
    assert selected_cloud_model(economy, direct=True) == "gpt-5.6-luna"
    assert selected_cloud_reason(economy).startswith(
        "Norllama production controller selected luna:"
    )


def test_luna_handles_moderate_or_uncertain_qwen_work() -> None:
    moderate = build_shadow_escalation_decision(
        {"lane": "llm_prep", "complexity": "moderate"}
    )
    uncertain = build_shadow_escalation_decision(
        {"lane": "web_crawl", "qwen_confidence": 0.6}
    )

    assert moderate["proposed_model"] == MODEL_BY_ROLE["economy"]
    assert uncertain["proposed_model"] == MODEL_BY_ROLE["economy"]


def test_terra_owns_authority_and_consequential_actions() -> None:
    decision = build_shadow_escalation_decision(
        {
            "lane": "purchase_behavior",
            "financial_action": True,
            "external_side_effect": True,
        }
    )

    assert decision["proposed_model"] == MODEL_BY_ROLE["authority"]
    assert decision["approval_required"] is True
    assert "authority_or_risk_boundary" in decision["reason_codes"]


def test_sol_is_blocked_without_prior_terra() -> None:
    blocked = build_shadow_escalation_decision(
        {
            "lane": "multi_agent",
            "requested_tier": "sol",
            "final_check": True,
        }
    )
    allowed = build_shadow_escalation_decision(
        {
            "lane": "multi_agent",
            "requested_tier": "sol",
            "final_check": True,
            "prior_tiers": ["terra"],
        }
    )

    assert blocked["proposed_model"] == MODEL_BY_ROLE["authority"]
    assert "frontier_blocked_without_prior_authority" in blocked["reason_codes"]
    assert allowed["proposed_model"] == MODEL_BY_ROLE["frontier"]
    assert allowed["sol_gate"]["passed"] is True


def test_unhealthy_local_runtime_uses_lane_cloud_default() -> None:
    luna = build_shadow_escalation_decision(
        {"lane": "llm_prep", "local_runtime_healthy": False}
    )
    terra = build_shadow_escalation_decision(
        {"lane": "code_flow", "local_runtime_healthy": False}
    )

    assert luna["proposed_model"] == MODEL_BY_ROLE["economy"]
    assert terra["proposed_model"] == MODEL_BY_ROLE["authority"]


def test_common_request_aliases_fail_closed() -> None:
    consequential = build_shadow_escalation_decision(
        {
            "lane": "data_operations",
            "local_healthy": True,
            "side_effects": True,
        }
    )
    local_down = build_shadow_escalation_decision(
        {"lane": "llm_prep", "local_healthy": False}
    )
    sol = build_shadow_escalation_decision(
        {
            "lane": "multi_agent",
            "sol_candidate": True,
            "prior_terra_evidence": True,
        }
    )

    assert consequential["proposed_model"] == MODEL_BY_ROLE["authority"]
    assert consequential["approval_required"] is True
    assert local_down["proposed_model"] == MODEL_BY_ROLE["economy"]
    assert sol["proposed_model"] == MODEL_BY_ROLE["frontier"]


def test_model_upgrade_requires_only_a_registry_change() -> None:
    controller = deepcopy(ESCALATION_CONTROLLER_CONTRACT)
    controller["registry_version"] = "future-eval-winner"
    controller["roles"]["resident"]["model"] = "future-local:40b"
    controller["roles"]["economy"]["model"] = "future-cloud-fast"
    controller["roles"]["authority"]["model"] = "future-cloud-authority"
    controller["roles"]["frontier"]["model"] = "future-cloud-frontier"

    resident = build_shadow_escalation_decision({}, controller=controller)
    economy = build_shadow_escalation_decision(
        {"complexity": "moderate"}, controller=controller
    )
    authority = build_shadow_escalation_decision(
        {"side_effects": True}, controller=controller
    )
    frontier = build_shadow_escalation_decision(
        {
            "requested_role": "frontier",
            "prior_roles": ["authority"],
        },
        controller=controller,
    )

    assert resident["proposed_model"] == "future-local:40b"
    assert economy["proposed_model"] == "future-cloud-fast"
    assert authority["proposed_model"] == "future-cloud-authority"
    assert frontier["proposed_model"] == "future-cloud-frontier"
    assert frontier["registry_version"] == "future-eval-winner"
