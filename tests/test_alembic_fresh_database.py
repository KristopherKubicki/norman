from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.db.base import Base


def test_upgrade_heads_and_create_metadata_on_fresh_sqlite_database(tmp_path):
    database_path = tmp_path / "norman.db"
    repository_root = Path(__file__).resolve().parents[1]
    config = Config(str(repository_root / "alembic.ini"))
    config.set_main_option("script_location", str(repository_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

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
