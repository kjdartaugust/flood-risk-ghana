"""Rainfall refresh: the scheduled job's write path.

It runs on a free instance an ocean away from its database, behind an IP that
Open-Meteo rate-limits, so how many requests and round trips it makes matters as
much as what it writes. No DB and no network here: a stub session records the
statements, and Open-Meteo is faked.
"""
from __future__ import annotations

import datetime as dt
import json

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
    """Answers the tile and route SELECTs; records every write it is sent."""

    def __init__(self, tiles, routes=()):
        self.tiles = tiles
        self.routes = [(rid, json.dumps({"type": "LineString", "coordinates": line}))
                       for rid, line in routes]
        self.sent: list[tuple[object, object]] = []
        self.committed = False

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if sql.lstrip().startswith("SELECT"):
            return _Result(self.routes if "trotro_routes" in sql else self.tiles)
        self.sent.append((stmt, params))
        return _Result([])

    async def commit(self):
        self.committed = True


def _tile(name, lat=5.6, lng=-0.2):
    return RiskTile(h3_index=f"cell{name}", centroid_lat=lat, centroid_lng=lng)


# Kaneshie to Circle, about 3.5 km: one rain cell or two.
KANESHIE_CIRCLE = [[-0.236, 5.562], [-0.223, 5.5665], [-0.205, 5.571]]


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


def test_a_long_straight_road_cant_skip_a_rain_cell():
    # 22 km due east along one latitude: every 0.05-degree cell on the way.
    cells = rainfall.route_cells([(-0.30, 5.55), (-0.10, 5.55)])
    assert cells == {(5.55, lng) for lng in (-0.3, -0.25, -0.2, -0.15, -0.1)}


def test_routes_are_sampled_where_the_tiles_stop():
    """Routes run out to Kasoa and Medie, past the risk grid; their rain has to
    be fetched there too."""
    tiles = _grid(40)
    kasoa = ("osm-1", [(-0.42, 5.53), (-0.25, 5.55)])
    with_route = rainfall.sample_points(tiles, [kasoa])
    assert set(rainfall.sample_points(tiles)) < set(with_route)
    assert (5.55, -0.4) in with_route


@pytest.mark.asyncio
async def test_whole_refresh_is_one_request_and_one_statement_each(openmeteo):
    """Per tile, 400 tiles was 400 Open-Meteo calls against a per-IP daily
    allowance, and row by row it was tens of thousands of round trips. The same
    goes for routes: there are hundreds."""
    routes = [(f"osm-{i}", KANESHIE_CIRCLE) for i in range(300)]
    db = FakeDB(_grid(250), routes)
    rows = await rainfall.refresh_rainfall(db)
    assert rows == 250 * HOURS
    assert len(openmeteo) == 1
    upsert, route_rain = db.sent
    assert len(upsert[1]) == rows
    assert len(route_rain[1]) == 300
    assert db.committed


@pytest.mark.asyncio
async def test_each_tile_takes_its_nearest_points_rain():
    db = FakeDB([_tile("a", 5.551, -0.249), _tile("b", 5.648, -0.152)])
    points = [(5.55, -0.25), (5.65, -0.15)]
    await rainfall.refresh_rainfall(db, fetched=(points, [_series(2.0), _series(9.0)]))
    [(_, params)] = db.sent
    assert {p["h3_index"]: p["precip_mm"] for p in params} == {"cella": 2.0, "cellb": 9.0}


@pytest.mark.asyncio
async def test_a_route_gets_the_wettest_cell_it_passes_each_hour():
    """Rain that floods one end of a route still blocks the trotro."""
    west_to_east = ("osm-7", [(-0.30, 5.55), (-0.15, 5.55)])
    db = FakeDB([_tile("a", 5.551, -0.249)], [west_to_east])
    points = [(5.55, -0.3), (5.55, -0.15), (5.75, -0.3)]
    rain = [_series(2.0), _series(9.0), _series(40.0)]  # the last is off the route
    await rainfall.refresh_rainfall(db, fetched=(points, rain))
    _, (_, [route]) = db.sent
    assert route["rid"] == "osm-7"
    hours = [(dt.datetime.fromisoformat(at), mm) for at, mm in route["fc"]]
    assert {mm for _, mm in hours} == {9.0}
    # Coming hours only: the past is no use to someone about to board.
    assert len(hours) == 47 and all(at > dt.datetime.now(dt.UTC) for at, _ in hours)


@pytest.mark.asyncio
async def test_a_route_whose_rain_failed_to_fetch_keeps_its_last_forecast():
    """Not "dry": unknown. Its last forecast stands until rain comes through."""
    db = FakeDB([_tile("a", 5.75, -0.10)], [("osm-7", KANESHIE_CIRCLE)])
    points = [(5.55, -0.25), (5.75, -0.1)]
    await rainfall.refresh_rainfall(db, fetched=(points, [None, _series(3.0)]))
    [(_, params)] = db.sent  # the tile's rain, and no route update
    assert {p["h3_index"] for p in params} == {"cella"}



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
    assert db.sent == []


@pytest.mark.asyncio
async def test_hours_split_into_observed_and_forecast():
    [tile] = _grid(1)
    db = FakeDB([tile])
    await rainfall.refresh_rainfall(db)
    [(_, params)] = db.sent
    assert {p["horizon"] for p in params} == {"obs", "forecast"}
    observed = [p for p in params if p["horizon"] == "obs"]
    assert all(p["observed_at"] <= dt.datetime.now(dt.UTC) for p in observed)
    # The tile's recent-rainfall feature counts observed hours only.
    assert tile.rainfall_recent_mm == pytest.approx(1.0 * len(observed))
