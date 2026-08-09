from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEMD_DIR = ROOT / "scripts" / "systemd"


def test_production_refreshes_the_shared_route_policy_before_starting() -> None:
    source = (SYSTEMD_DIR / "norman-production@.service").read_text(encoding="utf-8")

    assert (
        "ExecStartPre=/usr/local/libexec/norman-release-python %i --release-script "
        "scripts/norllama/refresh_route_policy.py --path "
        "/var/lib/norman/norllama/route_policy.json" in source
    )
    assert "Environment=NORMAN_RELEASE_SHA=%i" in source
    assert "norman-release-python %i -m uvicorn" in source
    assert ".venv-3.10" not in source


def test_tmpfiles_normalizes_legacy_policy_artifact_ownership() -> None:
    source = (ROOT / "scripts" / "tmpfiles.d" / "norman-production.conf").read_text(
        encoding="utf-8"
    )

    assert "d /var/lib/norman/norllama 0750 kristopher kristopher -" in source
    assert "Z /var/lib/norman/norllama 0750 kristopher kristopher -" in source
    assert (
        "z /var/lib/norman/norllama/route_policy.json 0640 kristopher kristopher -"
        in source
    )


def test_canary_uses_an_isolated_runtime_policy_artifact() -> None:
    source = (SYSTEMD_DIR / "norman-release@.service").read_text(encoding="utf-8")

    assert "RuntimeDirectory=norman-release-%i" in source
    assert (
        "Environment=NORMAN_NORLLAMA_ROUTE_POLICY_PATH="
        "/run/norman-release-%i/route_policy.json"
    ) in source
    assert (
        "ExecStartPre=/usr/local/libexec/norman-release-python %i --release-script "
        "scripts/norllama/refresh_route_policy.py --path "
        "/run/norman-release-%i/route_policy.json"
    ) in source
    assert "Environment=NORMAN_RELEASE_SHA=%i" in source
    assert "norman-release-python %i -m uvicorn" in source
    assert ".venv-3.10" not in source


def test_periodic_refresh_uses_the_active_sha_pinned_release() -> None:
    refresh_service = (SYSTEMD_DIR / "norman-route-policy-refresh.service").read_text(
        encoding="utf-8"
    )
    timer = (SYSTEMD_DIR / "norman-route-policy-refresh.timer").read_text(
        encoding="utf-8"
    )
    launcher = SYSTEMD_DIR / "norman-refresh-active-route-policy"

    assert "User=kristopher" in refresh_service
    assert (
        "ExecStart=/usr/local/libexec/norman-refresh-active-route-policy"
        in refresh_service
    )
    assert "OnUnitActiveSec=6h" in timer
    assert "Persistent=true" in timer

    syntax = subprocess.run(
        ["bash", "-n", str(launcher)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert syntax.returncode == 0, syntax.stderr

    source = launcher.read_text(encoding="utf-8")
    assert "norman-production@*.service" in source
    assert "norman-${release_sha}" in source
    assert "norman-release-python" in source
    assert "refresh_route_policy.py" in source
    assert ".venv-3.10" not in source
