"""Exercise router helpers via CRUD operations."""

from sqlalchemy.orm import Session

from app import crud
from app.schemas.channel import ChannelCreate
from app.tests.utils.utils import random_lower_string


def test_channel_router_crud(db: Session) -> None:
    name = random_lower_string()
    channel = crud.channel.create(db, obj_in=ChannelCreate(name=name, connector_id=1))
    assert channel.name == name

    channel = crud.channel.get(db, channel.id)
    assert channel

    channel = crud.channel.update(db, db_obj=channel, obj_in=ChannelCreate(name="updated", connector_id=1))
    assert channel.name == "updated"

    listing = crud.channel.get_multi(db)
    assert any(ch.id == channel.id for ch in listing)

    removed = crud.channel.remove(db, channel.id)
    assert removed.id == channel.id
