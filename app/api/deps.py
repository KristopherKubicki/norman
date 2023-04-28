from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import SessionLocal

def get_db():
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()

