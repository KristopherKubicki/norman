from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_browser_auth_local_once():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "browser_auth_local_once.py"
    )
    spec = importlib.util.spec_from_file_location(
        "browser_auth_local_once", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_merge_forward_url_query_preserves_existing_profile_and_route() -> None:
    module = _load_browser_auth_local_once()

    merged = module.merge_forward_url_query(
        "https://eyebat.home.arpa/auth/browser/callback?profile=evergreen&route=host",
        {
            "code": "abc123",
            "state": "state456",
            "scope": "openid profile",
        },
    )

    assert (
        merged == "https://eyebat.home.arpa/auth/browser/callback"
        "?profile=evergreen&route=host&code=abc123&state=state456&scope=openid+profile"
    )


def test_merge_forward_url_query_adds_query_when_none_exists() -> None:
    module = _load_browser_auth_local_once()

    merged = module.merge_forward_url_query(
        "https://eyebat.home.arpa/auth/browser/callback",
        {"code": "abc123", "state": "state456"},
    )

    assert (
        merged
        == "https://eyebat.home.arpa/auth/browser/callback?code=abc123&state=state456"
    )


def test_build_arm_href_preserves_forwarding_context() -> None:
    module = _load_browser_auth_local_once()

    href = module.build_arm_href(
        state="state456",
        forward_url="https://housebot.home.arpa/auth/browser/callback?profile=evergreen",
        label="Housebot",
        console_url="https://housebot.home.arpa/?profile=evergreen",
        next_url="https://auth.openai.com/oauth/authorize?state=state456",
    )

    assert href.startswith("/arm?")
    assert "state=state456" in href
    assert (
        "forward_url=https%3A%2F%2Fhousebot.home.arpa%2Fauth%2Fbrowser%2Fcallback%3Fprofile%3Devergreen"
        in href
    )
    assert "label=Housebot" in href
    assert (
        "console_url=https%3A%2F%2Fhousebot.home.arpa%2F%3Fprofile%3Devergreen" in href
    )
    assert (
        "next_url=https%3A%2F%2Fauth.openai.com%2Foauth%2Fauthorize%3Fstate%3Dstate456"
        in href
    )


def test_build_return_to_console_extra_includes_auto_return_script() -> None:
    module = _load_browser_auth_local_once()

    extra = module.build_return_to_console_extra(
        console_url="https://housebot.home.arpa/?profile=dusk",
        label="Housebot",
    )

    assert "This window will close automatically or return you to" in extra
    assert 'href="https://housebot.home.arpa/?profile=dusk"' in extra
    assert "window.close();" in extra
    assert "window.location.replace(target);" in extra
