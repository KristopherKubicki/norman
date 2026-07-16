import logging
from pathlib import Path

import pytest
import yaml

from app.core import config
from app.initial_setup import create_initial_admin_user


class DummyDB:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_create_initial_admin_user_creates(monkeypatch):
    db = DummyDB()
    monkeypatch.setattr("app.initial_setup.SessionLocal", lambda: db)

    calls = {}

    def fake_is_admin_user_exists(session):
        assert session is db
        calls["checked"] = True
        return False

    def fake_create_admin_user(session, email, password, username):
        calls["created"] = (email, password, username)

    monkeypatch.setattr(
        "app.initial_setup.is_admin_user_exists", fake_is_admin_user_exists
    )
    monkeypatch.setattr("app.initial_setup.create_admin_user", fake_create_admin_user)

    create_initial_admin_user()

    assert calls.get("checked") is True
    assert calls.get("created") == (
        config.settings.initial_admin_email,
        config.settings.initial_admin_password,
        config.settings.initial_admin_username,
    )
    assert db.closed


def test_create_initial_admin_user_skips_if_exists(monkeypatch):
    db = DummyDB()
    monkeypatch.setattr("app.initial_setup.SessionLocal", lambda: db)

    def fake_is_admin_user_exists(session):
        assert session is db
        return True

    called = False

    def fake_create_admin_user(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.initial_setup.is_admin_user_exists", fake_is_admin_user_exists
    )
    monkeypatch.setattr("app.initial_setup.create_admin_user", fake_create_admin_user)

    create_initial_admin_user()

    assert called is False
    assert db.closed


def test_ensure_user_config_does_not_log_bootstrap_credentials(
    monkeypatch, tmp_path: Path, caplog
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml.dist").write_text(
        yaml.safe_dump(
            {
                "secret_key": "placeholder",
                "admin_setup_key": "change_me_setup_key",
                "initial_admin_password": "change_me_too",
                "initial_admin_email": "admin@example.com",
                "initial_admin_username": "admin",
                "encryption_key": "placeholder",
                "encryption_salt": "placeholder",
            }
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger=config.__name__):
        config.ensure_user_config()

    generated = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    log_text = caplog.text
    assert "Generated config.yaml with bootstrap credentials" in log_text
    assert generated["initial_admin_username"] not in log_text
    assert generated["initial_admin_email"] not in log_text
    assert generated["initial_admin_password"] not in log_text
    assert generated["admin_setup_key"] not in log_text


def test_load_config_uses_brokered_secret_without_creating_local_config(
    monkeypatch, tmp_path: Path
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml.dist").write_text(
        (Path(__file__).resolve().parents[1] / "config.yaml.dist").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("NORMAN_CONFIG_PATH", raising=False)
    monkeypatch.setenv("NORMAN_CONFIG_SECRET", "norman/runtime-config")
    monkeypatch.setenv("NORMAN_CONFIG_SECRET_CMD", "cred get {name}")

    commands = []

    class Result:
        stdout = yaml.safe_dump(
            {
                "admin_setup_key": "brokered-setup-key",
                "secret_key": "brokered-secret-key",
            }
        )

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        return Result()

    monkeypatch.setattr(config.subprocess, "run", fake_run)

    loaded = config.load_config()

    assert loaded["admin_setup_key"] == "brokered-setup-key"
    assert loaded["secret_key"] == "brokered-secret-key"
    assert config.Settings(**loaded).secret_key == "brokered-secret-key"
    assert commands == [
        (
            ["cred", "get", "norman/runtime-config"],
            {
                "check": True,
                "capture_output": True,
                "text": True,
                "timeout": 5.0,
            },
        )
    ]
    assert not (tmp_path / "config.yaml").exists()
    assert config.active_config_file_path() is None


def test_load_config_uses_external_path_without_creating_local_config(
    monkeypatch, tmp_path: Path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external_config = tmp_path / "external-config.yaml"
    (workspace / "config.yaml.dist").write_text(
        yaml.safe_dump({"app_name": "norman", "connectors": []}),
        encoding="utf-8",
    )
    external_config.write_text(
        yaml.safe_dump(
            {
                "admin_setup_key": "external-setup-key",
                "secret_key": "external-secret-key",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(workspace)
    monkeypatch.delenv("NORMAN_CONFIG_SECRET", raising=False)
    monkeypatch.setenv("NORMAN_CONFIG_PATH", str(external_config))

    loaded = config.load_config()

    assert loaded["admin_setup_key"] == "external-setup-key"
    assert loaded["secret_key"] == "external-secret-key"
    assert not (workspace / "config.yaml").exists()
    assert config.active_config_file_path() == external_config


def test_config_path_rejects_a_file_inside_the_application_tree(
    monkeypatch, tmp_path: Path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NORMAN_CONFIG_PATH", str(tmp_path / "config.yaml"))

    with pytest.raises(config.ConfigSourceError, match="outside the application"):
        config.active_config_file_path()


def test_managed_config_never_generates_an_admin_setup_key(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external_config = tmp_path / "external-config.yaml"
    (workspace / "config.yaml.dist").write_text(
        yaml.safe_dump({"app_name": "norman", "connectors": []}),
        encoding="utf-8",
    )
    original_config = yaml.safe_dump({"secret_key": "external-secret-key"})
    external_config.write_text(original_config, encoding="utf-8")
    monkeypatch.chdir(workspace)
    monkeypatch.delenv("NORMAN_CONFIG_SECRET", raising=False)
    monkeypatch.setenv("NORMAN_CONFIG_PATH", str(external_config))

    with pytest.raises(config.ConfigSourceError, match="provide admin_setup_key"):
        config.load_config()

    assert external_config.read_text(encoding="utf-8") == original_config
    assert not (workspace / "config.yaml").exists()
