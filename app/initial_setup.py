# this should be called by the main.py and not by the command line 

from app.core.config import settings
from app.crud.user import is_admin_user_exists, create_admin_user
from app.db.session import SessionLocal

def create_initial_admin_user() -> None:

    db = SessionLocal()
    if not is_admin_user_exists(db):
        create_admin_user(
            db,
            settings.initial_admin_email,
            settings.initial_admin_password,
            settings.initial_admin_username,
        )
    db.close()
