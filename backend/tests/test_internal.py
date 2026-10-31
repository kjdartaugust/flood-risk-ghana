"""The cron-triggered ETL endpoint must not be an open door."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def runs_without_a_db(monkeypatch):
    """Accepted runs get a row in refresh_runs; these tests are about the door."""
    async def start_run():
        return 7

    monkeypatch.setattr("app.api.routes.internal._start_run", start_run)


async def _noop_cycle(run_id, fetched=None):
    pass


def test_disabled_when_nothing_is_configured(client, monkeypatch):
    """Absent config must fail closed, not open."""
    monkeypatch.setattr(settings, "cron_secret", "")
    monkeypatch.setattr(settings, "cron_github_repo", "")
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

    async def fake_cycle(run_id, fetched=None):
        ran.append(run_id)

    monkeypatch.setattr("app.api.routes.internal.refresh_cycle", fake_cycle)
    r = client.post("/api/v1/internal/refresh", headers={"X-Cron-Key": "s3cret"})
    assert r.status_code == 202
    # The run's id, so the caller can check how it went.
    assert r.json() == {"status": "accepted", "run": 7}
    # TestClient runs background tasks before returning, so the task was wired up.
    assert ran == [7]


def test_accepts_a_token_from_this_repos_refresh_workflow(client, monkeypatch):
    """No shared secret at all: GitHub vouches for the caller."""
    monkeypatch.setattr(settings, "cron_secret", "")
    monkeypatch.setattr(settings, "cron_github_repo", "owner/repo")
    asked = []

    async def github_says(token, repo, workflow):
        asked.append((token, repo, workflow))
        return token == "minted-by-github"

    monkeypatch.setattr("app.api.routes.internal.is_github_workflow", github_says)
    monkeypatch.setattr("app.api.routes.internal.refresh_cycle", _noop_cycle)

    ok = client.post("/api/v1/internal/refresh",
                     headers={"Authorization": "Bearer minted-by-github"})
    assert ok.status_code == 202
    assert asked == [("minted-by-github", "owner/repo", "refresh.yml")]

    forged = client.post("/api/v1/internal/refresh",
                         headers={"Authorization": "Bearer forged"})
    assert forged.status_code == 401
    # With no CRON_SECRET set, no key is a way in, not even an empty one.
    for key in ("", "guess"):
        assert client.post("/api/v1/internal/refresh",
                           headers={"X-Cron-Key": key}).status_code == 401


def test_rain_fetched_by_the_caller_is_handed_to_the_cycle(client, monkeypatch):
    """The scheduler may bring the rain, because Open-Meteo turns Render's
    shared IP away. It goes to the cycle as given, Open-Meteo's extras dropped."""
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    got = []

    async def fake_cycle(run_id, fetched=None):
        got.append(fetched)

    monkeypatch.setattr("app.api.routes.internal.refresh_cycle", fake_cycle)
    hourly = {"time": ["2026-10-31T12:00"], "precipitation": [4.2]}
    r = client.post("/api/v1/internal/refresh", headers={"X-Cron-Key": "s3cret"},
                    json={"points": [[5.55, -0.2]],
                          "forecasts": [{"hourly": hourly, "latitude": 5.55}]})
    assert r.status_code == 202
    assert got == [([(5.55, -0.2)], [{"hourly": hourly}])]

    # One forecast per point, or it's refused before any work starts.
    r = client.post("/api/v1/internal/refresh", headers={"X-Cron-Key": "s3cret"},
                    json={"points": [[5.55, -0.2], [5.6, -0.2]],
                          "forecasts": [{"hourly": hourly}]})
    assert r.status_code == 422
    assert len(got) == 1
