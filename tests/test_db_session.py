import importlib.util
import os
from app.core.config import settings


def test_engine_pool_settings():
    old_size = settings.database_pool_size
    old_overflow = settings.database_max_overflow
    settings.database_pool_size = 7
    settings.database_max_overflow = 3
    try:
        spec = importlib.util.spec_from_file_location(
            "temp_db_session", os.path.join("app", "db", "session.py")
        )
        db_session = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(db_session)
        assert db_session.engine.pool.size() == 7
        assert db_session.engine.pool._max_overflow == 3
        assert db_session.SessionLocal.kw["bind"] is db_session.engine
    finally:
        settings.database_pool_size = old_size
        settings.database_max_overflow = old_overflow

