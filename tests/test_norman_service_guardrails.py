from pathlib import Path


def test_norman_service_guardrails_bound_runtime_connection_load() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "systemd"
        / "norman.service.d"
        / "20-runtime-guardrails.conf"
    ).read_text(encoding="utf-8")

    assert "LimitNOFILE=65536" in source
    assert "--limit-concurrency 192" in source
    assert "--backlog 256" in source
    assert "--timeout-keep-alive 5" in source


def test_isolated_release_unit_requires_managed_configuration() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "systemd"
        / "norman-release@.service"
    ).read_text(encoding="utf-8")

    assert "WorkingDirectory=/home/kristopher/releases/norman-%i" in source
    assert "EnvironmentFile=-/etc/norman/release.env" in source
    assert "NORMAN_CONFIG_REQUESTER_ID=norman-release" in source
    assert 'test -n "$NORMAN_CONFIG_SECRET"' in source
    assert "NORMAN_CONFIG_SECRET_CMD" in source
    assert "--host 127.0.0.1 --port 18000" in source
    assert "NoNewPrivileges=true" in source
