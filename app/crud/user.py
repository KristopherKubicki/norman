# app/crud/user.py

from sqlalchemy.orm import Session
from app import models
from app.models.user import User
from app.schemas.user import UserCreate, UserAuthenticate
from app.core.security import get_password_hash, verify_password


def get_user_by_id(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_username(db: Session, username: str):
    return db.query(User).filter(User.username == username).first()

def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()

def create_user(db: Session, user: UserCreate):
    hashed_password = get_password_hash(user.password)
    db_user = User(
        username=user.username,
        email=user.email,
        password=hashed_password,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def authenticate_user(db: Session, user_auth: UserAuthenticate):
    user = get_user_by_email(db=db, email=user_auth.email) # should be an email address
    if not user:
        return None
    if not verify_password(user_auth.password, user.password):
        return None
    return user

def is_admin_user_exists(db: Session) -> bool:
    admin_user = db.query(models.User).filter(models.User.is_superuser == True).first()
    return admin_user is not None

def create_admin_user(db: Session, email: str, password: str):
    hashed_password = get_password_hash(password)
    user = models.User(email=email, password=hashed_password, is_superuser=True, username='admin') # todo: add to config
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
