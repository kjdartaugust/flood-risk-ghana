"""Rainfall ETL: pull observed + forecast precipitation into rainfall_obs.

Primary source is NASA GPM/IMERG (needs Earthdata token); we default to the
key-free Open-Meteo API which returns hourly precipitation for any lat/lng and
is a reliable proxy/fallback. We sample at the centroid of each risk tile so
rainfall aligns 1:1 with the H3 scoring grid.
"""
from __future__ import annotations

import datetime as dt
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import RainfallObs, RiskTile

log = logging.getLogger("etl.rainfall")


# Open-Meteo takes comma-separated coordinates and returns one result object per
# point. Batching turns a 400-tile refresh from 400 sequential HTTP calls into 4
# — which is the difference between a scheduled job that survives on a free
# instance and one that doesn't.
BATCH = 100


async def _fetch_openmeteo(
    client: httpx.AsyncClient, points: list[tuple[float, float]]
) -> list[dict]:
    """Hourly precipitation for a batch of (lat, lng), in order."""
    r = await client.get(
        f"{settings.openmeteo_base}/forecast",
        params={
            "latitude": ",".join(f"{lat:.5f}" for lat, _ in points),
            "longitude": ",".join(f"{lng:.5f}" for _, lng in points),
            "hourly": "precipitation",
            "past_days": 1, "forecast_days": 1, "timezone": "UTC",
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    # A single-point request returns an object; a batch returns a list.
    return data if isinstance(data, list) else [data]


async def _apply(db: AsyncSession, tile: RiskTile, data: dict,
                 now: dt.datetime) -> int:
    """Upsert one tile's hourly series and refresh its recent-rainfall feature."""
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    precip = hourly.get("precipitation", [])
    rows = 0
    for ts, mm in zip(times, precip, strict=False):
        observed_at = dt.datetime.fromisoformat(ts).replace(tzinfo=dt.UTC)
        stmt = insert(RainfallObs).values(
            h3_index=tile.h3_index, observed_at=observed_at,
            horizon="forecast" if observed_at > now else "obs",
            precip_mm=float(mm or 0.0), source="open-meteo",
        ).on_conflict_do_update(
            constraint="uq_rain_cell_ts",
            set_={"precip_mm": float(mm or 0.0)},
        )
        await db.execute(stmt)
        rows += 1
    # keep the tile's recent-rainfall feature warm
    tile.rainfall_recent_mm = round(sum(
        float(m or 0) for t, m in zip(times, precip, strict=False)
        if dt.datetime.fromisoformat(t).replace(tzinfo=dt.UTC) <= now
    ), 2)
    return rows


async def refresh_rainfall(db: AsyncSession, limit_tiles: int = 400) -> int:
    """Refresh rainfall for the highest-risk tiles. Returns rows upserted."""
    tiles = (await db.execute(
        select(RiskTile).order_by(RiskTile.risk_score.desc()).limit(limit_tiles)
    )).scalars().all()
    if not tiles:
        log.warning("no risk tiles yet; run ETL tiles/seed first")
        return 0

    now = dt.datetime.now(dt.UTC)
    rows = 0
    async with httpx.AsyncClient() as client:
        for i in range(0, len(tiles), BATCH):
            chunk = tiles[i : i + BATCH]
            try:
                results = await _fetch_openmeteo(
                    client, [(t.centroid_lat, t.centroid_lng) for t in chunk]
                )
            except Exception as e:  # noqa: BLE001
                log.warning("rain fetch failed for batch at %d: %s", i, e)
                continue
            for tile, data in zip(chunk, results, strict=False):
                rows += await _apply(db, tile, data, now)
        await db.commit()
    log.info("rainfall refresh: %d rows across %d tiles", rows, len(tiles))
    return rows
