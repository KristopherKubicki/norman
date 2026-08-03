from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_guard():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "norman_frontdoor_tls_guard.py"
    )
    spec = importlib.util.spec_from_file_location(
        "norman_frontdoor_tls_guard", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_discover_https_hosts_uses_only_tls_listener_routes() -> None:
    module = _load_guard()

    hosts = module.discover_https_hosts(
        {
            "apps": {
                "http": {
                    "servers": {
                        "https": {
                            "listen": [":443"],
                            "routes": [
                                {
                                    "match": [
                                        {
                                            "host": [
                                                "cp.kris.openbrand.com",
                                                "llm.home.arpa",
                                                "*.home.arpa",
                                            ]
                                        }
                                    ]
                                },
                                {
                                    "handle": [
                                        {
                                            "handler": "subroute",
                                            "routes": [
                                                {
                                                    "match": [
                                                        {"host": ["norman.home.arpa."]}
                                                    ]
                                                }
                                            ],
                                        }
                                    ]
                                },
                            ],
                        },
                        "http": {
                            "listen": [":80"],
                            "routes": [
                                {
                                    "match": [
                                        {"host": ["should-not-be-included.home.arpa"]}
                                    ]
                                }
                            ],
                        },
                    }
                }
            }
        }
    )

    assert hosts == [
        "cp.kris.openbrand.com",
        "llm.home.arpa",
        "norman.home.arpa",
    ]


def test_build_health_report_promotes_failed_and_expiring_certificates() -> None:
    module = _load_guard()

    report = module.build_health_report(
        [
            {
                "host": "cp.kris.openbrand.com",
                "status": "ok",
                "days_remaining": 75.0,
                "issuer": "CN=Lollie",
                "detail": "certificate valid for 75.0 days",
            },
            {
                "host": "llm.home.arpa",
                "status": "warn",
                "days_remaining": 21.0,
                "issuer": "CN=Lollie",
                "detail": "certificate expires in 21.0 days",
            },
            {
                "host": "norman.home.arpa",
                "status": "fail",
                "days_remaining": None,
                "issuer": "",
                "detail": "SSLCertVerificationError: certificate has expired",
            },
        ],
        checked_at="2026-07-31T12:00:00+00:00",
    )

    assert report["schema"] == "norman.frontdoor-tls-health.v1"
    assert report["status"] == "fail"
    assert report["summary"] == {
        "active": 0,
        "expected": 3,
        "fail": 1,
        "warn": 1,
        "hosts": 3,
        "ok": False,
    }
    assert report["issues"] == [
        {
            "severity": "warn",
            "host": "llm.home.arpa",
            "instance": "<frontdoor>",
            "check": "tls_certificate",
            "detail": "certificate expires in 21.0 days",
        },
        {
            "severity": "fail",
            "host": "norman.home.arpa",
            "instance": "<frontdoor>",
            "check": "tls_certificate",
            "detail": "SSLCertVerificationError: certificate has expired",
        },
    ]


def test_systemd_guard_runs_on_a_persistent_timer_and_posts_alerts() -> None:
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "scripts" / "systemd" / "norman-frontdoor-tls-guard.service"
    ).read_text(encoding="utf-8")
    timer = (
        root / "scripts" / "systemd" / "norman-frontdoor-tls-guard.timer"
    ).read_text(encoding="utf-8")

    assert (
        "After=network-online.target caddy.service switchboard-bbs.service" in service
    )
    assert "norman-frontdoor-dns-reconcile.service" in service
    assert "User=root" in service
    assert "Group=root" in service
    assert "StateDirectory=norman" in service
    assert "scripts/norman_frontdoor_tls_guard.py --post-alerts" in service
    assert "--output /var/lib/norman/frontdoor-tls-health.json" in service
    assert "OnBootSec=5min" in timer
    assert "OnUnitActiveSec=30min" in timer
    assert "Persistent=true" in timer
    assert "Unit=norman-frontdoor-tls-guard.service" in timer


def test_guard_posts_tls_alerts_with_the_tls_report_path(monkeypatch, tmp_path) -> None:
    module = _load_guard()
    calls = []

    def fake_run(command, check):
        calls.append((command, check))

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    report = tmp_path / "frontdoor-tls-health.json"

    module.post_alerts(
        alert_script=tmp_path / "tui_fleet_alerts.py",
        health_json=report,
        state=tmp_path / "alerts-state.json",
        thread_id="th_frontdoor_tls_health",
    )

    command, check = calls[0]
    assert check is True
    assert command[-4:] == [
        "--title",
        "Norman front-door TLS",
        "--report-path",
        str(report),
    ]


def test_tailnet_renewal_uses_tailscale_cert_and_reloads_caddy() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "refresh_norman_tail_cert.sh").read_text(
        encoding="utf-8"
    )
    service = (
        root / "scripts" / "systemd" / "norman-tail-cert-renew.service"
    ).read_text(encoding="utf-8")
    timer = (root / "scripts" / "systemd" / "norman-tail-cert-renew.timer").read_text(
        encoding="utf-8"
    )

    assert "tailscale cert" in script
    assert '--min-validity="${MIN_VALIDITY}"' in script
    assert 'openssl x509 -checkend "${RENEW_WINDOW_SECS}"' in script
    assert "systemctl reload caddy" in script
    assert "flock -n 9" in script
    assert "openssl s_client" in script
    assert "ExecStart=/usr/local/sbin/refresh-norman-tail-cert" in service
    assert "tailscaled.service" in service
    assert "Requires=caddy.service" in service
    assert "OnCalendar=*-*-* 03:15:00" in timer
    assert "Persistent=true" in timer
