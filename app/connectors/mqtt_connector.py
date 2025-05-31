try:
    import paho.mqtt.client as mqtt
except ModuleNotFoundError:  # pragma: no cover - library may be absent in tests
    import types

    class DummyClient:
        def __init__(self):
            self.published = []
        def connect(self, *args, **kwargs):
            pass

        def disconnect(self):
            pass

        def publish(self, *args, **kwargs):
            self.published.append((args[0], args[1] if len(args) > 1 else None))

    mqtt = types.SimpleNamespace(Client=DummyClient)
from .base_connector import BaseConnector


class MQTTConnector(BaseConnector):
    """Simple MQTT connector implementation."""

    id = 'mqtt'
    name = 'MQTT'

    def __init__(self, broker_url: str, topic: str, config=None):
        super().__init__(config)
        self.broker_url = broker_url
        self.topic = topic
        self.client = mqtt.Client()

    def connect(self):
        self.client.connect(self.broker_url)

    def disconnect(self):
        self.client.disconnect()

    def send_message(self, message: str, topic: str | None = None):
        self.client.publish(topic or self.topic, message)

    def receive_message(self):
        # Placeholder for a real receive implementation
        return []

    def listen_and_process(self):
        results = []
        for message in self.receive_message():
            processed = self.process_incoming(message)
            if processed:
                results.append(processed)
        return results

    def process_incoming(self, message):
        if not isinstance(message, dict):
            return {}
        return {
            'topic': message.get('topic', self.topic),
            'payload': message.get('payload'),
        }
