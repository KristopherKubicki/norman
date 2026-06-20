from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path


def _load_seed_module():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "seed_norman_keys_from_inventory.py"
    )
    spec = importlib.util.spec_from_file_location(
        "seed_norman_keys_from_inventory", script
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_norman_keys_from_inventory"] = module
    spec.loader.exec_module(module)
    return module


def _load_inventory_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "secrets_inventory.py"
    spec = importlib.util.spec_from_file_location("secrets_inventory", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["secrets_inventory"] = module
    spec.loader.exec_module(module)
    return module


def _create_keys_db(path: Path) -> None:
    db = sqlite3.connect(path)
    try:
        db.executescript(
            """
            create table secret_providers (
                id integer primary key,
                name varchar not null unique,
                kind varchar not null,
                enabled boolean not null,
                config json
            );
            create table secret_aliases (
                id integer primary key,
                name varchar not null unique,
                provider_id integer not null,
                backend_ref varchar not null,
                lane varchar not null,
                enabled boolean not null,
                default_ttl_seconds integer not null,
                allow_raw_reveal boolean not null,
                metadata_json json
            );
            create table secret_policies (
                id integer primary key,
                name varchar not null unique,
                requester_type varchar not null,
                requester_id varchar,
                lane varchar,
                secret_prefix varchar not null,
                allowed_modes json not null,
                max_ttl_seconds integer not null,
                approval_required boolean not null,
                raw_reveal_allowed boolean not null,
                allowed_hosts json,
                reuse_window_seconds integer not null,
                enabled boolean not null
            );
            """
        )
        db.commit()
    finally:
        db.close()


def test_seed_plan_groups_tui_policy_and_keeps_aliases_disabled() -> None:
    seed = _load_seed_module()
    inventory = _load_inventory_module()
    coverage = [
        inventory.KeyAliasCoverage(
            alias="tui.panelbot.web-token",
            source="tui-env",
            source_keys=["NORMAN_CODEX_WEB_TOKEN"],
            consumers=["work-special/panelbot"],
            locations=["/etc/panelbot/codex-web.env"],
            status="missing",
            policy_status="missing",
        ),
        inventory.KeyAliasCoverage(
            alias="tui.panelbot.browser-auth-clients",
            source="tui-env",
            source_keys=["NORMAN_CODEX_BROWSER_AUTH_CLIENTS"],
            consumers=["work-special/panelbot"],
            locations=["/etc/panelbot/codex-web.env"],
            status="missing",
            policy_status="missing",
        ),
    ]

    plan = seed.build_seed_plan(
        coverage=coverage,
        keys_db={"aliases": [], "policies": []},
    )

    assert [item.name for item in plan.aliases] == [
        "tui.panelbot.browser-auth-clients",
        "tui.panelbot.web-token",
    ]
    assert all(not item.enabled for item in plan.aliases)
    assert all(item.backend_ref.startswith("pending/") for item in plan.aliases)
    assert all(
        item.metadata_json["migration_mode"] == "catalog_only_no_secret_values"
        for item in plan.aliases
    )
    assert [item.secret_prefix for item in plan.policies] == ["tui.panelbot."]
    assert plan.policies[0].requester_type == "agent"
    assert plan.policies[0].requester_id == "panelbot"
    assert plan.policies[0].lane == "work"
    assert plan.policies[0].allowed_hosts == ["work-special"]
    assert not plan.policies[0].enabled


def test_apply_seed_plan_is_idempotent(tmp_path: Path) -> None:
    seed = _load_seed_module()
    inventory = _load_inventory_module()
    db_path = tmp_path / "norman.db"
    _create_keys_db(db_path)
    coverage = [
        inventory.KeyAliasCoverage(
            alias="notify.long-job.fleet-token",
            source="tui-env",
            source_keys=["NORMAN_CODEX_LONG_JOB_NOTIFY_TOKEN"],
            consumers=["work-special/panelbot", "toy-box/housebot"],
            locations=[
                "/etc/panelbot/codex-web.env",
                "/etc/housebot/codex-web.env",
            ],
            status="missing",
            policy_status="missing",
        )
    ]
    plan = seed.build_seed_plan(
        coverage=coverage,
        keys_db={"aliases": [], "policies": []},
    )

    first = seed.apply_seed_plan(db_path, plan)
    second = seed.apply_seed_plan(db_path, plan)

    assert first == {
        "provider_created": True,
        "aliases_created": 1,
        "policies_created": 1,
    }
    assert second == {
        "provider_created": False,
        "aliases_created": 0,
        "policies_created": 0,
    }
    db = sqlite3.connect(db_path)
    try:
        alias = db.execute(
            "select name, enabled, backend_ref from secret_aliases"
        ).fetchone()
        policy = db.execute(
            "select secret_prefix, requester_id, enabled from secret_policies"
        ).fetchone()
    finally:
        db.close()
    assert alias == (
        "notify.long-job.fleet-token",
        0,
        "pending/notify.long-job.fleet-token.secret",
    )
    assert policy == ("notify.long-job.", None, 0)


def test_seed_plan_uses_operator_policy_for_remote_host_files() -> None:
    seed = _load_seed_module()
    inventory = _load_inventory_module()
    coverage = [
        inventory.KeyAliasCoverage(
            alias="host.hal.aws.credentials",
            source="remote-host-file",
            source_keys=["aws_access_key_id", "aws_secret_access_key"],
            consumers=["hal"],
            locations=["/home/kristopher/.aws/credentials"],
            status="missing",
            policy_status="missing",
        )
    ]

    plan = seed.build_seed_plan(
        coverage=coverage,
        keys_db={"aliases": [], "policies": []},
    )

    assert [item.name for item in plan.aliases] == ["host.hal.aws.credentials"]
    assert plan.aliases[0].lane == "hal"
    assert plan.aliases[0].metadata_json["migration_mode"] == (
        "catalog_only_no_secret_values"
    )
    assert [item.secret_prefix for item in plan.policies] == [
        "host.hal.aws.credentials"
    ]
    assert plan.policies[0].requester_type == "operator"
    assert plan.policies[0].requester_id is None
    assert plan.policies[0].lane == "hal"
    assert plan.policies[0].allowed_modes == ["file"]
