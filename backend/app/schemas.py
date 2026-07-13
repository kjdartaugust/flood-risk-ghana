"""Pydantic request/response models (API contract → OpenAPI)."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, field_validator, model_validator


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


class PushSubscription(BaseModel):
    """What `PushManager.subscribe()` hands back in the browser, passed through.

    We never mint this — the browser does, against its own push service — so
    the shape is theirs, not ours.
    """

    endpoint: str = Field(min_length=1)
    keys: dict[str, str]

    @field_validator("keys")
    @classmethod
    def _has_encryption_keys(cls, v: dict[str, str]) -> dict[str, str]:
        missing = {"p256dh", "auth"} - v.keys()
        if missing:
            raise ValueError(f"push keys missing: {', '.join(sorted(missing))}")
        return v


class SubscribeRequest(BaseModel):
    route_id: str
    channel: str = Field(default="web", pattern="^(web|sms|push)$")
    contact: str | None = None
    push_subscription: PushSubscription | None = None

    @model_validator(mode="after")
    def _push_needs_a_handle(self) -> SubscribeRequest:
        if self.channel == "push" and self.push_subscription is None:
            raise ValueError("channel 'push' requires a push_subscription")
        return self


class SubscribeResponse(BaseModel):
    id: str
    route_id: str
    channel: str
    created: bool
    # False when the server has no VAPID keys: the subscription is stored and
    # the alert will still be raised, but nothing will be pushed to the device.
    # The UI needs to know that so it doesn't promise a notification it can't
    # send.
    delivers: bool = True


class VapidKeyResponse(BaseModel):
    """The public half of the VAPID pair — the browser needs it to subscribe."""

    public_key: str


class FloodReportRequest(BaseModel):
    lat: float = Field(ge=4.5, le=11.2)
    lng: float = Field(ge=-3.3, le=1.3)
    severity: int = Field(default=2, ge=1, le=5)
    area_name: str | None = Field(default=None, max_length=160)
    note: str | None = Field(default=None, max_length=500)


class FloodReportResponse(BaseModel):
    id: str
    lat: float
    lng: float
    severity: int
    area_name: str
    occurred_on: dt.date
    created: bool = True


class FloodReportFeature(BaseModel):
    id: str
    lat: float
    lng: float
    severity: int
    area_name: str
    occurred_on: dt.date
    source: str
