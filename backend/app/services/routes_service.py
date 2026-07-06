"""Trotro route flood logic: combine the static risk layer with rainfall forecast.

A route's live status = f(baseline_risk of the worst tile it crosses, forecast
rainfall over those tiles). Heavy forecast rain on an already-risky corridor is
what turns a 'watch' into a 'severe' warning.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TrotroRoute
from app.schemas import RouteForecastPoint, RouteForecastResponse, RouteSummary


def _status(risk: float, precip_mm: float) -> str:
    """Blend static risk (0..100) and forecast precip (mm) into a status."""
    if risk >= 60 and precip_mm >= 20:
        return "severe"
    if risk >= 45 and precip_mm >= 10:
        return "warning"
    if risk >= 30 and precip_mm >= 5:
        return "watch"
    if precip_mm >= 35:  # extreme rain floods even lower-risk roads
        return "warning"
    return "clear"


async def _route_forecast_precip(
    db: AsyncSession, route: TrotroRoute
) -> list[tuple[dt.datetime, float]]:
    """Max forecast precip per hour across the route's H3 cells."""
    stmt = text(
        """
        SELECT r.observed_at, MAX(r.precip_mm) AS mm
        FROM rainfall_obs r
        JOIN LATERAL (
          SELECT 1 FROM risk_tiles t
          WHERE ST_DWithin(
                  ST_SetSRID(
                    ST_MakePoint(t.centroid_lng, t.centroid_lat),4326)::geography,
                  (SELECT geom FROM trotro_routes WHERE id = :rid)::geography, 500)
            AND t.h3_index = r.h3_index
          LIMIT 1
        ) hit ON true
        WHERE r.horizon = 'forecast' AND r.observed_at > now()
        GROUP BY r.observed_at ORDER BY r.observed_at LIMIT 12
        """
    )
    rows = (await db.execute(stmt, {"rid": route.id})).all()
    return [(row[0], float(row[1] or 0.0)) for row in rows]


async def list_routes(db: AsyncSession) -> list[RouteSummary]:
    routes = (await db.execute(select(TrotroRoute))).scalars().all()
    out: list[RouteSummary] = []
    for r in routes:
        fc = await _route_forecast_precip(db, r)
        max_precip = max((p for _, p in fc), default=0.0)
        status = _status(r.baseline_risk, max_precip)
        active = (await db.execute(text(
            "SELECT count(*) FROM route_alerts WHERE route_id=:id AND active"),
            {"id": r.id})).scalar() or 0
        out.append(RouteSummary(
            id=r.id, name=r.name, from_stop=r.from_stop, to_stop=r.to_stop,
            baseline_risk=r.baseline_risk, current_status=status,
            active_alert=active > 0,
        ))
    return out


async def route_forecast(db: AsyncSession, route_id: str,
                         horizon_hours: int = 12) -> RouteForecastResponse:
    route = await db.get(TrotroRoute, route_id)
    if route is None:
        raise ValueError("route not found")
    fc = await _route_forecast_precip(db, route)
    points: list[RouteForecastPoint] = []
    worst = "clear"
    order = ["clear", "watch", "warning", "severe"]
    for at, precip in fc[:horizon_hours]:
        # rainfall raises effective risk on this corridor
        eff_risk = min(100.0, route.baseline_risk + precip * 1.2)
        st = _status(route.baseline_risk, precip)
        if order.index(st) > order.index(worst):
            worst = st
        points.append(RouteForecastPoint(
            at=at, precip_mm=round(precip, 1),
            risk_score=round(eff_risk, 1), status=st))
    summary = {
        "clear": "No flooding expected on this route in the forecast window.",
        "watch": "Minor flooding possible — allow extra travel time.",
        "warning": "Flooding likely at low points — expect delays / reroutes.",
        "severe": "Severe flooding expected — avoid this route during the peak.",
    }[worst]
    return RouteForecastResponse(
        route_id=route.id, name=route.name,
        generated_at=dt.datetime.now(dt.UTC),
        horizon_hours=horizon_hours, points=points, summary=summary,
    )
