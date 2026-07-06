"""Community flood reports — the crowdsourced write path.

A commuter/resident reports flooding at a spot. We persist it as a FloodEvent
(source='community') so it (a) shows on the map and (b) feeds back into the
historical-flood-density feature, nudging nearby risk scores up. This is the
end-to-end write action used to verify frontend → backend → DB persistence.
"""
from __future__ import annotations

import datetime as dt

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache_del
from app.config import settings
from app.models import FloodEvent
from app.schemas import FloodReportFeature, FloodReportRequest, FloodReportResponse
from app.services.geo import latlng_to_cell, nearest_hotspot


async def create_report(db: AsyncSession, req: FloodReportRequest) -> FloodReportResponse:
    area = req.area_name
    if not area:
        name, dist = nearest_hotspot(req.lat, req.lng)
        area = name if dist < 5 else "Community report"
    event = FloodEvent(
        occurred_on=dt.date.today(),
        area_name=area,
        severity=req.severity,
        source="community",
        notes=req.note,
        geom=from_shape(Point(req.lng, req.lat), srid=4326),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    # Bust the cached risk score for this cell so the report is reflected at once.
    cell = latlng_to_cell(req.lat, req.lng, settings.h3_resolution)
    await cache_del(f"risk:point:{cell}")
    return FloodReportResponse(
        id=event.id, lat=req.lat, lng=req.lng, severity=event.severity,
        area_name=area, occurred_on=event.occurred_on, created=True,
    )


async def recent_reports(db: AsyncSession, limit: int = 100) -> list[FloodReportFeature]:
    stmt = text(
        """
        SELECT id, ST_Y(geom) AS lat, ST_X(geom) AS lng, severity,
               area_name, occurred_on, source
        FROM flood_events
        ORDER BY created_at DESC
        LIMIT :lim
        """
    )
    rows = (await db.execute(stmt, {"lim": limit})).all()
    return [FloodReportFeature(
        id=r[0], lat=float(r[1]), lng=float(r[2]), severity=r[3],
        area_name=r[4], occurred_on=r[5], source=r[6],
    ) for r in rows]


async def report_count(db: AsyncSession) -> int:
    return (await db.execute(
        select(text("count(*)")).select_from(text("flood_events"))
    )).scalar() or 0
