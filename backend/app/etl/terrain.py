"""Terrain / land-cover ETL for risk tiles.

In production this reads SRTM/Copernicus DEM GeoTIFFs (elevation → slope →
drainage via flow accumulation) and Sentinel-2 land cover (imperviousness),
sampling each into H3 cells. Those pulls need large rasters + rasterio, so here
we provide a deterministic terrain proxy driven by distance-to-hotspot and a
DEM sampler hook you can swap for real rasterio reads. Keeps the grid fully
populated for local/dev while staying honest about where real data plugs in.
"""
from __future__ import annotations

import logging
import math

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.features import TileFeatures, band
from app.ml.model import get_model
from app.models import RiskTile
from app.services.geo import (
    cell_to_latlng,
    cells_in_bbox,
    nearest_hotspot,
)

log = logging.getLogger("etl.terrain")

# Greater Accra bbox — where we build a dense grid (min_lng,min_lat,max_lng,max_lat)
ACCRA_BBOX = (-0.35, 5.50, -0.05, 5.70)


def sample_dem(lat: float, lng: float) -> float:
    """Elevation sampler hook. Replace body with rasterio DEM read.

    Returns metres above sea level. The proxy uses distance from the coast +
    hotspot lows so relative ordering is sensible without the raster.
    """
    coast_dist = max(0.0, lat - 5.50) * 111  # km north of the coast
    _, hs_km = nearest_hotspot(lat, lng)
    return round(5 + coast_dist * 2.2 + math.log1p(hs_km) * 6, 1)


def _features_for_cell(lat: float, lng: float) -> TileFeatures:
    elev_m = sample_dem(lat, lng)
    _, hs_km = nearest_hotspot(lat, lng)
    proximity = max(0.0, 1.0 - hs_km / 8.0)
    elevation_score = max(0.0, min(1.0, 1.0 - elev_m / 60.0))
    slope_score = max(0.0, min(1.0, 0.25 + 0.55 * proximity))
    drainage_score = max(0.0, min(1.0, 0.30 + 0.55 * proximity))
    imperviousness = max(0.0, min(1.0, 0.35 + 0.45 * proximity))
    return TileFeatures(
        elevation_score=round(elevation_score, 3),
        slope_score=round(slope_score, 3),
        drainage_score=round(drainage_score, 3),
        imperviousness=round(imperviousness, 3),
        hist_flood_density=round(0.6 * proximity, 3),
        rainfall_recent_mm=0.0,
    )


async def build_tiles(db: AsyncSession, res: int,
                      bbox: tuple[float, float, float, float] = ACCRA_BBOX) -> int:
    """Generate/refresh RiskTile rows across a bbox at H3 resolution `res`."""
    model = get_model()
    cells = cells_in_bbox(*bbox, res)
    log.info("building %d tiles at res %d", len(cells), res)
    n = 0
    for cell in cells:
        lat, lng = cell_to_latlng(cell)
        feats = _features_for_cell(lat, lng)
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
                  "drainage_score": feats.drainage_score,
                  "model_version": model.version},
        )
        await db.execute(stmt)
        n += 1
    await db.commit()
    log.info("tiles built: %d (%s)", n, band(score if n else 0))
    return n
