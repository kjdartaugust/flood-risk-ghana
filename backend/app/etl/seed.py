"""One-shot seed: historical flood events, risk tiles, and trotro routes.

Run: python -m app.etl.seed
Idempotent — safe to re-run. Called by the backend entrypoint on first boot.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.etl.osm_routes import ingest_routes
from app.etl.terrain import build_tiles
from app.models import FloodEvent, RiskTile, TrotroRoute
from app.services.geo import ACCRA_HOTSPOTS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("seed")

# Historical flood events (area, date, severity 1..5). Compiled from widely
# reported Accra flooding at known hotspots (e.g. the June 3 2015 disaster).
HISTORICAL = [
    ("Kaneshie", "2015-06-03", 5), ("Circle", "2015-06-03", 5),
    ("Adabraka", "2015-06-03", 4), ("Alajo", "2016-06-10", 4),
    ("Kaneshie", "2018-06-18", 3), ("Circle", "2019-06-27", 4),
    ("Odawna", "2020-10-08", 3), ("Avenor", "2021-05-15", 4),
    ("Alajo", "2022-06-05", 3), ("Kaneshie", "2023-05-20", 4),
    ("Circle", "2023-10-02", 3), ("Adabraka", "2024-06-14", 4),
    ("Alajo", "2024-06-14", 5), ("Avenor", "2025-06-01", 4),
]


async def seed_flood_events() -> int:
    async with SessionLocal() as db:
        count = (await db.execute(select(func.count(FloodEvent.id)))).scalar()
        if count and count > 0:
            log.info("flood_events already seeded (%d)", count)
            return count
        for area, date, sev in HISTORICAL:
            lat, lng = ACCRA_HOTSPOTS.get(area, (5.56, -0.21))
            db.add(FloodEvent(
                occurred_on=dt.date.fromisoformat(date), area_name=area,
                severity=sev, source="historical-compilation",
                notes=f"Reported flooding at {area}",
                geom=from_shape(Point(lng, lat), srid=4326)))
        await db.commit()
        log.info("seeded %d flood events", len(HISTORICAL))
        return len(HISTORICAL)


async def _count(model) -> int:
    async with SessionLocal() as db:
        return (await db.execute(select(func.count()).select_from(model))).scalar() or 0


async def main() -> None:
    await seed_flood_events()
    # Skip the expensive rebuilds when already populated — this runs on every
    # (free-tier) cold start, and re-tiling 1000+ cells adds ~30s to first-request
    # latency for no benefit. A fresh DB (counts == 0) still seeds fully.
    if await _count(RiskTile) == 0:
        async with SessionLocal() as db:
            # Populate the risk grid first so routes can compute baseline risk.
            await build_tiles(db, settings.h3_resolution)
    else:
        log.info("risk_tiles already populated — skipping build_tiles")
    if await _count(TrotroRoute) == 0:
        async with SessionLocal() as db:
            await ingest_routes(db, use_overpass=False)
    else:
        log.info("trotro_routes already populated — skipping ingest_routes")
    log.info("seed complete")


if __name__ == "__main__":
    asyncio.run(main())
