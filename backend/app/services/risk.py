"""Risk scoring service: builds tile features from PostGIS and scores them.

Point/area lookups first try the precomputed `risk_tiles` table (fast path,
populated by ETL). On a miss they compute features on the fly from DEM-derived
columns and nearby historical flood density, then score with the ML model (or
weighted fallback). Results are cached in Redis.
"""
from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache_get, cache_set
from app.config import settings
from app.ml.features import TileFeatures, advice, band
from app.ml.model import get_model
from app.models import RiskTile
from app.schemas import RiskComponents, RiskPointResponse
from app.services.geo import (
    ACCRA_HOTSPOTS,
    cell_boundary_geojson,
    latlng_to_cell,
    nearest_hotspot,
)


async def _hist_flood_density(db: AsyncSession, lat: float, lng: float,
                              radius_m: int = 1500) -> float:
    """Fraction-style density of historical flood events within radius (0..1)."""
    stmt = text(
        """
        SELECT COALESCE(SUM(severity), 0) AS s
        FROM flood_events
        WHERE ST_DWithin(geom::geography,
                         ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                         :r)
        """
    )
    res = await db.execute(stmt, {"lat": lat, "lng": lng, "r": radius_m})
    total = float(res.scalar() or 0.0)
    return min(total / 15.0, 1.0)  # ~3 severe events saturates


async def _recent_rainfall(db: AsyncSession, h3_index: str) -> float:
    stmt = text(
        """
        SELECT COALESCE(SUM(precip_mm), 0) FROM rainfall_obs
        WHERE h3_index = :h AND horizon = 'obs'
          AND observed_at > now() - interval '24 hours'
        """
    )
    res = await db.execute(stmt, {"h": h3_index})
    return float(res.scalar() or 0.0)


async def _synthesize_features(db: AsyncSession, lat: float, lng: float,
                               h3_index: str) -> TileFeatures:
    """Fallback feature builder when no precomputed tile exists.

    Uses distance-to-hotspot as a proxy prior for the DEM/drainage signals that
    ETL would normally supply, blended with live historical + rainfall queries.
    """
    _, dist_km = nearest_hotspot(lat, lng)
    proximity = max(0.0, 1.0 - dist_km / 8.0)  # within 8 km of a hotspot
    hist = await _hist_flood_density(db, lat, lng)
    rain = await _recent_rainfall(db, h3_index)
    return TileFeatures(
        elevation_score=round(0.35 + 0.5 * proximity, 3),
        slope_score=round(0.30 + 0.5 * proximity, 3),
        drainage_score=round(0.40 + 0.45 * proximity, 3),
        imperviousness=round(0.45 + 0.4 * proximity, 3),
        hist_flood_density=max(hist, 0.6 * proximity),
        rainfall_recent_mm=rain,
    )


async def score_point(db: AsyncSession, lat: float, lng: float) -> RiskPointResponse:
    res = settings.h3_resolution
    h3_index = latlng_to_cell(lat, lng, res)
    cache_key = f"risk:point:{h3_index}"
    if (cached := await cache_get(cache_key)) is not None:
        return RiskPointResponse(**cached)

    model = get_model()
    tile = await db.get(RiskTile, h3_index)
    if tile is not None:
        feats = TileFeatures(
            elevation_score=tile.elevation_score,
            slope_score=tile.slope_score,
            drainage_score=tile.drainage_score,
            imperviousness=tile.imperviousness,
            hist_flood_density=tile.hist_flood_density,
            rainfall_recent_mm=tile.rainfall_recent_mm,
        )
        score, conf = tile.risk_score, tile.confidence
        version = tile.model_version
    else:
        feats = await _synthesize_features(db, lat, lng, h3_index)
        score, conf = model.predict(feats)
        version = model.version
        conf = round(conf * 0.85, 3)  # penalise on-the-fly estimates

    hotspot, dist = nearest_hotspot(lat, lng)
    resp = RiskPointResponse(
        lat=lat, lng=lng, h3_index=h3_index, resolution=res,
        risk_score=score, band=band(score), confidence=conf,
        components=RiskComponents(
            elevation=feats.elevation_score, slope=feats.slope_score,
            drainage=feats.drainage_score, imperviousness=feats.imperviousness,
            historical_flood_density=feats.hist_flood_density,
            recent_rainfall_mm=feats.rainfall_recent_mm,
        ),
        model_version=version,
        nearest_hotspot=hotspot if dist < 8 else None,
        advice=advice(score, hotspot if dist < 8 else None),
    )
    await cache_set(cache_key, resp.model_dump(), ttl=300)
    return resp


async def score_area(db: AsyncSession, name: str) -> RiskPointResponse:
    """Score a named area — resolves Accra hotspots, else geocodes via events."""
    key = name.strip().title()
    if key in ACCRA_HOTSPOTS:
        lat, lng = ACCRA_HOTSPOTS[key]
        return await score_point(db, lat, lng)
    stmt = (
        select(func.avg(func.ST_Y(text("geom"))), func.avg(func.ST_X(text("geom"))))
        .select_from(text("flood_events"))
        .where(text("area_name ILIKE :n"))
    )
    res = await db.execute(stmt, {"n": f"%{name}%"})
    row = res.first()
    if row and row[0] is not None:
        return await score_point(db, float(row[0]), float(row[1]))
    raise ValueError(f"Unknown area: {name}")


async def tiles_in_bbox(db: AsyncSession, min_lng: float, min_lat: float,
                        max_lng: float, max_lat: float,
                        res: int) -> list[dict]:
    """Return GeoJSON features for precomputed risk tiles in a bbox."""
    stmt = text(
        """
        SELECT h3_index, risk_score, confidence FROM risk_tiles
        WHERE resolution = :res
          AND centroid_lng BETWEEN :minx AND :maxx
          AND centroid_lat BETWEEN :miny AND :maxy
        LIMIT 5000
        """
    )
    rows = (await db.execute(stmt, {
        "res": res, "minx": min_lng, "maxx": max_lng,
        "miny": min_lat, "maxy": max_lat,
    })).all()
    features = []
    for h3_index, risk, conf in rows:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon",
                         "coordinates": [cell_boundary_geojson(h3_index)]},
            "properties": {"h3_index": h3_index, "risk_score": risk,
                           "band": band(risk), "confidence": conf},
        })
    return features
