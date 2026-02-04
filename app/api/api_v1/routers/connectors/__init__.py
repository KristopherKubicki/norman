from fastapi import APIRouter
from .telegram import router as telegram_router
from .slack import router as slack_router
from .teams import router as teams_router
from .google_chat import router as google_chat_router
from .discord import router as discord_router
from .webhook import router as webhook_router
from .whatsapp import router as whatsapp_router
from .jira import router as jira_router
from .facebook import router as facebook_router
from .instagram import router as instagram_router
from .pinterest import router as pinterest_router
from .linkedin import router as linkedin_router
from .reddit import router as reddit_router
from .twitter import router as twitter_router
from .mcp import router as mcp_router
from .aws_eventbridge import router as aws_eventbridge_router
from .azure_eventgrid import router as azure_eventgrid_router

router = APIRouter()

router.include_router(telegram_router, prefix="/telegram", tags=["Telegram"])
router.include_router(slack_router, prefix="/slack", tags=["Slack"])
router.include_router(teams_router, prefix="/microsoft_teams", tags=["Microsoft Teams"])
router.include_router(google_chat_router, prefix="/google_chat", tags=["Google Chat"])
router.include_router(discord_router, prefix="/discord", tags=["Discord"])
router.include_router(webhook_router, prefix="/webhook", tags=["Webhook"])
router.include_router(whatsapp_router, prefix="/whatsapp", tags=["WhatsApp"])
router.include_router(jira_router, prefix="/jira", tags=["Jira"])
router.include_router(facebook_router, prefix="/facebook", tags=["Facebook Messenger"])
router.include_router(instagram_router, prefix="/instagram", tags=["Instagram"])
router.include_router(pinterest_router, prefix="/pinterest", tags=["Pinterest"])
router.include_router(linkedin_router, prefix="/linkedin", tags=["LinkedIn"])
router.include_router(reddit_router, prefix="/reddit", tags=["Reddit"])
router.include_router(twitter_router, prefix="/twitter", tags=["Twitter/X"])
router.include_router(mcp_router, prefix="/mcp", tags=["MCP"])
router.include_router(
    aws_eventbridge_router,
    prefix="/aws_eventbridge",
    tags=["AWS EventBridge"],
)
router.include_router(
    azure_eventgrid_router,
    prefix="/azure_eventgrid",
    tags=["Azure Event Grid"],
)
