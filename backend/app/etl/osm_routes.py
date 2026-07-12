"""Ingest trotro routes from OpenStreetMap (Overpass API).

Queries Overpass for public-transport routes (route=bus/minibus) in Greater
Accra, builds a LineString per relation, and computes each route's baseline risk
as the max risk_score of the tiles it crosses. Falls back to a bundled seed set
of well-known Accra corridors when Overpass is unavailable (offline/dev).
"""
from __future__ import annotations

import logging

import httpx
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.etl.osm_terrain import OVERPASS, UA
from app.models import TrotroRoute

log = logging.getLogger("etl.osm")

# Fallback corridors: (name, from, to, [(lat,lng)...])
SEED_ROUTES = [
    ("Kaneshie – Circle", "Kaneshie", "Circle",
     [(5.5620, -0.2360), (5.5665, -0.2230), (5.5710, -0.2050)]),
    ("Circle – Achimota", "Circle", "Achimota",
     [(5.5710, -0.2050), (5.5900, -0.2170), (5.6110, -0.2230)]),
    ("Kaneshie – Mallam", "Kaneshie", "Mallam",
     [(5.5620, -0.2360), (5.5560, -0.2600), (5.5500, -0.2830)]),
    ("Circle – Adabraka – Accra Central", "Circle", "Accra Central",
     [(5.5710, -0.2050), (5.5620, -0.2110), (5.5480, -0.2050)]),
    ("Alajo – Circle", "Alajo", "Circle",
     [(5.5920, -0.2160), (5.5810, -0.2110), (5.5710, -0.2050)]),
]


async def _baseline_risk(db: AsyncSession, coords: list[tuple[float, float]]) -> float:
    """Max risk_score among tiles within 400 m of the route line."""
    line = "LINESTRING(" + ",".join(f"{lng} {lat}" for lat, lng in coords) + ")"
    stmt = text(
        """
        SELECT COALESCE(MAX(risk_score), 0) FROM risk_tiles
        WHERE ST_DWithin(
          ST_SetSRID(ST_MakePoint(centroid_lng, centroid_lat),4326)::geography,
          ST_GeogFromText('SRID=4326;' || :line), 400)
        """
    )
    return float((await db.execute(stmt, {"line": line})).scalar() or 0.0)


async def _upsert_route(db: AsyncSession, name: str, frm: str, to: str,
                        coords: list[tuple[float, float]], osm_id: str | None) -> None:
    exists = (await db.execute(
        select(TrotroRoute).where(TrotroRoute.name == name))).scalar_one_or_none()
    geom = from_shape(LineString([(lng, lat) for lat, lng in coords]), srid=4326)
    risk = await _baseline_risk(db, coords)
    if exists:
        exists.geom = geom
        exists.baseline_risk = risk
    else:
        db.add(TrotroRoute(name=name, from_stop=frm, to_stop=to, geom=geom,
                           osm_id=osm_id, baseline_risk=risk))


async def _fetch_overpass(client: httpx.AsyncClient) -> list:
    q = """
    [out:json][timeout:60];
    area["name"="Greater Accra Region"]->.a;
    relation["route"~"bus|minibus|share_taxi"](area.a);
    out geom;
    """
    # Without an identifying UA, Overpass's Apache front end answers 406 and we
    # silently fall through to SEED_ROUTES — which looked like "Overpass is
    # flaky" for a long time. OSM's usage policy requires a real UA anyway.
    r = await client.post(OVERPASS, data={"data": q}, headers=UA, timeout=70)
    r.raise_for_status()
    return r.json().get("elements", [])


async def ingest_routes(db: AsyncSession, use_overpass: bool = True) -> int:
    n = 0
    if use_overpass:
        try:
            async with httpx.AsyncClient() as client:
                for el in await _fetch_overpass(client):
                    geometry = [(g["lat"], g["lon"])
                                for m in el.get("members", [])
                                for g in m.get("geometry", []) if "lat" in g]
                    if len(geometry) < 2:
                        continue
                    tags = el.get("tags", {})
                    await _upsert_route(
                        db, tags.get("name", f"route-{el['id']}"),
                        tags.get("from", ""), tags.get("to", ""),
                        geometry, str(el["id"]))
                    n += 1
        except Exception as e:  # noqa: BLE001
            log.warning("Overpass failed (%s); using seed routes", e)
    if n == 0:
        for name, frm, to, coords in SEED_ROUTES:
            await _upsert_route(db, name, frm, to, coords, None)
            n += 1
    await db.commit()
    log.info("routes ingested: %d", n)
    return n
