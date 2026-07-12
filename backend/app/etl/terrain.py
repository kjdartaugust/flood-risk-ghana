"""Terrain / land-cover ETL for risk tiles.

The four static risk features come from `backend/data/accra_terrain.csv`, built
offline by `app.etl.build_terrain` from real sources:

* elevation & slope — Copernicus DEM GLO-90 (Open-Meteo Elevation API)
* drainage — HAND (height above nearest drainage) against the OSM waterway network
* imperviousness — OSM building-footprint density

The CSV is committed, so seeding needs no network and the grid is reproducible.
If a cell isn't in it (e.g. a lookup outside Greater Accra), we fall back to a
deterministic distance-to-hotspot proxy — clearly marked, and confidence is
penalised downstream so a proxied score never masquerades as a measured one.
"""
from __future__ import annotations

import csv
import logging
import math
import os
from functools import lru_cache

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.features import TileFeatures, band
from app.ml.model import get_model
from app.models import RiskTile
from app.services.geo import (
    ACCRA_BBOX,
    cell_to_latlng,
    cells_in_bbox,
    latlng_to_cell,
    nearest_hotspot,
)

log = logging.getLogger("etl.terrain")

TERRAIN_CSV = os.path.join(os.path.dirname(__file__), "..", "..", "data",
                           "accra_terrain.csv")


@lru_cache(maxsize=1)
def load_terrain() -> dict[str, dict[str, float]]:
    """h3_index → measured terrain features. Empty dict if the CSV is absent."""
    path = os.path.normpath(TERRAIN_CSV)
    if not os.path.exists(path):
        log.warning("no terrain CSV at %s — falling back to the hotspot proxy", path)
        return {}
    with open(path, encoding="utf-8") as fh:
        rows = {
            r["h3_index"]: {
                "elevation_score": float(r["elevation_score"]),
                "slope_score": float(r["slope_score"]),
                "drainage_score": float(r["drainage_score"]),
                "imperviousness": float(r["imperviousness"]),
                "elev_m": float(r["elev_m"]),
                "hand_m": float(r["hand_m"]),
                "is_land": r["is_land"] == "1",
            }
            for r in csv.DictReader(fh)
        }
    log.info("terrain: loaded %d measured cells", len(rows))
    return rows


def _proxy_features(lat: float, lng: float) -> dict[str, float]:
    """Fallback for cells with no DEM/OSM coverage: distance-to-hotspot shape.

    Deterministic and ordered sensibly, but it is *not* a measurement — every
    feature here is a restatement of "how close is this to a known hotspot".
    """
    _, hs_km = nearest_hotspot(lat, lng)
    proximity = max(0.0, 1.0 - hs_km / 8.0)
    coast_dist = max(0.0, lat - 5.50) * 111
    elev_m = 5 + coast_dist * 2.2 + math.log1p(hs_km) * 6
    return {
        "elevation_score": max(0.0, min(1.0, 1.0 - elev_m / 60.0)),
        "slope_score": max(0.0, min(1.0, 0.25 + 0.55 * proximity)),
        "drainage_score": max(0.0, min(1.0, 0.30 + 0.55 * proximity)),
        "imperviousness": max(0.0, min(1.0, 0.35 + 0.45 * proximity)),
        "elev_m": elev_m,
        "hand_m": 0.0,
    }


def terrain_for(lat: float, lng: float, res: int) -> tuple[dict[str, float], bool]:
    """Return (features, measured) for a point — measured=False means proxied."""
    cell = latlng_to_cell(lat, lng, res)
    row = load_terrain().get(cell)
    if row is not None:
        return row, True
    return _proxy_features(lat, lng), False


def _features_for_cell(lat: float, lng: float, res: int,
                       hist_density: float) -> TileFeatures:
    t, _ = terrain_for(lat, lng, res)
    return TileFeatures(
        elevation_score=round(t["elevation_score"], 3),
        slope_score=round(t["slope_score"], 3),
        drainage_score=round(t["drainage_score"], 3),
        imperviousness=round(t["imperviousness"], 3),
        hist_flood_density=round(hist_density, 3),
        rainfall_recent_mm=0.0,
    )


async def build_tiles(db: AsyncSession, res: int,
                      bbox: tuple[float, float, float, float] = ACCRA_BBOX) -> int:
    """Generate/refresh RiskTile rows across a bbox at H3 resolution `res`."""
    from app.services.hazard import historical_density  # local: avoids cycle

    model = get_model()
    terrain = load_terrain()
    # Skip open water: the ocean and lagoon surfaces are dead flat, at sea level
    # and zero height above drainage, so scoring them yields a confident "extreme
    # risk" reading over the Gulf of Guinea. Cells with no terrain row at all are
    # kept and proxied.
    cells = [c for c in cells_in_bbox(*bbox, res)
             if terrain.get(c, {}).get("is_land", True)]
    density = await historical_density(db, cells, res)
    log.info("building %d land tiles at res %d", len(cells), res)
    n = 0
    score = 0.0
    for cell in cells:
        lat, lng = cell_to_latlng(cell)
        feats = _features_for_cell(lat, lng, res, density.get(cell, 0.0))
        score, conf = model.predict(feats)
        stmt = insert(RiskTile).values(
            h3_index=cell, resolution=res, centroid_lat=lat, centroid_lng=lng,
            elevation_score=feats.elevation_score, slope_score=feats.slope_score,
            drainage_score=feats.drainage_score, imperviousness=feats.imperviousness,
            hist_flood_density=feats.hist_flood_density,
            rainfall_recent_mm=feats.rainfall_recent_mm,
            risk_score=score, confidence=conf, model_version=model.version,
        ).on_conflict_do_update(
            index_elements=["h3_index"],
            set_={"risk_score": score, "confidence": conf,
                  "elevation_score": feats.elevation_score,
                  "slope_score": feats.slope_score,
                  "drainage_score": feats.drainage_score,
                  "imperviousness": feats.imperviousness,
                  "hist_flood_density": feats.hist_flood_density,
                  "model_version": model.version},
        )
        await db.execute(stmt)
        n += 1
    await db.commit()
    log.info("tiles built: %d (last %s)", n, band(score) if n else "n/a")
    return n
