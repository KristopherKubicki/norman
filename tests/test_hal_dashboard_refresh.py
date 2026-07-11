from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_hal_dashboard_refresh():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "hal_dashboard_refresh.py"
    )
    spec = importlib.util.spec_from_file_location("hal_dashboard_refresh", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refresh_reason_matches_dashboard_windows() -> None:
    module = _load_hal_dashboard_refresh()

    assert (
        module.refresh_reason_for_title(
            "Dashboards | PanelBot-prod | CloudWatch | us-east-2 - Google Chrome"
        )
        == "cloudwatch"
    )
    assert (
        module.refresh_reason_for_title("Glimpser – Dashboard - Google Chrome")
        == "dashboard"
    )
    assert (
        module.refresh_reason_for_title(
            "RECOVERING CAMERA | Autocamera - Google Chrome"
        )
        == "autocamera"
    )


def test_refresh_reason_skips_non_dashboard_windows() -> None:
    module = _load_hal_dashboard_refresh()

    assert (
        module.refresh_reason_for_title("○ Norman Console · Ready - Google Chrome")
        is None
    )
    assert (
        module.refresh_reason_for_title("(1) Frame of Mind - YouTube - Google Chrome")
        is None
    )
    assert (
        module.refresh_reason_for_title("Greg Munves (EST) (DM) - OpenBrand - Slack")
        is None
    )
