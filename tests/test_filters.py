import pytest
from app.schemas import ChannelFilterCreate
from app.crud import filters
from app.core.database import get_db
from fastapi import HTTPException
from sqlalchemy.orm import Session

# You can replace this with the actual test filter data
test_filter_data = {
    "name": "Test Filter",
    "regex": r"\btest\b",
    "reply_channel_id": 1,
    "prompt": "Test prompt",
    "enabled": True,
    "rank": 1
}

def test_create_filter():
    db = next(get_db())
    filter_create = ChannelFilterCreate(**test_filter_data)
    created_filter = filters.create(db=db, filter_create=filter_create)
    assert created_filter.name == test_filter_data["name"]
    assert created_filter.regex == test_filter_data["regex"]
    assert created_filter.reply_channel_id == test_filter_data["reply_channel_id"]
    assert created_filter.prompt == test_filter_data["prompt"]
    assert created_filter.enabled == test_filter_data["enabled"]
    assert created_filter.rank == test_filter_data["rank"]

def test_get_filter_by_id():
    db = next(get_db())
    filter_id = 1  # Assume filter with ID 1 exists in the database
    retrieved_filter = filters.get(db=db, filter_id=filter_id)
    assert retrieved_filter.id == filter_id

def test_update_filter():
    db = next(get_db())
    filter_id = 1  # Assume filter with ID 1 exists in the database
    updated_data = {
        "name": "Updated Test Filter",
        "regex": r"\bupdated\b",
    }
    filter_update = ChannelFilterCreate(**updated_data)
    updated_filter = filters.update(db=db, filter_id=filter_id, filter_update=filter_update)
    assert updated_filter.name == updated_data["name"]
    assert updated_filter.regex == updated_data["regex"]

def test_delete_filter():
    db = next(get_db())
    filter_id = 1  # Assume filter with ID 1 exists in the database
    deleted_filter = filters.delete(db=db, filter_id=filter_id)
    assert deleted_filter.id == filter_id
    with pytest.raises(HTTPException):
        filters.get(db=db, filter_id=filter_id)

