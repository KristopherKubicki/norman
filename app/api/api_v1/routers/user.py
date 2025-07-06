from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud
from app.schemas.user import UserCreate, UserUpdate, User
from app.api.deps import get_db

router = APIRouter()


@router.post("/users/", response_model=User, status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate, db: Session = Depends(get_db)):
    """Create a new user account.

    Args:
        user: Incoming user data from the request body.
        db: Database session dependency.

    Returns:
        The created user instance.
    """

    return crud.user.create_user(db, user=user)


@router.get("/users/", response_model=List[User])
async def get_users(db: Session = Depends(get_db)):
    """Return all users.

    Args:
        db: Database session dependency.

    Returns:
        List of users.
    """

    return crud.user.get_users(db)


@router.get("/users/{user_id}", response_model=User)
async def get_user(user_id: int, db: Session = Depends(get_db)):
    """Fetch a user by ID.

    Args:
        user_id: Identifier of the user to fetch.
        db: Database session dependency.

    Returns:
        The requested user.

    Raises:
        HTTPException: If the user does not exist.
    """

    user = crud.user.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/users/{user_id}", response_model=User)
async def update_user(user_id: int, user: UserUpdate, db: Session = Depends(get_db)):
    """Update a user record.

    Args:
        user_id: Identifier of the user to update.
        user: New user values.
        db: Database session dependency.

    Returns:
        The updated user instance.

    Raises:
        HTTPException: If the user does not exist.
    """

    updated = crud.user.update_user(db, user_id=user_id, user_data=user)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    return updated


@router.delete("/users/{user_id}", response_model=User)
async def delete_user(user_id: int, db: Session = Depends(get_db)):
    """Delete a user by ID.

    Args:
        user_id: Identifier of the user to delete.
        db: Database session dependency.

    Returns:
        The deleted user instance.

    Raises:
        HTTPException: If the user does not exist.
    """

    deleted = crud.user.delete_user(db, user_id=user_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="User not found")
    return deleted
