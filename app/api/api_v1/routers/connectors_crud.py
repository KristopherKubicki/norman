from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app import crud
from app.connectors.connector_utils import connector_classes, get_connectors_data
from app.schemas import (
    ConnectorCreate,
    ConnectorUpdate,
    Connector,
    ConnectorInfo,
)
from app.api.deps import get_db

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.get("/available", response_model=List[ConnectorInfo])
async def list_available_connectors() -> List[ConnectorInfo]:
    """Return metadata about all available connector implementations."""
    return get_connectors_data()


@router.post("/", response_model=Connector, status_code=201)
async def create_connector(connector: ConnectorCreate, db: Session = Depends(get_db)):
    """Create a connector entry.

    Args:
        connector: Connector data from the request body.
        db: Database session dependency.

    Returns:
        The newly created connector.

    Raises:
        HTTPException: If the connector type is invalid or creation fails.
    """
    if connector.connector_type not in connector_classes:
        raise HTTPException(status_code=400, detail="Invalid connector type")
    try:
        return crud.connector.create(db, obj_in=connector)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=List[Connector])
async def get_connectors(db: Session = Depends(get_db)):
    """Return all connectors.

    Args:
        db: Database session dependency.

    Returns:
        List of connectors.
    """

    connectors = crud.connector.get_multi(db)
    return connectors


@router.get("/{connector_id}", response_model=Connector)
async def get_connector(connector_id: int, db: Session = Depends(get_db)):
    """Fetch a connector by ID.

    Args:
        connector_id: Identifier of the connector to fetch.
        db: Database session dependency.

    Returns:
        The requested connector.

    Raises:
        HTTPException: If the connector does not exist.
    """

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
    """Update an existing connector.

    Args:
        connector_id: Identifier of the connector to update.
        connector: Updated connector values.
        db: Database session dependency.

    Returns:
        The updated connector instance.

    Raises:
        HTTPException: If the connector does not exist or update fails.
    """
    db_connector = crud.connector.get(db, connector_id)
    if not db_connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    try:
        return crud.connector.update(db, db_obj=db_connector, obj_in=connector)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{connector_id}", response_model=Connector)
async def delete_connector(connector_id: int, db: Session = Depends(get_db)):
    """Delete a connector by ID.

    Args:
        connector_id: Identifier of the connector to delete.
        db: Database session dependency.

    Returns:
        The deleted connector instance.

    Raises:
        HTTPException: If the connector does not exist.
    """

    connector = crud.connector.remove(db, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector
