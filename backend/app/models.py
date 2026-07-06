"""SQLAlchemy ORM models.

Geospatial columns use GeoAlchemy2 (PostGIS). H3 hex tiles hold precomputed
risk so the map can serve thousands of cells fast. Auth users live in Supabase;
we only store a user_id reference for subscriptions.
"""
from __future__ import annotations

import datetime as dt
import uuid

from geoalchemy2 import Geometry
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class FloodEvent(Base):
    """Historical flood record (NADMO / Ghana Meteo / news-derived)."""

    __tablename__ = "flood_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    occurred_on: Mapped[dt.date] = mapped_column(nullable=False)
    area_name: Mapped[str] = mapped_column(String(160), index=True)
    severity: Mapped[int] = mapped_column(Integer, default=1)  # 1..5
    source: Mapped[str] = mapped_column(String(120), default="unknown")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_flood_events_geom", "geom", postgresql_using="gist"),)


class RainfallObs(Base):
    """Rainfall time-series sample tied to an H3 cell (GPM/IMERG or Open-Meteo)."""

    __tablename__ = "rainfall_obs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    h3_index: Mapped[str] = mapped_column(String(20), index=True)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    horizon: Mapped[str] = mapped_column(String(12), default="obs")  # obs | forecast
    precip_mm: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(60), default="open-meteo")

    __table_args__ = (
        UniqueConstraint("h3_index", "observed_at", "horizon", name="uq_rain_cell_ts"),
    )


class RiskTile(Base):
    """Precomputed flood-risk score for an H3 hex cell."""

    __tablename__ = "risk_tiles"

    h3_index: Mapped[str] = mapped_column(String(20), primary_key=True)
    resolution: Mapped[int] = mapped_column(Integer, index=True)
    centroid_lat: Mapped[float] = mapped_column(Float)
    centroid_lng: Mapped[float] = mapped_column(Float)
    # component features (0..1 normalised)
    elevation_score: Mapped[float] = mapped_column(Float, default=0.0)
    slope_score: Mapped[float] = mapped_column(Float, default=0.0)
    drainage_score: Mapped[float] = mapped_column(Float, default=0.0)
    imperviousness: Mapped[float] = mapped_column(Float, default=0.0)
    hist_flood_density: Mapped[float] = mapped_column(Float, default=0.0)
    rainfall_recent_mm: Mapped[float] = mapped_column(Float, default=0.0)
    # outputs
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0..100
    confidence: Mapped[float] = mapped_column(Float, default=0.5)  # 0..1
    model_version: Mapped[str] = mapped_column(String(40), default="weighted-v1")
    geom = mapped_column(Geometry("POLYGON", srid=4326), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_risk_tiles_geom", "geom", postgresql_using="gist"),)


class TrotroRoute(Base):
    """A trotro route (OSM-derived) with an ordered LineString geometry."""

    __tablename__ = "trotro_routes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    osm_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    from_stop: Mapped[str | None] = mapped_column(String(160), nullable=True)
    to_stop: Mapped[str | None] = mapped_column(String(160), nullable=True)
    geom = mapped_column(Geometry("LINESTRING", srid=4326), nullable=False)
    # cached: max risk tile the route passes through (0..100)
    baseline_risk: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    alerts: Mapped[list[RouteAlert]] = relationship(back_populates="route")

    __table_args__ = (
        Index("ix_trotro_routes_geom", "geom", postgresql_using="gist"),
    )


class RouteAlert(Base):
    """A flood alert raised for a route from combined risk + rainfall forecast."""

    __tablename__ = "route_alerts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    route_id: Mapped[str] = mapped_column(ForeignKey("trotro_routes.id"), index=True)
    level: Mapped[str] = mapped_column(String(12))  # watch | warning | severe
    message: Mapped[str] = mapped_column(Text)
    expected_precip_mm: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    route: Mapped[TrotroRoute] = relationship(back_populates="alerts")


class AlertSubscription(Base):
    """A commuter's subscription to route alerts (user_id from Supabase)."""

    __tablename__ = "alert_subscriptions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    route_id: Mapped[str] = mapped_column(ForeignKey("trotro_routes.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="web")  # web | sms | push
    contact: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "route_id", "channel", name="uq_sub_user_route"),
    )
