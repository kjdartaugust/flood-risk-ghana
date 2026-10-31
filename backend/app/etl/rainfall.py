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
import logging
from collections.abc import Sequence
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import RainfallObs, RiskTile

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


def sample_points(tiles: Sequence[RiskTile]) -> list[Point]:
    """One point per SAMPLE_DEG grid cell that holds a tile, in a stable order."""
    def snap(v: float) -> float:
        return round(round(v / SAMPLE_DEG) * SAMPLE_DEG, 4)

    return sorted({(snap(t.centroid_lat), snap(t.centroid_lng)) for t in tiles})


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


def _rows(tile: RiskTile, data: dict, now: dt.datetime) -> list[dict]:
    """One tile's hourly series as rainfall_obs rows; also refreshes the tile's
    recent-rainfall feature."""
    hourly = data.get("hourly", {})
    series = [
        (dt.datetime.fromisoformat(ts).replace(tzinfo=dt.UTC), float(mm or 0.0))
        for ts, mm in zip(hourly.get("time", []), hourly.get("precipitation", []),
                          strict=False)
    ]
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


async def refresh_rainfall(
    db: AsyncSession,
    limit_tiles: int = 400,
    fetched: tuple[Sequence[Point], Sequence[dict | None]] | None = None,
) -> int:
    """Refresh rainfall for the highest-risk tiles. Returns rows upserted.

    `fetched` is (points, forecasts) that a caller already fetched, as
    `openmeteo_url` asked; without it, we fetch them ourselves.
    """
    tiles = await top_tiles(db, limit_tiles)
    if not tiles:
        log.warning("no risk tiles yet; run ETL tiles/seed first")
        return 0
    if fetched is None:
        points = sample_points(tiles)
        forecasts = await _fetch_all(points)
    else:
        points, forecasts = fetched

    now = dt.datetime.now(dt.UTC)
    rows: list[dict] = []
    for tile in tiles:
        nearest = min(range(len(points)), key=lambda i: (
            (points[i][0] - tile.centroid_lat) ** 2
            + (points[i][1] - tile.centroid_lng) ** 2))
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
    await db.commit()
    log.info("rainfall refresh: %d rows across %d tiles from %d points",
             len(rows), len(tiles), len(points))
    return len(rows)
