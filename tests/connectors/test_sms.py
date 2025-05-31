import requests
from app.connectors.sms_connector import SMSConnector


class DummyResponse:
    def __init__(self, text="ok", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("error")


def test_send_message_success(monkeypatch):
    def fake_post(url, data=None, auth=None):
        assert "Accounts" in url
        assert data["Body"] == "hello"
        assert auth == ("SID", "TOKEN")
        return DummyResponse("sent")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = SMSConnector(
        account_sid="SID",
        auth_token="TOKEN",
        from_number="+1",
        to_number="+2",
    )
    assert connector.send_message("hello") == "sent"


def test_send_message_error(monkeypatch):
    def fake_post(url, data=None, auth=None):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "post", fake_post)
    connector = SMSConnector(
        account_sid="SID",
        auth_token="TOKEN",
        from_number="+1",
        to_number="+2",
    )
    assert connector.send_message("hello") is None
