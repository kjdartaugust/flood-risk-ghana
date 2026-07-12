"""OSM terrain sources via Overpass: waterways and building footprints.

Two real signals the old distance-to-hotspot proxy was standing in for:

* **waterways** (river/stream/drain/canal/ditch) — the drainage network. Their
  vertices give us, per H3 cell, the nearest point water actually flows to,
  which is what HAND (height above nearest drainage) is measured against.
* **buildings** — footprint density per cell is a standard, defensible proxy for
  imperviousness (paved/roofed fraction). We ask Overpass for centroids only
  (`out center`), which keeps a city-scale response small.

Used offline by `app.etl.build_terrain`. Overpass is rate-limited and
occasionally down; the builder caches results so this runs once, not per deploy.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("etl.osm_terrain")

OVERPASS = "https://overpass-api.de/api/interpreter"
WATERWAY_KINDS = "river|stream|drain|canal|ditch"

# Overpass sits behind Apache/mod_security, which answers 406 to the default
# `python-httpx` agent. OSM's usage policy wants a identifying UA regardless.
UA = {
    "User-Agent": (
        "FloodWatchGhana/0.1 (flood-risk ETL; "
        "github.com/kjdartaugust/flood-risk-ghana)"
    )
}


def _bbox_str(bbox: tuple[float, float, float, float]) -> str:
    """Overpass wants (south,west,north,east); our bboxes are (W,S,E,N)."""
    min_lng, min_lat, max_lng, max_lat = bbox
    return f"{min_lat},{min_lng},{max_lat},{max_lng}"


async def _overpass(query: str, client: httpx.AsyncClient) -> dict:
    r = await client.post(OVERPASS, data={"data": query}, headers=UA, timeout=180)
    r.raise_for_status()
    return r.json()


async def fetch_waterways(
    bbox: tuple[float, float, float, float], client: httpx.AsyncClient
) -> list[tuple[float, float]]:
    """Return every vertex (lat, lng) of the OSM drainage network in bbox."""
    q = (
        f'[out:json][timeout:120];'
        f'way[waterway~"^({WATERWAY_KINDS})$"]({_bbox_str(bbox)});'
        f'out geom;'
    )
    data = await _overpass(q, client)
    pts = [
        (float(p["lat"]), float(p["lon"]))
        for el in data.get("elements", [])
        for p in el.get("geometry", []) or []
    ]
    log.info("waterways: %d vertices from %d ways",
             len(pts), len(data.get("elements", [])))
    return pts


async def fetch_buildings(
    bbox: tuple[float, float, float, float], client: httpx.AsyncClient
) -> list[tuple[float, float]]:
    """Return the centroid (lat, lng) of every OSM building in bbox."""
    q = (
        f'[out:json][timeout:150];'
        f'(way[building]({_bbox_str(bbox)});'
        f'relation[building]({_bbox_str(bbox)}););'
        f'out center;'
    )
    data = await _overpass(q, client)
    pts = []
    for el in data.get("elements", []):
        c = el.get("center") or el
        if "lat" in c and "lon" in c:
            pts.append((float(c["lat"]), float(c["lon"])))
    log.info("buildings: %d centroids", len(pts))
    return pts
