from pydantic import BaseModel

class SlackCredentialUpdate(BaseModel):
    token: str
    channel_id: str
