from sqlalchemy.orm import Session

from app.crud import channel as channel_crud
from app.schemas.channel import ChannelCreate, ChannelUpdate


def test_channel_crud(db: Session) -> None:
    ch = channel_crud.create(db, obj_in=ChannelCreate(name="test", connector_id=1))
    assert ch.name == "test"
    assert ch.connector_id == 1
    channel_id = ch.id

    fetched = channel_crud.get(db, channel_id)
    assert fetched.id == channel_id
    assert fetched.connector_id == 1

    updated = channel_crud.update(db, db_obj=fetched, obj_in=ChannelUpdate(name="updated", connector_id=1))
    assert updated.name == "updated"

    all_channels = channel_crud.get_multi(db)
    assert any(c.id == channel_id for c in all_channels)

    removed = channel_crud.remove(db, channel_id)
    assert removed.id == channel_id
    assert channel_crud.get(db, channel_id) is None

