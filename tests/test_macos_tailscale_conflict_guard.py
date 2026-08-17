from __future__ import annotations

import plistlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "norllama" / "macos_tailscale_conflict_guard.sh"
PLIST = ROOT / "scripts" / "norllama" / "org.lollie.tailscale-conflict-guard.plist"


def test_guard_stops_tailscale_before_quitting_the_app() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert text.startswith("#!/bin/zsh\n")
    assert '"${tailscale_bin}" down' in text
    assert "/usr/bin/pkill -x Tailscale" in text
    assert '"${expressvpn_bin}" connect' in text
    assert '"${expressvpn_status}" == "Disconnected"' in text
    assert text.index('"${tailscale_bin}" down') < text.index(
        "/usr/bin/pkill -x Tailscale"
    )
    assert text.index("/usr/bin/pkill -x Tailscale") < text.index(
        '"${expressvpn_bin}" connect'
    )


def test_launch_agent_enforces_the_guard_frequently() -> None:
    with PLIST.open("rb") as handle:
        payload = plistlib.load(handle)

    assert payload["Label"] == "org.lollie.tailscale-conflict-guard"
    assert payload["ProgramArguments"] == [
        "/Users/k/norllama/macos_tailscale_conflict_guard.sh"
    ]
    assert payload["RunAtLoad"] is True
    assert payload["StartInterval"] == 30
