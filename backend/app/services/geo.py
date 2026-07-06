"""H3 helpers shared by scoring, ETL and routing.

Wraps the h3 v4 API so the rest of the codebase is version-agnostic and to give
GeoJSON-friendly outputs (lng/lat order).
"""
from __future__ import annotations

import h3

# Bounding box of Ghana (roughly) — used to constrain tile generation.
GHANA_BBOX = (-3.26, 4.71, 1.20, 11.17)  # min_lng, min_lat, max_lng, max_lat

# Known Accra flood hotspots (lat, lng). Used as priors + for "nearest hotspot".
ACCRA_HOTSPOTS: dict[str, tuple[float, float]] = {
    "Kaneshie": (5.5620, -0.2360),
    "Circle": (5.5710, -0.2050),
    "Adabraka": (5.5620, -0.2110),
    "Alajo": (5.5920, -0.2160),
    "Odawna": (5.5680, -0.2090),
    "Avenor": (5.5850, -0.2230),
}


def latlng_to_cell(lat: float, lng: float, res: int) -> str:
    return h3.latlng_to_cell(lat, lng, res)


def cell_to_latlng(cell: str) -> tuple[float, float]:
    lat, lng = h3.cell_to_latlng(cell)
    return lat, lng


def cell_boundary_geojson(cell: str) -> list[list[float]]:
    """Return the hex boundary as GeoJSON ring ([lng, lat], closed)."""
    ring = [[lng, lat] for lat, lng in h3.cell_to_boundary(cell)]
    ring.append(ring[0])
    return ring


def cells_in_bbox(
    min_lng: float, min_lat: float, max_lng: float, max_lat: float, res: int
) -> list[str]:
    """All H3 cells whose polygon intersects the bbox (h3 v4 polygon fill)."""
    poly = h3.LatLngPoly(
        [
            (min_lat, min_lng),
            (min_lat, max_lng),
            (max_lat, max_lng),
            (max_lat, min_lng),
        ]
    )
    return list(h3.polygon_to_cells(poly, res))


def line_cells(coords: list[tuple[float, float]], res: int) -> set[str]:
    """H3 cells traversed by a polyline given as (lat, lng) vertices."""
    cells: set[str] = set()
    for a, b in zip(coords, coords[1:], strict=False):
        ca = h3.latlng_to_cell(a[0], a[1], res)
        cb = h3.latlng_to_cell(b[0], b[1], res)
        try:
            cells.update(h3.grid_path_cells(ca, cb))
        except Exception:
            cells.update({ca, cb})
    return cells


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return h3.great_circle_distance(a, b, unit="km")


def nearest_hotspot(lat: float, lng: float) -> tuple[str, float]:
    """Return (name, distance_km) of the closest known Accra hotspot."""
    best, best_d = "", 1e9
    for name, (hlat, hlng) in ACCRA_HOTSPOTS.items():
        d = haversine_km((lat, lng), (hlat, hlng))
        if d < best_d:
            best, best_d = name, d
    return best, best_d
