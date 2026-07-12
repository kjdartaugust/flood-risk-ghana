"""Historical flood density per H3 cell, from real recorded flood events.

This replaces the old `0.6 * distance_to_hotspot` stand-in. Density is a
Gaussian kernel over the actual FloodEvent points in PostGIS: a cell sitting on
top of several reported incidents scores near 1, a cell kilometres from any
reported flooding scores near 0.

Note this feature is derived from the same incident records that any supervised
label set would come from, so it is **target leakage** for a trained classifier
and is deliberately excluded from `MODEL_FEATURE_ORDER`. It is legitimate in the
transparent weighted baseline, which is a hand-specified index rather than
something fitted to those labels.
"""
from __future__ import annotations

import logging
import math

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FloodEvent
from app.services.geo import cell_to_latlng, haversine_km

log = logging.getLogger("services.hazard")

# Influence radius of a reported incident. ~2 km is about the scale of an Accra
# drainage catchment, and keeps a report from bleeding across the whole city.
KERNEL_KM = 2.0


async def event_points(db: AsyncSession) -> list[tuple[float, float, int]]:
    """Every recorded flood event as (lat, lng, severity)."""
    rows = (
        await db.execute(
            select(
                func.ST_Y(FloodEvent.geom),
                func.ST_X(FloodEvent.geom),
                FloodEvent.severity,
            )
        )
    ).all()
    return [(float(la), float(ln), int(sev or 1)) for la, ln, sev in rows]


def density_at(lat: float, lng: float,
               events: list[tuple[float, float, int]]) -> float:
    """Severity-weighted Gaussian kernel density in 0..1 at one point."""
    if not events:
        return 0.0
    total = 0.0
    for elat, elng, sev in events:
        d = haversine_km((lat, lng), (elat, elng))
        total += (sev / 5.0) * math.exp(-((d / KERNEL_KM) ** 2))
    # Saturate: 2-3 nearby severe incidents is already "known flood zone".
    return round(min(total / 2.0, 1.0), 4)


async def historical_density(db: AsyncSession, cells: list[str],
                             res: int) -> dict[str, float]:
    """Map each H3 cell to its historical flood density."""
    events = await event_points(db)
    if not events:
        log.warning("no flood events recorded — hist_flood_density will be 0")
        return dict.fromkeys(cells, 0.0)
    out = {}
    for cell in cells:
        lat, lng = cell_to_latlng(cell)
        out[cell] = density_at(lat, lng, events)
    log.info("hist density over %d cells from %d events", len(cells), len(events))
    return out
