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

import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app


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
