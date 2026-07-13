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
