import pytest
from app.schemas.filter import FilterCreate, FilterUpdate, Filter
from app.crud import filters

# You can replace this with the actual test filter data
test_filter_data = {
    "channel_id": 1,
    "regex": r"\btest\b",
    "description": "Test filter",
}


def test_create_filter(db):
    filter_create = FilterCreate(**test_filter_data)
    created_filter = filters.create(db=db, filter_create=filter_create)
    assert created_filter.channel_id == test_filter_data["channel_id"]
    assert created_filter.regex == test_filter_data["regex"]
    assert created_filter.description == test_filter_data["description"]


def test_get_filter_by_id(db):
    filter_create = FilterCreate(**test_filter_data)
    created = filters.create(db=db, filter_create=filter_create)
    retrieved_filter = filters.get(db=db, filter_id=created.id)
    assert retrieved_filter.id == created.id


def test_update_filter(db):
    created = filters.create(db=db, filter_create=FilterCreate(**test_filter_data))
    updated_data = {"channel_id": 2, "regex": r"\bupdated\b", "description": "Updated"}
    filter_update = FilterUpdate(**updated_data)
    updated_filter = filters.update(
        db=db, filter_id=created.id, filter_update=filter_update
    )
    assert updated_filter.channel_id == updated_data["channel_id"]
    assert updated_filter.regex == updated_data["regex"]
    assert updated_filter.description == updated_data["description"]


def test_delete_filter(db):
    created = filters.create(db=db, filter_create=FilterCreate(**test_filter_data))
    deleted_filter = filters.delete(db=db, filter_id=created.id)
    assert deleted_filter.id == created.id
    assert filters.get(db=db, filter_id=created.id) is None
