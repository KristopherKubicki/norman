import asyncio
from app.connectors.linkedin_connector import LinkedInConnector


def test_send_message():
    connector = LinkedInConnector("token")
    result = asyncio.get_event_loop().run_until_complete(
        connector.send_message("hello")
    )
    assert result == "sent"
    assert connector.sent_messages == ["hello"]


def test_process_incoming():
    connector = LinkedInConnector("token")
    result = asyncio.get_event_loop().run_until_complete(
        connector.process_incoming({"foo": "bar"})
    )
    assert result == {"foo": "bar"}
