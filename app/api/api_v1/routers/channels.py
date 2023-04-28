from fastapi import APIRouter

router = APIRouter()

@router.post("/channels/")
async def create_channel(channel: ChannelCreate):
    pass

@router.get("/channels/{channel_id}")
async def get_channel(channel_id: int):
    pass

@router.put("/channels/{channel_id}")
async def update_channel(channel_id: int, channel: ChannelUpdate):
    pass

@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: int):
    pass
