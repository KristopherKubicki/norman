from pathlib import Path


def test_session_guard_units_are_low_priority_and_preserve_active_work():
    root = Path(__file__).resolve().parents[1]
    prune_service = (
        root / "scripts" / "systemd" / "codex-session-prune.service"
    ).read_text(encoding="utf-8")
    pressure_service = (
        root / "scripts" / "systemd" / "norman-codex-session-pressure.service"
    ).read_text(encoding="utf-8")
    alerts_service = (
        root / "scripts" / "systemd" / "norman-codex-session-pressure-alerts.service"
    ).read_text(encoding="utf-8")
    deploy = (root / "scripts" / "deploy_codex_session_guard.sh").read_text(
        encoding="utf-8"
    )

    for service in (prune_service, pressure_service):
        assert "Nice=19" in service
        assert "IOSchedulingClass=idle" in service
    assert "codex_session_prune.py" in prune_service
    assert "codex_session_pressure.py" in pressure_service
    assert "ConditionPathExists=/etc/norman/tui-fleet-alerts.env" in alerts_service
    assert "norman-tui-local-host-pressure-alerts.service" in deploy
    assert "norman-tui-fleet-alerts.service" in deploy
