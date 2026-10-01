from __future__ import annotations

import json
from pathlib import Path

from app.services.tui_fleet_health import (
    public_status_eligibility,
    read_tui_fleet_health,
)


def test_failed_private_workflow_cannot_create_public_incident() -> None:
    decision = public_status_eligibility(
        verified_customer_impact=False,
        component="Data API",
    )

    assert decision == {
        "visibility": "private",
        "incident_eligible": False,
        "component": "Data API",
        "reason": "customer_impact_not_verified",
    }


def test_verified_approved_component_is_public_status_eligible() -> None:
    decision = public_status_eligibility(
        verified_customer_impact=True,
        component="data api",
    )

    assert decision == {
        "visibility": "public",
        "incident_eligible": True,
        "component": "Data API",
        "reason": "verified_customer_impact",
    }


def test_unapproved_component_is_never_public_status_eligible() -> None:
    decision = public_status_eligibility(
        verified_customer_impact=True,
        component="Internal scheduler",
    )

    assert decision == {
        "visibility": "private",
        "incident_eligible": False,
        "component": "Internal scheduler",
        "reason": "component_not_approved_for_public_status",
    }


def test_reader_keeps_workflow_controls_private(tmp_path: Path) -> None:
    health_path = tmp_path / "health.json"
    health_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "summary": {},
                "hosts": [],
                "issues": [],
                "workflow_health": {
                    "visibility": "public",
                    "controls": [
                        {
                            "id": "openbrand_product_placement_recovery_control",
                            "visibility": "public",
                            "live_status_source": True,
                            "public_status_eligible": True,
                        }
                    ],
                    "public_status": {
                        "verified_customer_impact": False,
                        "component": "Data API",
                        "incident_eligible": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    health = read_tui_fleet_health(health_path)
    workflow = health["workflow_health"]
    control = workflow["controls"][0]

    assert workflow["visibility"] == "private"
    assert control["visibility"] == "private"
    assert control["live_status_source"] is False
    assert control["public_status_eligible"] is False
    assert workflow["public_status"]["incident_eligible"] is False
    assert workflow["public_status"]["visibility"] == "private"
