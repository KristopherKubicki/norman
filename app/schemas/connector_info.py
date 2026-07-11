from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ConnectorOAuthInfo(BaseModel):
    """OAuth/SSO capabilities for a connector type."""

    providers: List[str]
    default_provider: Optional[str] = None
    token_field: str = "oauth_access_token"
    scopes_by_provider: Optional[dict] = None


class ConnectorInfo(BaseModel):
    """Metadata about an available connector."""

    id: str
    name: str
    status: str
    fields: List[str]
    defaults: Dict[str, Any] = Field(default_factory=dict)
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    last_message_sent: Optional[str] = None
    enabled: bool
    oauth: Optional[ConnectorOAuthInfo] = None

    class Config:
        orm_mode = True
