import asyncio

from app.connectors.prometheus_alertmanager_connector import (
    PrometheusAlertmanagerConnector,
)


def test_process_incoming_alertmanager_event_normalizes_fields():
    connector = PrometheusAlertmanagerConnector(config={})
    payload = {
        "receiver": "norman",
        "status": "firing",
        "alerts": [
            {
                "labels": {"alertname": "HighCPU", "instance": "srv-1"},
                "annotations": {"summary": "CPU > 90%"},
            }
        ],
    }

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )

    assert result["text"] == "CPU > 90%"
    assert result["receiver"] == "norman"
    assert result["status"] == "firing"
    assert result["alert_count"] == 1
    assert result["alert_name"] == "HighCPU"
    assert result["instance"] == "srv-1"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "prometheus_alertmanager"
    assert result["sensor_type"] == "observability"


def test_process_incoming_alertmanager_string_uses_passive_defaults():
    connector = PrometheusAlertmanagerConnector(config={})

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming("alertmanager notify")
    )

    assert result["text"] == "alertmanager notify"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "prometheus_alertmanager"
    assert result["sensor_type"] == "observability"
