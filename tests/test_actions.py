import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import crud, models
from app.core.config import settings
from app.schemas.action import ActionCreate
from app.tests.utils.utils import random_lower_string

def test_create_action(test_app: TestClient, db: Session) -> None:
    prompt = random_lower_string()
    execution_order = 1
    action_in = ActionCreate(prompt=prompt, execution_order=execution_order)
    action = crud.action.create(db, obj_in=action_in)
    assert action.prompt == prompt
    assert action.execution_order == execution_order

def test_get_action(test_app: TestClient, db: Session) -> None:
    prompt = random_lower_string()
    execution_order = 1
    action_in = ActionCreate(prompt=prompt, execution_order=execution_order)
    action = crud.action.create(db, obj_in=action_in)
    action_2 = crud.action.get(db, action.id)
    assert action_2
    assert action.prompt == action_2.prompt
    assert action.execution_order == action_2.execution_order
    assert action.id == action_2.id
