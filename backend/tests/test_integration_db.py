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

import copy
import datetime as dt
import os
import uuid

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString

from app.config import settings
from app.db import SessionLocal
from app.etl import osm_routes, rainfall
from app.main import app
from app.models import TrotroRoute
from app.services import alerts_service, push


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


# Shaped like a browser's: a real P-256 point and a 16-byte auth secret.
BROWSER_KEYS = {"p256dh": push.generate_keys()[0], "auth": "AAAAAAAAAAAAAAAAAAAAAA"}

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
    # Accra's trotro lines from OpenStreetMap, not a handful of stand-ins.
    assert len(routes) >= 250
    statuses = {r["current_status"] for r in routes}
    assert statuses <= {"clear", "watch", "warning", "severe"}
    assert all(r["id"].startswith("osm-") for r in routes)
    assert all(isinstance(r["hours"], list) for r in routes)
    # The worst tile along a real route through central Accra is a real score.
    assert max(r["baseline_risk"] for r in routes) > 0


def test_route_lines_are_geojson_a_browser_can_keep():
    r = client.get("/api/v1/routes/lines", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/geo+json")
    assert r.headers["content-encoding"] == "gzip"  # ~300 KB as plain JSON
    lines = r.json()["features"]
    ids = {r["id"] for r in client.get("/api/v1/routes").json()}
    assert {f["properties"]["id"] for f in lines} == ids
    lng, lat = lines[0]["geometry"]["coordinates"][0]
    assert -0.6 < lng < 0.2 and 5.4 < lat < 6.0
    again = client.get("/api/v1/routes/lines",
                       headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


@pytest.mark.asyncio
async def test_route_sync_writes_only_changes_and_retires_old_routes():
    """Every boot syncs the bundle: nothing to write when nothing changed; a
    renamed line is rewritten; a route no longer in it goes, with anyone's
    subscription to it (the 5 hand-drawn stand-ins, on the first deploy)."""
    bundle = osm_routes.load_bundle()
    stand_in = TrotroRoute(id=str(uuid.uuid4()), name="Kaneshie – Circle",
                           geom=from_shape(LineString([(-0.236, 5.562), (-0.205, 5.571)]),
                                           srid=4326))
    async with SessionLocal() as db:
        assert await osm_routes.sync_routes(db, bundle) == []
        db.add(stand_in)
        await db.commit()
    sub = {"endpoint": f"https://fcm.googleapis.com/fcm/send/it-{uuid.uuid4()}",
           "keys": BROWSER_KEYS}
    assert client.post("/api/v1/alerts/subscribe", json={
        "route_id": stand_in.id, "channel": "push", "push_subscription": sub,
    }).status_code == 200

    renamed = copy.deepcopy(bundle)
    renamed[0]["properties"]["to"] += " Station"
    first = f"osm-{bundle[0]['properties']['osm_id']}"
    try:
        async with SessionLocal() as db:
            assert await osm_routes.sync_routes(db, renamed) == [first]
        routes = {r["id"]: r for r in client.get("/api/v1/routes").json()}
        assert stand_in.id not in routes
        assert routes[first]["name"].endswith(" Station")
        gone = client.post("/api/v1/alerts/unsubscribe",
                           json={"route_id": stand_in.id, "endpoint": sub["endpoint"]})
        assert gone.json() == {"removed": False}
    finally:
        async with SessionLocal() as db:
            assert await osm_routes.sync_routes(db, bundle) == [first]


def test_subscribe_requires_auth():
    r = client.post("/api/v1/alerts/subscribe",
                    json={"route_id": "x", "channel": "web"})
    assert r.status_code == 401


def test_anyone_can_subscribe_a_route_for_push_and_stop():
    """No account: the push endpoint is the identity, both for subscribing and
    for stopping. An unknown route is a 404, not a 500."""
    route_id = client.get("/api/v1/routes").json()[0]["id"]
    sub = {"endpoint": f"https://fcm.googleapis.com/fcm/send/it-{uuid.uuid4()}",
           "keys": BROWSER_KEYS}
    body = {"route_id": route_id, "channel": "push", "push_subscription": sub}

    first = client.post("/api/v1/alerts/subscribe", json=body)
    assert first.status_code == 200 and first.json()["created"] is True
    again = client.post("/api/v1/alerts/subscribe", json=body).json()
    assert again["created"] is False and again["id"] == first.json()["id"]
    unknown = client.post("/api/v1/alerts/subscribe",
                          json={**body, "route_id": "no-such-route"})
    assert unknown.status_code == 404

    stop = {"route_id": route_id, "endpoint": sub["endpoint"]}
    for removed in (True, False):
        r = client.post("/api/v1/alerts/unsubscribe", json=stop)
        assert r.json() == {"removed": removed}


def test_test_alert_reaches_the_stored_subscription_and_prunes_a_dead_one(monkeypatch):
    """The test takes the real path from the stored row; if the push service
    says the browser dropped it, the row goes."""
    route = client.get("/api/v1/routes").json()[0]
    sub = {"endpoint": f"https://fcm.googleapis.com/fcm/send/it-{uuid.uuid4()}",
           "keys": BROWSER_KEYS}
    client.post("/api/v1/alerts/subscribe", json={
        "route_id": route["id"], "channel": "push", "push_subscription": sub})

    pushed = []
    replies = iter([None, 410])

    async def push_service(handle, payload):
        pushed.append((handle["endpoint"], payload))
        return next(replies)

    monkeypatch.setattr(alerts_service, "send_push", push_service)
    monkeypatch.setattr("app.api.routes.alerts.push_enabled", lambda: True)
    ask = {"route_id": route["id"], "endpoint": sub["endpoint"]}

    assert client.post("/api/v1/alerts/test", json=ask).json() == {
        "sent": True, "status": None}
    endpoint, payload = pushed[0]
    assert endpoint == sub["endpoint"] and route["name"] in payload["body"]

    assert client.post("/api/v1/alerts/test", json=ask).json() == {
        "sent": False, "status": 410}
    assert client.post("/api/v1/alerts/test", json=ask).status_code == 404


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

    routes = client.get("/api/v1/routes").json()
    # Every route gets rain, including the ones running out past the risk grid.
    assert all(r["hours"] for r in routes), "a route got no rain"
    # Updated in place: the second run's value, not a duplicate of the first.
    hours = [h for r in routes for h in r["hours"]]
    assert {h["precip_mm"] for h in hours} == {7.0}
    # The forecast endpoint reads the same hours.
    forecast = client.get(f"/api/v1/routes/{routes[0]['id']}/forecast").json()
    assert forecast["points"] and {p["precip_mm"] for p in forecast["points"]} == {7.0}


def test_each_refresh_records_whether_it_saved_rain(monkeypatch):
    """A 202 only says a run started. GET /internal/refresh must say how it
    ended — saved rain, or failed and why."""
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    # The cycle loads the server's push keys into settings, as on a fresh
    # deploy; monkeypatch puts the blanks back for the tests that follow.
    monkeypatch.setattr(settings, "vapid_public_key", "")
    monkeypatch.setattr(settings, "vapid_private_key", "")
    times = [(dt.datetime.now(dt.UTC) + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:00")
             for h in range(-2, 4)]

    async def rain(client, points):
        return [{"hourly": {"time": times, "precipitation": [1.0] * len(times)}}
                for _ in points]

    async def down(client, points):
        raise httpx.ConnectError("no route to host")

    # The failing run re-raises after recording itself; that's the host's log.
    lenient = TestClient(app, raise_server_exceptions=False)
    for fetch, ok in ((rain, True), (down, False)):
        monkeypatch.setattr(rainfall, "_fetch_openmeteo", fetch)
        started = lenient.post("/api/v1/internal/refresh",
                               headers={"X-Cron-Key": "s3cret"})
        assert started.status_code == 202
        run = client.get("/api/v1/internal/refresh").json()
        assert run["id"] == started.json()["run"]
        assert run["finished_at"]
        if ok:
            assert run["error"] is None and run["rainfall_rows"] > 0
        else:
            assert run["rainfall_rows"] is None
            assert "every rain fetch failed" in run["error"]


def test_refresh_saves_rain_the_caller_fetched_as_planned(monkeypatch):
    """Production path: Open-Meteo turns Render's shared IP away, so the
    scheduler fetches what /refresh/plan asks for and posts it back. The server
    must save that, and must not fetch on its own."""
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    monkeypatch.setattr(settings, "vapid_public_key", "")
    monkeypatch.setattr(settings, "vapid_private_key", "")

    async def must_not_fetch(client, points):
        raise AssertionError("the server fetched rain it was handed")

    monkeypatch.setattr(rainfall, "_fetch_openmeteo", must_not_fetch)

    plan = client.get("/api/v1/internal/refresh/plan").json()
    assert plan["points"]
    assert plan["url"].startswith(f"{settings.openmeteo_base}/forecast?latitude=")
    times = [(dt.datetime.now(dt.UTC) + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:00")
             for h in range(-2, 4)]
    hourly = {"time": times, "precipitation": [3.0] * len(times)}
    started = client.post(
        "/api/v1/internal/refresh", headers={"X-Cron-Key": "s3cret"},
        json={"points": plan["points"],
              "forecasts": [{"hourly": hourly} for _ in plan["points"]]})
    assert started.status_code == 202
    run = client.get("/api/v1/internal/refresh").json()
    assert run["id"] == started.json()["run"]
    assert run["error"] is None and run["rainfall_rows"] > 0
