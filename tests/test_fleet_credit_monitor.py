from types import SimpleNamespace

import pytest

from app.services.console_status import ConsoleCreditAssessment
from app.services.fleet_credit_monitor import FleetCreditMonitorService


@pytest.mark.asyncio
async def test_fleet_credit_monitor_carries_subscription_capacity(monkeypatch) -> None:
    service = FleetCreditMonitorService()
    connector = SimpleNamespace(
        id=7,
        name="tmux-personal",
        config={"web_url": "https://eyebat.home.arpa/"},
    )
    monkeypatch.setattr(
        "app.services.fleet_credit_monitor.fetch_console_status",
        lambda *_args, **_kwargs: {
            "reachable": True,
            "usage_tracked": True,
            "codex_subscription_capacity_state": "available",
            "codex_subscription_capacity_fresh": True,
            "codex_subscription_capacity_observed_at": 1234567800,
            "codex_subscription_capacity_percent_left": 84,
            "codex_subscription_capacity_reset_hint": "2h 10m",
            "codex_subscription_capacity_eligible": True,
            "codex_subscription_capacity_tokens_per_hour": 4321,
            "codex_subscription_capacity_projected_tokens_to_reset": 9362,
        },
    )
    monkeypatch.setattr(
        "app.services.fleet_credit_monitor.classify_console_credit_assessment",
        lambda _status: ConsoleCreditAssessment(),
    )

    await service._check_one(connector)
    snapshot = await service.get_snapshot(connector.id)
    summary = await service.get_summary([connector.id])

    assert snapshot is not None
    assert snapshot.codex_subscription_capacity_percent_left == 84
    assert snapshot.codex_subscription_capacity_eligible is True
    assert summary["codex_subscription_capacity_available"] == 1
    assert summary["codex_subscription_capacity_eligible"] == 1
