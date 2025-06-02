import os
from sqlalchemy.engine import make_url

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.core.config import settings

# Ensure the SQLite database directory exists before creating the engine
db_url = settings.database_url
if db_url.startswith("sqlite"):
    db_path = make_url(db_url).database
    if db_path:
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

engine = create_engine(
    db_url,
    poolclass=QueuePool,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False}
    if db_url.startswith("sqlite")
    else {},
)

# Enable WAL mode when using SQLite for better concurrency
if settings.database_url.startswith("sqlite"):
    with engine.begin() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
