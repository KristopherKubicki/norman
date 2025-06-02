import asyncio
from app.connectors.xcom_connector import XComConnector


def test_send_message():
    connector = XComConnector("k", "s", "at", "ats")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message("hi")
    )
    assert result == "sent"
    assert connector.sent_messages == ["hi"]


def test_process_incoming():
    connector = XComConnector("k", "s", "at", "ats")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"msg": 1})
    )
    assert result == {"msg": 1}
