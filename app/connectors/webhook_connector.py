import httpx
from fastapi import HTTPException
from typing import Dict
from pydantic import BaseModel

class WebhookConnector:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def process_incoming(self, data: Dict[str, str]) -> str:
        response = await self.send_to_webhook(data)
        return response

    async def send_to_webhook(self, data: Dict[str, str]) -> str:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.webhook_url, json=data)
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=400, detail=f"Error sending message to webhook: {exc}")

class IncomingMessage(BaseModel):
    channel: str
    message: str
    user: str

async def process_webhook_message(message: IncomingMessage):
    webhook_connector = WebhookConnector("https://your-webhook-url.example.com/")
    response = await webhook_connector.process_incoming(message.dict())
    return response

