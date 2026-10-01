"""Credential CLI stdout is a transport channel, never an interactive display."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

CASES = [
    (
        "norman_codex_gateway_broker",
        ["get", "norman/prompt-proxy-token"],
        "_read_secret",
    ),
    ("norman_networking_secret_broker", ["get", "networking/firewall"], "_read_secret"),
    ("norman_ops_mcp_canary_broker", ["get"], "_read_secret"),
    (
        "norman_codex_gateway_token",
        ["--secret", "norman/prompt-proxy-token"],
        "resolve_token",
    ),
]


@pytest.mark.parametrize("name,args,resolver", CASES)
@pytest.mark.parametrize("interactive", [False, True])
def test_credential_output_requires_noninteractive_consumer(
    name, args, resolver, interactive, monkeypatch, capsys
):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []

    def resolve(*args):
        calls.append(args)
        return (
            ("synthetic-only", []) if resolver == "resolve_token" else "synthetic-only"
        )

    monkeypatch.setattr(module, resolver, resolve)
    monkeypatch.setattr(module, "_audit", lambda *args: None, raising=False)
    monkeypatch.setattr(module.sys.stdout, "isatty", lambda: interactive)
    status = module.main(args)
    captured = capsys.readouterr()
    if interactive:
        assert status == 1
        assert calls == []
        assert captured.out == ""
        assert "non-interactive consumer" in captured.err
    else:
        assert status == 0
        assert len(calls) == 1
        assert captured.out == "synthetic-only\n"
        assert captured.err == ""
