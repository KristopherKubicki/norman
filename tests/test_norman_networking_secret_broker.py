from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
BROKER_PATH = REPO_ROOT / "scripts" / "norman_networking_secret_broker.py"
CLIENT_PATH = REPO_ROOT / "scripts" / "norman_networking_secret_broker.sh"
DEPLOY_PATH = REPO_ROOT / "scripts" / "deploy_networking_secret_broker.sh"
LAUNCHER_PATH = REPO_ROOT / "scripts" / "norman_networking_secret_broker_launch.sh"
SUDOERS_PATH = REPO_ROOT / "scripts" / "norman_networking_secret_broker.sudoers"


def _load_broker_module():
    module_name = f"norman_networking_secret_broker_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, BROKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def test_broker_allows_only_tui_network_device_aliases():
    module = _load_broker_module()

    assert module.NETWORKING_SECRETS == {
        "networking/firewall",
        "networking/netgear",
        "networking/dot10",
    }


def test_broker_denies_unapproved_alias(monkeypatch, capsys):
    module = _load_broker_module()
    monkeypatch.setattr(module, "_audit", lambda *_args: None)

    assert module.main(["get", "networking/synology"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not approved" in captured.err


def test_broker_requires_systemd_scoped_credential_directory(
    monkeypatch, tmp_path, capsys
):
    module = _load_broker_module()
    cred = tmp_path / "cred"
    cred.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    cred.chmod(0o700)
    monkeypatch.setattr(module, "DEFAULT_CRED_BIN", cred)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.setattr(module, "_audit", lambda *_args: None)

    assert module.main(["get", "networking/firewall"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "systemd credentials directory is unavailable" in captured.err


def test_broker_falls_back_to_systemd_decrypted_cred_when_keys_is_unavailable(
    monkeypatch, tmp_path
):
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
    monkeypatch.setattr(
        module,
        "_read_from_norman_keys",
        lambda _secret_name: (_ for _ in ()).throw(
            module.NormanKeysUnavailableError("offline")
        ),
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="brokered-networking-secret")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module._read_secret("networking/firewall") == "brokered-networking-secret"
    assert calls == [
        (
            [
                str(cred),
                "--passphrase-file",
                str(passphrase_file),
                "get",
                "networking/firewall",
            ],
            {
                "check": True,
                "capture_output": True,
                "text": True,
                "timeout": 10,
            },
        )
    ]


def test_broker_prefers_norman_keys_and_creates_a_scoped_request(monkeypatch):
    module = _load_broker_module()
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"value":"brokered-networking-secret"}'

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(
        module,
        "_read_cred_secret",
        lambda secret_name: (
            "keys-service-token"
            if secret_name == module.KEYS_SERVICE_TOKEN_SECRET
            else (_ for _ in ()).throw(AssertionError("fallback vault should not run"))
        ),
    )
    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("NORMAN_NETWORKING_KEYS_URL", "http://keys.example.test")
    monkeypatch.setenv("NORMAN_NETWORKING_REQUESTER_ID", "networking-tui-test")
    monkeypatch.setenv("NORMAN_NETWORKING_SESSION_ID", "session-test")
    monkeypatch.setenv("NORMAN_NETWORKING_LANE", "personal")

    assert module._read_from_norman_keys("networking/firewall") == (
        "brokered-networking-secret"
    )
    request = captured["request"]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "http://keys.example.test/v1/secrets/get"
    assert request.get_header("Authorization") == "Bearer keys-service-token"
    assert captured["timeout"] == module.DEFAULT_TIMEOUT_SECONDS
    assert payload["name"] == "networking/firewall"
    assert payload["requester_id"] == "networking-tui-test"
    assert payload["session_id"] == "session-test"
    assert payload["lane"] == "personal"
    assert payload["intent"] == "networking-tui-secret-broker"


def test_broker_does_not_bypass_norman_keys_policy_denial(monkeypatch, tmp_path):
    module = _load_broker_module()
    credentials_dir = tmp_path / "credentials"
    credentials_dir.mkdir()
    (credentials_dir / "norman-cred-passphrase").write_text(
        "not-a-real-passphrase\n", encoding="utf-8"
    )
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials_dir))
    monkeypatch.setattr(
        module,
        "_read_from_norman_keys",
        lambda _secret_name: (_ for _ in ()).throw(
            module.BrokerError("Norman Keys requires policy approval")
        ),
    )
    monkeypatch.setattr(
        module,
        "_read_cred_secret",
        lambda _secret_name: (_ for _ in ()).throw(
            AssertionError("fallback vault must not bypass policy")
        ),
    )

    try:
        module._read_secret("networking/firewall")
    except module.BrokerError as exc:
        assert "policy approval" in str(exc)
    else:
        raise AssertionError("Norman Keys policy denial should be preserved")


def test_broker_explains_when_alias_is_missing_from_keys_and_fallback(
    monkeypatch, tmp_path
):
    module = _load_broker_module()
    credentials_dir = tmp_path / "credentials"
    credentials_dir.mkdir()
    (credentials_dir / "norman-cred-passphrase").write_text(
        "not-a-real-passphrase\n", encoding="utf-8"
    )
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials_dir))
    monkeypatch.setattr(
        module,
        "_read_from_norman_keys",
        lambda _secret_name: (_ for _ in ()).throw(
            module.NormanKeysAliasMissingError("missing")
        ),
    )
    monkeypatch.setattr(
        module,
        "_read_cred_secret",
        lambda _secret_name: (_ for _ in ()).throw(
            module.BrokerError("fallback missing")
        ),
    )

    try:
        module._read_secret("networking/firewall")
    except module.BrokerError as exc:
        assert "not provisioned in Norman Keys" in str(exc)
        assert "fallback vault" in str(exc)
    else:
        raise AssertionError("missing aliases should be reported clearly")


def test_client_rejects_unapproved_alias_before_starting_ssh(tmp_path):
    fake_ssh = tmp_path / "ssh"
    ssh_called = tmp_path / "ssh-called"
    fake_ssh.write_text(
        f"#!/usr/bin/env bash\ntouch {ssh_called}\nexit 99\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o700)
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}:{environment['PATH']}"

    result = subprocess.run(
        ["bash", str(CLIENT_PATH), "get", "networking/synology"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "unapproved alias" in result.stderr
    assert not ssh_called.exists()


def test_remote_launcher_uses_encrypted_systemd_credential_with_narrow_sudo():
    launcher = LAUNCHER_PATH.read_text(encoding="utf-8")
    sudoers = SUDOERS_PATH.read_text(encoding="utf-8")

    assert "LoadCredentialEncrypted=norman-cred-passphrase:" in launcher
    assert "--property=User=kristopher" in launcher
    assert "norman-networking-secret-broker" in sudoers
    assert "NOPASSWD" in sudoers


def test_networking_broker_deployer_never_falls_back_to_interactive_ssh():
    deployer = DEPLOY_PATH.read_text(encoding="utf-8")

    assert deployer.count("scp -q -o BatchMode=yes -o ConnectTimeout=5") == 3
    assert deployer.count("ssh -o BatchMode=yes -o ConnectTimeout=5") == 2
