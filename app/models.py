from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

Risk = Literal["AUTO","LOW","MEDIUM","HIGH","CRITICAL"]

class EventCreate(BaseModel):
    project_id: int = 1
    description: str = Field(min_length=4, max_length=8000)
    event_type: str = "observation"
    reported_risk: Risk = "AUTO"
    asset_ref: str | None = None
    lat: float | None = None
    lon: float | None = None
    media_sha: str | None = None

class ApprovalRequest(BaseModel):
    actor: str = Field(default="project_manager", min_length=2, max_length=120)

class DispatchRequest(BaseModel):
    actor: str = Field(default="site_manager", min_length=2, max_length=120)

class ReinspectionRequest(BaseModel):
    observation: str = Field(min_length=4, max_length=4000)
    resolved: bool
    media_sha: str | None = None
    actor: str = "inspector"

class GoldenDemoRequest(BaseModel):
    description: str = "Worker observed near an unprotected edge at Pier P47. Work is planned to continue this afternoon."
    asset_ref: str = "PIER-P47"
