import asyncio
from app.connectors.opcua_pubsub_connector import OPCUAPubSubConnector


def test_send_message():
    connector = OPCUAPubSubConnector("opc.tcp://server")
    result = asyncio.get_event_loop().run_until_complete(connector.send_message("hi"))
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = OPCUAPubSubConnector("opc.tcp://server")
    payload = {"foo": 1}
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming(payload)
    )
    assert result == payload
