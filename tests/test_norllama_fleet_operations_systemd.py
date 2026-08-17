from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "scripts" / "systemd"


def test_fleet_policy_refresh_is_periodic_and_noninteractive() -> None:
    service = (SYSTEMD / "norllama-fleet-policy-refresh.service").read_text(
        encoding="utf-8"
    )
    timer = (SYSTEMD / "norllama-fleet-policy-refresh.timer").read_text(
        encoding="utf-8"
    )

    assert "User=kristopher" in service
    assert "refresh_fleet_route_policy.py --apply --output" in service
    assert "--stage-only" not in service
    assert "OnUnitActiveSec=6h" in timer
    assert "Persistent=true" in timer


def test_fleet_health_alerts_reuse_the_standard_alert_contract() -> None:
    service = (SYSTEMD / "norllama-fleet-health.service").read_text(encoding="utf-8")
    alerts = (SYSTEMD / "norllama-fleet-alerts.service").read_text(encoding="utf-8")
    path = (SYSTEMD / "norllama-fleet-alerts.path").read_text(encoding="utf-8")

    assert "norllama-fleet-health.json" in service
    assert "tui_fleet_alerts.py" in alerts
    assert "norllama-fleet-health.json" in path


def test_policy_refresh_failures_trigger_the_standard_alert_contract() -> None:
    alerts = (SYSTEMD / "norllama-fleet-policy-refresh-alerts.service").read_text(
        encoding="utf-8"
    )
    path = (SYSTEMD / "norllama-fleet-policy-refresh-alerts.path").read_text(
        encoding="utf-8"
    )

    assert "tui_fleet_alerts.py" in alerts
    assert "norllama-fleet-policy-refresh.json" in path
