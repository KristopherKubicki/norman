from fastapi import APIRouter

router = APIRouter()

@router.post("/connectors/")
async def create_connector(connector: ConnectorCreate):
    pass

@router.get("/connectors/{connector_id}")
async def get_connector(connector_id: int):
    pass

@router.put("/connectors/{connector_id}")
async def update_connector(connector_id: int, connector: ConnectorUpdate):
    pass

@router.delete("/connectors/{connector_id}")
async def delete_connector(connector_id: int):
    pass

@router.get("/connectors/available")
async def list_available_connectors():
    pass
