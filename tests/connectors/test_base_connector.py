import asyncio
import contextlib
from app.connectors.base_connector import BaseConnector

class DummyConnector(BaseConnector):
    def __init__(self):
        super().__init__()
        self.sent = []
    def send_message(self, message):
        self.sent.append(message)
    async def listen_and_process(self):
        return None
    async def process_incoming(self, message):
        return message


def test_queue_and_dispatcher():
    connector = DummyConnector()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(connector.queue_message("hi"))
    task = loop.create_task(connector._dispatcher())
    loop.run_until_complete(asyncio.sleep(0))
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        loop.run_until_complete(task)
    assert connector.sent == ["hi"]
