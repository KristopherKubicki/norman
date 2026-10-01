from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace


BROKER_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "norman_bedrock_mantle_broker.py"
)


def _load_broker_module():
    module_name = f"norman_bedrock_mantle_broker_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, BROKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _scoped_cred(monkeypatch, tmp_path, module):
    credentials_dir = tmp_path / "credentials"
    credentials_dir.mkdir()
    passphrase_file = credentials_dir / "norman-cred-passphrase"
    passphrase_file.write_text("not-a-real-passphrase\n", encoding="utf-8")
    cred = tmp_path / "cred"
    cred.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    cred.chmod(0o700)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials_dir))
    monkeypatch.setattr(module, "DEFAULT_CRED_BIN", cred)
    return cred, passphrase_file


def test_broker_denies_every_alias_except_mantle(monkeypatch, capsys):
    module = _load_broker_module()
    monkeypatch.setattr(module, "_audit", lambda *_args: None)

    assert module.main(["get", "networking/firewall"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not approved" in captured.err


def test_broker_requires_systemd_credentials_directory(monkeypatch, tmp_path, capsys):
    module = _load_broker_module()
    cred = tmp_path / "cred"
    cred.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    cred.chmod(0o700)
    monkeypatch.setattr(module, "DEFAULT_CRED_BIN", cred)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.setattr(module, "_audit", lambda *_args: None)

    assert module.main(["get", module.MANTLE_SECRET_ALIAS]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "systemd credentials directory is unavailable" in captured.err


def test_broker_parses_expected_aws_credential_bundle_keys():
    module = _load_broker_module()

    credentials = module._parse_aws_credentials(
        json.dumps(
            {
                "credentials": {
                    "AccessKeyId": "AKIA_TEST_ACCESS_KEY",
                    "SecretAccessKey": "test-secret-access-key",
                    "SessionToken": "test-session-token",
                }
            }
        )
    )

    assert credentials.access_key == "AKIA_TEST_ACCESS_KEY"
    assert credentials.secret_key == "test-secret-access-key"
    assert credentials.token == "test-session-token"


def test_broker_uses_systemd_decrypted_passphrase_for_cred(
    monkeypatch,
    tmp_path,
):
    module = _load_broker_module()
    cred, passphrase_file = _scoped_cred(monkeypatch, tmp_path, module)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "AccessKeyId": "AKIA_TEST_ACCESS_KEY",
                    "SecretAccessKey": "test-secret-access-key",
                }
            )
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    credentials = module._read_aws_credentials()

    assert credentials.access_key == "AKIA_TEST_ACCESS_KEY"
    assert calls == [
        (
            [
                str(cred),
                "--passphrase-file",
                str(passphrase_file),
                "get",
                module.AWS_CREDENTIALS_ALIAS,
            ],
            {
                "check": True,
                "capture_output": True,
                "text": True,
                "timeout": 10,
            },
        )
    ]


def test_broker_mints_token_with_constructed_botocore_credentials(
    monkeypatch,
    tmp_path,
):
    module = _load_broker_module()
    _scoped_cred(monkeypatch, tmp_path, module)
    monkeypatch.setenv("NORMAN_BEDROCK_MANTLE_REGION", "us-east-2")

    def fake_run(_command, **_kwargs):
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "aws_access_key_id": "AKIA_TEST_ACCESS_KEY",
                    "aws_secret_access_key": "test-secret-access-key",
                    "aws_session_token": "test-session-token",
                }
            )
        )

    received = {}

    class FakeGenerator:
        def get_token(self, credentials, region):
            received["credentials"] = credentials
            received["region"] = region
            return "fresh-mantle-bearer"

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "BedrockTokenGenerator", FakeGenerator)

    assert module.get_mantle_token(module.MANTLE_SECRET_ALIAS) == "fresh-mantle-bearer"
    assert received["credentials"].access_key == "AKIA_TEST_ACCESS_KEY"
    assert received["credentials"].secret_key == "test-secret-access-key"
    assert received["credentials"].token == "test-session-token"
    assert received["region"] == "us-east-2"


def test_broker_prints_only_fresh_token(monkeypatch, capsys):
    module = _load_broker_module()
    monkeypatch.setattr(
        module,
        "get_mantle_token",
        lambda secret_name: (
            "fresh-mantle-bearer" if secret_name == module.MANTLE_SECRET_ALIAS else ""
        ),
    )
    monkeypatch.setattr(module, "_audit", lambda *_args: None)

    assert module.main(["get", module.MANTLE_SECRET_ALIAS]) == 0

    captured = capsys.readouterr()
    assert captured.out == "fresh-mantle-bearer\n"
    assert captured.err == ""


def test_broker_error_does_not_disclose_credentials_or_token(
    monkeypatch,
    capsys,
):
    module = _load_broker_module()
    access_key = "AKIA_TEST_ACCESS_KEY"
    secret_key = "test-secret-access-key"
    bearer = "fresh-mantle-bearer"
    monkeypatch.setattr(
        module,
        "_read_aws_credentials",
        lambda: module.Credentials(access_key, secret_key, "test-session-token"),
    )
    monkeypatch.setattr(module, "_region", lambda: "us-east-2")
    monkeypatch.setattr(module, "_audit", lambda *_args: None)

    class ExplodingGenerator:
        def get_token(self, _credentials, _region):
            raise RuntimeError(f"{access_key} {secret_key} {bearer}")

    monkeypatch.setattr(module, "BedrockTokenGenerator", ExplodingGenerator)

    assert module.main(["get", module.MANTLE_SECRET_ALIAS]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Bedrock Mantle bearer token generation failed" in captured.err
    assert access_key not in captured.err
    assert secret_key not in captured.err
    assert bearer not in captured.err
