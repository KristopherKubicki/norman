from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.crud import action as crud_action
from app.schemas.action import ActionCreate, ActionUpdate
from app.tests.utils.utils import random_lower_string

def test_create_action(test_app: TestClient, db: Session) -> None:
    prompt = random_lower_string()
    execution_order = 1
    action_in = ActionCreate(
        channel_filter_id=1,
        prompt=prompt,
        reply_channel_id=1,
        execution_order=execution_order,
    )
    action = crud_action.create(db, obj_in=action_in)
    assert action.prompt == prompt
    assert action.execution_order == execution_order

def test_get_action(test_app: TestClient, db: Session) -> None:
    prompt = random_lower_string()
    execution_order = 1
    action_in = ActionCreate(
        channel_filter_id=1,
        prompt=prompt,
        reply_channel_id=1,
        execution_order=execution_order,
    )
    action = crud_action.create(db, obj_in=action_in)
    action_2 = crud_action.get(db, action.id)
    assert action_2
    assert action.prompt == action_2.prompt
    assert action.execution_order == action_2.execution_order
    assert action.id == action_2.id


def test_update_action(test_app: TestClient, db: Session) -> None:
    prompt = random_lower_string()
    action_in = ActionCreate(
        channel_filter_id=1,
        prompt=prompt,
        reply_channel_id=1,
        execution_order=1,
    )
    action = crud_action.create(db, obj_in=action_in)
    new_prompt = random_lower_string()
    action_up = ActionUpdate(
        channel_filter_id=1,
        prompt=new_prompt,
        reply_channel_id=1,
        execution_order=2,
    )
    updated = crud_action.update(db, db_obj=action, obj_in=action_up)
    assert updated.prompt == new_prompt
    assert updated.execution_order == 2


def test_remove_action(test_app: TestClient, db: Session) -> None:
    action_in = ActionCreate(
        channel_filter_id=1,
        prompt=random_lower_string(),
        reply_channel_id=1,
        execution_order=1,
    )
    action = crud_action.create(db, obj_in=action_in)
    removed = crud_action.remove(db, action.id)
    assert removed.id == action.id
    assert crud_action.get(db, action.id) is None
