import asyncio

from app.connectors.glimpser_connector import GlimpserConnector


def test_process_incoming_glimpser_event_normalizes_fields():
    connector = GlimpserConnector(config={})
    payload = {
        "event": "motion.detected",
        "camera": "Front Door",
        "summary": "Person detected at front door",
        "confidence": 94,
        "image_url": "https://example.com/snap.jpg",
    }

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )

    assert result["text"] == "Person detected at front door"
    assert result["event"] == "motion.detected"
    assert result["camera"] == "Front Door"
    assert result["confidence"] == 94
    assert result["image_url"] == "https://example.com/snap.jpg"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "glimpser"
    assert result["sensor_type"] == "vision"


def test_process_incoming_string_uses_webhook_fallback():
    connector = GlimpserConnector(config={})

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming("motion near driveway")
    )

    assert result["text"] == "motion near driveway"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "glimpser"
    assert result["sensor_type"] == "vision"
