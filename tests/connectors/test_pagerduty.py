import requests
from app.connectors.pagerduty_connector import PagerDutyConnector

class DummyResponse:
    def __init__(self, text="ok", status=200):
        self.text = text
        self.status_code = status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.RequestException("error")

def test_send_message_success(monkeypatch):
    def fake_post(url, json=None):
        assert "events.pagerduty.com" in url
        return DummyResponse("sent")
    monkeypatch.setattr(requests, "post", fake_post)
    connector = PagerDutyConnector("KEY")
    assert connector.send_message({"summary": "hi"}) == "sent"

def test_send_message_error(monkeypatch):
    def fake_post(url, json=None):
        raise requests.RequestException("boom")
    monkeypatch.setattr(requests, "post", fake_post)
    connector = PagerDutyConnector("KEY")
    assert connector.send_message({"summary": "hi"}) is None
