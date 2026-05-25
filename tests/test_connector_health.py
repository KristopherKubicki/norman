import pytest

from app import models
from app.services.connector_health import ConnectorHealthService


@pytest.mark.asyncio
async def test_connector_health_service_tracks_bounded_history(monkeypatch):
    service = ConnectorHealthService()
    service.history_limit = 3
    results = iter([False, False, True, False])

    class DummyConnector:
        def is_connected(self):
            result = next(results)
            if result:
                return True
            raise RuntimeError("connector down")

    monkeypatch.setattr(
        "app.services.connector_health.get_connector",
        lambda *args, **kwargs: DummyConnector(),
    )

    connector = models.Connector(id=1, connector_type="irc", config={})
    for _ in range(4):
        await service._check_one(connector)

    history = await service.get_history(1, limit=10)
    assert len(history) == 3
    assert history[0].status == "down"
    assert history[1].status == "up"
    assert history[2].status == "down"
    assert any(entry.error for entry in history)
