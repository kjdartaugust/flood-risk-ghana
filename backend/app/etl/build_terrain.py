"""Offline builder: real terrain features per H3 cell → committed CSV.

    python -m app.etl.build_terrain            # rebuild from live sources
    python -m app.etl.build_terrain --out X    # write elsewhere

Pulls Copernicus DEM elevation (Open-Meteo) and the OSM drainage/building
network (Overpass), derives the four static risk features, and writes
`backend/data/accra_terrain.csv`. That file is committed, so `seed`/CI/Docker
never touch the network — this script is run by a human when the inputs should
be refreshed, not on every boot.

Derivations (all real, none derived from flood labels):

* elevation_score — inverse percentile rank of elevation within Greater Accra.
  Rank-normalised rather than divided by a magic constant, so it means "low-lying
  *relative to this city*" and needs no rescaling if the bbox changes.
* slope_score     — steepest gradient to an H3 neighbour, in %. Flat ⇒ 1.
* drainage_score  — from HAND (height above nearest drainage): a cell sitting at
  the level of the nearest stream/drain has nowhere to shed water. HAND 0 m ⇒ 1,
  ≥ HAND_CEILING_M ⇒ 0. This is the standard fluvial-exposure terrain metric.
* imperviousness  — percentile rank of OSM building-footprint count per cell.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os

import httpx
import numpy as np

from app.etl.elevation import fetch_elevations
from app.etl.osm_terrain import fetch_buildings, fetch_waterways
from app.services.geo import (
    ACCRA_BBOX,
    cell_to_latlng,
    cells_in_bbox,
    latlng_to_cell,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("etl.build_terrain")

DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "..", "..", "data",
                           "accra_terrain.csv")
# The DEM pull is quota-throttled to a few minutes; cache it so re-running the
# builder to tweak a derivation doesn't re-pay for it. Not committed.
ELEV_CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "data",
                          ".elevation_cache.json")

# A cell this far above the nearest drainage is treated as fully drained.
HAND_CEILING_M = 12.0
# Slope at or above this (%) is "steep enough to shed water" in an urban delta.
SLOPE_CEILING_PCT = 5.0

FIELDS = [
    "h3_index", "centroid_lat", "centroid_lng",
    "elev_m", "slope_pct", "hand_m", "water_dist_m", "building_count",
    "is_land",
    "elevation_score", "slope_score", "drainage_score", "imperviousness",
]

# Open water reads as the perfect flood cell — 0 m elevation, dead flat, zero
# height above drainage — so without a mask the index confidently rates the Gulf
# of Guinea an extreme flood risk. The DEM returns exactly 0.0 at sea level and
# nobody builds on water, so "no buildings AND at/below 2 m" masks the ocean and
# open lagoon surface while keeping low-lying built-up coastal land like Chorkor.
# Upgrade seam: intersect against OSM `natural=water` polygons for a true mask.
SEA_LEVEL_M = 2.0

R_EARTH_M = 6_371_000.0


def _haversine_m(lat1, lng1, lat2, lng2):
    """Vectorised great-circle distance in metres (numpy broadcasting)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lng2) - np.radians(lng1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R_EARTH_M * np.arcsin(np.sqrt(a))


def _pct_rank(x: np.ndarray) -> np.ndarray:
    """Percentile rank in [0,1]; ties share the average rank.

    Ties matter here: most cells have zero buildings, and splitting them by
    arbitrary index order would invent an imperviousness gradient that isn't
    in the data.
    """
    order = np.argsort(x, kind="stable")
    ranks = np.empty(len(x), dtype=float)
    ranks[order] = np.arange(len(x), dtype=float)
    # average the ranks within each group of equal values
    vals, inv = np.unique(x, return_inverse=True)
    sums = np.bincount(inv, weights=ranks, minlength=len(vals))
    counts = np.bincount(inv, minlength=len(vals))
    ranks = (sums / counts)[inv]
    return ranks / max(len(x) - 1, 1)


def _slopes(cells: list[str], elev: dict[str, float],
            lat: np.ndarray, lng: np.ndarray) -> np.ndarray:
    """Steepest % gradient from each cell to any H3 neighbour we have DEM for."""
    import h3

    idx = {c: i for i, c in enumerate(cells)}
    out = np.zeros(len(cells))
    for i, c in enumerate(cells):
        best = 0.0
        for nb in h3.grid_disk(c, 1):
            j = idx.get(nb)
            if j is None or j == i:
                continue
            d_m = _haversine_m(lat[i], lng[i], lat[j], lng[j])
            if d_m < 1:
                continue
            best = max(best, abs(elev[c] - elev[nb]) / d_m * 100.0)
        out[i] = best
    return out


async def build(out_path: str, res: int = 8) -> int:
    cells = sorted(cells_in_bbox(*ACCRA_BBOX, res))
    latlngs = [cell_to_latlng(c) for c in cells]
    lat = np.array([p[0] for p in latlngs])
    lng = np.array([p[1] for p in latlngs])
    log.info("study area: %d cells at res %d", len(cells), res)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    cache = os.path.normpath(ELEV_CACHE)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    cached: dict[str, float] = {}
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as fh:
            cached = json.load(fh)

    async with httpx.AsyncClient(timeout=180) as client:
        if all(c in cached for c in cells):
            log.info("elevation: %d cells from cache", len(cells))
            elev_list = [cached[c] for c in cells]
        else:
            elev_list = await fetch_elevations(latlngs, client)
            with open(cache, "w", encoding="utf-8") as fh:
                json.dump(dict(zip(cells, elev_list, strict=True)), fh)
        water_pts = await fetch_waterways(ACCRA_BBOX, client)
        bldg_pts = await fetch_buildings(ACCRA_BBOX, client)

    elev = dict(zip(cells, elev_list, strict=True))
    elev_arr = np.array(elev_list)

    # --- drainage: HAND against the nearest OSM waterway vertex ---------------
    # Snap each waterway vertex to its H3 cell so we can read the DEM there
    # without a second elevation fetch. Vertices outside the study grid drop out.
    drain_cells = {latlng_to_cell(la, lo, res) for la, lo in water_pts}
    drain_cells &= set(cells)
    if not drain_cells:
        raise RuntimeError("no waterways landed inside the study grid")
    dl = np.array([cell_to_latlng(c) for c in sorted(drain_cells)])
    d_elev = np.array([elev[c] for c in sorted(drain_cells)])
    log.info("drainage network: %d cells carry a waterway", len(drain_cells))

    # (cells x drain_cells) distance matrix — 1.3k x ~300 is trivial for numpy.
    dist = _haversine_m(lat[:, None], lng[:, None], dl[None, :, 0], dl[None, :, 1])
    near = dist.argmin(axis=1)
    water_dist_m = dist[np.arange(len(cells)), near]
    hand_m = np.maximum(elev_arr - d_elev[near], 0.0)

    # --- imperviousness: building footprints per cell -------------------------
    counts = dict.fromkeys(cells, 0)
    for la, lo in bldg_pts:
        c = latlng_to_cell(la, lo, res)
        if c in counts:
            counts[c] += 1
    bldg = np.array([counts[c] for c in cells], dtype=float)

    slope_pct = _slopes(cells, elev, lat, lng)

    is_land = ~((bldg == 0) & (elev_arr <= SEA_LEVEL_M))
    log.info("land mask: %d land / %d water cells", int(is_land.sum()),
             int((~is_land).sum()))

    # Rank-normalise over land only — otherwise ~300 ocean cells sit at the
    # bottom of the elevation distribution and shove every inhabited cell up the
    # ranking, making the whole city look high-lying relative to the sea.
    elevation_score = np.zeros(len(cells))
    imperviousness = np.zeros(len(cells))
    elevation_score[is_land] = 1.0 - _pct_rank(elev_arr[is_land])
    imperviousness[is_land] = _pct_rank(bldg[is_land])
    slope_score = 1.0 - np.clip(slope_pct / SLOPE_CEILING_PCT, 0, 1)
    drainage_score = np.clip(1.0 - hand_m / HAND_CEILING_M, 0, 1)

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for i, c in enumerate(cells):
            w.writerow([
                c, round(lat[i], 6), round(lng[i], 6),
                round(elev_arr[i], 1), round(slope_pct[i], 3),
                round(hand_m[i], 1), round(water_dist_m[i], 0), int(bldg[i]),
                int(is_land[i]),
                round(elevation_score[i], 4), round(slope_score[i], 4),
                round(drainage_score[i], 4), round(imperviousness[i], 4),
            ])
    log.info("wrote %d rows → %s", len(cells), out_path)
    log.info("elev %.0f–%.0f m | HAND %.0f–%.0f m | buildings %d–%d",
             elev_arr.min(), elev_arr.max(), hand_m.min(), hand_m.max(),
             int(bldg.min()), int(bldg.max()))
    return len(cells)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.normpath(DEFAULT_OUT))
    ap.add_argument("--res", type=int, default=8)
    args = ap.parse_args()
    asyncio.run(build(args.out, args.res))
