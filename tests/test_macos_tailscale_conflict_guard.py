from __future__ import annotations

import plistlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "norllama" / "macos_tailscale_conflict_guard.sh"
PLIST = ROOT / "scripts" / "norllama" / "org.lollie.tailscale-conflict-guard.plist"


def test_guard_requires_expressvpn_split_tunnel_bypasses() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert text.startswith("#!/bin/zsh\n")
    assert '"100.64.0.0/10"' in text
    assert '"fd7a:115c:a1e0::/48"' in text
    assert '"192.168.2.0/24"' in text
    assert '"${expressvpn_bin}" --unstable dump daemon-settings' in text
    assert 'settings.get("splitTunnelEnabled") is True' in text
    assert 'settings.get("splitTunnelDNS") is False' in text
    assert "required <= bypasses" in text
    assert 'rule.get("path") == "/Applications/Tailscale.app"' in text
    assert '"${tailscale_bin}" down' in text


def test_guard_runs_both_vpns_when_the_split_tunnel_contract_is_valid() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert '"${expressvpn_bin}" get connectionstate' in text
    assert '"${expressvpn_bin}" connect' in text
    assert "/usr/bin/open -gja /Applications/Tailscale.app" in text
    assert '"${tailscale_bin}" set --accept-dns=false' in text
    assert '"${tailscale_bin}" status --json' in text
    assert '"${tailscale_bin}" up' in text
    assert '"${tailscale_online}" != "true"' in text
    assert "/usr/bin/pkill" not in text


def test_launch_agent_enforces_the_guard_frequently() -> None:
    with PLIST.open("rb") as handle:
        payload = plistlib.load(handle)

    assert payload["Label"] == "org.lollie.tailscale-conflict-guard"
    assert payload["ProgramArguments"] == [
        "/Users/k/norllama/macos_tailscale_conflict_guard.sh"
    ]
    assert payload["RunAtLoad"] is True
    assert payload["StartInterval"] == 30
