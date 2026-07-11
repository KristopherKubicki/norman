from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConnectorBundleConnector(BaseModel):
    name: str
    connector_type: str
    config: Dict[str, Any] = Field(default_factory=dict)


class ConnectorBundleRoutingRule(BaseModel):
    name: str
    connector_name: Optional[str] = None
    connector_type: Optional[str] = None
    destination_connector_name: Optional[str] = None
    destination_connector_type: Optional[str] = None
    bot_id: Optional[int] = None
    bot_name: Optional[str] = None
    bot_session_id: Optional[str] = None
    match_type: str = "all"
    match_value: Optional[str] = None
    priority: int = 0
    is_active: bool = True


class ConnectorBundlePayload(BaseModel):
    version: int = 1
    exported_at: Optional[datetime] = None
    connectors: List[ConnectorBundleConnector] = Field(default_factory=list)
    routing_rules: List[ConnectorBundleRoutingRule] = Field(default_factory=list)


class ConnectorBundleImportResult(BaseModel):
    version: int = 1
    connectors_created: int = 0
    connectors_updated: int = 0
    routing_rules_created: int = 0
    routing_rules_updated: int = 0
    warnings: List[str] = Field(default_factory=list)
