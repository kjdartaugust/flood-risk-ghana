"""Internal ETL trigger, for an external scheduler.

Render's free tier has no background workers, so `app.etl.worker` (APScheduler)
never runs in production: rainfall was never refreshed, `rainfall_recent_mm`
stayed 0, and `evaluate_and_raise_alerts` never fired. Half the product was
static.

This endpoint is the free-tier substitute — GitHub Actions (`.github/workflows/
refresh.yml`) calls it on a schedule and the work happens inside the web service
we already pay nothing for. The refresh takes a couple of minutes, so it runs as
a background task and the endpoint returns 202 immediately; a scheduler that has
to hold a two-minute HTTP connection open is a scheduler that will time out.

There is no user here, so auth isn't a user JWT. Either of these is enough:

* a GitHub Actions OIDC token from `refresh.yml` in the repo this server was
  deployed from (`CRON_GITHUB_REPO`, which Render fills in by itself). GitHub
  signs it, so nothing has to be copied between GitHub and the host: on a fresh
  deploy the schedule just works.
* `CRON_SECRET`, sent as `X-Cron-Key`, for any other scheduler.

With neither configured the endpoint is disabled outright rather than left open.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.config import settings
from app.db import SessionLocal
from app.etl.rainfall import refresh_rainfall
from app.security import bearer, is_github_workflow
from app.services.alerts_service import evaluate_and_raise_alerts
from app.services.push import load_keys

log = logging.getLogger("api.internal")

router = APIRouter(prefix="/internal", tags=["internal"])


async def _authorise(key: str | None, token: str | None) -> None:
    if not settings.cron_secret and not settings.cron_github_repo:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "refresh endpoint disabled — set CRON_GITHUB_REPO or CRON_SECRET",
        )
    # Constant-time: a plain `!=` leaks the secret one byte at a time to anyone
    # who can measure response latency. Bytes, because compare_digest refuses
    # non-ASCII str and a header can carry some.
    if key and settings.cron_secret and secrets.compare_digest(
        key.encode(), settings.cron_secret.encode()
    ):
        return
    if token and settings.cron_github_repo and await is_github_workflow(
        token, settings.cron_github_repo, "refresh.yml"
    ):
        return
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad cron credentials")


async def refresh_cycle() -> None:
    """Pull rainfall, then re-evaluate route flood alerts against it."""
    # A no-op once the web app has loaded them; here for the standalone worker.
    await load_keys()
    try:
        async with SessionLocal() as db:
            rows = await refresh_rainfall(db)
        async with SessionLocal() as db:
            raised = await evaluate_and_raise_alerts(db)
        log.info("refresh done: %d rainfall rows, %d alerts raised", rows, raised)
    except Exception:
        # A background task that dies silently is a scheduled job that looks
        # healthy while doing nothing — which is the bug we are fixing.
        log.exception("refresh cycle failed")
        raise


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
async def trigger_refresh(
    background: BackgroundTasks,
    x_cron_key: str | None = Header(default=None, alias="X-Cron-Key"),
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    """Kick off a rainfall + alert-evaluation cycle. Returns immediately."""
    await _authorise(x_cron_key, creds.credentials if creds else None)
    background.add_task(refresh_cycle)
    log.info("refresh accepted")
    return {"status": "accepted"}
