from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class RoutingRuleBase(BaseModel):
    name: str
    connector_id: Optional[int] = None
    connector_type: Optional[str] = None
    destination_connector_id: Optional[int] = None
    bot_id: int
    match_type: str = "all"
    match_value: Optional[str] = None
    priority: int = 0
    is_active: bool = True


class RoutingRuleCreate(RoutingRuleBase):
    pass


class RoutingRuleUpdate(BaseModel):
    name: Optional[str] = None
    connector_id: Optional[int] = None
    connector_type: Optional[str] = None
    destination_connector_id: Optional[int] = None
    bot_id: Optional[int] = None
    match_type: Optional[str] = None
    match_value: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class RoutingRuleOut(RoutingRuleBase):
    id: int
    user_id: int

    class Config:
        orm_mode = True


class RoutingEventOut(BaseModel):
    id: int
    user_id: int
    connector_id: Optional[int]
    connector_type: Optional[str]
    destination_connector_id: Optional[int]
    destination_connector_type: Optional[str]
    bot_id: Optional[int]
    rule_id: Optional[int]
    message_text: Optional[str]
    status: str
    delivery_status: str
    error: Optional[str]
    delivery_error: Optional[str]
    created_at: Optional[datetime]

    class Config:
        orm_mode = True


class RoutingJobOut(BaseModel):
    id: int
    event_id: Optional[int]
    connector_id: Optional[int]
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: Optional[datetime]
    last_error: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    event_status: Optional[str] = None
    event_delivery_status: Optional[str] = None
    event_delivery_error: Optional[str] = None
    event_connector_id: Optional[int] = None
    event_connector_type: Optional[str] = None
    destination_connector_id: Optional[int] = None
    destination_connector_type: Optional[str] = None
    bot_id: Optional[int] = None
    rule_id: Optional[int] = None
    message_text: Optional[str] = None


class RoutingTraceConnector(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    connector_type: Optional[str] = None


class RoutingTraceBot(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    session_id: Optional[str] = None
    gpt_model: Optional[str] = None


class RoutingTraceRule(BaseModel):
    id: int
    name: str
    connector_id: Optional[int] = None
    connector_type: Optional[str] = None
    destination_connector_id: Optional[int] = None
    bot_id: int
    match_type: str
    match_value: Optional[str] = None
    priority: int
    is_active: bool = True


class RoutingTraceJob(BaseModel):
    id: int
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: Optional[datetime] = None
    last_error: Optional[str] = None


class RoutingTraceOut(BaseModel):
    event: RoutingEventOut
    source_connector: Optional[RoutingTraceConnector] = None
    destination_connector: Optional[RoutingTraceConnector] = None
    bot: Optional[RoutingTraceBot] = None
    rule: Optional[RoutingTraceRule] = None
    latest_job: Optional[RoutingTraceJob] = None
    decision: str
    explanation: list[str] = []


class RoutingSimulationRequest(BaseModel):
    connector_id: Optional[int] = None
    connector_type: Optional[str] = None
    message_text: str
    signal_class: Optional[str] = None
    passive_source: Optional[str] = None


class RoutingSimulationMatch(BaseModel):
    rule_id: int
    rule_name: str
    bot_id: int
    bot_name: Optional[str] = None
    priority: int
    match_type: str
    match_value: Optional[str] = None
    is_active: bool = True


class RoutingSimulationResponse(BaseModel):
    selected_rule_id: Optional[int] = None
    selected_bot_id: Optional[int] = None
    selected_bot_name: Optional[str] = None
    selected_destination_connector_id: Optional[int] = None
    decision: str
    matches: list[RoutingSimulationMatch] = []
