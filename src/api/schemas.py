"""Pydantic v2 models for raw alerts.in.ua API response shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RawAlert(BaseModel):
    id: int
    region_id: int
    region_name: str
    region_type: Literal["oblast", "raion", "city", "district"] = "oblast"
    alert_type: str = "air_raid"
    started_at: datetime
    finished_at: datetime | None = None
    updated_at: datetime | None = None


class ActiveAlertRegion(BaseModel):
    region_id: int
    region_name: str
    alert_type: str


class AlertsActiveResponse(BaseModel):
    alerts: list[ActiveAlertRegion] = Field(default_factory=list)


class AlertsHistoryResponse(BaseModel):
    alerts: list[RawAlert] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    per_page: int = 100
