from pathlib import Path


def test_production_service_has_persistent_database_state_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    unit = (root / "scripts" / "systemd" / "norman-production@.service").read_text(
        encoding="utf-8"
    )
    tmpfiles = (root / "scripts" / "tmpfiles.d" / "norman-production.conf").read_text(
        encoding="utf-8"
    )

    assert "After=systemd-tmpfiles-setup.service" in unit
    assert "Wants=systemd-tmpfiles-setup.service" in unit
    assert "ExecStartPre=/usr/bin/test -w /var/lib/norman/state" in unit
    assert "d /var/lib/norman/state 0750 kristopher kristopher -" in tmpfiles
    assert "z /var/lib/norman/state/norman.db* 0640 kristopher kristopher -" in tmpfiles
