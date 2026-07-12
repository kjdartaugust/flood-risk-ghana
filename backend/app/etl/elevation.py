"""Elevation source: Open-Meteo Elevation API (Copernicus DEM GLO-90).

Key-free, batched 100 coordinates per request. This replaces the old
`sample_dem` proxy with real metres-above-sea-level, which is the input the
slope and HAND (height-above-nearest-drainage) features are derived from.

Used offline by `app.etl.build_terrain`; the fetched values are committed to
`backend/data/accra_terrain.csv` so seed/CI never need the network.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger("etl.elevation")

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
BATCH = 100  # API caps a single request at 100 coordinates
# Open-Meteo bills each *coordinate* against the quota, not each request, so a
# full 100-point batch costs 100 calls against a ~600/min free-tier budget.
# Pace batches to stay under it; a whole-city rebuild then takes a few minutes.
PAUSE_S = 11.0
MAX_RETRIES = 5


async def _get_batch(client: httpx.AsyncClient, chunk: list[tuple[float, float]]):
    params = {
        "latitude": ",".join(f"{lat:.5f}" for lat, _ in chunk),
        "longitude": ",".join(f"{lng:.5f}" for _, lng in chunk),
    }
    for attempt in range(MAX_RETRIES):
        r = await client.get(ELEVATION_URL, params=params)
        if r.status_code == 429:
            wait = PAUSE_S * (2**attempt)
            log.warning("elevation: rate-limited, backing off %.0fs", wait)
            await asyncio.sleep(wait)
            continue
        r.raise_for_status()
        got = r.json()["elevation"]
        if len(got) != len(chunk):
            raise ValueError(
                f"elevation API returned {len(got)} values for {len(chunk)} points"
            )
        return [float(v) for v in got]
    raise RuntimeError(f"elevation API still rate-limiting after {MAX_RETRIES} tries")


async def fetch_elevations(
    points: list[tuple[float, float]], client: httpx.AsyncClient | None = None
) -> list[float]:
    """Return elevation (m) for each (lat, lng), in order.

    Raises on transport/HTTP failure — the caller decides whether to fall back.
    """
    own = client is None
    client = client or httpx.AsyncClient(timeout=60)
    out: list[float] = []
    try:
        batches = [points[i : i + BATCH] for i in range(0, len(points), BATCH)]
        for n, chunk in enumerate(batches):
            out.extend(await _get_batch(client, chunk))
            log.info("elevation: %d/%d", len(out), len(points))
            if n < len(batches) - 1:
                await asyncio.sleep(PAUSE_S)
    finally:
        if own:
            await client.aclose()
    return out
