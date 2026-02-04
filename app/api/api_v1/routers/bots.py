from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.schemas import BotCreate, BotUpdate, Bot
from app.api.deps import get_db, get_current_user
from app.crud import create_bot, update_bot, delete_bot, get_bot_by_id


router = APIRouter()


# endpoints and handlers go here
@router.post("/bots/", response_model=Bot)
async def api_create_bot(
    bot: BotCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Bot:
    """Create a new bot.

    Args:
        bot: Data required to create the bot.
        db: Database session dependency.

    Returns:
        The persisted bot instance.

    Raises:
        HTTPException: If the bot could not be created.
    """

    bot = create_bot(db=db, bot_create=bot, user_id=current_user.id)
    if bot is None:
        raise HTTPException(status_code=400, detail="Failed to create bot")
    return bot


@router.get("/bots/", response_model=List[Bot])
async def api_get_bots(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> List[Bot]:
    """Return all bots.

    Args:
        db: Database session dependency.

    Returns:
        A list of bots from the database.
    """

    return db.query(models.Bot).filter(models.Bot.user_id == current_user.id).all()


@router.get("/bots/{bot_id}", response_model=Bot)
async def api_get_bot(
    bot_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Bot:
    """Fetch a bot by ID.

    Args:
        bot_id: Identifier of the bot to fetch.
        db: Database session dependency.

    Returns:
        The requested bot instance.

    Raises:
        HTTPException: If the bot does not exist.
    """

    bot = get_bot_by_id(db=db, bot_id=bot_id)
    if bot is None or bot.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot


@router.put("/bots/{bot_id}", response_model=Bot)
async def api_update_bot(
    bot_id: int,
    bot: BotUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Bot:
    """Update an existing bot.

    Args:
        bot_id: Identifier of the bot to update.
        bot: New bot values.
        db: Database session dependency.

    Returns:
        The updated bot instance.

    Raises:
        HTTPException: If the bot does not exist.
    """

    existing = get_bot_by_id(db=db, bot_id=bot_id)
    if existing is None or existing.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Bot not found")
    updated = update_bot(db=db, bot_id=bot_id, bot_data=bot)
    if updated is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return updated


@router.delete("/bots/{bot_id}", response_model=Bot)
async def api_delete_bot(
    bot_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Bot:
    """Delete a bot by ID.

    Args:
        bot_id: Identifier of the bot to delete.
        db: Database session dependency.

    Returns:
        The deleted bot instance.

    Raises:
        HTTPException: If the bot does not exist.
    """

    existing = get_bot_by_id(db=db, bot_id=bot_id)
    if existing is None or existing.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Bot not found")
    bot = delete_bot(db=db, bot_id=bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot
