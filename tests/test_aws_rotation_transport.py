"""Transport and profile receiver safety, with dummy credentials only."""

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import aws_rotation_transport as transport
from app.services.aws_rotation_store import RotationError

spec = importlib.util.spec_from_file_location(
    "receiver",
    Path(__file__).resolve().parents[1] / "scripts/norman_aws_rotation_receiver.py",
)
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)


def test_dummy_receiver_preserves_unrelated_profiles():
    receiver.dummy_check()


def test_transport_pins_hosts_and_never_uses_secret_in_arguments(monkeypatch):
    execute = Mock(
        return_value=SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "version": transport.VERSION,
                    "host": "hal",
                    "action": "install",
                }
            ),
        )
    )
    monkeypatch.setattr(transport.subprocess, "run", execute)
    transport.SSHHostTransport().install("hal:kristopher", "dummy-key", "dummy-secret")
    args, kwargs = execute.call_args
    assert "dummy-secret" not in repr(args)
    assert "dummy-secret" in kwargs["input"].decode()
    assert "StrictHostKeyChecking=yes" in args[0]
    assert "UserKnownHostsFile=/etc/norman-aws-rotation-known-hosts" in args[0]
    assert kwargs.get("shell", False) is False


@pytest.mark.parametrize(
    "stdout",
    [
        b'{"ok":true}',
        b"secret-dummy",
        json.dumps(
            {
                "ok": True,
                "version": transport.VERSION,
                "host": "netops",
                "action": "install",
            }
        ),
    ],
)
def test_untrusted_output_never_leaves_transport(monkeypatch, stdout):
    monkeypatch.setattr(
        transport.subprocess,
        "run",
        Mock(return_value=SimpleNamespace(returncode=0, stdout=stdout)),
    )
    with pytest.raises(RotationError) as error:
        transport.SSHHostTransport().install(
            "hal:kristopher", "dummy-key", "dummy-secret"
        )
    assert "dummy-secret" not in str(error.value)
    assert "secret-dummy" not in str(error.value)


def test_unknown_host_never_executes(monkeypatch):
    execute = Mock()
    monkeypatch.setattr(transport.subprocess, "run", execute)
    with pytest.raises(RotationError):
        transport.SSHHostTransport().call("attacker", {"action": "ready"})
    execute.assert_not_called()


def profile_file(tmp_path):
    path = tmp_path / "credentials"
    path.write_text(
        "".join(
            f"[{p}]\naws_access_key_id={receiver.OLD_KEY}\naws_secret_access_key=dummy-old\n"
            for p in receiver.PROFILES
        )
    )
    path.chmod(0o600)
    return path


def test_receiver_rejects_unknown_existing_key(tmp_path):
    path = profile_file(tmp_path)
    original = path.read_text().replace(receiver.OLD_KEY, "other-key")
    path.write_text(original)
    with pytest.raises(ValueError):
        receiver.replace_profiles(
            path, os.getuid(), os.getgid(), "dummy-new", "dummy-secret"
        )
    assert path.read_text() == original


def test_failed_atomic_replace_preserves_original_and_cleans_staging(
    tmp_path, monkeypatch
):
    path = profile_file(tmp_path)
    original = path.read_text()
    monkeypatch.setattr(
        receiver.os, "replace", Mock(side_effect=OSError("dummy failure"))
    )
    with pytest.raises(OSError):
        receiver.replace_profiles(
            path, os.getuid(), os.getgid(), "dummy-new", "dummy-secret"
        )
    assert path.read_text() == original
    assert list(tmp_path.iterdir()) == [path]


def test_receiver_rejects_symlink_and_permissive_file(tmp_path):
    path = profile_file(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        receiver.parse_credentials(link, os.getuid())
    path.chmod(0o644)
    with pytest.raises(ValueError):
        receiver.parse_credentials(path, os.getuid())


def test_receiver_rejects_unexpected_fields_before_credentials(monkeypatch):
    lookup = Mock()
    monkeypatch.setattr(receiver.pwd, "getpwnam", lookup)
    with pytest.raises(ValueError):
        receiver.handle({"action": "ready", "path": "/arbitrary"}, "hal", "kristopher")
    lookup.assert_not_called()


def test_receiver_waits_for_application_after_service_restart(monkeypatch):
    execute = Mock()
    health = Mock(side_effect=[ConnectionRefusedError(), None])
    monkeypatch.setattr(receiver.subprocess, "run", execute)
    monkeypatch.setattr(receiver, "http_health", health)
    monkeypatch.setattr(receiver.time, "sleep", Mock())
    receiver.service_check("hal", restart=True)
    assert health.call_count == 2
    assert execute.call_args_list[0].args[0][1] == "restart"


def test_local_receiver_does_not_require_privilege_escalation(monkeypatch):
    execute = Mock(
        return_value=SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "version": transport.VERSION,
                    "host": "norman",
                    "action": "dummy",
                }
            ),
        )
    )
    monkeypatch.setattr(transport.subprocess, "run", execute)
    assert transport.SSHHostTransport().call("norman:kristopher", {"action": "dummy"})
    assert execute.call_args.args[0] == [transport.RECEIVER]
