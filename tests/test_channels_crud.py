import pytest
from sqlalchemy.orm import Session

from app import crud
from app.schemas.channel import ChannelCreate
from app.schemas.connector import ConnectorCreate


def create_connector(db: Session) -> int:
    connector_in = ConnectorCreate(name="test", connector_type="irc", config={})
    connector = crud.connector.create(db, obj_in=connector_in)
    return connector.id


def test_create_and_get_channel(db: Session):
    connector_id = create_connector(db)
    channel_in = ChannelCreate(name="my_channel", connector_id=connector_id)
    channel = crud.channel.create(db, obj_in=channel_in)
    assert channel.name == "my_channel"
    assert channel.connector_id == connector_id

    fetched = crud.channel.get(db, channel.id)
    assert fetched is not None
    assert fetched.id == channel.id
    assert fetched.connector_id == connector_id
