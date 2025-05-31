"""CRUD tests for channels using helper functions."""

from sqlalchemy.orm import Session

from app import crud
from app.schemas.channel import ChannelCreate, ChannelUpdate
from app.tests.utils.utils import random_lower_string


def test_channel_crud(db: Session) -> None:
    name = random_lower_string()
    ch = crud.channel.create(db, obj_in=ChannelCreate(name=name, connector_id=1))
    assert ch.name == name

    fetched = crud.channel.get(db, ch.id)
    assert fetched

    updated = crud.channel.update(db, db_obj=fetched, obj_in=ChannelUpdate(name="updated", connector_id=1))
    assert updated.name == "updated"

    all_ch = crud.channel.get_multi(db)
    assert any(c.id == ch.id for c in all_ch)

    removed = crud.channel.remove(db, ch.id)
    assert removed.id == ch.id
    assert crud.channel.get(db, ch.id) is None
