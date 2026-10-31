"""DB-backed integration tests.

Skipped automatically unless a live PostGIS is reachable (set by CI via the
DATABASE_URL_SYNC env var pointing at a running postgis service). These exercise
the real query paths that the unit tests cannot: PostGIS spatial queries, the
seed pipeline, and every DB-backed endpoint.

Run locally with:  docker compose up -d postgis redis
                    alembic upgrade head && python -m app.etl.seed
                    pytest tests/test_integration_db.py
"""
from __future__ import annotations

import datetime as dt
import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.etl import rainfall
from app.main import app
from app.services import push


def _db_available() -> bool:
    url = os.environ.get("DATABASE_URL_SYNC", "")
    if not url:
        return False
    # psycopg wants a plain DSN, strip SQLAlchemy's driver prefix.
    dsn = url.replace("postgresql+psycopg://", "postgresql://")
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="no live PostGIS (integration test)"
)

client = TestClient(app)


def test_health_reports_db_up():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["db"] is True


def test_risk_point_returns_score_in_accra():
    # Kaneshie hotspot — should score and name the nearest hotspot.
    r = client.get("/api/v1/risk/point", params={"lat": 5.5620, "lng": -0.2360})
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["risk_score"] <= 100
    assert body["band"] in {"low", "moderate", "high", "severe", "extreme"}
    assert 0 <= body["confidence"] <= 1
    assert body["nearest_hotspot"] == "Kaneshie"
    assert set(body["components"]) == {
        "elevation", "slope", "drainage", "imperviousness",
        "historical_flood_density", "recent_rainfall_mm",
    }


def test_risk_area_named_hotspot():
    r = client.get("/api/v1/risk/area", params={"name": "Circle"})
    assert r.status_code == 200
    assert r.json()["risk_score"] >= 0


def test_risk_area_unknown_is_404():
    r = client.get("/api/v1/risk/area", params={"name": "Nowhereville"})
    assert r.status_code == 404


def test_risk_tiles_geojson_in_accra_bbox():
    r = client.get("/api/v1/risk/tiles",
                   params={"bbox": "-0.35,5.50,-0.05,5.70", "res": 8})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection"
    # seed builds the Accra grid → expect tiles present
    if body["count"]:
        f = body["features"][0]
        assert f["geometry"]["type"] == "Polygon"
        assert "risk_score" in f["properties"]


def test_routes_listed_with_status():
    r = client.get("/api/v1/routes")
    assert r.status_code == 200
    routes = r.json()
    assert isinstance(routes, list)
    if routes:
        assert routes[0]["current_status"] in {
            "clear", "watch", "warning", "severe"}


def test_subscribe_requires_auth():
    r = client.post("/api/v1/alerts/subscribe",
                    json={"route_id": "x", "channel": "web"})
    assert r.status_code == 401


def test_flood_report_persists_end_to_end():
    """The full write path: POST a report → it is stored → GET recent shows it."""
    before = client.get("/api/v1/reports/recent", params={"limit": 500}).json()
    payload = {"lat": 5.5610, "lng": -0.2355, "severity": 4,
               "note": "integration-test report"}
    created = client.post("/api/v1/reports", json=payload)
    assert created.status_code == 201
    body = created.json()
    assert body["created"] is True
    new_id = body["id"]

    after = client.get("/api/v1/reports/recent", params={"limit": 500}).json()
    assert len(after) == len(before) + 1
    assert any(r["id"] == new_id for r in after)
    assert any(r["source"] == "community" for r in after)


def test_flood_report_rejects_out_of_ghana():
    r = client.post("/api/v1/reports", json={"lat": 51.5, "lng": -0.12})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_server_mints_its_push_keys_once_and_keeps_them(monkeypatch):
    """No VAPID env ⇒ push still works, and a restart must not swap the pair —
    every existing subscription is bound to it."""
    def restart():
        monkeypatch.setattr(settings, "vapid_public_key", "")
        monkeypatch.setattr(settings, "vapid_private_key", "")

    restart()
    await push.load_keys()
    minted = (settings.vapid_public_key, settings.vapid_private_key)
    assert len(minted[0]) == 87 and len(minted[1]) == 43

    restart()
    await push.load_keys()
    assert (settings.vapid_public_key, settings.vapid_private_key) == minted
    assert client.get("/api/v1/alerts/vapid-key").json()["public_key"] == minted[0]


@pytest.mark.asyncio
async def test_rain_refresh_upserts_and_routes_forecast_from_it(monkeypatch):
    """The scheduled job's real SQL, minus the network: every tile's hours land,
    a second run updates them in place, and routes then forecast from them."""
    start = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
    times = [(start + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M")
             for h in range(-3, 9)]

    def rain(mm):
        async def fetch(client, points):
            return [{"hourly": {"time": times, "precipitation": [mm] * len(times)}}
                    for _ in points]
        return fetch

    for mm in (2.0, 7.0):
        monkeypatch.setattr(rainfall, "_fetch_openmeteo", rain(mm))
        async with SessionLocal() as db:
            assert await rainfall.refresh_rainfall(db, limit_tiles=5000) > 0

    forecasts = [client.get(f"/api/v1/routes/{r['id']}/forecast").json()
                 for r in client.get("/api/v1/routes").json()]
    points = [p for f in forecasts for p in f["points"]]
    assert points, "no route crosses a refreshed tile"
    # Updated in place: the second run's value, not a duplicate of the first.
    assert {p["precip_mm"] for p in points} == {7.0}
