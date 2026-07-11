from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.crud import connector as connector_crud
from app.connectors.jira_service_desk_connector import JiraServiceDeskConnector
from app.routing.engine import enqueue_routing_job

router = APIRouter()


@router.post("/webhooks/jira/{connector_id}")
async def process_jira_update_for_connector(
    connector_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    connector = connector_crud.get(db, connector_id)
    if not connector or connector.connector_type != "jira_service_desk":
        raise HTTPException(status_code=404, detail="Connector not found")

    config = connector.config or {}
    secret = config.get("webhook_secret")
    if secret:
        header = request.headers.get("X-Atlassian-Token")
        if header and header != "no-check":
            raise HTTPException(status_code=401, detail="Invalid webhook token")

    payload = await request.json()
    jira_connector = JiraServiceDeskConnector(
        url=config.get("url", ""),
        email=config.get("email", ""),
        api_token=config.get("api_token", ""),
        project_key=config.get("project_key", ""),
        config=config,
    )
    normalized = jira_connector.process_incoming(payload)
    await enqueue_routing_job(
        db=db, connector=connector, normalized=normalized, payload=payload
    )
    return {"detail": "Update processed"}
