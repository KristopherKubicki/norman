

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from pathlib import Path

from app.core.config import settings


# Ensure the SQLite database directory exists before creating the engine
if settings.database_url.startswith("sqlite"):
    db_path = settings.database_url.replace("sqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    poolclass=QueuePool,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)


if settings.database_url.startswith("sqlite"):
    # Ensure the SQLite database directory exists before connecting
    db_path = engine.url.database
    if db_path and db_path != ":memory:":
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA synchronous=NORMAL"))

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
