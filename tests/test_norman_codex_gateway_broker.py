from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

from scripts import codex_route


BROKER_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "norman_codex_gateway_broker.py"
)


def _load_broker_module():
    module_name = f"norman_codex_gateway_broker_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, BROKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_broker_aliases_match_the_checkout_route_table():
    module = _load_broker_module()

    expected = {route.resolved_token_secret for route in codex_route.ROUTES}

    assert module.ROUTE_SECRETS == expected


def test_broker_denies_unapproved_alias(monkeypatch, capsys):
    module = _load_broker_module()
    monkeypatch.setattr(module, "_audit", lambda *_args: None)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", "/tmp/credentials")

    assert module.main(["get", "networking/firewall"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "failed" in captured.err


def test_broker_provision_copies_shared_gateway_token(monkeypatch, capsys):
    module = _load_broker_module()
    writes = []
    monkeypatch.setattr(module, "_read_secret", lambda _name: "token-value")
    monkeypatch.setattr(
        module,
        "_write_secret",
        lambda name, value: writes.append((name, value)),
    )
    monkeypatch.setattr(module, "_audit", lambda *_args: None)

    assert module.main(["provision"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "provisioned=14 aliases\n"
    assert captured.err == ""
    assert {name for name, value in writes} == (
        module.ROUTE_SECRETS - {module.DEFAULT_SOURCE_SECRET}
    )
    assert {value for _name, value in writes} == {"token-value"}


def test_broker_get_prints_only_the_requested_token(monkeypatch, capsys):
    module = _load_broker_module()
    calls = []
    monkeypatch.setattr(
        module,
        "_read_secret",
        lambda name: calls.append(name) or "brokered-token",
    )
    monkeypatch.setattr(module, "_audit", lambda *_args: None)

    assert module.main(["get", "gold-book/prompt-proxy-token"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "brokered-token\n"
    assert captured.err == ""
    assert calls == ["gold-book/prompt-proxy-token"]


def test_broker_uses_credential_scoped_cred_command(monkeypatch, tmp_path):
    module = _load_broker_module()
    credentials_dir = tmp_path / "credentials"
    credentials_dir.mkdir()
    passphrase_file = credentials_dir / "norman-cred-passphrase"
    passphrase_file.write_text("not-a-real-passphrase\n", encoding="utf-8")
    cred = tmp_path / "cred"
    cred.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    cred.chmod(0o700)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials_dir))
    monkeypatch.setattr(module, "DEFAULT_CRED_BIN", cred)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="brokered-token")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module._read_secret("infra/prompt-proxy-token") == "brokered-token"
    assert calls == [
        (
            [
                str(cred),
                "--passphrase-file",
                str(passphrase_file),
                "get",
                "infra/prompt-proxy-token",
            ],
            {
                "check": True,
                "capture_output": True,
                "text": True,
                "timeout": 10,
            },
        )
    ]
