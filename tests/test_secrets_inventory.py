from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_inventory_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "secrets_inventory.py"
    spec = importlib.util.spec_from_file_location("secrets_inventory", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["secrets_inventory"] = module
    spec.loader.exec_module(module)
    return module


def test_key_alias_coverage_dedupes_shared_fleet_tokens() -> None:
    module = _load_inventory_module()
    files = [
        module.FileInventory(
            path="/etc/norman/switchboard-bbs.env",
            exists=True,
            area="norman system env",
            secret_keys=["SWITCHBOARD_TOKEN"],
        )
    ]
    tuis = [
        module.TuiEnvInventory(
            host="work-special",
            name="panelbot",
            env_file="/etc/panelbot/codex-web.env",
            secret_keys=[
                "NORMAN_CODEX_BROWSER_AUTH_CLIENTS",
                "NORMAN_CODEX_LONG_JOB_NOTIFY_TOKEN",
                "NORMAN_CODEX_WEB_TOKEN",
            ],
        ),
        module.TuiEnvInventory(
            host="work-special",
            name="control-plane",
            env_file="/etc/control-plane/codex-web.env",
            secret_keys=["NORMAN_CODEX_LONG_JOB_NOTIFY_TOKEN"],
        ),
    ]
    keys_db = {
        "aliases": [{"name": "notify.long-job.fleet-token", "enabled": 1}],
        "policies": [{"secret_prefix": "notify.long-job.", "enabled": 1}],
    }

    coverage = module.build_key_alias_coverage(
        files=files,
        tuis=tuis,
        keys_db=keys_db,
    )
    by_alias = {item.alias: item for item in coverage}

    assert by_alias["notify.long-job.fleet-token"].status == "covered"
    assert by_alias["notify.long-job.fleet-token"].policy_status == "covered"
    assert by_alias["notify.long-job.fleet-token"].consumers == [
        "work-special/panelbot",
        "work-special/control-plane",
    ]
    assert by_alias["tui.panelbot.web-token"].status == "missing"
    assert by_alias["tui.panelbot.browser-auth-clients"].status == "missing"
    assert by_alias["bbs.switchboard.post-token"].status == "missing"


def test_key_alias_coverage_uses_canonical_tui_actor_names() -> None:
    module = _load_inventory_module()
    coverage = module.build_key_alias_coverage(
        files=[],
        tuis=[
            module.TuiEnvInventory(
                host="hal",
                name="autocamera",
                env_file="/etc/autocamera/codex-web.env",
                secret_keys=["NORMAN_CODEX_WEB_TOKEN"],
            ),
            module.TuiEnvInventory(
                host="toy-box",
                name="studio",
                env_file="/etc/studio/codex-web.env",
                secret_keys=["NORMAN_CODEX_WEB_TOKEN"],
            ),
            module.TuiEnvInventory(
                host="networking-host",
                name="networking",
                env_file="/etc/net-agents/networking.env",
                secret_keys=["NORMAN_CODEX_WEB_TOKEN"],
            ),
        ],
        keys_db={"aliases": [], "policies": []},
    )
    by_alias = {item.alias: item for item in coverage}

    assert "tui.studio.web-token" not in by_alias
    assert "tui.networking.web-token" not in by_alias
    assert by_alias["tui.autocamera.web-token"].consumers == [
        "hal/autocamera",
        "toy-box/studio",
    ]
    assert by_alias["tui.netops.web-token"].consumers == ["networking-host/networking"]
    assert any(
        "canonical actor autocamera" in note
        for note in by_alias["tui.autocamera.web-token"].notes
    )
    assert any(
        "canonical actor netops" in note
        for note in by_alias["tui.netops.web-token"].notes
    )


def test_secrets_inventory_report_includes_key_coverage_section() -> None:
    module = _load_inventory_module()
    coverage = [
        module.KeyAliasCoverage(
            alias="tui.panelbot.web-token",
            source="tui-env",
            source_keys=["NORMAN_CODEX_WEB_TOKEN"],
            consumers=["work-special/panelbot"],
            locations=["/etc/panelbot/codex-web.env"],
            status="missing",
            policy_status="missing",
        )
    ]

    report = module.render_report(
        files=[],
        tuis=[],
        remote_files=[],
        keys_db={"available": True, "aliases": [], "policies": [], "providers": []},
        key_alias_coverage=coverage,
    )

    assert "## Norman Keys Coverage" in report
    assert "| Missing key aliases | 1 |" in report
    assert "tui.panelbot.web-token" in report


def test_parse_key_lines_strips_shell_export_prefix() -> None:
    module = _load_inventory_module()

    keys, nonsecret = module.parse_key_lines(
        "export JIRA_API_TOKEN=redacted\nPLAIN=value\n",
        path="/tmp/test.env",
    )

    assert keys == ["JIRA_API_TOKEN"]
    assert nonsecret == 1


def test_secrets_inventory_report_includes_remote_host_files() -> None:
    module = _load_inventory_module()
    report = module.render_report(
        files=[],
        tuis=[],
        remote_files=[
            module.RemoteFileInventory(
                host="hal",
                path="/home/kristopher/.aws/credentials",
                exists=True,
                area="remote aws local profile",
                mode="-rw-------",
                owner="kristopher",
                group="kristopher",
                secret_keys=["aws_access_key_id", "aws_secret_access_key"],
            )
        ],
        keys_db={"available": True, "aliases": [], "policies": [], "providers": []},
        key_alias_coverage=[],
    )

    assert "## Remote Host Secret Files" in report
    assert "| Remote host files with secret-like keys or notes | 1 |" in report
    assert "/home/kristopher/.aws/credentials" in report


def test_key_alias_coverage_includes_remote_host_files_without_dup_tui_envs() -> None:
    module = _load_inventory_module()
    coverage = module.build_key_alias_coverage(
        files=[],
        tuis=[],
        remote_files=[
            module.RemoteFileInventory(
                host="hal",
                path="/etc/autocamera/codex-web.env",
                exists=True,
                area="remote system secret file",
                secret_keys=["NORMAN_CODEX_WEB_TOKEN"],
            ),
            module.RemoteFileInventory(
                host="hal",
                path="/etc/autocamera/switchboard-bbs.env",
                exists=True,
                area="remote system secret file",
                secret_keys=["SWITCHBOARD_TOKEN"],
            ),
            module.RemoteFileInventory(
                host="hal",
                path="/home/kristopher/.aws/credentials",
                exists=True,
                area="remote aws local profile",
                secret_keys=["aws_access_key_id", "aws_secret_access_key"],
            ),
            module.RemoteFileInventory(
                host="networking-host",
                path="/root/.codex-cloudagent/switchboard-bbs.env",
                exists=True,
                area="remote codex auth",
                secret_keys=["SWITCHBOARD_TOKEN"],
            ),
        ],
        keys_db={"aliases": [], "policies": []},
    )
    aliases = {item.alias for item in coverage}
    by_alias = {item.alias: item for item in coverage}

    assert "host.hal.etc.autocamera.codex-web-env" not in aliases
    assert "bbs.autocamera.post-token" in aliases
    assert "bbs.cloudagent.post-token" in aliases
    assert "host.hal.aws.credentials" in aliases
    assert by_alias["host.hal.aws.credentials"].source_keys == [
        "aws_access_key_id",
        "aws_secret_access_key",
    ]


def test_remote_secret_scan_specs_include_discovered_tui_roots() -> None:
    module = _load_inventory_module()
    fake_sync = SimpleNamespace(
        HOSTS={
            "toy-box": object(),
            "work-special": object(),
        },
        discover_all_instances=lambda host_names: (
            {
                "toy-box": [
                    SimpleNamespace(
                        env_file="/etc/castle/codex-web.env",
                        prompt_file="/etc/castle/codex-system-prompt.txt",
                        codex_home="/root/.codex-castle",
                    )
                ],
                "work-special": [
                    SimpleNamespace(
                        env_file="/etc/panelbot/codex-web.env",
                        prompt_file="/etc/panelbot/codex-system-prompt.txt",
                        codex_home="/home/kristopher/.codex-panelbot",
                    )
                ],
            },
            {},
        ),
    )

    specs = module.remote_secret_scan_specs(fake_sync)

    assert set(specs) == {"toy-box", "work-special"}
    assert "/etc/castle" in specs["toy-box"]["roots"]
    assert "/root/.codex-castle" in specs["toy-box"]["roots"]
    assert "/etc/panelbot" in specs["work-special"]["roots"]
    assert "/home/kristopher/.codex-panelbot" in specs["work-special"]["roots"]
    assert "/home/kristopher/.aws" in specs["work-special"]["roots"]
