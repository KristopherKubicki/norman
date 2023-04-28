from fastapi import APIRouter

router = APIRouter()

@router.post("/channel_filters/")
async def create_channel_filter(channel_filter: ChannelFilterCreate):
    pass

@router.get("/channel_filters/{channel_filter_id}")
async def get_channel_filter(channel_filter_id: int):
    pass

@router.put("/channel_filters/{channel_filter_id}")
async def update_channel_filter(channel_filter_id: int, channel_filter: ChannelFilterUpdate):
    pass

@router.delete("/channel_filters/{channel_filter_id}")
async def delete_channel_filter(channel_filter_id: int):
    pass
