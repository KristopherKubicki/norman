from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.schemas import BotCreate, BotUpdate, Bot
from app.api.deps import get_db
from app.crud import create_bot, update_bot, delete_bot, get_bot_by_id


router = APIRouter()

# endpoints and handlers go here
@router.post("/bots/", response_model=Bot)
async def api_create_bot(bot: BotCreate, db: Session = Depends(get_db)) -> Bot:
    # Logic to create a new bot
    bot = create_bot(db=db, bot_create=bot)
    if bot is None:
        raise HTTPException(status_code=400, detail="Failed to create bot")
    return bot

@router.get("/bots/", response_model=List[Bot])
async def api_get_bots(db: Session = Depends(get_db)) -> List[Bot]:
    """Return all bots."""
    return db.query(models.Bot).all()

@router.get("/bots/{bot_id}", response_model=Bot)
async def api_get_bot(bot_id: int, db: Session = Depends(get_db)) -> Bot:
    """Return a bot by ID."""
    bot = get_bot_by_id(db=db, bot_id=bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot

@router.put("/bots/{bot_id}", response_model=Bot)
async def api_update_bot(
    bot_id: int, bot: BotUpdate, db: Session = Depends(get_db)
) -> Bot:
    """Update an existing bot."""
    updated = update_bot(db=db, bot_id=bot_id, bot_data=bot)
    if updated is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return updated

@router.delete("/bots/{bot_id}", response_model=Bot)
async def api_delete_bot(bot_id: int, db: Session = Depends(get_db)) -> Bot:
    bot = delete_bot(db=db, bot_id=bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot



