from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_renderer():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "render_networking_frontdoor_probe_systemd.py"
    )
    spec = importlib.util.spec_from_file_location(
        "render_networking_frontdoor_probe_systemd",
        script_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_service_runs_networking_dns_profile_to_state_directory() -> None:
    module = _load_renderer()

    rendered = module.render_service()

    assert "After=network-online.target tailscaled.service" in rendered
    assert "StateDirectory=norman" in rendered
    assert "WorkingDirectory=/home/debian/code/norman" in rendered
    assert "--profile road --dns-profile networking" in rendered
    assert "--no-trust-check --timeout 3 --json" in rendered
    assert "--output /var/lib/norman/frontdoor-road-health.json" in rendered
    assert "--exit-zero" in rendered


def test_timer_runs_every_two_minutes_by_default() -> None:
    module = _load_renderer()

    rendered = module.render_timer()

    assert "OnBootSec=45s" in rendered
    assert "OnUnitActiveSec=2min" in rendered
    assert "Unit=norman-frontdoor-probe.service" in rendered
    assert "WantedBy=timers.target" in rendered


def test_renderer_allows_paths_and_interval_overrides() -> None:
    module = _load_renderer()

    rendered = module.render_all(
        repo_root="/opt/norman",
        python="/usr/bin/python3",
        output_path="/tmp/frontdoor.json",
        timeout_seconds=5,
        interval="5min",
    )

    assert "WorkingDirectory=/opt/norman" in rendered
    assert (
        "ExecStart=/usr/bin/python3 /opt/norman/scripts/check_frontdoor_tls.py"
        in rendered
    )
    assert "--timeout 5" in rendered
    assert "--output /tmp/frontdoor.json" in rendered
    assert "OnUnitActiveSec=5min" in rendered
