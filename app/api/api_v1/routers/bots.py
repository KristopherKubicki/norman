from fastapi import APIRouter

router = APIRouter()

@router.post("/bots/")
async def create_bot(bot: BotCreate):
    pass

@router.get("/bots/{bot_id}")
async def get_bot(bot_id: int):
    pass

@router.put("/bots/{bot_id}")
async def update_bot(bot_id: int, bot: BotUpdate):
    pass

@router.delete("/bots/{bot_id}")
async def delete_bot(bot_id: int):
    pass
