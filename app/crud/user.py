# app/crud/user.py

from sqlalchemy.orm import Session
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
        full_name=user.full_name,
        hashed_password=hashed_password,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def authenticate_user(db: Session, user_auth: UserAuthenticate):
    user = get_user_by_email(db=db, email=user_auth.email)
    if not user:
        return None
    if not verify_password(user_auth.password, user.hashed_password):
        return None
    return user
