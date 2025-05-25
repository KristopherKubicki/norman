import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud, models
from app.core.config import settings
from app.schemas.channel_filter import FilterCreate
from app.tests.utils.utils import random_lower_string

def test_create_channel_filter(test_app: TestClient, db: Session) -> None:
    regex = r"helpdesk"
    description = random_lower_string()
    channel_filter_in = FilterCreate(regex=regex, description=description)
    channel_filter = crud.channel_filter.create(db, obj_in=channel_filter_in)
    assert channel_filter.regex == regex
    assert channel_filter.description == description

def test_get_channel_filter(test_app: TestClient, db: Session) -> None:
    regex = r"helpdesk"
    description = random_lower_string()
    channel_filter_in = FilterCreate(regex=regex, description=description)
    channel_filter = crud.channel_filter.create(db, obj_in=channel_filter_in)
    channel_filter_2 = crud.channel_filter.get(db, channel_filter.id)
    assert channel_filter_2
    assert channel_filter.regex == channel_filter_2.regex
    assert channel_filter.description == channel_filter_2.description
    assert channel_filter.id == channel_filter_2.id
