"""Rainfall refresh: the scheduled job's write path.

It runs on a free instance an ocean away from its database, so how many round
trips it makes matters as much as what it writes. No DB and no network here: a
stub session records the statements, and Open-Meteo is faked.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.etl import rainfall
from app.models import RiskTile

HOURS = 48  # past_days=1 + forecast_days=1
MM = 1.5


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


def _tiles(n):
    return [RiskTile(h3_index=f"cell{i}", centroid_lat=5.6, centroid_lng=-0.2)
            for i in range(n)]


@pytest.fixture(autouse=True)
def openmeteo(monkeypatch):
    """A day of history and a day of forecast, the shape Open-Meteo returns."""
    start = (dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
             - dt.timedelta(hours=24))
    times = [(start + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M")
             for h in range(HOURS)]

    async def fetch(client, points):
        return [{"hourly": {"time": times, "precipitation": [MM] * HOURS}}
                for _ in points]

    monkeypatch.setattr(rainfall, "_fetch_openmeteo", fetch)


@pytest.mark.asyncio
async def test_one_statement_per_batch_not_one_per_row():
    """Row by row, 400 tiles was 19,200 round trips: longer than Render lets an
    idle free instance live, so the job died before it ever committed."""
    db = FakeDB(_tiles(250))
    rows = await rainfall.refresh_rainfall(db)
    assert rows == 250 * HOURS
    upserts = db.sent[1:]  # [0] is the tile SELECT
    assert len(upserts) == 3  # 250 tiles in batches of 100
    assert sum(len(params) for _, params in upserts) == rows
    assert db.committed


@pytest.mark.asyncio
async def test_hours_split_into_observed_and_forecast():
    [tile] = _tiles(1)
    db = FakeDB([tile])
    await rainfall.refresh_rainfall(db)
    [(_, params)] = db.sent[1:]
    assert {p["horizon"] for p in params} == {"obs", "forecast"}
    observed = [p for p in params if p["horizon"] == "obs"]
    assert all(p["observed_at"] <= dt.datetime.now(dt.UTC) for p in observed)
    # The tile's recent-rainfall feature counts observed hours only.
    assert tile.rainfall_recent_mm == pytest.approx(MM * len(observed))
