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


def test_sqlite_check_same_thread():
    spec = importlib.util.spec_from_file_location(
        "temp_db_session", os.path.join("app", "db", "session.py")
    )
    db_session = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db_session)
    if settings.database_url.startswith("sqlite"):
        connect_args = db_session.engine.pool._creator.__closure__[1].cell_contents
        assert connect_args.get("check_same_thread") is False


def test_sqlite_wal_enabled():
    spec = importlib.util.spec_from_file_location(
        "temp_db_session", os.path.join("app", "db", "session.py")
    )
    db_session = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db_session)
    if settings.database_url.startswith("sqlite"):
        with db_session.engine.connect() as conn:
            mode = conn.execute(db_session.text("PRAGMA journal_mode")).scalar().lower()
        assert mode == "wal"


def test_sqlite_synchronous_normal():
    spec = importlib.util.spec_from_file_location(
        "temp_db_session", os.path.join("app", "db", "session.py")
    )
    db_session = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db_session)
    if settings.database_url.startswith("sqlite"):
        with db_session.engine.connect() as conn:
            synchronous = conn.execute(db_session.text("PRAGMA synchronous")).scalar()
        assert synchronous == 1


def test_sqlite_foreign_keys_on():
    spec = importlib.util.spec_from_file_location(
        "temp_db_session", os.path.join("app", "db", "session.py")
    )
    db_session = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db_session)
    if settings.database_url.startswith("sqlite"):
        with db_session.engine.connect() as conn:
            fk = conn.execute(db_session.text("PRAGMA foreign_keys")).scalar()
        assert fk == 1


def test_session_connection_cleanup():
    spec = importlib.util.spec_from_file_location(
        "temp_db_session", os.path.join("app", "db", "session.py")
    )
    db_session = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db_session)
    engine = db_session.engine
    start_checked_out = engine.pool.checkedout()
    session = db_session.SessionLocal()
    session.execute("SELECT 1")
    assert engine.pool.checkedout() == start_checked_out + 1
    session.close()
    assert engine.pool.checkedout() == start_checked_out


def test_engine_pool_timeout_and_recycle():
    old_timeout = settings.database_pool_timeout
    old_recycle = settings.database_pool_recycle
    settings.database_pool_timeout = 99
    settings.database_pool_recycle = 50
    try:
        spec = importlib.util.spec_from_file_location(
            "temp_db_session", os.path.join("app", "db", "session.py")
        )
        db_session = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(db_session)
        assert db_session.engine.pool._timeout == 99
        assert db_session.engine.pool._recycle == 50
    finally:
        settings.database_pool_timeout = old_timeout
        settings.database_pool_recycle = old_recycle

