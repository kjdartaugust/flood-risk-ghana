"""Pydantic request/response models (API contract → OpenAPI)."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    db: bool
    redis: bool


class RiskComponents(BaseModel):
    elevation: float = Field(ge=0, le=1)
    slope: float = Field(ge=0, le=1)
    drainage: float = Field(ge=0, le=1)
    imperviousness: float = Field(ge=0, le=1)
    historical_flood_density: float = Field(ge=0, le=1)
    recent_rainfall_mm: float = Field(ge=0)


class RiskPointResponse(BaseModel):
    lat: float
    lng: float
    h3_index: str
    resolution: int
    risk_score: float = Field(ge=0, le=100, description="0=low, 100=extreme")
    band: str = Field(description="low | moderate | high | severe | extreme")
    confidence: float = Field(ge=0, le=1)
    components: RiskComponents
    model_version: str
    nearest_hotspot: str | None = None
    advice: str


class RiskTileFeature(BaseModel):
    h3_index: str
    risk_score: float
    band: str
    confidence: float
    centroid: tuple[float, float]


class RiskTilesResponse(BaseModel):
    type: str = "FeatureCollection"
    resolution: int
    count: int
    features: list[dict]  # GeoJSON features


class RouteSummary(BaseModel):
    id: str
    name: str
    from_stop: str | None
    to_stop: str | None
    baseline_risk: float
    current_status: str  # clear | watch | warning | severe
    active_alert: bool


class RouteForecastPoint(BaseModel):
    at: dt.datetime
    precip_mm: float
    risk_score: float
    status: str


class RouteForecastResponse(BaseModel):
    route_id: str
    name: str
    generated_at: dt.datetime
    horizon_hours: int
    points: list[RouteForecastPoint]
    summary: str


class AlertResponse(BaseModel):
    id: str
    route_id: str
    route_name: str
    level: str
    message: str
    expected_precip_mm: float
    risk_score: float
    starts_at: dt.datetime
    expires_at: dt.datetime


class SubscribeRequest(BaseModel):
    route_id: str
    channel: str = Field(default="web", pattern="^(web|sms|push)$")
    contact: str | None = None


class SubscribeResponse(BaseModel):
    id: str
    route_id: str
    channel: str
    created: bool
