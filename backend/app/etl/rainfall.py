"""Rainfall ETL: pull observed + forecast precipitation into rainfall_obs.

Primary source is NASA GPM/IMERG (needs Earthdata token); we default to the
key-free Open-Meteo API which returns hourly precipitation for any lat/lng and
is a reliable proxy/fallback. Each risk tile takes the series of its nearest
sample point, so rainfall still aligns 1:1 with the H3 scoring grid.

Open-Meteo's free API limits each IP per day, and Render's free tier shares one
outbound IP among many apps, which use the allowance up early in the day. So in
production the scheduler fetches the rain (see `openmeteo_url`) and hands it
over; we only fetch it ourselves when nobody did.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
from collections.abc import Sequence
from urllib.parse import urlencode

import httpx
from sqlalchemy import bindparam, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import RainfallObs, RiskTile, TrotroRoute

log = logging.getLogger("etl.rainfall")

Point = tuple[float, float]

# Open-Meteo takes comma-separated coordinates and returns one result object per
# point, so a refresh is one HTTP call per BATCH points.
BATCH = 100

# Open-Meteo's models resolve rain at ~10 km here: 100 Accra tiles came back as
# only 8 distinct series. So sample one point per ~5 km grid cell rather than
# one per 500 m tile: 26 points for the 400 tiles, the same rain, and a
# fifteenth of the per-IP allowance.
SAMPLE_DEG = 0.05

# A route as (id, [(lng, lat), ...]).
Line = tuple[str, list[tuple[float, float]]]


def _snap(v: float) -> float:
    return round(round(v / SAMPLE_DEG) * SAMPLE_DEG, 4)


def route_cells(coords: Sequence[tuple[float, float]]) -> set[Point]:
    """The grid cells a line passes through, as sample points. Steps a quarter
    cell at a time, so a long straight stretch can't skip one."""
    cells = {(_snap(lat), _snap(lng)) for lng, lat in coords[:1]}
    for (x1, y1), (x2, y2) in zip(coords, coords[1:], strict=False):
        steps = max(1, math.ceil(max(abs(x2 - x1), abs(y2 - y1)) / (SAMPLE_DEG / 4)))
        cells |= {(_snap(y1 + (y2 - y1) * k / steps), _snap(x1 + (x2 - x1) * k / steps))
                  for k in range(1, steps + 1)}
    return cells


def sample_points(tiles: Sequence[RiskTile], lines: Sequence[Line] = ()) -> list[Point]:
    """One point per SAMPLE_DEG grid cell that holds a tile or that a route
    passes through, in a stable order. Routes reach well past the risk grid:
    out to Kasoa, Medie and Tema."""
    cells = {(_snap(t.centroid_lat), _snap(t.centroid_lng)) for t in tiles}
    for _, coords in lines:
        cells |= route_cells(coords)
    return sorted(cells)


def _params(points: Sequence[Point]) -> dict:
    return {
        "latitude": ",".join(f"{lat:.4f}" for lat, _ in points),
        "longitude": ",".join(f"{lng:.4f}" for _, lng in points),
        "hourly": "precipitation",
        # Two days, not one: days are UTC days, so with one a 21:00 run would
        # see only 2 hours ahead against a 12-hour route forecast.
        "past_days": 1, "forecast_days": 2, "timezone": "UTC",
    }


def openmeteo_url(points: Sequence[Point]) -> str:
    """The request we would make, for a caller fetching on our behalf."""
    return f"{settings.openmeteo_base}/forecast?{urlencode(_params(points))}"


async def _fetch_openmeteo(
    client: httpx.AsyncClient, points: Sequence[Point]
) -> list[dict]:
    """Hourly precipitation for a batch of (lat, lng), in order."""
    r = await client.get(f"{settings.openmeteo_base}/forecast",
                         params=_params(points), timeout=60)
    if r.is_error:
        # Open-Meteo says why in the body ({"reason": ...}). Keep that: the URL
        # in a plain raise_for_status() message is just a wall of coordinates.
        raise httpx.HTTPStatusError(f"Open-Meteo {r.status_code}: {r.text[:200]}",
                                    request=r.request, response=r)
    data = r.json()
    # A single-point request returns an object; a batch returns a list.
    return data if isinstance(data, list) else [data]


async def _fetch_all(points: Sequence[Point]) -> list[dict | None]:
    """Forecasts for `points`, in order; None where a batch failed. Raises if
    every batch failed: that's an outage, not a dry day, and the run should be
    recorded as failed rather than as one that just saved nothing."""
    out: list[dict | None] = []
    failures: list[str] = []
    async with httpx.AsyncClient() as client:
        for i in range(0, len(points), BATCH):
            chunk = points[i : i + BATCH]
            try:
                results = await _fetch_openmeteo(client, chunk)
                if len(results) != len(chunk):
                    raise ValueError(f"{len(results)} forecasts for {len(chunk)} points")
                out += results
            except Exception as e:  # noqa: BLE001
                log.warning("rain fetch failed for batch at %d: %s", i, e)
                failures.append(f"{type(e).__name__}: {e}")
                out += [None] * len(chunk)
    if failures and not any(out):
        raise RuntimeError(
            f"every rain fetch failed ({len(failures)} batches): {failures[0]}")
    return out


def _series(data: dict) -> list[tuple[dt.datetime, float]]:
    """Open-Meteo's hourly arrays as (UTC hour, mm) pairs."""
    hourly = data.get("hourly", {})
    return [
        (dt.datetime.fromisoformat(ts).replace(tzinfo=dt.UTC), float(mm or 0.0))
        for ts, mm in zip(hourly.get("time", []), hourly.get("precipitation", []),
                          strict=False)
    ]


def _nearest(points: Sequence[Point], lat: float, lng: float) -> int:
    return min(range(len(points)), key=lambda i: (
        (points[i][0] - lat) ** 2 + (points[i][1] - lng) ** 2))


def _rows(tile: RiskTile, data: dict, now: dt.datetime) -> list[dict]:
    """One tile's hourly series as rainfall_obs rows; also refreshes the tile's
    recent-rainfall feature."""
    series = _series(data)
    # keep the tile's recent-rainfall feature warm
    tile.rainfall_recent_mm = round(sum(mm for at, mm in series if at <= now), 2)
    return [
        {"h3_index": tile.h3_index, "observed_at": at,
         "horizon": "forecast" if at > now else "obs",
         "precip_mm": mm, "source": "open-meteo"}
        for at, mm in series
    ]


async def top_tiles(db: AsyncSession, limit: int = 400) -> Sequence[RiskTile]:
    """The tiles a refresh covers: the highest-risk ones."""
    return (await db.execute(
        select(RiskTile).order_by(RiskTile.risk_score.desc()).limit(limit)
    )).scalars().all()


async def route_lines(db: AsyncSession) -> list[Line]:
    """Every route's line, as (id, [(lng, lat), ...])."""
    rows = (await db.execute(
        select(TrotroRoute.id, func.ST_AsGeoJSON(TrotroRoute.geom, 5))
    )).all()
    return [(rid, [tuple(c) for c in json.loads(geom)["coordinates"]])
            for rid, geom in rows]


async def plan_points(db: AsyncSession) -> list[Point]:
    """Where a refresh samples rain: the top tiles' cells and every route's."""
    return sample_points(await top_tiles(db), await route_lines(db))


async def refresh_route_rain(
    db: AsyncSession,
    lines: Sequence[Line],
    points: Sequence[Point],
    forecasts: Sequence[dict | None],
    now: dt.datetime,
) -> int:
    """Store each route's coming hours of rain on the route: per hour, the most
    forecast for any cell it passes through. Returns the routes updated.

    One statement for all of them. A route whose cells all failed to fetch
    keeps its last forecast rather than being told it will be dry."""
    updates = []
    for rid, coords in lines:
        near = {_nearest(points, lat, lng) for lat, lng in route_cells(coords)}
        hours: dict[dt.datetime, float] = {}
        for i in near:
            for at, mm in _series(forecasts[i]) if forecasts[i] is not None else []:
                if at > now:
                    hours[at] = max(hours.get(at, 0.0), mm)
        if hours:
            updates.append({"rid": rid, "fc": [[at.isoformat(), round(mm, 2)]
                                               for at, mm in sorted(hours.items())]})
    if updates:
        routes = TrotroRoute.__table__
        await db.execute(
            update(routes).where(routes.c.id == bindparam("rid"))
            .values(forecast=bindparam("fc", type_=routes.c.forecast.type)),
            updates)
    return len(updates)


async def refresh_rainfall(
    db: AsyncSession,
    limit_tiles: int = 400,
    fetched: tuple[Sequence[Point], Sequence[dict | None]] | None = None,
) -> int:
    """Refresh rainfall for the highest-risk tiles and along every route.
    Returns tile rows upserted.

    `fetched` is (points, forecasts) that a caller already fetched, as
    `openmeteo_url` asked; without it, we fetch them ourselves.
    """
    tiles = await top_tiles(db, limit_tiles)
    if not tiles:
        log.warning("no risk tiles yet; run ETL tiles/seed first")
        return 0
    lines = await route_lines(db)
    if fetched is None:
        points = sample_points(tiles, lines)
        forecasts = await _fetch_all(points)
    else:
        points, forecasts = fetched

    now = dt.datetime.now(dt.UTC)
    rows: list[dict] = []
    for tile in tiles:
        nearest = _nearest(points, tile.centroid_lat, tile.centroid_lng)
        if forecasts[nearest] is not None:
            rows += _rows(tile, forecasts[nearest], now)

    # One statement for the whole refresh, never one per row. The database is
    # an ocean away (Render Frankfurt, Neon us-east-1): row by row, 400 tiles
    # would be tens of thousands of ~90 ms round trips, longer than Render keeps
    # an idle free instance up. Core table rather than the entity: a plain
    # executemany, no ORM bulk-insert machinery in the way.
    upsert = insert(RainfallObs.__table__)
    upsert = upsert.on_conflict_do_update(
        constraint="uq_rain_cell_ts",
        set_={"precip_mm": upsert.excluded.precip_mm},
    )
    if rows:
        await db.execute(upsert, rows)
    routes = await refresh_route_rain(db, lines, points, forecasts, now)
    await db.commit()
    log.info("rainfall refresh: %d rows across %d tiles and %d routes from %d points",
             len(rows), len(tiles), routes, len(points))
    return len(rows)
