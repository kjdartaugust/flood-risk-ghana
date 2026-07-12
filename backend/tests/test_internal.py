"""The cron-triggered ETL endpoint must not be an open door."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_disabled_when_no_secret_is_set(client, monkeypatch):
    """Absent config must fail closed, not open."""
    monkeypatch.setattr(settings, "cron_secret", "")
    r = client.post("/api/v1/internal/refresh")
    assert r.status_code == 503


def test_rejects_missing_or_wrong_key(client, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    assert client.post("/api/v1/internal/refresh").status_code == 401
    assert client.post(
        "/api/v1/internal/refresh", headers={"X-Cron-Key": "wrong"}
    ).status_code == 401


def test_accepts_valid_key_and_returns_immediately(client, monkeypatch):
    """202 + work deferred: a scheduler must not hold a 2-minute connection."""
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    ran = []

    async def fake_cycle():
        ran.append(True)

    monkeypatch.setattr("app.api.routes.internal.refresh_cycle", fake_cycle)
    r = client.post("/api/v1/internal/refresh", headers={"X-Cron-Key": "s3cret"})
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"
    # TestClient runs background tasks before returning, so the task was wired up.
    assert ran == [True]
