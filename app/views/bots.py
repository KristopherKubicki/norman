# app/views/bots.py
from fastapi import APIRouter, Request
from app.models import Bot

router = APIRouter()

@router.get("/")
async def get_bots(request: Request):
    bots = await Bot.all()
    return templates.TemplateResponse("bots/list.html", {"request": request, "bots": bots})

@router.post("/create")
async def create_bot(request: Request, bot: BotCreate):
    new_bot = await Bot.create(bot)
    return RedirectResponse(url="/bots", status_code=303)
