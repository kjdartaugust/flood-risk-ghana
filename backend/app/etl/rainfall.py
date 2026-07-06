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


async def _fetch_openmeteo(client: httpx.AsyncClient, lat: float, lng: float) -> dict:
    r = await client.get(
        f"{settings.openmeteo_base}/forecast",
        params={
            "latitude": lat, "longitude": lng,
            "hourly": "precipitation",
            "past_days": 1, "forecast_days": 1, "timezone": "UTC",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


async def refresh_rainfall(db: AsyncSession, limit_tiles: int = 400) -> int:
    """Refresh rainfall for the most-populated tiles. Returns rows upserted."""
    tiles = (await db.execute(
        select(RiskTile).order_by(RiskTile.risk_score.desc()).limit(limit_tiles)
    )).scalars().all()
    if not tiles:
        log.warning("no risk tiles yet; run ETL tiles/seed first")
        return 0

    now = dt.datetime.now(dt.UTC)
    rows = 0
    async with httpx.AsyncClient() as client:
        for tile in tiles:
            try:
                data = await _fetch_openmeteo(client, tile.centroid_lat,
                                              tile.centroid_lng)
            except Exception as e:  # noqa: BLE001
                log.warning("rain fetch failed %s: %s", tile.h3_index, e)
                continue
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            precip = hourly.get("precipitation", [])
            for ts, mm in zip(times, precip, strict=False):
                observed_at = dt.datetime.fromisoformat(ts).replace(
                    tzinfo=dt.UTC)
                horizon = "forecast" if observed_at > now else "obs"
                stmt = insert(RainfallObs).values(
                    h3_index=tile.h3_index, observed_at=observed_at,
                    horizon=horizon, precip_mm=float(mm or 0.0),
                    source="open-meteo",
                ).on_conflict_do_update(
                    constraint="uq_rain_cell_ts",
                    set_={"precip_mm": float(mm or 0.0)},
                )
                await db.execute(stmt)
                rows += 1
            # keep the tile's recent-rainfall feature warm
            recent = sum(float(m or 0) for t, m in zip(times, precip, strict=False)
                         if dt.datetime.fromisoformat(t).replace(
                             tzinfo=dt.UTC) <= now)
            tile.rainfall_recent_mm = round(recent, 2)
        await db.commit()
    log.info("rainfall refresh: %d rows across %d tiles", rows, len(tiles))
    return rows
