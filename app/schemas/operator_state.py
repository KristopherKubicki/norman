from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class OperatorSourceSnapshot(BaseModel):
    kind: str
    source: str
    label: str
    status: str
    fresh: bool
    observed_at: Optional[datetime] = None
    age_seconds: Optional[int] = None
    device: Optional[str] = None
    attribute: Optional[str] = None
    value: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class OperatorStateOut(BaseModel):
    state: str
    summary: str
    confidence: str
    observed_at: Optional[datetime] = None
    home_present: Optional[bool] = None
    office_present: Optional[bool] = None
    workstation_active: Optional[bool] = None
    screen_awake: Optional[bool] = None
    display_idle_seconds: Optional[int] = None
    sources: List[OperatorSourceSnapshot] = Field(default_factory=list)
