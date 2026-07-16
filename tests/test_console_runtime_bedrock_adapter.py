from __future__ import annotations

import json

import pytest

from app.services.console_runtime.adapters.bedrock import BedrockModelAdapter
from app.services.console_runtime.adapters.norllama import NorllamaModelAdapter
from app.services.console_runtime.types import ModelBudget, ModelRequest
from app.services.console_runtime.worker import (
    ConsoleRuntimeRunOptions,
    DbConsoleRuntimeWorker,
)
from app.services.norllama import bedrock as bedrock_module
from app.services.norllama.routing import route_task
from app.services.norllama.types import NorllamaTaskRequest


class _FakeBedrockClient:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response or {}
        self.error = error
        self.calls: list[dict] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def _request() -> ModelRequest:
    return ModelRequest(
        messages=[
            {"role": "system", "content": "Follow the kernel policy."},
            {"role": "user", "content": "Plan the rollout."},
            {"role": "assistant", "content": "I will inspect the release gates."},
            {"role": "user", "content": "Return the final plan."},
        ],
        model="anthropic.claude-test",
        system="You are the runtime planner.",
        temperature=0.35,
        budget=ModelBudget(max_output_tokens=321),
        metadata={
            "request_id": "bedrock-request-1",
            "invocation_id": "worker:job-bedrock:plan:1:model",
            "console_runtime_job_id": "job-bedrock",
            "norllama_task_kind": "plan",
            "route_policy": {
                "provider": "bedrock",
                "model": "anthropic.claude-test",
                "allow_cloud_proxy": True,
                "aws_region": "us-east-2",
                "aws_profile": "norman-bedrock",
            },
        },
    )


def test_bedrock_adapter_builds_native_converse_request_and_receipt():
    client = _FakeBedrockClient(
        {
            "stopReason": "end_turn",
            "usage": {
                "inputTokens": 12,
                "outputTokens": 8,
                "totalTokens": 20,
            },
            "output": {
                "message": {
                    "content": [{"text": "Inspect tests."}, {"text": "Ship safely."}]
                }
            },
        }
    )
    factory_calls: list[dict] = []

    def client_factory(**kwargs):
        factory_calls.append(kwargs)
        return client

    result = BedrockModelAdapter(client_factory=client_factory).invoke(_request())

    assert len(factory_calls) == 1
    factory_call = factory_calls[0]
    assert {key: value for key, value in factory_call.items() if key != "config"} == {
        "service_name": "bedrock-runtime",
        "region_name": "us-east-2",
        "profile_name": "norman-bedrock",
    }
    assert factory_call["config"].connect_timeout == 10.0
    assert factory_call["config"].read_timeout == 300.0
    assert factory_call["config"].retries == {
        "mode": "standard",
        "total_max_attempts": 1,
    }
    assert client.calls == [
        {
            "modelId": "anthropic.claude-test",
            "system": [
                {"text": "You are the runtime planner."},
                {"text": "Follow the kernel policy."},
            ],
            "messages": [
                {"role": "user", "content": [{"text": "Plan the rollout."}]},
                {
                    "role": "assistant",
                    "content": [{"text": "I will inspect the release gates."}],
                },
                {
                    "role": "user",
                    "content": [{"text": "Return the final plan."}],
                },
            ],
            "inferenceConfig": {"maxTokens": 321, "temperature": 0.35},
        }
    ]
    assert result.provider == "bedrock"
    assert result.model == "anthropic.claude-test"
    assert result.text == "Inspect tests.\nShip safely."
    assert result.stop_reason == "end_turn"
    assert result.usage.as_dict() == {
        "input_tokens": 12,
        "output_tokens": 8,
        "total_tokens": 20,
    }
    receipt = result.metadata["norllama_receipt"]["route_receipt"]
    assert receipt["selected_provider"] == "bedrock"
    assert receipt["cloud_proxy"] is True
    assert receipt["usage_bucket"] == "bedrock_amazon"
    assert receipt["input_tokens"] == 12
    assert receipt["output_tokens"] == 8
    assert receipt["total_tokens"] == 20
    assert receipt["invocation_id"] == "worker:job-bedrock:plan:1:model"
    assert result.metadata["bedrock_timeout_seconds"] == 300.0


def test_bedrock_adapter_applies_explicit_timeout_bounded_by_model_budget():
    client = _FakeBedrockClient(
        {
            "output": {"message": {"content": [{"text": "bounded"}]}},
            "usage": {},
        }
    )
    config_calls: list[dict] = []
    request = _request()
    request.budget = ModelBudget(max_runtime_seconds=45, max_output_tokens=321)
    request.metadata["route_policy"]["bedrock_timeout_seconds"] = 120

    result = BedrockModelAdapter(
        client_factory=lambda **kwargs: client,
        config_factory=lambda **kwargs: config_calls.append(kwargs) or kwargs,
    ).invoke(request)

    assert config_calls == [
        {
            "connect_timeout": 10.0,
            "read_timeout": 45.0,
            "retries": {"mode": "standard", "total_max_attempts": 1},
        }
    ]
    assert result.metadata["bedrock_timeout_seconds"] == 45.0


def test_bedrock_adapter_uses_brokered_norman_keys_credentials_without_receipt_leak(
    monkeypatch,
):
    monkeypatch.setenv("NORMAN_KEYS_URL", "http://keys.norman.test")
    monkeypatch.setenv("NORMAN_KEYS_TOKEN", "keys-api-token")
    monkeypatch.setenv("NORMAN_KEYS_TIMEOUT_SECONDS", "2.5")
    monkeypatch.delenv("NORMAN_SECRET_CMD", raising=False)
    requests: list[tuple[object, float]] = []
    access_key_id = "TEST_AWS_ACCESS_KEY"
    secret_access_key = "TEST_AWS_SECRET_KEY"
    session_token = "TEST_AWS_SESSION_TOKEN"

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "value": json.dumps(
                        {
                            "aws_access_key_id": access_key_id,
                            "aws_secret_access_key": secret_access_key,
                            "aws_session_token": session_token,
                        }
                    ),
                    "lease_id": "lease-bedrock-1",
                    "request_id": "keys-request-1",
                    "expires_at": "2026-07-16T18:30:00+00:00",
                }
            ).encode()

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(bedrock_module.urllib_request, "urlopen", fake_urlopen)
    client = _FakeBedrockClient(
        {
            "output": {"message": {"content": [{"text": "brokered"}]}},
            "usage": {},
        }
    )
    session_calls: list[dict] = []
    client_calls: list[dict] = []

    class FakeSession:
        def client(self, service_name, **kwargs):
            client_calls.append({"service_name": service_name, **kwargs})
            return client

    def session_factory(**kwargs):
        session_calls.append(kwargs)
        return FakeSession()

    request = _request()
    request.metadata["route_policy"]["aws_credentials_secret"] = (
        "host.hal.aws.credentials"
    )
    result = BedrockModelAdapter(session_factory=session_factory).invoke(request)

    assert session_calls == [
        {
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
            "aws_session_token": session_token,
            "region_name": "us-east-2",
        }
    ]
    assert client_calls[0]["service_name"] == "bedrock-runtime"
    assert "profile_name" not in client_calls[0]
    assert len(requests) == 1
    broker_request, broker_timeout = requests[0]
    assert broker_request.full_url == "http://keys.norman.test/v1/secrets/get"
    assert broker_request.get_header("Authorization") == "Bearer keys-api-token"
    assert broker_timeout == 2.5
    payload = json.loads(broker_request.data.decode())
    assert payload["name"] == "host.hal.aws.credentials"
    assert payload["requester_id"] == "console-runtime-bedrock"
    assert payload["session_id"] == "job-bedrock"
    assert result.metadata["bedrock_profile"] == ""
    assert result.metadata["bedrock_credentials"] == {
        "source": "norman_keys",
        "secret_name": "host.hal.aws.credentials",
        "lease_id": "lease-bedrock-1",
        "request_id": "keys-request-1",
        "expires_at": "2026-07-16T18:30:00+00:00",
    }
    receipt = result.metadata["norllama_receipt"]["route_receipt"]
    assert receipt["cloud_credentials"] == result.metadata["bedrock_credentials"]
    serialized = json.dumps(
        {
            "metadata": result.metadata,
            "receipt": receipt,
            "raw": result.raw,
        },
        sort_keys=True,
    )
    assert access_key_id not in serialized
    assert secret_access_key not in serialized
    assert session_token not in serialized


def test_bedrock_credentials_can_use_norman_secret_command(monkeypatch):
    monkeypatch.delenv("NORMAN_KEYS_URL", raising=False)
    monkeypatch.delenv("NORMAN_KEYS_API_BASE", raising=False)
    monkeypatch.delenv("NORMAN_KEYS_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("NORMAN_SECRET_CMD", "keysctl read {name}")
    calls: list[tuple[list[str], dict]] = []

    class Result:
        stdout = json.dumps(
            {
                "credentials": {
                    "AccessKeyId": "TEST_AWS_ACCESS_KEY",
                    "SecretAccessKey": "TEST_AWS_SECRET_KEY",
                    "SessionToken": "TEST_AWS_SESSION_TOKEN",
                }
            }
        )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr(bedrock_module.subprocess, "run", fake_run)

    credentials = bedrock_module.resolve_bedrock_credentials(
        {"aws_credentials_secret": "host.hal.aws.credentials"},
        timeout_seconds=12,
        session_id="job-bedrock",
    )

    assert credentials is not None
    assert credentials.access_key_id == "TEST_AWS_ACCESS_KEY"
    assert credentials.secret_access_key == "TEST_AWS_SECRET_KEY"
    assert credentials.session_token == "TEST_AWS_SESSION_TOKEN"
    assert credentials.receipt_metadata() == {
        "source": "secret_command",
        "secret_name": "host.hal.aws.credentials",
    }
    assert calls == [
        (
            ["keysctl", "read", "host.hal.aws.credentials"],
            {
                "check": True,
                "capture_output": True,
                "text": True,
                "timeout": 2.0,
            },
        )
    ]


def test_bedrock_adapter_propagates_native_converse_failure():
    client = _FakeBedrockClient(error=RuntimeError("AccessDeniedException"))

    with pytest.raises(RuntimeError, match="AccessDeniedException"):
        BedrockModelAdapter(client_factory=lambda **kwargs: client).invoke(_request())


def test_bedrock_adapter_rejects_serialized_cloud_route_without_policy_permission():
    client = _FakeBedrockClient()
    request = _request()
    policy = request.metadata["route_policy"]
    route = route_task(
        NorllamaTaskRequest(
            kind="plan",
            messages=request.messages,
            route_policy=policy,
            metadata=request.metadata,
        )
    )
    request.metadata["norllama_route"] = route.as_dict()
    request.metadata["route_policy"] = {
        **policy,
        "allow_cloud_proxy": False,
    }

    result = BedrockModelAdapter(client_factory=lambda **kwargs: client).invoke(request)

    assert client.calls == []
    assert result.stop_reason == "policy_blocked"
    assert result.metadata["policy_authorization"]["reason"] == (
        "bedrock_cloud_proxy_not_explicitly_allowed"
    )
    receipt = result.metadata["norllama_receipt"]["route_receipt"]
    assert receipt["policy_authorization"]["allowed"] is False


def test_bedrock_adapter_blocks_before_brokered_credential_lookup(monkeypatch):
    client = _FakeBedrockClient()
    request = _request()
    policy = request.metadata["route_policy"]
    route = route_task(
        NorllamaTaskRequest(
            kind="plan",
            messages=request.messages,
            route_policy=policy,
            metadata=request.metadata,
        )
    )
    request.metadata["norllama_route"] = route.as_dict()
    request.metadata["route_policy"] = {
        **policy,
        "allow_cloud_proxy": False,
        "aws_credentials_secret": "networking/bedrock",
    }
    monkeypatch.setenv("NORMAN_KEYS_URL", "http://keys.norman.test")
    monkeypatch.delenv("NORMAN_SECRET_CMD", raising=False)

    def unexpected_broker_lookup(*_args, **_kwargs):
        raise AssertionError("blocked Bedrock route must not request credentials")

    monkeypatch.setattr(
        bedrock_module.urllib_request,
        "urlopen",
        unexpected_broker_lookup,
    )

    result = BedrockModelAdapter(client_factory=lambda **kwargs: client).invoke(request)

    assert client.calls == []
    assert result.stop_reason == "policy_blocked"
    assert result.metadata["policy_authorization"]["reason"] == (
        "bedrock_cloud_proxy_not_explicitly_allowed"
    )


def test_bedrock_adapter_rejects_serialized_route_when_policy_selects_norllama():
    client = _FakeBedrockClient()
    request = _request()
    policy = request.metadata["route_policy"]
    route = route_task(
        NorllamaTaskRequest(
            kind="plan",
            messages=request.messages,
            route_policy=policy,
            metadata=request.metadata,
        )
    )
    request.metadata["norllama_route"] = route.as_dict()
    request.metadata["route_policy"] = {
        **policy,
        "provider": "norllama",
        "allow_cloud_proxy": True,
    }

    result = BedrockModelAdapter(client_factory=lambda **kwargs: client).invoke(request)

    assert client.calls == []
    assert result.stop_reason == "policy_blocked"
    assert result.metadata["policy_authorization"]["reason"] == (
        "bedrock_route_not_selected_by_policy"
    )


def test_bedrock_adapter_honors_cloud_disabled_mode_before_invocation():
    client = _FakeBedrockClient()
    request = _request()
    request.metadata["route_policy"] = {
        **request.metadata["route_policy"],
        "cloud_llm_disabled": True,
    }

    result = BedrockModelAdapter(client_factory=lambda **kwargs: client).invoke(request)

    assert client.calls == []
    assert result.stop_reason == "policy_blocked"
    assert result.metadata["policy_authorization"]["reason"] == (
        "bedrock_cloud_llm_disabled_by_policy"
    )


def test_bedrock_adapter_reports_missing_boto3(monkeypatch):
    monkeypatch.setattr(bedrock_module, "boto3", None)

    with pytest.raises(RuntimeError, match="boto3 is not installed"):
        BedrockModelAdapter().invoke(_request())


def test_bedrock_session_factory_receives_named_profile_and_region(monkeypatch):
    monkeypatch.setattr(bedrock_module, "boto3", None)
    session_calls: list[dict] = []
    client_calls: list[dict] = []
    expected_client = object()

    class FakeSession:
        def client(self, service_name, **kwargs):
            client_calls.append({"service_name": service_name, **kwargs})
            return expected_client

    def session_factory(**kwargs):
        session_calls.append(kwargs)
        return FakeSession()

    client = bedrock_module.create_bedrock_runtime_client(
        region="us-east-2",
        profile="norman-bedrock",
        session_factory=session_factory,
    )

    assert client is expected_client
    assert session_calls == [
        {"profile_name": "norman-bedrock", "region_name": "us-east-2"}
    ]
    assert client_calls == [
        {"service_name": "bedrock-runtime", "region_name": "us-east-2"}
    ]


def test_worker_defaults_to_bedrock_only_for_selected_bedrock_cloud_proxy_route():
    worker = DbConsoleRuntimeWorker()
    options = ConsoleRuntimeRunOptions(
        dry_run=False,
        live_execution_approved=True,
    )

    bedrock = worker._default_adapter(
        options,
        "use native Bedrock",
        route={"provider": "bedrock", "cloud_proxy": True},
    )
    local = worker._default_adapter(
        options,
        "keep local default",
        route={"provider": "bedrock", "cloud_proxy": False},
    )
    local_bedrock = worker._default_adapter(
        options,
        "do not use a native cloud adapter for a local lane",
        route={"provider": "bedrock", "cloud_proxy": True, "local": True},
    )
    tool_bedrock = worker._default_adapter(
        options,
        "do not use a native cloud adapter for a tool lane",
        route={"provider": "bedrock", "cloud_proxy": True, "tool_lane": True},
    )
    other_cloud = worker._default_adapter(
        options,
        "do not infer a Bedrock adapter",
        route={"provider": "openai", "cloud_proxy": True},
    )
    codex = worker._default_adapter(
        options,
        "keep Codex behind the Norllama path",
        route={"provider": "codex", "cloud_proxy": True},
    )
    string_false = worker._default_adapter(
        options,
        "do not treat serialized false as true",
        route={"provider": "bedrock", "cloud_proxy": "false"},
    )

    assert isinstance(bedrock, BedrockModelAdapter)
    assert isinstance(local, NorllamaModelAdapter)
    assert isinstance(local_bedrock, NorllamaModelAdapter)
    assert isinstance(tool_bedrock, NorllamaModelAdapter)
    assert isinstance(other_cloud, NorllamaModelAdapter)
    assert isinstance(codex, NorllamaModelAdapter)
    assert isinstance(string_false, NorllamaModelAdapter)
