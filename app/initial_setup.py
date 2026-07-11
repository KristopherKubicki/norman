# this should be called by the main.py and not by the command line

from app.core.config import settings
from app.crud.user import is_admin_user_exists, create_admin_user
from app.db import session as db_session

# Allow tests to monkeypatch `app.initial_setup.SessionLocal` directly, while
# defaulting to the application's configured SessionLocal.
SessionLocal = None


def create_initial_admin_user():
    session_factory = SessionLocal or db_session.SessionLocal
    db = session_factory()
    if not is_admin_user_exists(db):
        create_admin_user(
            db,
            settings.initial_admin_email,
            settings.initial_admin_password,
            settings.initial_admin_username,
        )
    db.close()
