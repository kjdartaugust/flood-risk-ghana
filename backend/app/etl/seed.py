"""One-shot seed: historical flood events, risk tiles, and trotro routes.

Run: python -m app.etl.seed
Idempotent — safe to re-run. The backend entrypoint runs it on every boot, and
each step writes only when something changed.
"""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import logging
import os

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import delete, func, select

from app.config import settings
from app.db import SessionLocal
from app.etl.osm_routes import set_baselines, sync_routes
from app.etl.terrain import build_tiles
from app.models import FloodEvent, RiskTile

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("seed")

INCIDENTS_CSV = os.path.join(os.path.dirname(__file__), "..", "..", "data",
                             "accra_flood_incidents.csv")

# Every incident is anchored to the 3 June 2015 Accra flood disaster: a single
# real, city-wide, well-documented event. We deliberately do NOT invent per-
# community dates or severities — see docs/DATA.md for what this label set is
# and is not.
EVENT_DATE = dt.date(2015, 6, 3)
EVENT_SEVERITY = 3
SOURCE = "public-reporting:2015-06-03-accra-flood"
# The first version of this seed wrote a hand-made list under this source, with
# per-area dates (2016-2025) and severities nobody had recorded. A database
# seeded back then still holds those rows, and because seeding skipped whenever
# any event existed, the real list above never replaced them. They go; riders'
# own reports (source "community") stay.
LEGACY_SOURCE = "historical-compilation"


def load_incidents() -> list[dict]:
    """Reported-flooded communities with OSM-geocoded coordinates."""
    path = os.path.normpath(INCIDENTS_CSV)
    if not os.path.exists(path):
        log.warning("no incidents CSV at %s", path)
        return []
    with open(path, encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r["flood_reported"] == "1"]


async def seed_flood_events() -> bool:
    """Make the recorded history the real one. True if it changed (re-tile then:
    each tile bakes in the flood history around it)."""
    incidents = load_incidents()
    async with SessionLocal() as db:
        legacy = (await db.execute(
            delete(FloodEvent).where(FloodEvent.source == LEGACY_SOURCE)
        )).rowcount or 0
        if legacy:
            log.info("removed %d made-up flood events (%s)", legacy, LEGACY_SOURCE)
        have = (await db.execute(
            select(func.count(FloodEvent.id)).where(FloodEvent.source == SOURCE)
        )).scalar() or 0
        if have:
            log.info("flood_events already seeded (%d)", have)
        else:
            for r in incidents:
                db.add(FloodEvent(
                    occurred_on=EVENT_DATE, area_name=r["area_name"],
                    severity=EVENT_SEVERITY, source=SOURCE,
                    notes=(f"{r['area_name']} reported flooded in the 3 June 2015 "
                           "Accra flood disaster; coordinates geocoded from OSM."),
                    geom=from_shape(Point(float(r["lng"]), float(r["lat"])),
                                    srid=4326)))
            log.info("seeded %d flood events", len(incidents))
        await db.commit()
        return bool(legacy) or (not have and bool(incidents))


async def _count(model) -> int:
    async with SessionLocal() as db:
        return (await db.execute(select(func.count()).select_from(model))).scalar() or 0


async def _tiles_are_stale() -> bool:
    """True if the grid is missing, or was built by a different model version.

    Tiling is expensive and runs on every free-tier cold start, so we skip it
    when the grid is current. But the grid bakes in both the terrain data and the
    model, so a deploy that changes either must re-tile — otherwise the API keeps
    serving scores from the old features forever.
    """
    from app.ml.model import get_model

    if await _count(RiskTile) == 0:
        return True
    async with SessionLocal() as db:
        versions = set((await db.execute(
            select(RiskTile.model_version).distinct()
        )).scalars().all())
    current = get_model().version
    if versions != {current}:
        log.info("risk_tiles built by %s, current model is %s — re-tiling",
                 versions or "{}", current)
        return True
    return False


async def main() -> None:
    history_changed = await seed_flood_events()
    retiled = history_changed or await _tiles_are_stale()
    if retiled:
        async with SessionLocal() as db:
            # Populate the risk grid first so routes can compute baseline risk.
            await build_tiles(db, settings.h3_resolution)
    else:
        log.info("risk_tiles current — skipping build_tiles")
    async with SessionLocal() as db:
        changed = await sync_routes(db)
        # A new grid moves every route's worst tile, not just the changed routes'.
        await set_baselines(db, None if retiled else changed)
    log.info("seed complete")


if __name__ == "__main__":
    asyncio.run(main())
