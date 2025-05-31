import asyncio
from app.connectors.steam_connector import SteamConnector


def test_process_incoming():
    connector = SteamConnector(api_key='x', chat_id='C1')
    payload = {'text': 'hi', 'user': 'U1'}
    result = asyncio.run(connector.process_incoming(payload))
    assert result == payload
