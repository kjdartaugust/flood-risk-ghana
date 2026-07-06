"""API smoke tests that don't require a live DB.

The root and OpenAPI endpoints must work without a database. DB-backed endpoints
are covered by integration tests in CI where Postgres/PostGIS is available.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["service"] == "floodwatch-ghana"


def test_openapi_schema_lists_risk_endpoints():
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/v1/risk/point" in paths
    assert "/api/v1/routes" in paths
    assert "/api/v1/alerts" in paths
    assert "/api/v1/reports" in paths


def test_risk_point_rejects_out_of_ghana():
    # lat/lng validation happens before any DB access → 422
    r = client.get("/api/v1/risk/point", params={"lat": 51.5, "lng": -0.12})
    assert r.status_code == 422
