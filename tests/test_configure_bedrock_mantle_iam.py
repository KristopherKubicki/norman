from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "configure_bedrock_mantle_iam.py"
)


def _load_module():
    module_name = f"configure_bedrock_mantle_iam_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class FakeIam:
    def __init__(self, decisions=None):
        self.decisions = decisions or {}
        self.put_calls = []
        self.simulation_calls = []

    def put_user_policy(self, **kwargs):
        self.put_calls.append(kwargs)

    def simulate_principal_policy(self, **kwargs):
        self.simulation_calls.append(kwargs)
        action = kwargs["ActionNames"][0]
        decision = self.decisions.get(action, "allowed")
        return {"EvaluationResults": [{"EvalDecision": decision}]}


class FakeSession:
    def __init__(self, iam):
        self.iam = iam

    def client(self, service):
        if service == "sts":
            return SimpleNamespace(
                get_caller_identity=lambda: {"Account": "970651210182"}
            )
        assert service == "iam"
        return self.iam


def test_policy_scopes_inference_to_one_project():
    module = _load_module()

    document = module.policy_document("970651210182", "us-east-2", "default")

    inference = document["Statement"][0]
    assert inference["Resource"] == (
        "arn:aws:bedrock-mantle:us-east-2:970651210182:project/default"
    )
    assert "bedrock-mantle:CreateInference" in inference["Action"]
    assert document["Statement"][1] == {
        "Sid": "CallMantleWithBearerToken",
        "Effect": "Allow",
        "Action": "bedrock-mantle:CallWithBearerToken",
        "Resource": "*",
    }


def test_dry_run_does_not_write_policy(monkeypatch):
    module = _load_module()
    iam = FakeIam()
    monkeypatch.setattr(
        module.boto3,
        "Session",
        lambda **_kwargs: FakeSession(iam),
    )

    summary = module.configure(
        SimpleNamespace(
            profile="kk-personal",
            user_name="offsite-work-runner",
            region="us-east-2",
            project="default",
            apply=False,
        )
    )

    assert summary["applied"] is False
    assert summary["policy_name"] == "norman-bedrock-mantle-default"
    assert iam.put_calls == []
    assert iam.simulation_calls == []


def test_apply_writes_policy_and_verifies_both_actions(monkeypatch):
    module = _load_module()
    iam = FakeIam()
    monkeypatch.setattr(
        module.boto3,
        "Session",
        lambda **_kwargs: FakeSession(iam),
    )

    summary = module.configure(
        SimpleNamespace(
            profile="kk-personal",
            user_name="offsite-work-runner",
            region="us-east-2",
            project="default",
            apply=True,
        )
    )

    assert summary["applied"] is True
    assert len(iam.put_calls) == 1
    written = iam.put_calls[0]
    assert written["UserName"] == "offsite-work-runner"
    assert json.loads(written["PolicyDocument"]) == summary["policy_document"]
    assert [call["ActionNames"][0] for call in iam.simulation_calls] == [
        "bedrock-mantle:CreateInference",
        "bedrock-mantle:CallWithBearerToken",
    ]


def test_apply_fails_when_simulation_is_denied(monkeypatch):
    module = _load_module()
    iam = FakeIam({"bedrock-mantle:CreateInference": "implicitDeny"})
    monkeypatch.setattr(
        module.boto3,
        "Session",
        lambda **_kwargs: FakeSession(iam),
    )
    args = SimpleNamespace(
        profile="kk-personal",
        user_name="offsite-work-runner",
        region="us-east-2",
        project="default",
        apply=True,
    )

    try:
        module.configure(args)
    except module.ConfigurationError as exc:
        assert "CreateInference" in str(exc)
    else:
        raise AssertionError("expected denied simulation to fail")
