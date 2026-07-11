from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_frontdoor_tls_probe():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "check_frontdoor_tls.py"
    )
    spec = importlib.util.spec_from_file_location("check_frontdoor_tls", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_road_profile_covers_norman_switchboard_and_core_road_hosts() -> None:
    module = _load_frontdoor_tls_probe()

    specs = module.build_profile_specs("road")
    by_host = {spec.host: spec for spec in specs}

    assert "norman.home.arpa" in by_host
    assert "switchboard.home.arpa" in by_host
    assert (
        by_host["keystone.home.arpa"].redirect_to_host == "keystone.kris.openbrand.com"
    )
    assert by_host["kpis.home.arpa"].redirect_to_host == "kpis.kris.openbrand.com"
    assert by_host["keystone.kris.openbrand.com"].redirect_to_host == ""
    assert by_host["kpis.kris.openbrand.com"].redirect_to_host == ""
    assert by_host["keystone.home.arpa"].surface == "bot-tui"
    assert by_host["keystone.home.arpa"].expected_lan_addresses == ("192.168.2.241",)
    assert by_host["keystone.home.arpa"].expected_road_addresses == ("100.103.34.17",)
    assert by_host["housebot.home.arpa"].surface == "bot-tui"
    assert "networking.home.arpa" in by_host
    assert "uplink.home.arpa" in by_host
    assert "eyebat.home.arpa" in by_host
    assert "glimpser.home.arpa" in by_host
    assert by_host["glimpser.home.arpa"].surface == "app"
    assert by_host["glimpser.home.arpa"].expected_lan_addresses == ()
    assert "glimpser.knox.lollie.org" in by_host


def test_networking_dns_profile_checks_lan_and_dohio_paths() -> None:
    module = _load_frontdoor_tls_probe()

    paths = module.build_dns_probe_paths("networking")

    assert [(path.name, path.resolver, path.transport) for path in paths] == [
        ("lan", "192.168.2.1", "udp"),
        ("dohio-udp", "100.99.220.14", "udp"),
        ("dohio-tcp", "100.99.220.14", "tcp"),
    ]


def test_select_specs_reuses_profile_expectations_for_known_host() -> None:
    module = _load_frontdoor_tls_probe()

    specs = module.select_specs("road", ["housebot.home.arpa", "other.home.arpa"])

    assert specs[0].host == "housebot.home.arpa"
    assert specs[0].expected_lan_addresses == ("192.168.2.241",)
    assert specs[0].expected_road_addresses == ("100.103.34.17",)
    assert specs[1].host == "other.home.arpa"
    assert specs[1].expected_lan_addresses == ()


def test_probe_host_accepts_matching_redirect(monkeypatch) -> None:
    module = _load_frontdoor_tls_probe()
    spec = module.HostExpectation(
        host="keystone.home.arpa",
        label="Keystone",
        redirect_to_host="keystone.kris.openbrand.com",
    )

    monkeypatch.setattr(
        module,
        "resolve_host_addresses",
        lambda host, port=443: ("192.168.2.241",),
    )
    monkeypatch.setattr(
        module,
        "fetch_tls_snapshot",
        lambda host,
        port=443,
        timeout=module.DEFAULT_TIMEOUT_SECONDS: module.TlsSnapshot(
            issuer="organizationName=Caddy Local Authority",
            not_before="Apr 24 04:15:13 2026 GMT",
            not_after="Apr 30 04:15:13 2026 GMT",
            san_dns=("keystone.home.arpa",),
            san_ip_addresses=(),
            hostname_matches=True,
            days_remaining=5.7,
            tls_version="TLSv1.3",
            cipher="TLS_AES_256_GCM_SHA384",
        ),
    )
    monkeypatch.setattr(
        module,
        "check_system_trust",
        lambda host, port=443, timeout=module.DEFAULT_TIMEOUT_SECONDS: "",
    )
    monkeypatch.setattr(
        module,
        "fetch_http_snapshot",
        lambda host,
        port=443,
        path="/",
        timeout=module.DEFAULT_TIMEOUT_SECONDS: module.HttpSnapshot(
            status=308,
            reason="Permanent Redirect",
            location="https://keystone.kris.openbrand.com/",
            server="Caddy",
        ),
    )

    result = module.probe_host(spec, min_lifetime_days=2.0)

    assert result.ok is True
    assert result.issues == ()
    assert result.warnings == ()


def test_probe_host_accepts_expected_networking_dns_paths(monkeypatch) -> None:
    module = _load_frontdoor_tls_probe()
    spec = module.HostExpectation(
        host="housebot.home.arpa",
        label="Housebot",
        surface="bot-tui",
        expected_lan_addresses=("192.168.2.241",),
        expected_road_addresses=("100.103.34.17",),
    )
    paths = module.build_dns_probe_paths("networking")

    def fake_dns(
        host, *, resolver, transport="udp", timeout=module.DEFAULT_TIMEOUT_SECONDS
    ):
        assert host == "housebot.home.arpa"
        if resolver == "192.168.2.1":
            return ("192.168.2.241",), ""
        return ("100.103.34.17",), ""

    monkeypatch.setattr(module, "resolve_host_addresses_via_dns", fake_dns)
    monkeypatch.setattr(
        module,
        "resolve_host_addresses",
        lambda host, port=443: ("192.168.2.241",),
    )
    monkeypatch.setattr(
        module,
        "fetch_tls_snapshot",
        lambda host,
        port=443,
        timeout=module.DEFAULT_TIMEOUT_SECONDS: module.TlsSnapshot(
            issuer="organizationName=Caddy Local Authority",
            not_before="Apr 24 04:15:13 2026 GMT",
            not_after="Apr 30 04:15:13 2026 GMT",
            san_dns=("housebot.home.arpa",),
            san_ip_addresses=(),
            hostname_matches=True,
            days_remaining=5.7,
            tls_version="TLSv1.3",
            cipher="TLS_AES_256_GCM_SHA384",
        ),
    )
    monkeypatch.setattr(
        module,
        "check_system_trust",
        lambda host, port=443, timeout=module.DEFAULT_TIMEOUT_SECONDS: "",
    )
    monkeypatch.setattr(
        module,
        "fetch_http_snapshot",
        lambda host,
        port=443,
        path="/",
        timeout=module.DEFAULT_TIMEOUT_SECONDS: module.HttpSnapshot(
            status=200,
            reason="OK",
            location="",
            server="Caddy",
        ),
    )

    result = module.probe_host(spec, min_lifetime_days=2.0, dns_paths=paths)

    assert result.ok is True
    assert [(snapshot.name, snapshot.ok) for snapshot in result.dns_paths] == [
        ("lan", True),
        ("dohio-udp", True),
        ("dohio-tcp", True),
    ]


def test_probe_host_flags_dohio_udp_dns_failure(monkeypatch) -> None:
    module = _load_frontdoor_tls_probe()
    spec = module.HostExpectation(
        host="housebot.home.arpa",
        label="Housebot",
        surface="bot-tui",
        expected_lan_addresses=("192.168.2.241",),
        expected_road_addresses=("100.103.34.17",),
    )
    paths = module.build_dns_probe_paths("networking")

    def fake_dns(
        host, *, resolver, transport="udp", timeout=module.DEFAULT_TIMEOUT_SECONDS
    ):
        if resolver == "192.168.2.1":
            return ("192.168.2.241",), ""
        if transport == "udp":
            return (), "dig timed out after 5.0s"
        return ("100.103.34.17",), ""

    monkeypatch.setattr(module, "resolve_host_addresses_via_dns", fake_dns)
    monkeypatch.setattr(
        module,
        "resolve_host_addresses",
        lambda host, port=443: ("192.168.2.241",),
    )
    monkeypatch.setattr(
        module,
        "fetch_tls_snapshot",
        lambda host,
        port=443,
        timeout=module.DEFAULT_TIMEOUT_SECONDS: module.TlsSnapshot(
            issuer="organizationName=Caddy Local Authority",
            not_before="Apr 24 04:15:13 2026 GMT",
            not_after="Apr 30 04:15:13 2026 GMT",
            san_dns=("housebot.home.arpa",),
            san_ip_addresses=(),
            hostname_matches=True,
            days_remaining=5.7,
            tls_version="TLSv1.3",
            cipher="TLS_AES_256_GCM_SHA384",
        ),
    )
    monkeypatch.setattr(
        module,
        "check_system_trust",
        lambda host, port=443, timeout=module.DEFAULT_TIMEOUT_SECONDS: "",
    )
    monkeypatch.setattr(
        module,
        "fetch_http_snapshot",
        lambda host,
        port=443,
        path="/",
        timeout=module.DEFAULT_TIMEOUT_SECONDS: module.HttpSnapshot(
            status=200,
            reason="OK",
            location="",
            server="Caddy",
        ),
    )

    result = module.probe_host(spec, min_lifetime_days=2.0, dns_paths=paths)

    assert result.ok is False
    assert any("dohio-udp DNS failed" in issue for issue in result.issues)
    assert [snapshot.ok for snapshot in result.dns_paths] == [True, False, True]


def test_probe_host_flags_trust_lifetime_and_redirect_failures(monkeypatch) -> None:
    module = _load_frontdoor_tls_probe()
    spec = module.HostExpectation(
        host="kpis.home.arpa",
        label="Leadership KPIs",
        redirect_to_host="kpis.kris.openbrand.com",
    )

    monkeypatch.setattr(
        module,
        "resolve_host_addresses",
        lambda host, port=443: ("192.168.2.241",),
    )
    monkeypatch.setattr(
        module,
        "fetch_tls_snapshot",
        lambda host,
        port=443,
        timeout=module.DEFAULT_TIMEOUT_SECONDS: module.TlsSnapshot(
            issuer="organizationName=Caddy Local Authority",
            not_before="Apr 24 04:15:13 2026 GMT",
            not_after="Apr 24 16:15:13 2026 GMT",
            san_dns=("kpis.home.arpa",),
            san_ip_addresses=(),
            hostname_matches=True,
            days_remaining=0.4,
            tls_version="TLSv1.3",
            cipher="TLS_AES_256_GCM_SHA384",
        ),
    )
    monkeypatch.setattr(
        module,
        "check_system_trust",
        lambda host,
        port=443,
        timeout=module.DEFAULT_TIMEOUT_SECONDS: "SSLCertVerificationError: self-signed certificate",
    )
    monkeypatch.setattr(
        module,
        "fetch_http_snapshot",
        lambda host,
        port=443,
        path="/",
        timeout=module.DEFAULT_TIMEOUT_SECONDS: module.HttpSnapshot(
            status=200,
            reason="OK",
            location="",
            server="Caddy",
        ),
    )

    result = module.probe_host(spec, min_lifetime_days=2.0)

    assert result.ok is False
    assert any("system trust check failed" in issue for issue in result.issues)
    assert any("certificate expires too soon" in issue for issue in result.issues)
    assert any(
        "expected redirect to kpis.kris.openbrand.com" in issue
        for issue in result.issues
    )


def test_probe_host_warns_on_backend_5xx_without_failing(monkeypatch) -> None:
    module = _load_frontdoor_tls_probe()
    spec = module.HostExpectation(
        host="networking.home.arpa",
        label="Networking",
    )

    monkeypatch.setattr(
        module,
        "resolve_host_addresses",
        lambda host, port=443: ("192.168.2.242",),
    )
    monkeypatch.setattr(
        module,
        "fetch_tls_snapshot",
        lambda host,
        port=443,
        timeout=module.DEFAULT_TIMEOUT_SECONDS: module.TlsSnapshot(
            issuer="organizationName=Caddy Local Authority",
            not_before="Apr 24 04:15:13 2026 GMT",
            not_after="Apr 30 04:15:13 2026 GMT",
            san_dns=("networking.home.arpa",),
            san_ip_addresses=(),
            hostname_matches=True,
            days_remaining=5.7,
            tls_version="TLSv1.3",
            cipher="TLS_AES_256_GCM_SHA384",
        ),
    )
    monkeypatch.setattr(
        module,
        "check_system_trust",
        lambda host, port=443, timeout=module.DEFAULT_TIMEOUT_SECONDS: "",
    )
    monkeypatch.setattr(
        module,
        "fetch_http_snapshot",
        lambda host,
        port=443,
        path="/",
        timeout=module.DEFAULT_TIMEOUT_SECONDS: module.HttpSnapshot(
            status=501,
            reason="Not Implemented",
            location="",
            server="Caddy",
        ),
    )

    result = module.probe_host(spec, min_lifetime_days=2.0)

    assert result.ok is True
    assert result.issues == ()
    assert result.warnings == ("backend returned HTTP 501",)
