from app.api.api_v1.routers.connectors import sms as sms_router


def _create_sms_connector(test_app):
    response = test_app.post(
        "/api/v1/connectors/",
        json={
            "connector_type": "sms",
            "name": "Housebot SMS",
            "config": {
                "account_sid": "SID",
                "auth_token": "TOKEN",
                "from_number": "+15550000001",
                "to_number": "+15550000002",
            },
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_process_sms_update_for_connector(monkeypatch, test_app):
    captured = {}

    class DummyConnector:
        def __init__(
            self,
            account_sid: str,
            auth_token: str,
            from_number: str,
            to_number: str,
            config=None,
        ):
            captured["config"] = {
                "account_sid": account_sid,
                "auth_token": auth_token,
                "from_number": from_number,
                "to_number": to_number,
            }

        def verify_signature(self, signature: str, url: str, form):
            captured["signature"] = (signature, url, dict(form))
            return True

        async def process_incoming(self, payload):
            captured["incoming"] = dict(payload)
            return {
                "text": payload.get("Body", ""),
                "from": payload.get("From"),
                "sid": payload.get("MessageSid"),
                "text_summary": "sms • hello from housebot",
            }

    async def fake_enqueue_routing_job(*, db, connector, normalized, payload):
        captured["enqueued"] = {
            "connector_id": connector.id,
            "normalized": normalized,
            "payload": payload,
        }

    monkeypatch.setattr(sms_router, "SMSConnector", DummyConnector)
    monkeypatch.setattr(sms_router, "enqueue_routing_job", fake_enqueue_routing_job)

    connector_id = _create_sms_connector(test_app)
    response = test_app.post(
        f"/api/v1/connectors/sms/webhooks/sms/{connector_id}",
        data={
            "Body": "hello from housebot",
            "From": "+15551230000",
            "To": "+15557650000",
            "MessageSid": "SM123",
        },
    )

    assert response.status_code == 200
    assert captured["config"]["from_number"] == "+15550000001"
    assert captured["incoming"]["Body"] == "hello from housebot"
    assert captured["enqueued"]["connector_id"] == connector_id
    assert captured["enqueued"]["payload"]["MessageSid"] == "SM123"
    assert captured["enqueued"]["normalized"]["text"] == "hello from housebot"


def test_process_sms_update_for_connector_rejects_invalid_signature(
    monkeypatch, test_app
):
    class DummyConnector:
        def __init__(
            self,
            account_sid: str,
            auth_token: str,
            from_number: str,
            to_number: str,
            config=None,
        ):
            pass

        def verify_signature(self, signature: str, url: str, form):
            return False

        async def process_incoming(self, payload):  # pragma: no cover - must not run
            raise AssertionError(
                "process_incoming should not run for invalid signature"
            )

    async def fail_enqueue(**kwargs):  # pragma: no cover - must not run
        raise AssertionError("enqueue_routing_job should not run for invalid signature")

    monkeypatch.setattr(sms_router, "SMSConnector", DummyConnector)
    monkeypatch.setattr(sms_router, "enqueue_routing_job", fail_enqueue)

    connector_id = _create_sms_connector(test_app)
    response = test_app.post(
        f"/api/v1/connectors/sms/webhooks/sms/{connector_id}",
        data={"Body": "blocked"},
        headers={"X-Twilio-Signature": "bad-signature"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid Twilio signature"
