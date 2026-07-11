import asyncio

from app.connectors.docker_events_connector import DockerEventsConnector


def test_process_incoming_docker_event_normalizes_fields():
    connector = DockerEventsConnector(config={})
    payload = {
        "Type": "container",
        "Action": "start",
        "Actor": {
            "ID": "abc123",
            "Attributes": {"name": "web", "image": "nginx:latest"},
        },
        "host": "dock-1",
        "time": 1739933000,
    }

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )

    assert result["text"] == "container start web nginx:latest"
    assert result["event_type"] == "container"
    assert result["action"] == "start"
    assert result["container"] == "web"
    assert result["image"] == "nginx:latest"
    assert result["host"] == "dock-1"
    assert result["event_id"] == "abc123"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "docker_events"
    assert result["sensor_type"] == "containers"


def test_process_incoming_docker_string_uses_passive_defaults():
    connector = DockerEventsConnector(config={})

    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming("container crashed")
    )

    assert result["text"] == "container crashed"
    assert result["signal_class"] == "passive"
    assert result["passive_source"] == "docker_events"
    assert result["sensor_type"] == "containers"
