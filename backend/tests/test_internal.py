"""The cron-triggered ETL endpoint must not be an open door."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


async def _noop_cycle():
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

    async def fake_cycle():
        ran.append(True)

    monkeypatch.setattr("app.api.routes.internal.refresh_cycle", fake_cycle)
    r = client.post("/api/v1/internal/refresh", headers={"X-Cron-Key": "s3cret"})
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"
    # TestClient runs background tasks before returning, so the task was wired up.
    assert ran == [True]


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
    # With no CRON_SECRET set, no key is a way in — not even an empty one.
    for key in ("", "guess"):
        assert client.post("/api/v1/internal/refresh",
                           headers={"X-Cron-Key": key}).status_code == 401
