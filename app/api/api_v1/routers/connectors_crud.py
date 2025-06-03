from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app import crud
from app.connectors.connector_utils import connector_classes
from app.schemas import ConnectorCreate, ConnectorUpdate, Connector
from app.api.deps import get_db

router = APIRouter(prefix="/connectors", tags=["connectors"])

@router.post("/", response_model=Connector, status_code=201)
async def create_connector(
    connector: ConnectorCreate, db: Session = Depends(get_db)
):
    if connector.connector_type not in connector_classes:
        raise HTTPException(status_code=400, detail="Invalid connector type")
    try:
        return crud.connector.create(db, obj_in=connector)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/", response_model=List[Connector])
async def get_connectors(db: Session = Depends(get_db)):
    connectors = crud.connector.get_multi(db)
    return connectors

@router.get("/{connector_id}", response_model=Connector)
async def get_connector(connector_id: int, db: Session = Depends(get_db)):
    connector = crud.connector.get(db, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector

@router.put("/{connector_id}", response_model=Connector)
async def update_connector(
    connector_id: int,
    connector: ConnectorUpdate,
    db: Session = Depends(get_db),
):
    db_connector = crud.connector.get(db, connector_id)
    if not db_connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    try:
        return crud.connector.update(db, db_obj=db_connector, obj_in=connector)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{connector_id}", response_model=Connector)
async def delete_connector(connector_id: int, db: Session = Depends(get_db)):
    connector = crud.connector.remove(db, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector

