from fastapi import APIRouter

router = APIRouter()

@router.post("/actions/")
async def create_action(action: ActionCreate):
    pass

@router.get("/actions/{action_id}")
async def get_action(action_id: int):
    pass

@router.put("/actions/{action_id}")
async def update_action(action_id: int, action: ActionUpdate):
    pass

@router.delete("/actions/{action_id}")
async def delete_action(action_id: int):
    pass
