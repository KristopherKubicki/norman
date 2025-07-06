# app/crud/user.py

from sqlalchemy.orm import Session
from app import models
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate, UserAuthenticate
from app.core.security import get_password_hash, verify_password


def get_user_by_id(db: Session, user_id: int):
    """Return a user by ID."""
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_username(db: Session, username: str):
    """Return a user by username."""
    return db.query(User).filter(User.username == username).first()


def get_user_by_email(db: Session, email: str):
    """Return a user by email address."""
    return db.query(User).filter(User.email == email).first()


def create_user(db: Session, user: UserCreate):
    """Create a new user."""
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
    """Authenticate a user by email and password."""
    user = get_user_by_email(db=db, email=user_auth.email)  # should be an email address
    if not user:
        return None
    if not verify_password(user_auth.password, user.password):
        return None
    return user


def is_admin_user_exists(db: Session) -> bool:
    """Check if an administrator user exists."""
    admin_user = db.query(models.User).filter(models.User.is_superuser == True).first()
    return admin_user is not None


def create_admin_user(
    db: Session, email: str, password: str, username: str
) -> models.User:
    """Create the initial administrator user."""
    hashed_password = get_password_hash(password)
    user = models.User(
        email=email,
        password=hashed_password,
        is_superuser=True,
        username=username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_users(db: Session, skip: int = 0, limit: int = 100):
    """Return multiple users with optional pagination."""
    return db.query(User).offset(skip).limit(limit).all()


def delete_user(db: Session, user_id: int):
    """Delete a user by ID and return the deleted instance."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None
    db.delete(user)
    db.commit()
    return user


def update_user(db: Session, user_id: int, user_data: UserUpdate):
    """Update an existing user."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None

    update_data = user_data.dict(exclude_unset=True)
    if "password" in update_data:
        user.password = get_password_hash(update_data.pop("password"))
    for field, value in update_data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user
