"""Trotro route flood logic: combine the static risk layer with rainfall forecast.

A route's live status = f(baseline_risk of the worst tile it crosses, forecast
rainfall along it). Heavy forecast rain on an already-risky corridor is what
turns a 'watch' into a 'severe' warning.

There are hundreds of routes, so nothing here queries per route: each rain
refresh stores a route's coming hours on the route itself (see
`app.etl.rainfall.refresh_route_rain`), and judging them all is one query.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.models import RouteAlert, TrotroRoute
from app.schemas import RouteForecastPoint, RouteForecastResponse, RouteHour, RouteSummary

_SUMMARY = {
    "clear": "No flooding expected on this route in the forecast window.",
    "watch": "Minor flooding possible — allow extra travel time.",
    "warning": "Flooding likely at low points — expect delays / reroutes.",
    "severe": "Severe flooding expected — avoid this route during the peak.",
}
_ORDER = ["clear", "watch", "warning", "severe"]


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


def coming_hours(route: TrotroRoute, horizon: int = 12,
                 now: dt.datetime | None = None) -> list[tuple[dt.datetime, float]]:
    """The route's forecast rain, from the next hour on."""
    now = now or dt.datetime.now(dt.UTC)
    hours = ((dt.datetime.fromisoformat(at), float(mm))
             for at, mm in route.forecast or [])
    return [(at, mm) for at, mm in hours if at > now][:horizon]


def forecast_for(route: TrotroRoute, horizon: int = 12) -> RouteForecastResponse:
    points = []
    worst = "clear"
    for at, precip in coming_hours(route, horizon):
        # rainfall raises effective risk on this corridor
        eff_risk = min(100.0, route.baseline_risk + precip * 1.2)
        st = _status(route.baseline_risk, precip)
        if _ORDER.index(st) > _ORDER.index(worst):
            worst = st
        points.append(RouteForecastPoint(
            at=at, precip_mm=round(precip, 1),
            risk_score=round(eff_risk, 1), status=st))
    return RouteForecastResponse(
        route_id=route.id, name=route.name,
        generated_at=dt.datetime.now(dt.UTC),
        horizon_hours=horizon, points=points, summary=_SUMMARY[worst],
    )


# What judging a route needs; the line itself stays in the database.
JUDGE = load_only(TrotroRoute.name, TrotroRoute.from_stop, TrotroRoute.to_stop,
                  TrotroRoute.baseline_risk, TrotroRoute.forecast)


async def list_routes(db: AsyncSession) -> list[RouteSummary]:
    routes = (await db.execute(
        select(TrotroRoute).options(JUDGE).order_by(TrotroRoute.name)
    )).scalars().all()
    alerting = set((await db.execute(
        select(RouteAlert.route_id).where(RouteAlert.active).distinct()
    )).scalars().all())
    out: list[RouteSummary] = []
    for r in routes:
        hours = coming_hours(r)
        wettest = max((p for _, p in hours), default=0.0)
        out.append(RouteSummary(
            id=r.id, name=r.name, from_stop=r.from_stop, to_stop=r.to_stop,
            baseline_risk=r.baseline_risk,
            current_status=_status(r.baseline_risk, wettest),
            active_alert=r.id in alerting,
            hours=[RouteHour(at=at, precip_mm=round(p, 1),
                             status=_status(r.baseline_risk, p)) for at, p in hours],
        ))
    return out


async def route_forecast(db: AsyncSession, route_id: str,
                         horizon_hours: int = 12) -> RouteForecastResponse:
    route = await db.get(TrotroRoute, route_id, options=[JUDGE])
    if route is None:
        raise ValueError("route not found")
    return forecast_for(route, horizon_hours)


# The lines only change when a deploy brings a new route bundle, so build the
# GeoJSON once in a while rather than per request: it's ~300 KB.
_LINES_TTL = 600.0
_lines: tuple[float, str, str] | None = None


async def route_lines(db: AsyncSession) -> tuple[str, str]:
    """Every route's line as a GeoJSON FeatureCollection, and its ETag."""
    global _lines
    if _lines and time.monotonic() - _lines[0] < _LINES_TTL:
        return _lines[1], _lines[2]
    rows = (await db.execute(
        select(TrotroRoute.id, TrotroRoute.name, func.ST_AsGeoJSON(TrotroRoute.geom, 5))
        .order_by(TrotroRoute.id)
    )).all()
    body = '{"type":"FeatureCollection","features":[' + ",".join(
        '{"type":"Feature","properties":'
        + json.dumps({"id": rid, "name": name}, ensure_ascii=False)
        + ',"geometry":' + geom + "}"
        for rid, name, geom in rows
    ) + "]}"
    etag = '"' + hashlib.sha256(body.encode()).hexdigest()[:20] + '"'
    _lines = (time.monotonic(), body, etag)
    return body, etag
