from fastapi import APIRouter
from .telegram import router as telegram_router
from .slack import router as slack_router
from .teams import router as teams_router
from .google_chat import router as google_chat_router
from .discord import router as discord_router
from .webhook import router as webhook_router
from .mcp import router as mcp_router

router = APIRouter()

router.include_router(telegram_router, prefix="/telegram", tags=["Telegram"])
router.include_router(slack_router, prefix="/slack", tags=["Slack"])
router.include_router(teams_router, prefix="/microsoft_teams", tags=["Microsoft Teams"])
router.include_router(google_chat_router, prefix="/google_chat", tags=["Google Chat"])
router.include_router(discord_router, prefix="/discord", tags=["Discord"])
router.include_router(webhook_router, prefix="/webhook", tags=["Webhook"])
router.include_router(mcp_router, prefix="/mcp", tags=["MCP"])

