from pathlib import Path
import subprocess

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.db.base import Base


def test_upgrade_heads_and_create_metadata_on_fresh_sqlite_database(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "norman.db"
    repository_root = Path(__file__).resolve().parents[1]
    config = Config(str(repository_root / "alembic.ini"))
    config.set_main_option("script_location", str(repository_root / "alembic"))
    monkeypatch.setenv("NORMAN_ALEMBIC_DATABASE_URL", f"sqlite:///{database_path}")

    command.upgrade(config, "heads")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)
        assert "estate_services" in inspector.get_table_names()
        columns = {
            column["name"] for column in inspector.get_columns("estate_services")
        }
        assert {
            "console_url",
            "web_url_tailnet",
            "console_url_tailnet",
        } <= columns
    finally:
        engine.dispose()


def test_startup_migrations_pass_configured_database_to_alembic(monkeypatch, tmp_path):
    import main

    database_url = f"sqlite:///{tmp_path / 'configured.db'}"
    captured = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(main.settings, "database_url", database_url)
    monkeypatch.setattr(main.subprocess, "run", fake_run)

    main.run_alembic_migrations()

    assert captured["args"][0] == [
        main.sys.executable,
        "-m",
        "alembic",
        "upgrade",
        "heads",
    ]
    assert captured["kwargs"]["env"]["NORMAN_ALEMBIC_DATABASE_URL"] == database_url
