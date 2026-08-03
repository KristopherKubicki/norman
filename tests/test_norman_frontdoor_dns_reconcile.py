from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError


def _load_reconciler():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "norman_frontdoor_dns_reconcile.py"
    )
    spec = importlib.util.spec_from_file_location(
        "norman_frontdoor_dns_reconcile", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_reconciled_hosts_keeps_active_fqdns_and_excludes_tailnet() -> None:
    module = _load_reconciler()

    assert module.reconciled_hosts(
        [
            "cp.kris.openbrand.com",
            "CP.KRIS.OPENBRAND.COM.",
            "norman.tail94915.ts.net",
            "localhost",
            "*.home.arpa",
            "not a host.home.arpa",
        ]
    ) == ["cp.kris.openbrand.com"]


def test_dns_drift_selects_only_missing_or_wrong_answers() -> None:
    module = _load_reconciler()
    answers = {
        "correct.home.arpa": ("192.168.2.241",),
        "missing.home.arpa": (),
        "wrong.home.arpa": ("192.168.2.242",),
        "mixed.home.arpa": ("192.168.2.241", "192.168.2.242"),
    }

    def query(host, *, resolver, timeout):
        assert resolver == "192.168.2.1"
        assert timeout == 5
        return answers[host]

    assert module.dns_drift(
        sorted(answers),
        resolver="192.168.2.1",
        frontdoor_address="192.168.2.241",
        timeout=5,
        query=query,
    ) == {
        "missing.home.arpa": "192.168.2.241",
        "mixed.home.arpa": "192.168.2.241",
        "wrong.home.arpa": "192.168.2.241",
    }


def test_pfsense_payload_only_replaces_selected_a_records() -> None:
    module = _load_reconciler()

    code = module._php_apply_code({"cp.kris.openbrand.com": "192.168.2.241"})

    assert "before-norman-frontdoor-dns-reconcile" in code
    assert 'require_once("config.inc")' in code
    assert "services_unbound_configure()" in code
    assert "IN\\s+A\\s+" in code
    assert "networking/firewall" not in code


def test_broker_failure_is_redacted_from_receipt(monkeypatch, tmp_path) -> None:
    module = _load_reconciler()
    output = tmp_path / "dns.json"
    monkeypatch.setattr(
        module, "load_active_hosts", lambda *_args, **_kwargs: ["cp.kris.openbrand.com"]
    )
    monkeypatch.setattr(
        module,
        "dns_drift",
        lambda *_args, **_kwargs: {"cp.kris.openbrand.com": "192.168.2.241"},
    )

    def fail_broker(*, timeout):
        raise module.NormanKeysLookupError("firewall-password-must-not-appear")

    monkeypatch.setattr(module, "fetch_firewall_password", fail_broker)

    assert module.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "fail"
    assert report["error"] == "NormanKeysLookupError"
    assert "firewall-password-must-not-appear" not in output.read_text(encoding="utf-8")


def test_dns_verification_failure_returns_nonzero(monkeypatch, tmp_path) -> None:
    module = _load_reconciler()
    output = tmp_path / "dns.json"
    monkeypatch.setattr(
        module, "load_active_hosts", lambda *_args, **_kwargs: ["cp.kris.openbrand.com"]
    )
    monkeypatch.setattr(
        module,
        "dns_drift",
        lambda *_args, **_kwargs: {"cp.kris.openbrand.com": "192.168.2.241"},
    )
    monkeypatch.setattr(module, "fetch_firewall_password", lambda **_kwargs: "secret")
    monkeypatch.setattr(module, "apply_pfsense_records", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module, "verify_records", lambda *_args, **_kwargs: ["cp.kris.openbrand.com"]
    )

    assert module.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "fail"
    assert report["error"] == "DNSVerificationError"


def test_pfsense_authentication_failure_is_classified_without_output(
    monkeypatch,
) -> None:
    module = _load_reconciler()

    class Result:
        returncode = 255
        stdout = "Permission denied, please try again."

    monkeypatch.setattr(module, "_ssh_askpass", lambda *_args: _AskpassContext())
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: Result())

    try:
        module.apply_pfsense_records(
            {"cp.kris.openbrand.com": "192.168.2.241"},
            firewall_host="192.168.2.1",
            firewall_user="admin",
            firewall_password="not-disclosed",
            timeout=5,
        )
    except module.FirewallAuthenticationError as exc:
        assert str(exc) == "pfSense rejected the brokered automation credential"
    else:
        raise AssertionError("pfSense authentication failure should be classified")


class _AskpassContext:
    def __enter__(self):
        return Path("/tmp/askpass"), {}

    def __exit__(self, *_args):
        return False


def test_fetch_firewall_password_uses_norman_keys(monkeypatch) -> None:
    module = _load_reconciler()
    monkeypatch.setenv("NORMAN_KEYS_URL", "http://keys.norman.test")
    monkeypatch.setenv("NORMAN_KEYS_TOKEN", "service-token")
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"value": "firewall-password"}'

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    assert module.fetch_firewall_password(timeout=7) == "firewall-password"
    request, timeout = requests[0]
    assert request.full_url == "http://keys.norman.test/v1/secrets/get"
    assert request.get_header("Authorization") == "Bearer service-token"
    assert timeout == 7


def test_fetch_firewall_password_uses_approved_broker_command(monkeypatch) -> None:
    module = _load_reconciler()
    monkeypatch.delenv("NORMAN_KEYS_URL", raising=False)
    monkeypatch.delenv("NORMAN_KEYS_API_BASE", raising=False)
    monkeypatch.setenv(
        "NORMAN_CONFIG_SECRET_CMD", "/usr/local/bin/norman-keys --lease {name}"
    )
    calls = []

    class Result:
        stdout = "firewall-password\n"

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.fetch_firewall_password(timeout=7) == "firewall-password"
    assert calls == [
        (
            [
                "/usr/local/bin/norman-keys",
                "--lease",
                "networking/firewall",
            ],
            {
                "check": True,
                "stdin": module.subprocess.DEVNULL,
                "stdout": module.subprocess.PIPE,
                "stderr": module.subprocess.PIPE,
                "text": True,
                "timeout": 7,
            },
        )
    ]


def test_fetch_firewall_password_rejects_broker_errors(monkeypatch) -> None:
    module = _load_reconciler()
    monkeypatch.setenv("NORMAN_KEYS_URL", "http://keys.norman.test")
    monkeypatch.setenv("NORMAN_KEYS_TOKEN", "service-token")

    def fail_urlopen(*_args, **_kwargs):
        raise URLError("unavailable")

    monkeypatch.setattr(module.urllib.request, "urlopen", fail_urlopen)

    try:
        module.fetch_firewall_password(timeout=7)
    except module.NormanKeysLookupError as exc:
        assert str(exc) == "Norman Keys lookup for the firewall credential failed"
    else:
        raise AssertionError("broker failure should not be ignored")


def test_fetch_firewall_password_classifies_a_missing_alias(monkeypatch) -> None:
    module = _load_reconciler()
    monkeypatch.delenv("NORMAN_KEYS_URL", raising=False)
    monkeypatch.delenv("NORMAN_KEYS_API_BASE", raising=False)
    monkeypatch.setenv("NORMAN_SECRET_CMD", "/usr/local/bin/norman-keys {name}")

    def fail_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(
            1,
            ["norman-keys"],
            stderr="credential networking/firewall not found",
        )

    monkeypatch.setattr(module.subprocess, "run", fail_run)

    try:
        module.fetch_firewall_password(timeout=7)
    except module.NormanKeysSecretMissingError as exc:
        assert str(exc) == "Norman Keys has no approved firewall credential"
    else:
        raise AssertionError("missing secret aliases should be classified")


def test_fetch_firewall_password_requires_an_approved_broker_path(monkeypatch) -> None:
    module = _load_reconciler()
    monkeypatch.delenv("NORMAN_KEYS_URL", raising=False)
    monkeypatch.delenv("NORMAN_KEYS_API_BASE", raising=False)
    monkeypatch.delenv("NORMAN_SECRET_CMD", raising=False)
    monkeypatch.delenv("NORMAN_CONFIG_SECRET_CMD", raising=False)

    try:
        module.fetch_firewall_password(timeout=7)
    except module.NormanKeysConfigurationError as exc:
        assert str(exc) == "Norman Keys broker credentials are not configured"
    else:
        raise AssertionError("missing secret broker configuration should be classified")


def test_systemd_reconciler_uses_encrypted_credential_and_tls_guard_waits() -> None:
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "scripts" / "systemd" / "norman-frontdoor-dns-reconcile.service"
    ).read_text(encoding="utf-8")
    timer = (
        root / "scripts" / "systemd" / "norman-frontdoor-dns-reconcile.timer"
    ).read_text(encoding="utf-8")
    guard = (
        root / "scripts" / "systemd" / "norman-frontdoor-tls-guard.service"
    ).read_text(encoding="utf-8")
    wrapper = (root / "scripts" / "run_norman_frontdoor_dns_reconcile.sh").read_text(
        encoding="utf-8"
    )

    assert "EnvironmentFile=-/etc/norman/runtime-identities.env" in service
    assert (
        "LoadCredentialEncrypted=norman-cred-passphrase:"
        "/etc/norman/credentials/norman-cred-passphrase.cred" in service
    )
    assert "User=kristopher" in service
    assert "StateDirectory=norman-frontdoor-dns" in service
    assert "--output /var/lib/norman-frontdoor-dns/frontdoor-dns-health.json" in service
    assert "OnUnitActiveSec=10min" in timer
    assert "Persistent=true" in timer
    assert "Unit=norman-frontdoor-dns-reconcile.service" in timer
    assert "norman-frontdoor-dns-reconcile.service" in guard
    assert "norman/keys-service-token" in wrapper
    assert "NORMAN_KEYS_TOKEN" in wrapper
    assert "NORMAN_CONFIG_SECRET_CMD" in wrapper
