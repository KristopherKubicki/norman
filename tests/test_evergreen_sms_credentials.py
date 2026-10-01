from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from urllib import parse


CLOUD_DIR = Path(__file__).resolve().parents[1] / "projects" / "evergreen-sms-cloud"


def _load_cloud_module(filename: str, module_name: str):
    if str(CLOUD_DIR) not in sys.path:
        sys.path.insert(0, str(CLOUD_DIR))
    spec = importlib.util.spec_from_file_location(module_name, CLOUD_DIR / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_twilio_token_uses_secret_manager_and_caches(monkeypatch) -> None:
    module = _load_cloud_module(
        "twilio_credentials.py", "evergreen_sms_credentials_for_tests"
    )
    calls: list[str] = []

    class SecretsClient:
        def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
            calls.append(SecretId)
            return {"SecretString": json.dumps({"auth_token": "secret-token"})}

    monkeypatch.setenv("TWILIO_AUTH_TOKEN_SECRET_ARN", "arn:secret:twilio")
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(module.boto3, "client", lambda service: SecretsClient())
    module._TOKEN_CACHE.clear()

    assert module.twilio_auth_token() == "secret-token"
    assert module.twilio_auth_token() == "secret-token"
    assert calls == ["arn:secret:twilio"]


def test_twilio_token_allows_environment_only_for_local_fallback(monkeypatch) -> None:
    module = _load_cloud_module(
        "twilio_credentials.py", "evergreen_sms_credentials_local_for_tests"
    )
    monkeypatch.delenv("TWILIO_AUTH_TOKEN_SECRET_ARN", raising=False)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "local-token")

    assert module.twilio_auth_token() == "local-token"


def test_inbound_handler_uses_secret_backed_token_without_aws(monkeypatch) -> None:
    module = _load_cloud_module("inbound_handler.py", "evergreen_sms_inbound_for_tests")
    used_tokens: list[str] = []

    class Store:
        def __init__(self, _table: Any, **_kwargs: Any) -> None:
            pass

        def accept_inbound(self, _incoming: Any) -> dict[str, Any]:
            return {"should_dispatch": False}

    class Dynamo:
        def Table(self, _name: str) -> object:
            return object()

    class Boto:
        def resource(self, service: str) -> Dynamo:
            assert service == "dynamodb"
            return Dynamo()

    params = {
        "MessageSid": "SM-1",
        "From": "+15550000001",
        "To": "+15550000002",
        "AccountSid": "AC-1",
        "Body": "hello",
    }
    webhook_url = "https://example.test/twilio/inbound"
    signature = base64.b64encode(
        __import__("hmac")
        .new(
            b"secret-token",
            (
                webhook_url + "".join(f"{key}{params[key]}" for key in sorted(params))
            ).encode("utf-8"),
            __import__("hashlib").sha1,
        )
        .digest()
    ).decode("ascii")
    monkeypatch.setenv("SMS_CONVERSATIONS_TABLE", "conversations")
    monkeypatch.setenv("INBOUND_QUEUE_URL", "https://sqs.example.test/inbound")
    monkeypatch.setenv("TWILIO_WEBHOOK_URL", webhook_url)
    monkeypatch.setattr(
        module,
        "twilio_auth_token",
        lambda: used_tokens.append("secret-manager") or "secret-token",
    )
    monkeypatch.setattr(module, "ConversationStore", Store)
    monkeypatch.setattr(module, "boto3", Boto())

    response = module.lambda_handler(
        {
            "body": parse.urlencode(params),
            "headers": {"X-Twilio-Signature": signature},
            "rawPath": "/twilio/inbound",
        },
        None,
    )

    assert response["statusCode"] == 200
    assert response["body"] == "<Response/>"
    assert used_tokens == ["secret-manager"]


def test_outbound_handler_loads_secret_before_twilio_request(monkeypatch) -> None:
    module = _load_cloud_module(
        "outbound_handler.py", "evergreen_sms_outbound_for_tests"
    )
    captured: dict[str, Any] = {}

    class Response:
        status = 201

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return b'{"sid":"SM-outbound"}'

    def fake_urlopen(req: Any, *, timeout: int) -> Response:
        captured["authorization"] = req.get_header("Authorization")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(module, "twilio_auth_token", lambda: "secret-token")
    monkeypatch.setattr(module.request, "urlopen", fake_urlopen)

    provider_sid = module._twilio_send(
        {
            "account_sid": "AC-1",
            "from": "+15550000002",
            "to": "+15550000001",
            "body": "Done.",
        }
    )

    assert provider_sid == "SM-outbound"
    assert captured["timeout"] == 15
    assert captured["authorization"] == "Basic QUMtMTpzZWNyZXQtdG9rZW4="
