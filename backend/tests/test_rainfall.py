"""Rainfall refresh: the scheduled job's write path.

It runs on a free instance an ocean away from its database, behind an IP that
Open-Meteo rate-limits, so how many requests and round trips it makes matters as
much as what it writes. No DB and no network here: a stub session records the
statements, and Open-Meteo is faked.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.etl import rainfall
from app.models import RiskTile

HOURS = 72  # past_days=1 + forecast_days=2


class _Result:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class FakeDB:
    """Answers the tile SELECT, then records every statement it is sent."""

    def __init__(self, tiles):
        self.tiles = tiles
        self.sent: list[tuple[object, object]] = []
        self.committed = False

    async def execute(self, stmt, params=None):
        self.sent.append((stmt, params))
        return _Result(self.tiles)

    async def commit(self):
        self.committed = True


def _tile(name, lat=5.6, lng=-0.2):
    return RiskTile(h3_index=f"cell{name}", centroid_lat=lat, centroid_lng=lng)


def _grid(n):
    """n tiles spread over about 11 x 11 km of Accra."""
    return [_tile(i, 5.55 + (i % 20) * 0.005, -0.25 + (i // 20) * 0.008)
            for i in range(n)]


def _series(mm):
    """A day of history and two of forecast, the shape Open-Meteo returns."""
    start = (dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
             - dt.timedelta(hours=24))
    times = [(start + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M")
             for h in range(HOURS)]
    return {"hourly": {"time": times, "precipitation": [mm] * HOURS}}


@pytest.fixture(autouse=True)
def openmeteo(monkeypatch):
    """Fake Open-Meteo. Returns the list of requests made, each its points."""
    asked: list[list] = []

    async def fetch(client, points):
        asked.append(list(points))
        return [_series(1.0) for _ in points]

    monkeypatch.setattr(rainfall, "_fetch_openmeteo", fetch)
    return asked


def test_one_sample_point_per_5km_cell_not_one_per_tile():
    tiles = _grid(250)
    points = rainfall.sample_points(tiles)
    assert 4 <= len(points) <= 12
    assert points == sorted(set(points))
    assert rainfall.sample_points(list(reversed(tiles))) == points


@pytest.mark.asyncio
async def test_whole_refresh_is_one_request_and_one_statement(openmeteo):
    """Per tile, 400 tiles was 400 Open-Meteo calls against a per-IP daily
    allowance, and row by row it was tens of thousands of round trips."""
    db = FakeDB(_grid(250))
    rows = await rainfall.refresh_rainfall(db)
    assert rows == 250 * HOURS
    assert len(openmeteo) == 1
    upserts = db.sent[1:]  # [0] is the tile SELECT
    assert len(upserts) == 1 and len(upserts[0][1]) == rows
    assert db.committed


@pytest.mark.asyncio
async def test_each_tile_takes_its_nearest_points_rain():
    db = FakeDB([_tile("a", 5.551, -0.249), _tile("b", 5.648, -0.152)])
    points = [(5.55, -0.25), (5.65, -0.15)]
    await rainfall.refresh_rainfall(db, fetched=(points, [_series(2.0), _series(9.0)]))
    [(_, params)] = db.sent[1:]
    assert {p["h3_index"]: p["precip_mm"] for p in params} == {"cella": 2.0, "cellb": 9.0}


@pytest.mark.asyncio
async def test_rain_handed_over_is_used_without_fetching(openmeteo):
    db = FakeDB(_grid(30))
    points = rainfall.sample_points(db.tiles)
    rows = await rainfall.refresh_rainfall(
        db, fetched=(points, [_series(1.0)] * len(points)))
    assert rows == 30 * HOURS
    assert openmeteo == []


@pytest.mark.asyncio
async def test_every_fetch_failing_is_an_error_not_a_dry_day(monkeypatch):
    async def down(client, points):
        raise rainfall.httpx.ConnectError("no route to host")

    monkeypatch.setattr(rainfall, "_fetch_openmeteo", down)
    db = FakeDB(_grid(250))
    with pytest.raises(RuntimeError, match="every rain fetch failed .*ConnectError"):
        await rainfall.refresh_rainfall(db)
    assert db.sent[1:] == []


@pytest.mark.asyncio
async def test_hours_split_into_observed_and_forecast():
    [tile] = _grid(1)
    db = FakeDB([tile])
    await rainfall.refresh_rainfall(db)
    [(_, params)] = db.sent[1:]
    assert {p["horizon"] for p in params} == {"obs", "forecast"}
    observed = [p for p in params if p["horizon"] == "obs"]
    assert all(p["observed_at"] <= dt.datetime.now(dt.UTC) for p in observed)
    # The tile's recent-rainfall feature counts observed hours only.
    assert tile.rainfall_recent_mm == pytest.approx(1.0 * len(observed))
